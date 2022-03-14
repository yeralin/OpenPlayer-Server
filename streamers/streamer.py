
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Generator, List, Tuple

from models import Entry


class Streamer(ABC):

    @property
    def stream_path(self):
        raise NotImplementedError

    @property
    def search_path(self):
        raise NotImplementedError

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> List[Entry]:
        pass

    @abstractmethod
    def request_stream(self, id: str) -> Tuple[Generator[BytesIO, None, None], int, int]:
        pass

    @abstractmethod
    def generate_stream(self, payload: Any, bitrate: int, size: int) -> Generator[BytesIO, None, None]:
        pass
