from TTS.api import TTS

class TTSEngine:
    def __init__(self, model_name="tts_models/multilingual/multi-dataset/xtts_v2"):
        self.tts = TTS(model_name=model_name, progress_bar=False)
        self.gpt_latent, self.spk_emb = None, None

    def set_voice(self, ref_voice_path: str):
        # доступ к модели через synthesizer
        xtts_model = self.tts.synthesizer.tts_model
        self.gpt_latent, self.spk_emb = xtts_model.get_conditioning_latents(audio_path=[ref_voice_path])

    def synthesize(self, annotated, lang="en"):
        xtts_model = self.tts.synthesizer.tts_model
        wavs = []
        for s in annotated:
            wav = xtts_model.inference(
                text=s["text"],
                language=lang,
                gpt_cond_latent=self.gpt_latent,
                speaker_embedding=self.spk_emb,
                temperature=0.7,
                do_sample=False
            )["wav"]
            wavs.append(wav)
        return wavs