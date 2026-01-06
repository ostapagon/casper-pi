"""Base provider interface for STT, LLM, and TTS"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class BaseProvider(ABC):
    """Abstract base class for voice assistant providers."""
    
    @abstractmethod
    async def stream_speech_to_text(
        self, 
        audio_chunk_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        Stream audio chunks to STT API and yield text chunks as they're recognized.
        
        Args:
            audio_chunk_stream: Async iterator of audio chunks (bytes)
            
        Yields:
            Text chunks (str) as they're recognized (interim results)
        """
        pass
    
    @abstractmethod
    async def stream_generate_response(
        self,
        text_stream: AsyncIterator[str],
        conversation_history: Optional[list] = None
    ) -> AsyncIterator[str]:
        """
        Stream text to LLM API and yield response text chunks as they're generated.
        
        Args:
            text_stream: Async iterator of text chunks
            conversation_history: Optional list of previous messages
            
        Yields:
            Response text chunks (str) as they're generated (token-by-token)
        """
        pass
    
    @abstractmethod
    async def stream_text_to_speech(
        self,
        text_stream: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """
        Stream text to TTS API and yield audio chunks as they're synthesized.
        
        Args:
            text_stream: Async iterator of text chunks
            
        Yields:
            Audio chunks (bytes) as they're synthesized
        """
        pass
    
    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Initialize the provider with configuration."""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources when done."""
        pass

