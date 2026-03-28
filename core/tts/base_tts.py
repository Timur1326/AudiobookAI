from abc import ABC, abstractmethod
from pathlib import Path
from core.models import Paragraph


class BaseTTS(ABC):

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, output_path: Path) -> Path:
        """Синтезировать текст → сохранить в output_path, вернуть путь."""
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """Вернуть список доступных голосов [{id, name, ...}]."""
        ...