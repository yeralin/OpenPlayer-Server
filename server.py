from dotenv import load_dotenv;load_dotenv()
from os import getenv
from streamers.youtube import YouTubeStreamer
from streamers.spotify import SpotifyStreamer
from streamers.exceptions import StreamerError
from models import Version
from flask import Flask, Response, jsonify, request
from librespot.core import Session
from flask_httpauth import HTTPBasicAuth
import waitress


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


@app.route(SpotifyStreamer.stream_path, methods=['GET'])
@auth.login_required
def stream_spotify():
    track_id = request.args.get('trackId')
    if not track_id:
        return "Missing 'trackId' query param", 400
    try:
        stream, duration, size = spotify_streamer.request_stream(track_id)
    except StreamerError as e:
        return str(e), 400
    return Response(stream(), headers={
        'Content-Length': str(size),
        'Audio-Duration': str(duration),
        'Content-Type': 'audio/mpeg'
    })


@app.route(YouTubeStreamer.stream_path, methods=['GET'])
@auth.login_required
def stream_youtube():
    video_id = request.args.get('videoId')
    if not video_id:
        return 'Missing videoId query param', 400
    try:
        stream, duration, size = youtube_streamer.request_stream(video_id)
    except StreamerError as e:
        return str(e), 400
    return Response(stream(), headers={
        'Content-Length': str(size),
        'Audio-Duration': str(duration),
        'Content-Type': 'audio/mpeg'
    })


if __name__ == "__main__":
    waitress.serve(app, host='0.0.0.0', port=8000)
