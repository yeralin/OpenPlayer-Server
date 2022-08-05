from io import BytesIO
from os import getenv
import re
import subprocess
import threading
from typing import Generator, List, Optional, Tuple
from librespot.proto.Metadata_pb2 import AudioFile
from models import Entry
from streamers import utils
from streamers.base_streamer import BaseStreamer
from streamers.exceptions import StreamerError
from librespot.core import Session
from librespot.audio import PlayableContentFeeder
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.metadata import TrackId
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials


class SpotifyStreamer(BaseStreamer):
    
    stream_path = '/stream/spotify'
    search_path = '/search/spotify'
    spotify_track_regex = r'([a-zA-Z0-9]{22})'

    def __init__(self, username: str = getenv('SPOTIFY_USERNAME'),
                 pwd: str = getenv('SPOTIFY_PASSWORD'),
                 client_id: str = getenv('SPOTIFY_CLIENT_ID'),
                 client_secret: str = getenv('SPOTIFY_CLIENT_SECRET'),
                 chunk_size: int = 50000) -> None:
        super().__init__()
        self.chunk_size = chunk_size
        self.session = Session.Builder().user_pass(username, pwd).create()
        self.content_feeder = self.session.content_feeder()
        self.spotify_api = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(client_id=client_id,
                                                  client_secret=client_secret))

    def _parse_spotify_track_id(self, track_id: str) -> Optional[str]:
        match = re.search(self.spotify_track_regex, track_id)
        if not match:
            return None
        return match.group()

    def _extract_bitrate(self, audio_format: AudioFile.Format) -> int:
        if audio_format in [
                AudioFile.MP3_96,
                AudioFile.OGG_VORBIS_96,
                AudioFile.AAC_24_NORM,
        ]:
            return 96
        if audio_format in [
                AudioFile.MP3_160,
                AudioFile.MP3_160_ENC,
                AudioFile.OGG_VORBIS_160,
                AudioFile.AAC_24,
        ]:
            return 160
        if audio_format in [
                AudioFile.MP3_320,
                AudioFile.MP3_256,
                AudioFile.OGG_VORBIS_320,
                AudioFile.AAC_48,
        ]:
            return 320
        raise RuntimeError("Unknown format: {}".format(format))

    def get_name(self) -> str:
        return 'Spotify'

    def search(self, query: str, limit: int = 20) -> List[Entry]:
        results = []
        search_output = self.spotify_api.search(q=query, limit=limit)
        for item in search_output['tracks']['items']:
            # Construct title
            artists = ', '.join([artist['name'] for artist in item['artists']])
            title = ' - '.join([artists, item['name']])
            # Construct url
            track_id = self._parse_spotify_track_id(item['uri'])
            url = utils.construct_url(self.stream_path, trackId=track_id)
            results.append(Entry(title, url, self.get_name()))
        return results
    
    def request_stream(self, id: str) -> Tuple[Generator[BytesIO, None, None], str, int, int]:
        track_id = self._parse_spotify_track_id(id)
        if not track_id:
            raise StreamerError(
                'Invalid trackId param, expected ' + self.spotify_track_regex)
        preferred_quality = VorbisOnlyAudioQuality(AudioQuality.HIGH)
        playable_content = self.content_feeder.load(
            TrackId.from_uri("spotify:track:" + track_id), preferred_quality, False, None)
        preferred_file = preferred_quality.get_file(
            playable_content.track.file)
        artists = ', '.join([artist.name for artist in playable_content.track.artist])
        title = ' - '.join([artists, playable_content.track.name])
        bitrate = self._extract_bitrate(preferred_file.format)
        duration = playable_content.track.duration // 1000  # ms to sec
        size = utils.estimate_size(duration, bitrate)
        stream = self.generate_stream(playable_content, bitrate, size)
        return (stream, title, duration, size)

    def generate_stream(self, payload: PlayableContentFeeder.LoadedStream,
                        bitrate: int, size: int) -> Generator[BytesIO, None, None]:
        
        def async_write(ffmpeg_process, stream):
            while True:
                in_chunk = stream.read(self.chunk_size)
                if not in_chunk:
                    ffmpeg_process.stdin.close()
                    break
                ffmpeg_process.stdin.write(in_chunk)

        def stream():
            input_stream = payload.input_stream.stream()
            ffmpeg_process = subprocess.Popen(
                'ffmpeg -f ogg -i - -vn -b:a {}k -f mp3 -'
                .format(bitrate).split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            write_t = threading.Thread(target=async_write, args=(ffmpeg_process,input_stream,))
            write_t.start()
            transmitted = 0
            try:
                while True:
                    out_chunk = ffmpeg_process.stdout.read(self.chunk_size)
                    if not out_chunk:
                        ffmpeg_process.stdout.close()
                        ffmpeg_process.terminate()
                        if transmitted < size:
                            yield b'\0' * (size-transmitted)
                        return
                    transmitted += len(out_chunk)
                    yield out_chunk
            except GeneratorExit:
                ffmpeg_process.stdin.close()
                ffmpeg_process.stdout.close()
                ffmpeg_process.terminate()
        return stream
