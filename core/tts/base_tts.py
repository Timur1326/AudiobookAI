from abc import ABC, abstractmethod
from pathlib import Path


class BaseTTS(ABC):

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, output_path: Path) -> Path:
        """Synthesize text to speech and save it to output_path. Returns the path to the saved audio file."""
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """Return a list of available voices with their metadata """
        ...