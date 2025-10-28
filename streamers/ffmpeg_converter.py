"""This module provides FFmpeg-based audio conversion functionality."""
import subprocess
import threading
from typing import Generator, Optional
import logging

logger = logging.getLogger(__name__)


class FFmpegConverter:
    """
    Handles conversion of audio streams using FFmpeg.
    Manages the FFmpeg subprocess and ensures proper cleanup.
    """

    def __init__(self, chunk_size: int = (128 * 1024)) -> None:
        """
        Initialize the FFmpeg converter.

        Args:
            chunk_size: Size of chunks to read/write during conversion.
        """
        self.chunk_size = chunk_size
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._write_thread: Optional[threading.Thread] = None
        self._input_stream = None

    def _async_write(self, ffmpeg_process: subprocess.Popen, stream) -> None:
        """
        Asynchronously write input stream data to FFmpeg stdin.

        Args:
            ffmpeg_process: The FFmpeg subprocess.
            stream: The input stream to read from.
        """
        try:
            while True:
                in_chunk = stream.read(self.chunk_size)
                if not in_chunk:
                    break
                ffmpeg_process.stdin.write(in_chunk)
        except (BrokenPipeError, ValueError) as e:
            logger.debug(f"Write stream closed: {e}")
        except Exception as e:
            logger.error(f"Error writing to FFmpeg stdin: {e}")
        finally:
            try:
                if ffmpeg_process.stdin and not ffmpeg_process.stdin.closed:
                    ffmpeg_process.stdin.close()
            except Exception as e:
                logger.error(f"Error closing FFmpeg stdin: {e}")
            try:
                stream.close()
            except Exception as e:
                logger.debug(f"Error closing input stream: {e}")

    def convert_ogg_to_mp3(
        self,
        input_stream,
        bitrate: int,
        estimated_size: int
    ) -> Generator[bytes, None, None]:
        """
        Convert OGG audio stream to MP3 on the fly using FFmpeg.

        Args:
            input_stream: The input OGG stream.
            bitrate: Target bitrate for MP3 output.
            estimated_size: Estimated output size in bytes.

        Yields:
            bytes: Chunks of MP3 audio data.
        """
        self._input_stream = input_stream
        
        try:
            # Start FFmpeg process
            self._ffmpeg_process = subprocess.Popen(
                ['ffmpeg', '-f', 'ogg', '-i', '-', '-vn', '-b:a', f'{bitrate}k', '-f', 'mp3', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            
            # Start async writer thread
            self._write_thread = threading.Thread(
                target=self._async_write,
                args=(self._ffmpeg_process, input_stream),
                daemon=False
            )
            self._write_thread.start()
            
            transmitted = 0
            try:
                while True:
                    out_chunk = self._ffmpeg_process.stdout.read(self.chunk_size)
                    if not out_chunk:
                        # Pad output if needed to match estimated size
                        if transmitted < estimated_size:
                            yield b'\0' * (estimated_size - transmitted)
                        break
                    transmitted += len(out_chunk)
                    yield out_chunk
            except GeneratorExit:
                logger.debug("Generator exit - client disconnected")
                raise
            except Exception as e:
                logger.error(f"Error reading from FFmpeg stdout: {e}")
                raise
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """
        Clean up FFmpeg process and writer thread.
        Ensures no zombie processes or hanging threads remain.
        """
        # Close FFmpeg stdin if still open
        if self._ffmpeg_process and self._ffmpeg_process.stdin:
            try:
                if not self._ffmpeg_process.stdin.closed:
                    self._ffmpeg_process.stdin.close()
            except Exception as e:
                logger.debug(f"Error closing FFmpeg stdin during cleanup: {e}")

        # Close FFmpeg stdout if still open
        if self._ffmpeg_process and self._ffmpeg_process.stdout:
            try:
                if not self._ffmpeg_process.stdout.closed:
                    self._ffmpeg_process.stdout.close()
            except Exception as e:
                logger.debug(f"Error closing FFmpeg stdout during cleanup: {e}")

        # Terminate FFmpeg process
        if self._ffmpeg_process:
            try:
                if self._ffmpeg_process.poll() is None:  # Process still running
                    self._ffmpeg_process.terminate()
                    try:
                        self._ffmpeg_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        logger.warning("FFmpeg process did not terminate, killing it")
                        self._ffmpeg_process.kill()
                        self._ffmpeg_process.wait()
            except Exception as e:
                logger.error(f"Error terminating FFmpeg process: {e}")
            finally:
                self._ffmpeg_process = None

        # Wait for writer thread to finish
        if self._write_thread and self._write_thread.is_alive():
            try:
                self._write_thread.join(timeout=2)
                if self._write_thread.is_alive():
                    logger.warning("Writer thread did not finish in time")
            except Exception as e:
                logger.error(f"Error joining writer thread: {e}")
            finally:
                self._write_thread = None

        # Close input stream
        if self._input_stream:
            try:
                self._input_stream.close()
            except Exception as e:
                logger.debug(f"Error closing input stream during cleanup: {e}")
            finally:
                self._input_stream = None

    def __del__(self) -> None:
        """Destructor to ensure cleanup on garbage collection."""
        self.cleanup()
