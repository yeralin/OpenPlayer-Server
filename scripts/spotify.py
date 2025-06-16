#!/usr/bin/env python3
"""
Module for downloading songs using a Spotify-based API.

Note:
    For proper naming style, consider renaming this file to 
    "download_songs.py" (i.e. use snake_case).

    This module now supports fetching songs from a Spotify playlist,
    processing local MP3 tracks, downloading tracks from a file of
    Spotify URLs, or syncing local playlist directories to Spotify playlists.
"""

import argparse
import logging
import os
import re
import time
from typing import Optional, Dict, List
from urllib.parse import quote, unquote

import requests
import spotipy
from fuzzywuzzy import fuzz
from mutagen._util import MutagenError
from mutagen.mp3 import MP3
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth


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
        client_id: Optional[str] = os.getenv("SPOTIFY_CLIENT_ID").strip(),
        client_secret: Optional[str] = os.getenv("SPOTIFY_CLIENT_SECRET").strip(),
        spotipy_auth_manager=None,
    ) -> None:
        """
        Initialize the Spotify client with an optional requests.Session
        for connection reuse and initialize a Spotipy client.

        If spotipy_auth_manager is provided, it will be used for Spotipy authentication.
        Otherwise, SpotifyClientCredentials will be used.
        """
        self.session = session if session is not None else requests.Session()
        if spotipy_auth_manager is not None:
            # User-level access
            self.spotify_api = spotipy.Spotify(auth_manager=spotipy_auth_manager)
        else:
            # App-only access
            self.spotify_api = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=client_id, client_secret=client_secret
                )
            )

    @classmethod
    def with_oauth(
        cls,
        session: Optional[requests.Session] = None,
        client_id: Optional[str] = os.getenv("SPOTIFY_CLIENT_ID").strip(),
        client_secret: Optional[str] = os.getenv("SPOTIFY_CLIENT_SECRET").strip(),
        redirect_uri: Optional[str] = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
        scope: Optional[str] = None,
    ):
        """
        Alternative constructor that uses SpotifyOAuth for user-level actions.
        """
        if scope is None:
            # Default to all scopes needed for user-level actions
            scope = (
                "playlist-read-private playlist-read-collaborative "
                "playlist-modify-public playlist-modify-private "
                "user-read-private user-read-email"
            )
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
        )
        return cls(session=session, client_id=client_id, client_secret=client_secret, spotipy_auth_manager=auth_manager)

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

    def create_playlist(self, playlist_name: str, user_id: str) -> Optional[str]:
        """
        Create a Spotify playlist with the given name for the user if it doesn't exist.

        :param playlist_name: Name of the playlist to create.
        :param user_id: Spotify user ID.
        :return: Playlist ID if created or found, None otherwise.
        """
        # Get all user's playlists (name -> id)
        try:
            playlists = {}
            results = self.spotify_api.current_user_playlists()
            while results:
                for pl in results["items"]:
                    playlists[pl["name"]] = pl["id"]
                if results["next"]:
                    results = self.spotify_api.next(results)
                else:
                    break
        except Exception as exc:
            logging.error("Could not fetch user's playlists: %s", exc)
            return None

        playlist_id = playlists.get(playlist_name)
        if not playlist_id:
            try:
                created = self.spotify_api.user_playlist_create(
                    user=user_id,
                    name=playlist_name,
                    public=True
                )
                playlist_id = created["id"]
                logging.info("Created playlist '%s' (id: %s)", playlist_name, playlist_id)
            except Exception as exc:
                logging.error("Failed to create playlist '%s': %s", playlist_name, exc)
                return None
        else:
            logging.info("Using existing playlist '%s' (id: %s)", playlist_name, playlist_id)
        return playlist_id

    def sync_playlists(self, playlists_root_dir: str, user_id: Optional[str] = None) -> None:
        """
        Sync local playlists (each subdirectory is a playlist) to Spotify.

        For each subdirectory in playlists_root_dir:
            - Use subdirectory name as playlist name.
            - Create the playlist in Spotify if it doesn't exist.
            - For each file in the subdirectory, parse as "Artist - Song.mp3".
            - Find the song in Spotify and add it to the playlist.

        :param playlists_root_dir: Directory containing subdirectories as playlists.
        :param user_id: Spotify user ID. If None, will try to get from Spotify API.
        """
        if not os.path.isdir(playlists_root_dir):
            logging.error("Provided playlists root directory '%s' does not exist or is not a directory.", playlists_root_dir)
            return

        # Get user_id if not provided
        if user_id is None:
            try:
                user_profile = self.spotify_api.me()
                user_id = user_profile["id"]
            except Exception as exc:
                logging.error("Could not get Spotify user ID: %s", exc)
                return

        for subdir in os.listdir(playlists_root_dir):
            subdir_path = os.path.join(playlists_root_dir, subdir)
            if not os.path.isdir(subdir_path):
                continue
            playlist_name = subdir
            playlist_id = self.create_playlist(playlist_name, user_id)
            if not playlist_id:
                continue

            # Fetch all existing track URIs in the playlist to avoid duplicates
            existing_uris = set()
            try:
                results = self.spotify_api.playlist_tracks(playlist_id)
                while True:
                    items = results.get("items", [])
                    for item in items:
                        track = item.get("track")
                        if track and "uri" in track:
                            existing_uris.add(track["uri"])
                    if results.get("next"):
                        results = self.spotify_api.next(results)
                    else:
                        break
            except Exception as exc:
                logging.error("Failed to fetch existing tracks for playlist '%s': %s", playlist_name, exc)
                # If we can't fetch, fallback to adding all tracks (may cause duplicates)
                existing_uris = set()

            # Gather track URIs to add, skipping those already in the playlist
            track_uris = []
            files = os.listdir(subdir_path)
            # Sort files by modification time (oldest first)
            files.sort(key=lambda f: os.path.getmtime(os.path.join(subdir_path, f)))

            for file in files:
                base = os.path.splitext(file)[0]
                # Try to parse "Artist - Song"
                if " - " in base:
                    artist, title = base.split(" - ", 1)
                else:
                    # fallback: treat whole as title
                    artist, title = "", base
                query = f"{artist} {title}".strip()
                try:
                    # Use Spotipy search for best match
                    results = self.spotify_api.search(q=query, type="track", limit=1)
                    items = results.get("tracks", {}).get("items", [])
                    if items:
                        track_uri = items[0]["uri"]
                        if track_uri in existing_uris:
                            logging.info("Track already in playlist, skipping: '%s' (%s)", file, track_uri)
                        else:
                            track_uris.append(track_uri)
                            logging.info("Found track for '%s': %s", file, track_uri)
                    else:
                        logging.warning("No Spotify track found for '%s'", file)
                except Exception as exc:
                    logging.error("Error searching for '%s': %s", file, exc)

            # Add tracks to playlist in batches of 100
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                try:
                    self.spotify_api.playlist_add_items(playlist_id, batch)
                    logging.info("Added %d tracks to playlist '%s'", len(batch), playlist_name)
                except Exception as exc:
                    logging.error("Failed to add tracks to playlist '%s': %s", playlist_name, exc)


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
    # The mutually exclusive group ensures that -e, -s, -p, and -y cannot be mixed.
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-e",
        "--enhance",
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
    group.add_argument(
        "-y",
        "--sync-playlists",
        help="Directory where each sub-directory is a playlist to sync to Spotify",
        type=str,
    )
    parser.add_argument(
        "--delay",
        help=(
            "Delay between downloads in seconds "
            "(default: 20 to wait in between downloads)"
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

    # Determine if user-level actions are needed
    # Use SpotifyOAuth for commands that require user-level data
    if args.sync_playlists:
        # Use user-level OAuth for playlist sync
        spotify_client = SpotifyClient.with_oauth()
    else:
        # For other commands, client credentials is sufficient
        spotify_client = SpotifyClient()

    if args.enhance:
        delay_val = args.delay if args.delay is not None else 20
        enhance_tracks(spotify_client, tracks_dir=args.enhance, delay=delay_val)
    elif args.songs:
        delay_val = args.delay if args.delay is not None else 20
        process_songs_file(spotify_client, songs_file=args.songs, delay=delay_val)
    elif args.playlist:
        delay_val = args.delay if args.delay is not None else 20
        download_playlist(
            spotify_client, playlist_id=args.playlist, download_dir=".", delay=delay_val
        )
    elif args.sync_playlists:
        # No delay argument for sync_playlists, as it's not a download operation
        spotify_client.sync_playlists(args.sync_playlists)


if __name__ == "__main__":
    main()
