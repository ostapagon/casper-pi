"""Wake word detection using pre-trained Porcupine model"""

import pvporcupine
from typing import Optional, Callable


class WakeWordDetector:
    """Wake word detector using Picovoice Porcupine."""
    
    def __init__(self, keyword: str = "computer", sensitivity: float = 0.5):
        """
        Initialize wake word detector.
        
        Args:
            keyword: Pre-trained keyword (e.g., "computer", "hey siri", "alexa")
            sensitivity: Detection sensitivity (0.0 to 1.0)
        """
        self.keyword = keyword
        self.sensitivity = sensitivity
        self.porcupine: Optional[pvporcupine.Porcupine] = None
        self.callback: Optional[Callable[[], None]] = None
        
    def initialize(self, access_key: Optional[str] = None) -> None:
        """
        Initialize Porcupine with wake word model.
        
        Args:
            access_key: Picovoice access key (optional, uses free tier if None)
        """
        try:
            # Try to initialize with the specified keyword
            # Porcupine has pre-trained models for common keywords
            keywords = [self.keyword]
            
            self.porcupine = pvporcupine.create(
                keywords=keywords,
                sensitivities=[self.sensitivity],
                access_key=access_key
            )
        except Exception as e:
            # If keyword not available, try with "computer" as fallback
            if self.keyword != "computer":
                print(f"Warning: Keyword '{self.keyword}' not available, using 'computer'")
                self.keyword = "computer"
                self.porcupine = pvporcupine.create(
                    keywords=["computer"],
                    sensitivities=[self.sensitivity],
                    access_key=access_key
                )
            else:
                raise RuntimeError(f"Failed to initialize Porcupine: {e}")
    
    def set_callback(self, callback: Callable[[], None]) -> None:
        """Set callback function to call when wake word is detected."""
        self.callback = callback
    
    def process(self, audio_frame: bytes) -> bool:
        """
        Process audio frame and detect wake word.
        
        Args:
            audio_frame: Audio frame bytes (must match Porcupine frame length)
            
        Returns:
            True if wake word detected, False otherwise
        """
        if self.porcupine is None:
            raise RuntimeError("Wake word detector not initialized")
        
        # Convert bytes to int16 array
        import array
        pcm = array.array('h', audio_frame)
        pcm = pcm[:self.porcupine.frame_length]
        
        # Pad if necessary
        if len(pcm) < self.porcupine.frame_length:
            pcm.extend([0] * (self.porcupine.frame_length - len(pcm)))
        
        keyword_index = self.porcupine.process(pcm)
        
        if keyword_index >= 0:
            if self.callback:
                self.callback()
            return True
        
        return False
    
    def get_frame_length(self) -> int:
        """Get required frame length for Porcupine."""
        if self.porcupine is None:
            raise RuntimeError("Wake word detector not initialized")
        return self.porcupine.frame_length
    
    def get_sample_rate(self) -> int:
        """Get required sample rate for Porcupine."""
        if self.porcupine is None:
            raise RuntimeError("Wake word detector not initialized")
        return self.porcupine.sample_rate
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self.porcupine is not None:
            self.porcupine.delete()
            self.porcupine = None

