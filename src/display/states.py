"""Display state definitions"""

from enum import Enum, auto


class DisplayState(Enum):
    """Display states"""
    SLEEP = auto()
    IDLE = auto()  # Future: waiting for wake word
    ACTIVE = auto()  # Future: conversation active

