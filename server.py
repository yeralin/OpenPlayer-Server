from os import getenv
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_httpauth import HTTPBasicAuth

from models import Version
from streamers.exceptions import StreamerError
from streamers.spotify import SpotifyStreamer

app = Flask(__name__)
app.url_map.strict_slashes = False
auth = HTTPBasicAuth()
spotify_streamer = SpotifyStreamer()


@auth.verify_password
def verify_password(username, password):
    return username == getenv("USERNAME") and password == getenv("PASSWORD")


@app.route("/version", methods=["GET"])
def version():
    return jsonify(Version("0.0.3"))


@app.route(SpotifyStreamer.search_path, methods=["GET"])
@auth.login_required
def search_spotify():
    search_query = request.args.get("q")
    limit = int(request.args.get("limit", 20))
    if not search_query:
        return "Missing 'q' query param", 400
    results = spotify_streamer.search(query=search_query, limit=limit)
    return jsonify(results)


@app.route(SpotifyStreamer.stream_path, methods=["GET", "HEAD"])
@auth.login_required
def stream_spotify():
    track_id = request.args.get("trackId")
    download = request.args.get("download", False)
    range_header = request.headers.get("Range")
    if not track_id:
        return "Missing 'trackId' query param", 400
    try:
        if range_header:
            range_start, range_end = range_header.replace("bytes=", "").split("-")
            range_start = int(range_start) if range_start else 0
            range_end = int(range_end) if range_end else None
        else:
            range_start, range_end = (0, None)
        stream, title, duration, size = spotify_streamer.request_stream(
            track_id, range_start, range_end
        )
        if not range_end:
            range_end = size
        headers = {
            "Content-Range": f"bytes {range_start}-{range_end - 1}/{size}",
            "Content-Length": str(range_end - range_start),
            "Accept-Ranges": "bytes",
            "Content-Type": "audio/mp3",
            "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{quote(title)}.mp3"',
            "Audio-Duration": str(duration),  # Custom header
        }
    except StreamerError as e:
        return str(e), 400
    return Response(
        stream_with_context(stream()) if request.method == "GET" else {},
        headers=headers,
        status=206 if range_header else 200,
    )


if __name__ == "__main__":
    app.run("0.0.0.0", 8000)
