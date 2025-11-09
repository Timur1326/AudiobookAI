from src.pipeline.audiobook_generator import AudiobookGenerator
import warnings

warnings.filterwarnings('ignore')

if __name__ == "__main__":
    generator = AudiobookGenerator("data/book.txt", "data/reference.wav")
    generator.run("data/output.wav")