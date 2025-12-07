import azure.cognitiveservices.speech as speechsdk
import html


class AzureTTSEngine:
    def __init__(self, key: str, region: str, voice: str = "en-US-AriaNeural"):
        self.speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        self.speech_config.speech_synthesis_voice_name = voice

        self.valid_styles = {
            "en-US-AriaNeural": [
                "chat", "customerservice", "narration-professional",
                "newscast-casual", "newscast-formal",
                "cheerful", "empathetic", "angry", "sad", "excited",
                "friendly", "terrified", "shouting", "unfriendly",
                "whispering", "hopeful"
            ]
        }

        self.emotion_map = {
            "anger": ("angry", "+10%", "+2Hz", "1.3"),
            "disgust": ("unfriendly", "-5%", "-2Hz", "1.1"),
            "fear": ("terrified", "+5%", "+3Hz", "1.2"),
            "joy": ("cheerful", "+10%", "+2Hz", "1.2"),
            "neutral": ("narration-professional", "+0%", "+0Hz", "1.0"),
            "sadness": ("sad", "-10%", "-3Hz", "1.2"),
            "surprise": ("excited", "+12%", "+3Hz", "1.3"),
            "default": ("narration-professional", "+0%", "+0Hz", "1.0")
        }
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )


    def synthesize(self, text: str, output_path: str, emotion="neutral"):
        if not text.strip():
            print(f"Skipping empty text segment.")
            return

        style, rate, pitch, styledegree = self.emotion_map.get(emotion, self.emotion_map["default"])

        safe_text = html.escape(text)
        voice_name = self.speech_config.speech_synthesis_voice_name
        styles = self.valid_styles.get(voice_name, [])

        # # Если стиль не поддерживается — fallback
        # if style not in styles:
        #     print(f"[⚠️] Voice '{voice_name}' does not support style '{style}', using plain text.")
        #     ssml = f"""
        #     <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>
        #         <voice name='{voice_name}'>
        #             {safe_text}
        #         </voice>
        #     </speak>
        #     """
        # else:
        ssml = f"""
        <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
               xmlns:mstts='http://www.w3.org/2001/mstts'
               xml:lang='en-US'>
            <voice name='{voice_name}'>
                <mstts:express-as style='{style}' styledegree='{styledegree}'>
                    <prosody rate='{rate}' pitch='{pitch}'>
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>
        """

        print(f"Synthesizing → emotion='{emotion}', style='{style}', "
              f"rate={rate}, pitch={pitch}, styledegree={styledegree}")

        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config,
            audio_config=audio_config
        )

        result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Audio saved: {output_path}")
        else:
            cancellation = result.cancellation_details
            print("Speech synthesis canceled:", cancellation.reason)
            if cancellation.reason == speechsdk.CancellationReason.Error:
                print("Error details:", cancellation.error_details)