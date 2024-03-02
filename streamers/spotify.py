"""This module provides functionality for streaming Spotify tracks using the Spotify API and librespot."""
import re
from io import BytesIO
from os import getenv
from typing import Generator, List, Optional, Tuple

import spotipy
from librespot.audio import PlayableContentFeeder
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import Session
from librespot.metadata import TrackId
from spotipy.oauth2 import SpotifyClientCredentials

from models import Entry
from streamers import utils
from streamers.base_streamer import BaseStreamer
from streamers.exceptions import StreamerError


class SpotifyStreamer(BaseStreamer):
    """
    This class handles streaming of Spotify tracks by interfacing with the Spotify API and librespot.
    """

    stream_path = "/stream/spotify"
    search_path = "/search/"
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
        self.session = Session.Builder().user_pass(username, pwd).create()
        self.content_feeder = self.session.content_feeder()
        self.spotify_api = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
        )

    def parse_spotify_track_id(self, track_id: str) -> Optional[TrackId]:
        match = re.search(self.spotify_track_regex, track_id)
        if not match:
            return None
        return match.group()

    def get_name(self) -> str:
        return "Spotify"

    def search(self, query: str, limit: int = 20) -> List[Entry]:
        results = []
        search_output = self.spotify_api.search(q=query, limit=limit)
        for item in search_output["tracks"]["items"]:
            # Construct title
            artists = ", ".join([artist["name"] for artist in item["artists"]])
            title = " - ".join([artists, item["name"]])
            # Construct url
            track_id = self.parse_spotify_track_id(item["uri"])
            url = utils.construct_url(self.stream_path, trackId=track_id)
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
        preferred_quality = VorbisOnlyAudioQuality(AudioQuality.HIGH)
        playable_content = self.content_feeder.load(
            TrackId.from_uri("spotify:track:" + spotify_track_id), preferred_quality, False, None
        )
        # Get metadata
        artists = ", ".join([artist.name for artist in playable_content.track.artist])
        title = " - ".join([artists, playable_content.track.name])
        duration = playable_content.track.duration // 1000  # ms to sec
        # Generate stream
        stream = self.generate_stream(playable_content, range_start, range_end)
        return (stream, title, duration, playable_content.input_stream.size)

    def generate_stream(
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
