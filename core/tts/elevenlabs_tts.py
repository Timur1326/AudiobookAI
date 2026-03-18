import os
import time
from pathlib import Path

from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

from core.tts.base_tts import BaseTTS


# Голос по умолчанию — нейтральный нарратор (Rachel)
DEFAULT_NARRATOR_VOICE = "SAz9YHcvj6GT2YYXdXww"

# Модель: eleven_turbo_v2_5 (быстро, дёшево), eleven_multilingual_v2 (лучше качество)
DEFAULT_MODEL = "eleven_turbo_v2_5"


class ElevenLabsTTS(BaseTTS):

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("ELEVENLABS_API_KEY не задан")
        self.client = ElevenLabs(api_key=key)
        self.model = model

    # ──────────────────────────────────────────────────────────────
    # Публичные методы
    # ──────────────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_NARRATOR_VOICE,
        output_path: Path = None,
        voice_settings: VoiceSettings | None = None,
    ) -> Path:
        """Синтезировать один текстовый фрагмент → mp3."""
        if output_path is None:
            raise ValueError("output_path обязателен")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        settings = voice_settings or VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
        )

        audio = self.client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=self.model,
            voice_settings=settings,
        )

        with open(output_path, "wb") as f:
            f.write(b"".join(audio))

        return output_path

    def list_voices(self) -> list[dict]:
        """Вернуть список доступных голосов."""
        response = self.client.voices.get_all()
        return [
            {"id": v.voice_id, "name": v.name, "category": v.category}
            for v in response.voices
        ]