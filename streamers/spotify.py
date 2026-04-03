"""This module provides functionality for streaming Spotify tracks using the Spotify API and librespot."""
import re
import logging
from io import BytesIO
from os import getenv
from typing import Generator, List, Optional, Tuple

import spotipy
from librespot.audio import LoadedStream
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.proto.Metadata_pb2 import AudioFile
from librespot.core import Session
from librespot.metadata import TrackId
from spotipy.oauth2 import SpotifyClientCredentials

from models import Entry
from streamers import utils
from streamers.base_streamer import BaseStreamer
from streamers.exceptions import StreamerError
from streamers.ffmpeg_converter import FFmpegConverter

logger = logging.getLogger(__name__)


class SpotifyStreamer(BaseStreamer):
    """
    This class handles streaming of Spotify tracks by interfacing with the Spotify API and librespot.
    """

    stream_path = "/stream/spotify"
    search_path = "/search/spotify"
    spotify_track_regex = r"([a-zA-Z0-9]{22})"

    def __init__(
        self,
        username: str = getenv("SPOTIFY_USERNAME"),
        pwd: str = getenv("SPOTIFY_PASSWORD"),
        client_id: str = getenv("SPOTIFY_CLIENT_ID"),
        client_secret: str = getenv("SPOTIFY_CLIENT_SECRET"),
        chunk_size: int = (128 * 1024),
    ) -> None:
        super().__init__()
        self.chunk_size = chunk_size
        self.spotify_api = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
        )
        self.session = None
        self.content_feeder = None
        self.init_session()
    
    def init_session(self):
        """Initialize or reinitialize the Spotify session."""
        # Clean up existing session if any
        self.cleanup_session()
        
        try:
            self.session = Session.Builder().stored_file().create()
            self.content_feeder = self.session.content_feeder()
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            raise
    
    def cleanup_session(self):
        """Clean up the current Spotify session."""
        # Content feeder is part of session, no need to close separately
        self.content_feeder = None
        
        if self.session is not None:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
            finally:
                self.session = None

    def parse_spotify_track_id(self, track_id: str) -> Optional[TrackId]:
        match = re.search(self.spotify_track_regex, track_id)
        if not match:
            return None
        return match.group()

    def get_name(self) -> str:
        return "Spotify"

    def _extract_bitrate(self, audio_format: AudioFile.Format) -> int:
        if audio_format in [
                AudioFile.MP3_96,
                AudioFile.OGG_VORBIS_96,
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

    def search(self, query: str, limit: int = 20) -> List[Entry]:
        results = []
        search_output = self.spotify_api.search(q=query, limit=limit)
        for item in search_output["tracks"]["items"]:
            # Construct title
            artists = ", ".join([artist["name"] for artist in item["artists"]])
            title = " - ".join([artists, item["name"]])
            # Construct url
            track_id = self.parse_spotify_track_id(item["uri"])
            url = utils.construct_url(self.stream_path, scheme="https", trackId=track_id)
            results.append(Entry(title, url, self.get_name()))
        return results

    def request_stream(
        self, track_id: str, range_start: int, range_end: Optional[int]
    ) -> Tuple[Generator[BytesIO, None, None], str, int, int]:
        spotify_track_id = self.parse_spotify_track_id(track_id)
        if not spotify_track_id:
            raise StreamerError(
                "Invalid trackId param, expected " + self.spotify_track_regex
            )
        preferred_quality = VorbisOnlyAudioQuality(AudioQuality.VERY_HIGH) # VERY_HIGH & LOSSLESS only on Spotify Premium
        try:
            playable_content = self.content_feeder.load(
                TrackId.from_uri("spotify:track:" + spotify_track_id), preferred_quality, False, None
            )
        except Exception:
            # Reset session
            self.cleanup_session()
            self.init_session()
            playable_content = self.content_feeder.load(
                TrackId.from_uri("spotify:track:" + spotify_track_id), preferred_quality, False, None
            )
        
        preferred_file = preferred_quality.get_file(
            playable_content.track.file)
        # Get metadata
        artists = ", ".join([artist.name for artist in playable_content.track.artist])
        title = " - ".join([artists, playable_content.track.name])
        duration = playable_content.track.duration // 1000  # ms to sec
        bitrate = self._extract_bitrate(preferred_file.format)
        size = utils.estimate_size(duration, bitrate)
        # Generate stream
        stream = self.generate_stream(playable_content, bitrate, size)
        return (stream, title, duration, size)
        """ Pass-through Ogg stream (not used)
        stream = self.generate_stream_ogg(playable_content, range_start, range_end)
        return (stream, title, duration, playable_content.input_stream.size)
        """

    def generate_stream(self, payload: LoadedStream,
                        bitrate: int, size: int) -> Generator[BytesIO, None, None]:
        """
        Converts OGG to MP3 on the fly using FFmpeg.
        
        Args:
            payload: The loaded stream from Spotify.
            bitrate: Target bitrate for MP3 output.
            size: Estimated size of output.
            
        Returns:
            A generator function that yields MP3 audio chunks.
        """
        def stream():
            input_stream = payload.input_stream.stream()
            converter = FFmpegConverter(chunk_size=self.chunk_size)
            try:
                yield from converter.convert_ogg_to_mp3(input_stream, bitrate, size)
            finally:
                # Ensure cleanup happens even if generator is not fully consumed
                converter.cleanup()
        
        return stream
    
    def __del__(self):
        """Destructor to ensure session cleanup on garbage collection."""
        self.cleanup_session()

""" Pass-through, streaming in original OGG format

    def generate_stream_ogg(
        self,
        content: PlayableContentFeeder.LoadedStream,
        range_start: int,
        range_end: int,
    ) -> Generator[BytesIO, None, None]:
        def stream():
            input_stream = content.input_stream
            max_chunk = content.input_stream.size / self.chunk_size
            start_chunk = int(range_start / self.chunk_size)
            end_chunk = int(range_end / self.chunk_size) if range_end else max_chunk
            while start_chunk < end_chunk:
                start = self.chunk_size * start_chunk
                end = (start_chunk + 1) * self.chunk_size - 1
                out_chunk = input_stream.request(
                    range_start=start, range_end=end
                ).buffer
                decrypted_chunk = input_stream._Streamer__audio_decrypt.decrypt_chunk(
                    start_chunk, out_chunk
                )
                start_chunk += 1
                yield decrypted_chunk

        return stream
"""
