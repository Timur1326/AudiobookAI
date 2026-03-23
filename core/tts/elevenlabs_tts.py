import os
import time
from pathlib import Path

from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

from core.tts.base_tts import BaseTTS


DEFAULT_NARRATOR_VOICE = "SAz9YHcvj6GT2YYXdXww"

DEFAULT_MODEL = "eleven_turbo_v2_5"


class ElevenLabsTTS(BaseTTS):

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("ELEVENLABS_API_KEY не задан")
        self.client = ElevenLabs(api_key=key)
        self.model = model


    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_NARRATOR_VOICE,
        output_path: Path = None,
        voice_settings: VoiceSettings | None = None,
    ) -> Path:
        if output_path is None:
            raise ValueError("output_path is required")

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
        response = self.client.voices.get_all()
        return [
            {"id": v.voice_id, "name": v.name, "category": v.category}
            for v in response.voices
        ]