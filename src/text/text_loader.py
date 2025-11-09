class TextLoader:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> str:
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def clean(self, text: str) -> str:
        return " ".join(text.split())