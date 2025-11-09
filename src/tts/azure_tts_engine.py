import azure.cognitiveservices.speech as speechsdk

class AzureTTSEngine:
    def __init__(self, key: str, region: str, voice: str = "en-US-AriaNeural"):
        self.speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        self.speech_config.speech_synthesis_voice_name = voice

    def synthesize(self, text: str, output_path: str, style="general", rate="+0%", pitch="+0Hz"):
        ssml = f"""
        <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
               xmlns:mstts='http://www.w3.org/2001/mstts'
               xml:lang='en-US'>
            <voice name='{self.speech_config.speech_synthesis_voice_name}'>
                <mstts:express-as style='{style}'>
                    <prosody rate='{rate}' pitch='{pitch}'>
                        {text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>
        """

        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config, audio_config=audio_config
        )

        result = synthesizer.speak_ssml_async(ssml).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Audio saved successfully: {output_path}")
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            print("Speech synthesis canceled:", cancellation.reason)
            if cancellation.reason == speechsdk.CancellationReason.Error:
                print("Error details:", cancellation.error_details)