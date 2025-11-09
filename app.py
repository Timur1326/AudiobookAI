from src.pipeline.audiobook_generator import AudiobookGenerator
import warnings
from src.tts.azure_tts_engine import AzureTTSEngine

warnings.filterwarnings('ignore')

if __name__ == "__main__":
    # key = "d818daf5cc10465c92732f50f10412eb"
    # region = "westeurope"

    generator = AudiobookGenerator(
        input_text_path="data/book.txt",
        azure_key="d818daf5cc10465c92732f50f10412eb",
        azure_region="westeurope",
    )

    generator.run("data/output.wav")


    # tts = AzureTTSEngine(key, region, voice="en-US-JennyNeural")
    #
    # tts.synthesize("Hello, I am happy to see you!", "data/angry.wav", style="angry", rate="+10%", pitch="+5Hz")
    # tts.synthesize("Hello, I am happy to see you!", "data/whispering.wav", style="sport_commentary", rate="+10%", pitch="+5Hz")

    # tts.synthesize("I can’t believe this happened...", "data/sad.wav", style="sad", rate="-10%", pitch="-3Hz")

    # generator = AudiobookGenerator("data/book.txt", "data/reference.wav")
    # generator.run("data/output.wav")