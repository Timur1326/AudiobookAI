import os
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk

from core.tts.base_tts import BaseTTS

DEFAULT_NARRATOR_VOICE = "en-US-BrianNeural"   # мужской, нарраторский
DEFAULT_REGION = "eastus"


class AzureTTS(BaseTTS):

    def __init__(self, api_key: str | None = None, region: str | None = None):
        key = api_key or os.environ.get("AZURE_SPEECH_KEY")
        if not key:
            raise ValueError("AZURE_SPEECH_KEY не задан в .env")
        self.region = region or os.environ.get("AZURE_SPEECH_REGION", DEFAULT_REGION)
        self.config = speechsdk.SpeechConfig(subscription=key, region=self.region)
        self.config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
        )

    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_NARRATOR_VOICE,
        output_path: Path = None,
    ) -> Path:
        if output_path is None:
            raise ValueError("output_path обязателен")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.config.speech_synthesis_voice_name = voice_id
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.config,
            audio_config=audio_config,
        )

        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            raise RuntimeError(f"Azure TTS error: {details.reason} — {details.error_details}")

        return output_path

    def list_voices(self, language: str = "en-US") -> list[dict]:
        """Вернуть список нейронных голосов для языка."""
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.config,
            audio_config=None,
        )
        result = synthesizer.get_voices_async(language).get()
        if result.reason != speechsdk.ResultReason.VoicesListRetrieved:
            raise RuntimeError(f"Не удалось получить голоса: {result.reason}")

        return [
            {
                "id":     v.short_name,
                "name":   v.local_name,
                "gender": v.gender.name,
                "locale": v.locale,
            }
            for v in result.voices
            if "Neural" in v.voice_type.name
        ]