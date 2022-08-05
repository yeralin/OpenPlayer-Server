
from io import BytesIO
from os import getenv
import pyyoutube
import re
import subprocess
from typing import Generator, List, Tuple
from pytube import YouTube
from models import Entry
from streamers import utils
from streamers.base_streamer import BaseStreamer
from streamers.exceptions import StreamerError
from pytube.streams import Stream


class YouTubeStreamer(BaseStreamer):

    stream_path = '/stream/youtube'
    search_path = '/search/youtube'
    youtube_video_id_regex = r'([a-zA-Z0-9_-]{11})'

    MUSIC_CATEGORY = '10'

    def __init__(self, search_type: List[str] = ['video'],
                 video_category_id: str = MUSIC_CATEGORY,
                 api_key: str = getenv('YOUTUBE_API_KEY'),
                 chunk_size: int = 50000) -> None:
        super().__init__()
        self.search_type = search_type
        self.video_category_id = video_category_id
        self.youtube_api = pyyoutube.Api(api_key=api_key)
        self.chunk_size = chunk_size

    def _parse_youtube_video_id(self, video_id: str) -> str:
        match = re.search(self.youtube_video_id_regex, video_id)
        if not match:
            return None
        return match.group()

    def get_name(self) -> str:
        return 'YouTube'

    def search(self, query: str, limit: int = 20) -> List[Entry]:
        results = []
        search_output = self.youtube_api.search_by_keywords(
            q=query,
            search_type=self.search_type,
            video_category_id=self.video_category_id,
            limit=limit,
            count=limit)
        for item in search_output.items:
            video_id = item.id.videoId
            title = item.snippet.title
            url = utils.construct_url(self.stream_path, videoId=video_id)
            results.append(Entry(title, url, self.get_name()))
        return results

    def request_stream(self, id: str) -> Tuple[Generator[BytesIO, None, None], str, int, int]:
        video_id = self._parse_youtube_video_id(id)
        if not video_id:
            raise StreamerError(
                'Invalid videoId param, expected ' + self.youtube_video_id_regex)
        youtube_video = YouTube('v='+video_id)
        title = youtube_video.title
        duration = youtube_video.length
        hq_audio = max(youtube_video.streams.filter(
            adaptive=True, only_audio=True), key=lambda s: s.bitrate)
        bitrate = int(hq_audio.abr.replace('kbps', ''))  # hq_audio.abr is rounded
        size = utils.estimate_size(duration, bitrate)
        stream = self.generate_stream(hq_audio, bitrate, size)
        return (stream, title, duration, size)

    def generate_stream(self, payload: Stream, bitrate: int, size: int) -> Generator[BytesIO, None, None]:
        def stream():
            ffmpeg_process = subprocess.Popen(
                'ffmpeg -f webm -i {} -vn -b:a {}k -f mp3 -'.format(
                    payload.url, bitrate).split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            transmitted = 0
            try:
                while True:
                    chunk = ffmpeg_process.stdout.read(self.chunk_size)
                    if not chunk:
                        ffmpeg_process.stdout.close()
                        ffmpeg_process.terminate()
                        if transmitted < size:
                            yield b'\0' * (size-transmitted)
                        return
                    transmitted += len(chunk)
                    yield chunk
            except GeneratorExit:
                ffmpeg_process.stdout.close()
                ffmpeg_process.terminate()
        return stream
