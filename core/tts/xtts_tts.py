"""
XTTS v2 TTS engine (Coqui TTS, local).

voice_id = path to a reference WAV file (3–30 sec) for voice cloning.

Usage:
    tts = XttsTTS()
    tts.synthesize("Hello world", voice_id="storage/voices/alice.wav", output_path=Path("out.wav"))
"""

from pathlib import Path

from core.tts.base_tts import BaseTTS

DEFAULT_LANGUAGE = "en"


class XttsTTS(BaseTTS):

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        self.language = language
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is not None:
            return
        from TTS.api import TTS
        print("Loading XTTS v2 model (first run may download ~1.8 GB)...")
        self._model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
        print("XTTS v2 ready.")

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
    ) -> Path:
        """
        voice_id: path to reference WAV file for voice cloning.
        output_path: where to save the result (wav or mp3).
        """
        self._load_model()

        reference = Path(voice_id)
        if not reference.exists():
            raise FileNotFoundError(f"Reference audio not found: {reference}")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # XTTS outputs WAV — convert to mp3 if needed
        wav_path = output_path.with_suffix(".wav")

        self._model.tts_to_file(
            text=text,
            speaker_wav=str(reference),
            language=self.language,
            file_path=str(wav_path),
        )

        if output_path.suffix == ".mp3":
            from pydub import AudioSegment
            AudioSegment.from_wav(str(wav_path)).export(str(output_path), format="mp3")
            wav_path.unlink()

        return output_path

    def list_voices(self) -> list[dict]:
        """Returns reference WAV files from storage/voices/."""
        voices_dir = Path("storage/voices")
        if not voices_dir.exists():
            return []
        return [
            {"id": str(f), "name": f.stem}
            for f in sorted(voices_dir.glob("*.wav"))
        ]