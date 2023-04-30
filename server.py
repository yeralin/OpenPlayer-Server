from dotenv import load_dotenv;load_dotenv()
from os import getenv
from streamers.youtube import YouTubeStreamer
from streamers.spotify import SpotifyStreamer
from streamers.exceptions import StreamerError
from models import Version
from flask import Flask, Response, jsonify, request
from flask_httpauth import HTTPBasicAuth


app = Flask(__name__)
auth = HTTPBasicAuth()
spotify_streamer = SpotifyStreamer()
youtube_streamer = YouTubeStreamer()


@auth.verify_password
def verify_password(username, password):
    return username == getenv("USERNAME") \
        and password == getenv("PASSWORD")


@app.route('/version', methods=['GET'])
def version():
    return jsonify(Version('0.0.3'))


@app.route('/search', methods=['GET'])
@auth.login_required
def search():
    search_query = request.args.get('q')
    limit = int(request.args.get('limit', 20))
    if not search_query:
        return "Missing 'q' query param", 400
    spotify_results = spotify_streamer.search(
        query=search_query, limit=limit//2)
    youtube_results = youtube_streamer.search(
        query=search_query, limit=limit//2)
    return jsonify(spotify_results + youtube_results)

@app.route('/stream', methods=['GET'])
@auth.login_required
def stream():
    id = request.args.get('id')
    download = request.args.get('download', False)
    if not id:
        return 'Missing id query param', 400
    try:
        track_id = spotify_streamer.parse_spotify_track_id(id)
        video_id = youtube_streamer.parse_youtube_video_id(id)
        if track_id:
            stream, title, duration, size = spotify_streamer.request_stream(track_id)
        elif video_id:
            stream, title, duration, size = youtube_streamer.request_stream(video_id)
        headers = {
            'Content-Length': str(size),
            'Audio-Duration': str(duration),
            'Content-Type': 'audio/mpeg'
        }
        if download:
            headers['Content-Disposition'] = f'attachment; filename="{title}.mp3"'
    except StreamerError as e:
        return str(e), 400
    return Response(stream(), headers=headers)

@app.route(SpotifyStreamer.search_path, methods=['GET'])
@auth.login_required
def search_spotify():
    search_query = request.args.get('q')
    limit = int(request.args.get('limit', 20))
    if not search_query:
        return "Missing 'q' query param", 400
    results = spotify_streamer.search(query=search_query, limit=limit)
    return jsonify(results)


@app.route(YouTubeStreamer.search_path, methods=['GET'])
@auth.login_required
def search_youtube():
    search_query = request.args.get('q')
    limit = int(request.args.get('limit', 20))
    if not search_query:
        return "Missing 'q' query param", 400
    results = youtube_streamer.search(query=search_query, limit=limit)
    return jsonify(results)


@app.route(SpotifyStreamer.stream_path, methods=['GET', 'HEAD'])
@auth.login_required
def stream_spotify():
    method = request.method
    track_id = request.args.get('trackId')
    download = request.args.get('download', False)
    if not track_id:
        return "Missing 'trackId' query param", 400
    try:
        stream, title, duration, size = spotify_streamer.request_stream(track_id)
        headers = {
            'Content-Length': str(size),
            'Audio-Duration': str(duration),
            'Content-Type': 'audio/mpeg'
        }
        if download:
            headers['Content-Disposition'] = f'attachment; filename="{title}.mp3"'
    except StreamerError as e:
        return str(e), 400
    return Response(stream() if method == 'GET' else {}, headers=headers)


@app.route(YouTubeStreamer.stream_path, methods=['GET'])
@auth.login_required
def stream_youtube():
    video_id = request.args.get('videoId')
    download = request.args.get('download', False)
    if not video_id:
        return 'Missing videoId query param', 400
    try:
        stream, title, duration, size = youtube_streamer.request_stream(video_id)
        headers = {
            'Content-Length': str(size),
            'Audio-Duration': str(duration),
            'Content-Type': 'audio/mpeg'
        }
        if download:
            headers['Content-Disposition'] = f'attachment; filename="{title}.mp3"'
    except StreamerError as e:
        return str(e), 400
    return Response(stream(), headers=headers)


if __name__ == "__main__":
    import bjoern
    bjoern.run(app, "0.0.0.0", 8000)
