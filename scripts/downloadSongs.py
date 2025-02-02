import os
import time
import requests
from mutagen.mp3 import MP3
from urllib.parse import quote, unquote
from fuzzywuzzy import fuzz
import subprocess

# Paths
TRACKS_DIR = "."
SONGS_FILE = "songs.txt"

class SpotifyClient:
    # Endpoints
    SEARCH_URL = "https://music.yeralin.net/search/spotify?q={}"
    STREAM_URL = "https://music.yeralin.net/stream/spotify?trackId={}&download=true"

    # Authentication Header
    AUTH_HEADERS = {"Authorization": "Basic ZGFuaXlhcjpkajJndmNQNiVvTiVlcQ=="}

    @staticmethod
    def search_spotify(track_name):
        """Search for Spotify track ID."""
        response = requests.get(SpotifyClient.SEARCH_URL.format(quote(track_name)), headers=SpotifyClient.AUTH_HEADERS)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                for entry in data:
                    entry["match_score"] = fuzz.ratio(
                        entry["title"].lower(), track_name.lower()
                    )
                best_match = max(
                    data, key=lambda x: x["match_score"], default={"match_score": 0}
                )
                if best_match["match_score"] > 80:  # Threshold for fuzzy matching
                    print(f"Best match for '{track_name}' is '{best_match}'")
                    return best_match["url"]
                print(
                    f"No close match found for '{track_name}'. Best match: '{best_match}'"
                )
        else:
            print(
                f"Failed to search Spotify for '{track_name}'. HTTP {response.status_code}"
            )
        return None

    @staticmethod
    def download_spotify_track(track_url, file_path=None):
        """Download the track using the Spotify track URL."""
        download_url = f"{track_url}&download=true"
        response = requests.get(download_url, headers=SpotifyClient.AUTH_HEADERS)
        if response.status_code == 200 or response.status_code == 206:
            content_disposition = response.headers.get("Content-Disposition", "")
            if "filename=" in content_disposition:
                filename = unquote(content_disposition.split("filename=")[-1].strip('"'))
                invalid_chars = '<>:"/\\|?*'
                for char in invalid_chars:
                    filename = filename.replace(char, "_")
                dirname = "."
                if file_path:
                    dirname = os.path.dirname(file_path)
                    os.remove(file_path)  # Delete the old file
                file_path = os.path.join(dirname, filename)
            with open(file_path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded track to {file_path}")
        elif response.status_code == 400:
            print(f"Spotify track ID not found for '{track_url}'")
        else:
            print(f"Failed to download track. HTTP {response.status_code}")


def process_tracks(spotify_client: SpotifyClient):
    """Process all tracks in the directory."""
    for root, _, files in os.walk(TRACKS_DIR):
        for file in files:
            if file.lower().endswith(".mp3"):
                filepath = os.path.join(root, file)
                audio = MP3(filepath)
                bitrate = audio.info.bitrate // 1000  # Convert to kbps
                if bitrate < 320:
                    if (
                        audio
                        and audio.tags
                        and "TPE1" in audio.tags
                        and "TIT2" in audio.tags
                    ):
                        artist = audio.tags["TPE1"].text[0]
                        title = audio.tags["TIT2"].text[0]
                        track_name = f"{artist} - {title}"
                    else:
                        track_name = os.path.splitext(file)[
                            0
                        ]  # Extract name from filename
                    print(
                        f"Track '{track_name}' has bitrate {bitrate}kbps. Processing..."
                    )
                    track_url = spotify_client.search_spotify(track_name)
                    if track_url:
                        spotify_client.download_spotify_track(track_url, filepath)
                        time.sleep(60)
                    else:
                        print(f"Spotify track ID not found for '{track_name}'")
                else:
                    print(f"Track '{file}' has acceptable bitrate ({bitrate}kbps)")


def process_songs_file(spotify_client: SpotifyClient):
    """Process the songs file to download tracks."""
    with open(SONGS_FILE, "r") as file:
        for line in file:
            track_id = line.strip()
            if "spotify.com" in track_id:
                track_url = SpotifyClient.STREAM_URL.format(track_id)
                spotify_client.download_spotify_track(track_url)
                time.sleep(20)
            else:
                print(f"Invalid track URL: {track_id}")


if __name__ == "__main__":
    spotify_client = SpotifyClient()
    process_songs_file(spotify_client)
