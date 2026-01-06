"""Audio I/O for streaming microphone input and speaker output"""

import pyaudio
import asyncio
from typing import AsyncIterator, Optional


class AudioStream:
    """Audio streaming for microphone input and speaker output."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None
    ):
        """
        Initialize audio stream.
        
        Args:
            sample_rate: Audio sample rate (Hz)
            channels: Number of audio channels (1 = mono, 2 = stereo)
            chunk_size: Size of audio chunks in frames
            input_device: Input device index (None = default)
            output_device: Output device index (None = default)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.input_device = input_device
        self.output_device = output_device
        
        self.audio = pyaudio.PyAudio()
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None
        
    def initialize_input(self) -> None:
        """Initialize microphone input stream."""
        self.input_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.input_device,
            frames_per_buffer=self.chunk_size,
            stream_callback=None
        )
        self.input_stream.start_stream()
    
    def initialize_output(self) -> None:
        """Initialize speaker output stream."""
        self.output_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            output_device_index=self.output_device,
            frames_per_buffer=self.chunk_size,
            stream_callback=None
        )
        self.output_stream.start_stream()
    
    async def stream_microphone(self) -> AsyncIterator[bytes]:
        """
        Stream audio chunks from microphone.
        
        Yields:
            Audio chunks (bytes) from microphone
        """
        if self.input_stream is None:
            self.initialize_input()
        
        while True:
            try:
                # Read audio chunk (non-blocking)
                data = self.input_stream.read(
                    self.chunk_size,
                    exception_on_overflow=False
                )
                yield data
            except Exception as e:
                print(f"Error reading audio: {e}")
                await asyncio.sleep(0.01)
    
    async def play_audio(self, audio_chunk: bytes) -> None:
        """
        Play audio chunk through speaker.
        
        Args:
            audio_chunk: Audio chunk bytes to play
        """
        if self.output_stream is None:
            self.initialize_output()
        
        try:
            self.output_stream.write(audio_chunk)
        except Exception as e:
            print(f"Error playing audio: {e}")
    
    async def stream_to_speaker(self, audio_stream: AsyncIterator[bytes]) -> None:
        """
        Stream audio chunks to speaker.
        
        Args:
            audio_stream: Async iterator of audio chunks
        """
        async for chunk in audio_stream:
            await self.play_audio(chunk)
    
    def get_sample_rate(self) -> int:
        """Get audio sample rate."""
        return self.sample_rate
    
    def get_chunk_size(self) -> int:
        """Get audio chunk size."""
        return self.chunk_size
    
    def cleanup(self) -> None:
        """Clean up audio resources."""
        if self.input_stream is not None:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
        
        if self.output_stream is not None:
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
        
        if self.audio is not None:
            self.audio.terminate()

