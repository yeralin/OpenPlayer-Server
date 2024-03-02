from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Generator, List, Tuple, Optional

from models import Entry


class BaseStreamer(ABC):
    """
    Abstract base class for streamers.
    """

    @property
    def stream_path(self):
        """
        Define the path for streaming.

        Raises:
            NotImplementedError: If the method is not implemented.
        """
        raise NotImplementedError

    @property
    def search_path(self):
        """
        Define the path for search operations.

        Raises:
            NotImplementedError: If the method is not implemented.
        """
        raise NotImplementedError

    @abstractmethod
    def get_name(self) -> str:
        """
        Retrieve the name of the streamer.

        Returns:
            str: The name of the streamer.
        """

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> List[Entry]:
        """
        Search for entries matching the query.

        Args:
            query (str): The search query.
            limit (int, optional): The maximum number of entries to return. Defaults to 20.

        Returns:
            List[Entry]: A list of entries matching the search criteria.
        """

    @abstractmethod
    def request_stream(
        self, track_id: str, range_start: int, range_end: Optional[int]
    ) -> Tuple[Generator[BytesIO, None, None], str, int, int]:
        """
        Request a stream for a specific track.

        Args:
            track_id (str): The unique identifier for the track.
            range_start (int): The starting byte position of the stream.
            range_end (Optional[int]): The ending byte position of the stream. None for no end limit.

        Returns:
            Tuple[Generator[BytesIO, None, None], str, int, int]: A tuple containing the stream generator, 
                content type, start byte, and end byte.
        """

    @abstractmethod
    def generate_stream(
        self, content: Any, range_start: int, range_end: Optional[int]
    ) -> Generator[BytesIO, None, None]:
        """
        Generate a stream from the given content.

        Args:
            content (Any): The content to stream.
            range_start (int): The starting byte position of the stream.
            range_end (Optional[int]): The ending byte position of the stream, or None for no end limit.

        Returns:
            Generator[BytesIO, None, None]: A generator yielding the stream's bytes.
        """