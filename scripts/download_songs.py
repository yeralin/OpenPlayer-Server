#!/usr/bin/env python3
"""
Module for downloading songs using a Spotify-based API.

Note:
    For proper naming style, consider renaming this file to 
    "download_songs.py" (i.e. use snake_case).

    This module now supports fetching songs from a Spotify playlist,
    processing local MP3 tracks, or downloading tracks from a file of
    Spotify URLs.
"""

import argparse
import logging
import os
import re
import time
from typing import Optional
from urllib.parse import quote, unquote

import requests
import spotipy
from fuzzywuzzy import fuzz
from mutagen._util import MutagenError
from mutagen.mp3 import MP3
from spotipy.oauth2 import SpotifyClientCredentials


def sanitize_filename(filename: str) -> str:
    """
    Sanitize the filename by replacing invalid characters.
    """
    return re.sub(r'[<>:"/\\|?*]', "_", filename)


class SpotifyClient:
    """
    A client to search for Spotify tracks and download them via API.

    Also initializes a Spotipy client for fetching playlist information.
    """

    SEARCH_URL_TEMPLATE: str = "https://music.yeralin.net/search/spotify?q={}"
    STREAM_URL_TEMPLATE: str = (
        "https://music.yeralin.net/stream/spotify?trackId={}&download=true"
    )
    AUTH_HEADERS: dict = {"Authorization": "Basic ZGFuaXlhcjpkajJndmNQNiVvTiVlcQ=="}
    FUZZY_MATCH_THRESHOLD: int = 80

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        client_id: Optional[str] = os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret: Optional[str] = os.getenv("SPOTIFY_CLIENT_SECRET"),
    ) -> None:
        """
        Initialize the Spotify client with an optional requests.Session
        for connection reuse and initialize a Spotipy client.
        """
        self.session = session if session is not None else requests.Session()
        self.spotify_api = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
        )

    def search_spotify(self, track_name: str) -> Optional[str]:
        """
        Search for a Spotify track by name.

        :param track_name: Track name (usually "Artist - Title")
        :return: URL of the best matching track or None if not found.
        """
        search_url = self.SEARCH_URL_TEMPLATE.format(quote(track_name))
        try:
            response = self.session.get(
                search_url, headers=self.AUTH_HEADERS, timeout=10
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logging.error(
                "HTTP error when searching for track '%s': %s",
                track_name,
                exc,
            )
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logging.error("Error decoding JSON for track '%s': %s", track_name, exc)
            return None

        if not data:
            logging.warning("No search results for track '%s'.", track_name)
            return None

        # Compute fuzzy matching scores.
        for entry in data:
            title = entry.get("title", "")
            entry["match_score"] = fuzz.ratio(title.lower(), track_name.lower())

        best_match = max(data, key=lambda x: x.get("match_score", 0), default={})
        match_score = best_match.get("match_score", 0)
        if match_score >= self.FUZZY_MATCH_THRESHOLD:
            logging.info(
                "Best match for '%s' is '%s' with score %d",
                track_name,
                best_match,
                match_score,
            )
            return best_match.get("url")
        else:
            logging.info(
                "No sufficient match for '%s'. Best score was %d",
                track_name,
                match_score,
            )
            return None

    def download_spotify_track(
        self, track_url: str, file_path: Optional[str] = None
    ) -> bool:
        """
        Download a track from Spotify using the provided track URL.

        If file_path points to a directory, the file is saved in that directory
        (using the filename extracted from the response header).

        :param track_url: URL for the track download.
        :param file_path: Target file path (or directory) where the track should be saved.
                           If given as a file path and the file exists, it is removed before saving.
        :return: True if download succeeds; False otherwise.
        """
        download_url = f"{track_url}&download=true"
        try:
            response = self.session.get(
                download_url, headers=self.AUTH_HEADERS, timeout=20
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logging.error(
                "Failed to download track from URL '%s': %s",
                track_url,
                exc,
            )
            return False

        if response.status_code in (200, 206):
            content_disp = response.headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                filename = unquote(content_disp.split("filename=")[-1].strip('"'))
                filename = sanitize_filename(filename)
                if file_path:
                    if os.path.isdir(file_path):
                        dirname = file_path
                    else:
                        dirname = os.path.dirname(file_path)
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except OSError as exc:
                            logging.error("Error removing file %s: %s", file_path, exc)
                    file_path = os.path.join(dirname, filename)
                else:
                    file_path = filename
            else:
                file_path = f"download_{int(time.time())}.mp3"

            try:
                with open(file_path, "wb") as f:
                    f.write(response.content)
                logging.info("Downloaded track to '%s'", file_path)
                return True
            except OSError as exc:
                logging.error("Error writing file '%s': %s", file_path, exc)
                return False
        elif response.status_code == 400:
            logging.error(
                "Spotify track ID not found for URL '%s' (HTTP 400)", track_url
            )
            return False
        else:
            logging.error(
                "Failed to download track from '%s'. HTTP status: %d",
                track_url,
                response.status_code,
            )
            return False


def download_playlist(
    spotify_client: SpotifyClient,
    playlist_id: str,
    download_dir: str = ".",
    delay: int = 60,
) -> None:
    """
    Fetch songs from a Spotify playlist and download them.

    Uses the Spotipy client (already initialized in the SpotifyClient instance)
    to retrieve the playlist's tracks. For each track, the track ID is extracted
    and used directly to construct the download URL via STREAM_URL_TEMPLATE.

    :param spotify_client: An instance of SpotifyClient.
    :param playlist_id: The Spotify playlist ID or URL.
    :param download_dir: Directory to save downloaded songs.
    :param delay: Seconds to wait between downloads.
    """
    try:
        results = spotify_client.spotify_api.playlist_tracks(playlist_id)
    except Exception as exc:
        logging.error("Error fetching playlist: %s", exc)
        return

    tracks = results.get("items", [])
    while results.get("next"):
        results = spotify_client.spotify_api.next(results)
        tracks.extend(results.get("items", []))

    for item in tracks:
        track_info = item.get("track")
        if not track_info:
            continue

        track_id = track_info.get("id")
        if not track_id:
            logging.warning("No track id found in item: %s", item)
            continue

        # Directly construct the download URL using the track ID.
        track_url = SpotifyClient.STREAM_URL_TEMPLATE.format(track_id)
        logging.info("Processing playlist track: '%s'", track_url)

        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)
        spotify_client.download_spotify_track(track_url, download_dir)
        time.sleep(delay)


def enhance_tracks(
    spotify_client: SpotifyClient, tracks_dir: str = ".", delay: int = 60
) -> None:
    """
    Enhance all MP3 tracks in the given directory. For tracks with a bitrate
    lower than 320 kbps, search for a high-quality version and download it.

    :param spotify_client: An instance of SpotifyClient.
    :param tracks_dir: Directory containing MP3 files.
    :param delay: Seconds to wait between downloads.
    """
    for root, _, files in os.walk(tracks_dir):
        for file in files:
            if file.lower().endswith(".mp3"):
                filepath = os.path.join(root, file)
                try:
                    audio = MP3(filepath)
                except MutagenError as exc:
                    logging.error("Failed to read MP3 file '%s': %s", filepath, exc)
                    continue

                bitrate = (
                    (getattr(audio.info, "bitrate", 0) // 1000) if audio.info else 0
                )
                if bitrate < 320:
                    if audio.tags and "TPE1" in audio.tags and "TIT2" in audio.tags:
                        try:
                            artist = audio.tags["TPE1"].text[0]
                            title = audio.tags["TIT2"].text[0]
                            track_name = f"{artist} - {title}"
                        except (IndexError, AttributeError) as exc:
                            logging.error(
                                "Error extracting metadata from '%s': %s", filepath, exc
                            )
                            track_name = os.path.splitext(file)[0]
                    else:
                        track_name = os.path.splitext(file)[0]

                    logging.info(
                        "Track '%s' has bitrate %dkbps. Processing...",
                        track_name,
                        bitrate,
                    )
                    track_url = spotify_client.search_spotify(track_name)
                    if track_url:
                        if spotify_client.download_spotify_track(track_url, filepath):
                            logging.info("Successfully processed track '%s'", track_name)
                        else:
                            logging.error("Failed to download improved version for '%s'", track_name)
                        time.sleep(delay)
                    else:
                        logging.warning("Spotify track not found for '%s'", track_name)
                else:
                    logging.info("Track '%s' has acceptable bitrate (%dkbps)", file, bitrate)


def process_songs_file(
    spotify_client: SpotifyClient, songs_file: str = "songs.txt", delay: int = 20
) -> None:
    """
    Process a file containing Spotify track URLs and download each track.

    :param spotify_client: An instance of SpotifyClient.
    :param songs_file: Path to the file with Spotify track URLs.
    :param delay: Seconds to wait between downloads.
    """
    if not os.path.exists(songs_file):
        logging.error("Songs file '%s' does not exist.", songs_file)
        return

    with open(songs_file, "r", encoding="utf-8") as file:
        for line in file:
            track_id = line.strip()
            if "spotify.com" in track_id:
                track_url = SpotifyClient.STREAM_URL_TEMPLATE.format(track_id)
                if spotify_client.download_spotify_track(track_url):
                    logging.info("Downloaded track from '%s'", track_url)
                else:
                    logging.error("Failed to download track from '%s'", track_url)
                time.sleep(delay)
            else:
                logging.warning("Invalid track URL: '%s'", track_id)


def main() -> None:
    """
    Main entry point for the application.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Spotify Track Downloader - Download high-quality tracks "
            "using a Spotify-based API."
        )
    )
    # The mutually exclusive group ensures that -d, -s, and -p cannot be mixed.
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-d",
        "--directory",
        help="Directory containing MP3 tracks to process",
        type=str,
    )
    group.add_argument(
        "-s",
        "--songs",
        help="File containing Spotify track URLs to download",
        type=str,
    )
    group.add_argument(
        "-p",
        "--playlist",
        help="Spotify playlist ID or URL to download tracks from",
        type=str,
    )
    parser.add_argument(
        "--delay",
        help=(
            "Delay between downloads in seconds "
            "(default: 60 for directory/playlist, 20 for songs file)"
        ),
        type=int,
    )
    parser.add_argument(
        "--log-level",
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Default is INFO.",
        default="INFO",
        type=str,
    )
    args = parser.parse_args()

    numeric_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(
        level=numeric_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    spotify_client = SpotifyClient()

    if args.directory:
        delay_val = args.delay if args.delay is not None else 20
        enhance_tracks(spotify_client, tracks_dir=args.directory, delay=delay_val)
    elif args.songs:
        delay_val = args.delay if args.delay is not None else 20
        process_songs_file(spotify_client, songs_file=args.songs, delay=delay_val)
    elif args.playlist:
        delay_val = args.delay if args.delay is not None else 20
        download_playlist(
            spotify_client, playlist_id=args.playlist, download_dir=".", delay=delay_val
        )


if __name__ == "__main__":
    main()
