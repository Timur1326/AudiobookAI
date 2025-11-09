import numpy as np
import soundfile as sf

class AudioMixer:
    def __init__(self, sample_rate=24000):
        self.sample_rate = sample_rate

    def mix(self, segments, annotations):
        result = []
        for i, seg in enumerate(segments):
            result.extend(seg)
            silence = np.zeros(int(annotations[i]["pause"] * self.sample_rate))
            result.extend(silence)
        return np.array(result)

    def export(self, mixed, path="output.wav"):
        sf.write(path, mixed, self.sample_rate)