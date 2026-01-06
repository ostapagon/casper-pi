"""Gemini provider implementation with streaming STT, LLM, and TTS"""

import asyncio
import os
from typing import AsyncIterator, Optional
import google.generativeai as genai
from google.cloud import speech_v1
from google.cloud import texttospeech_v1

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    """Gemini provider with Google Cloud STT and TTS."""
    
    def __init__(self):
        self.gemini_model = None
        self.speech_client = None
        self.tts_client = None
        self.conversation_history = []
        
    async def initialize(self, config: dict) -> None:
        """Initialize Gemini and Google Cloud clients."""
        # Initialize Gemini
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        genai.configure(api_key=api_key)
        self.gemini_model = genai.GenerativeModel('gemini-pro')
        
        # Initialize Google Cloud Speech-to-Text
        self.speech_client = speech_v1.SpeechClient()
        
        # Initialize Google Cloud Text-to-Speech
        self.tts_client = texttospeech_v1.TextToSpeechClient()
        
    async def stream_speech_to_text(
        self,
        audio_chunk_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        Stream audio chunks to Google Cloud Speech-to-Text API.
        
        Uses streaming recognition with interim results.
        """
        # Configure streaming recognition
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            enable_automatic_punctuation=True,
            enable_interim_results=True,  # Get interim results for streaming
        )
        
        streaming_config = speech_v1.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
        )
        
        # Use a queue to bridge async audio stream to sync generator
        import queue
        audio_queue = queue.Queue()
        stop_flag = asyncio.Event()
        
        # Task to feed audio chunks to queue
        async def audio_feeder():
            try:
                async for chunk in audio_chunk_stream:
                    audio_queue.put(chunk)
                    if stop_flag.is_set():
                        break
            except Exception as e:
                print(f"Error in audio feeder: {e}")
            finally:
                audio_queue.put(None)  # Sentinel
        
        # Create streaming request generator (sync, for Google Cloud API)
        def request_generator():
            # First request with config
            yield speech_v1.StreamingRecognizeRequest(
                streaming_config=streaming_config
            )
            
            # Then stream audio chunks from queue
            while True:
                try:
                    chunk = audio_queue.get(timeout=1.0)
                    if chunk is None:  # Sentinel
                        break
                    yield speech_v1.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    if stop_flag.is_set():
                        break
                    continue
                except Exception as e:
                    print(f"Error in request generator: {e}")
                    break
        
        # Start audio feeder task
        feeder_task = asyncio.create_task(audio_feeder())
        
        try:
            # Run streaming recognition in thread pool (it's a blocking call)
            loop = asyncio.get_event_loop()
            
            def run_recognition():
                requests = request_generator()
                return self.speech_client.streaming_recognize(requests)
            
            stream = await loop.run_in_executor(None, run_recognition)
            
            # Process responses and yield text chunks
            for response in stream:
                if not response.results:
                    continue
                
                for result in response.results:
                    if result.alternatives:
                        transcript = result.alternatives[0].transcript
                        if transcript:
                            yield transcript
                            
                            # If this is a final result, yield a separator
                            if result.is_final_result:
                                yield "\n"
        finally:
            stop_flag.set()
            feeder_task.cancel()
            try:
                await feeder_task
            except asyncio.CancelledError:
                pass
    
    async def stream_generate_response(
        self,
        text_stream: AsyncIterator[str],
        conversation_history: Optional[list] = None
    ) -> AsyncIterator[str]:
        """
        Stream text to Gemini API and yield response chunks.
        
        Collects text from stream, then streams Gemini response.
        """
        # Collect text from stream
        full_text = ""
        async for chunk in text_stream:
            full_text += chunk
        
        if not full_text.strip():
            return
        
        # Add to conversation history
        if conversation_history is None:
            conversation_history = self.conversation_history
        
        conversation_history.append({"role": "user", "content": full_text})
        
        # Generate response with streaming
        response = await asyncio.to_thread(
            self.gemini_model.generate_content,
            full_text,
            stream=True
        )
        
        # Stream response chunks
        assistant_response = ""
        for chunk in response:
            if chunk.text:
                assistant_response += chunk.text
                yield chunk.text
        
        # Add assistant response to history
        if assistant_response:
            conversation_history.append({
                "role": "assistant",
                "content": assistant_response
            })
    
    async def stream_text_to_speech(
        self,
        text_stream: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """
        Stream text to Google Cloud Text-to-Speech API.
        
        Collects text chunks and synthesizes in sentence-sized chunks.
        """
        # Collect text from stream
        full_text = ""
        async for chunk in text_stream:
            full_text += chunk
        
        if not full_text.strip():
            return
        
        # Split into sentences for better streaming
        import re
        sentences = re.split(r'[.!?]\s+', full_text)
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            # Synthesize sentence
            synthesis_input = texttospeech_v1.SynthesisInput(text=sentence)
            voice = texttospeech_v1.VoiceSelectionParams(
                language_code="en-US",
                ssml_gender=texttospeech_v1.SsmlVoiceGender.NEUTRAL,
            )
            audio_config = texttospeech_v1.AudioConfig(
                audio_encoding=texttospeech_v1.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
            )
            
            response = await asyncio.to_thread(
                self.tts_client.synthesize_speech,
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            # Yield audio in chunks
            audio_data = response.audio_content
            chunk_size = 4096
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i + chunk_size]
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        # Google Cloud clients don't need explicit cleanup
        self.speech_client = None
        self.tts_client = None
        self.gemini_model = None

