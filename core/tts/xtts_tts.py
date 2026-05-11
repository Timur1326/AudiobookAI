"""
XTTS v2 TTS backend (Coqui TTS, runs locally).

voice_id is a path to a reference audio file (3-30 sec) used for voice cloning.
The model is loaded lazily on the first synthesize call and reused for all subsequent calls.
"""

import re
from pathlib import Path

from core.tts.base_tts import BaseTTS

DEFAULT_LANGUAGE = "en"
XTTS_CHAR_LIMIT  = 230


def _split_text(text: str, limit: int = XTTS_CHAR_LIMIT) -> list[str]:
    """Split text into chunks under the XTTS character limit, breaking at sentences."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(current) + len(sentence) + 1 <= limit:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text]


class XttsTTS(BaseTTS):
    """TTS backend that synthesizes audio locally using the XTTS v2 model."""

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        self.language = language
        self._model = None  # loaded on first synthesize call

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
        **kwargs,
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

        chunks = _split_text(text)

        if len(chunks) == 1:
            wav_path = output_path.with_suffix(".wav")
            self._model.tts_to_file(
                text=chunks[0],
                speaker_wav=str(reference),
                language=self.language,
                file_path=str(wav_path),
            )
            segments = [wav_path]
        else:
            segments = []
            for i, chunk in enumerate(chunks):
                chunk_wav = output_path.with_suffix(f".chunk{i}.wav")
                self._model.tts_to_file(
                    text=chunk,
                    speaker_wav=str(reference),
                    language=self.language,
                    file_path=str(chunk_wav),
                )
                segments.append(chunk_wav)

            # Merge all chunks into one wav
            from pydub import AudioSegment as _AS
            merged = sum((_AS.from_wav(str(s)) for s in segments), _AS.empty())
            wav_path = output_path.with_suffix(".wav")
            merged.export(str(wav_path), format="wav")
            for s in segments:
                s.unlink(missing_ok=True)

        if output_path.suffix == ".mp3":
            from pydub import AudioSegment
            AudioSegment.from_wav(str(wav_path)).export(str(output_path), format="mp3")
            wav_path.unlink()
        else:
            wav_path.rename(output_path)

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