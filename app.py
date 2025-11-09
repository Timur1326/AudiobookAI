from src.pipeline.audiobook_generator import AudiobookGenerator
import warnings
from src.tts.azure_tts_engine import AzureTTSEngine

warnings.filterwarnings('ignore')

if __name__ == "__main__":
    key = "d818daf5cc10465c92732f50f10412eb"
    region = "westeurope"

    tts = AzureTTSEngine(key, region, voice="en-US-JennyNeural")

    tts.synthesize("Hello, I am happy to see you!", "data/happy.wav", style="cheerful", rate="+10%", pitch="+5Hz")
    tts.synthesize("I can’t believe this happened...", "data/sad.wav", style="sad", rate="-10%", pitch="-3Hz")

    # generator = AudiobookGenerator("data/book.txt", "data/reference.wav")
    # generator.run("data/output.wav")