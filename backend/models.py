import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done    = "done"
    error   = "error"


STEP_NAMES = {
    1: "Parse",
    2: "Split quotes",
    3: "Detect scenes",
    4: "Attribute dialogue",
    5: "Extract characters",
    6: "Assign voices",
    7: "Synthesis",
}


class User(Base):
    __tablename__ = "users"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    email:      Mapped[str]      = mapped_column(String, unique=True, index=True)
    password:   Mapped[str]      = mapped_column(String)   # bcrypt hash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    books: Mapped[list["Book"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = "books"

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int | None]    = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    slug:       Mapped[str]           = mapped_column(String, unique=True, index=True)
    title:      Mapped[str]           = mapped_column(String)
    author:     Mapped[str]           = mapped_column(String, default="")
    epub_path:  Mapped[str]           = mapped_column(String)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)

    user:       Mapped["User | None"]            = relationship(back_populates="books")
    steps:      Mapped[list["PipelineStep"]]     = relationship(back_populates="book", cascade="all, delete-orphan")
    chapters:   Mapped[list["Chapter"]]          = relationship(back_populates="book", cascade="all, delete-orphan", order_by="Chapter.chapter_index")
    characters: Mapped[list["Character"]]        = relationship(back_populates="book", cascade="all, delete-orphan")


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id:         Mapped[int]        = mapped_column(Integer, primary_key=True)
    book_id:    Mapped[int]        = mapped_column(ForeignKey("books.id"))
    step:       Mapped[int]        = mapped_column(Integer)
    status:     Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.pending)
    updated_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    error_msg:  Mapped[str | None] = mapped_column(String, nullable=True)

    book: Mapped["Book"] = relationship(back_populates="steps")

    @property
    def name(self) -> str:
        return STEP_NAMES.get(self.step, f"Шаг {self.step}")


class Chapter(Base):
    __tablename__ = "chapters"

    id:            Mapped[int]        = mapped_column(Integer, primary_key=True)
    book_id:       Mapped[int]        = mapped_column(ForeignKey("books.id"))
    chapter_index: Mapped[int]        = mapped_column(Integer)
    chapter_id:    Mapped[int]        = mapped_column(Integer)  # id from parsed JSON
    title:         Mapped[str]        = mapped_column(String)
    audio_path:    Mapped[str | None] = mapped_column(String, nullable=True)
    synth_status:  Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.pending)
    synth_engine:  Mapped[str | None] = mapped_column(String, nullable=True)

    book:       Mapped["Book"]            = relationship(back_populates="chapters")
    scenes:     Mapped[list["Scene"]]     = relationship(back_populates="chapter", cascade="all, delete-orphan", order_by="Scene.scene_index")
    paragraphs: Mapped[list["Paragraph"]] = relationship(back_populates="chapter", cascade="all, delete-orphan", order_by="Paragraph.index")


class Scene(Base):
    __tablename__ = "scenes"

    id:          Mapped[int]        = mapped_column(Integer, primary_key=True)
    chapter_id:  Mapped[int]        = mapped_column(ForeignKey("chapters.id"), index=True)
    scene_index: Mapped[int]        = mapped_column(Integer)
    preview:     Mapped[str | None] = mapped_column(Text, nullable=True)

    chapter:        Mapped["Chapter"]             = relationship(back_populates="scenes")
    paragraphs:     Mapped[list["Paragraph"]]    = relationship(back_populates="scene")
    ambient_scenes: Mapped[list["AmbientScene"]] = relationship(back_populates="scene", cascade="all, delete-orphan")


class Paragraph(Base):
    __tablename__ = "paragraphs"

    id:         Mapped[int]        = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int]        = mapped_column(ForeignKey("chapters.id"), index=True)
    scene_id:   Mapped[int | None] = mapped_column(ForeignKey("scenes.id"), nullable=True, index=True)
    index:      Mapped[int]        = mapped_column(Integer)   # position in chapter
    text:       Mapped[str]        = mapped_column(Text)
    type:       Mapped[str]        = mapped_column(String, default="narration")  # "dialogue" | "narration"
    speaker:    Mapped[str | None] = mapped_column(String, nullable=True)

    chapter:    Mapped["Chapter"]                  = relationship(back_populates="paragraphs")
    scene:      Mapped["Scene | None"]             = relationship(back_populates="paragraphs")
    timestamps: Mapped[list["ParagraphTimestamp"]] = relationship(back_populates="paragraph", cascade="all, delete-orphan")


class ParagraphTimestamp(Base):
    __tablename__ = "paragraph_timestamps"

    id:           Mapped[int]   = mapped_column(Integer, primary_key=True)
    paragraph_id: Mapped[int]   = mapped_column(ForeignKey("paragraphs.id"), index=True)
    engine:       Mapped[str]   = mapped_column(String)   # "elevenlabs" | "azure" | "xtts"
    start:        Mapped[float] = mapped_column(Float)
    end:          Mapped[float] = mapped_column(Float)

    paragraph: Mapped["Paragraph"] = relationship(back_populates="timestamps")


class AmbientScene(Base):
    __tablename__ = "ambient_scenes"

    id:        Mapped[int]           = mapped_column(Integer, primary_key=True)
    scene_id:  Mapped[int]           = mapped_column(ForeignKey("scenes.id"), index=True)
    engine:    Mapped[str]           = mapped_column(String)
    start:     Mapped[float | None]  = mapped_column(Float, nullable=True)
    end:       Mapped[float | None]  = mapped_column(Float, nullable=True)
    sound_url: Mapped[str | None]    = mapped_column(String, nullable=True)
    queries:   Mapped[str | None]    = mapped_column(Text, nullable=True)

    scene: Mapped["Scene"] = relationship(back_populates="ambient_scenes")


class Character(Base):
    __tablename__ = "characters"

    id:          Mapped[int]        = mapped_column(Integer, primary_key=True)
    book_id:     Mapped[int]        = mapped_column(ForeignKey("books.id"))
    name:        Mapped[str]        = mapped_column(String)
    gender:      Mapped[str | None] = mapped_column(String, nullable=True)
    age:         Mapped[str | None] = mapped_column(String, nullable=True)
    personality: Mapped[str | None] = mapped_column(String, nullable=True)
    accent:      Mapped[str | None] = mapped_column(String, nullable=True)
    voice_desc:  Mapped[str | None] = mapped_column(String, nullable=True)
    sample_text: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_id:               Mapped[str | None]   = mapped_column(String, nullable=True)
    engine:                 Mapped[str | None]   = mapped_column(String, nullable=True)
    voice_stability:        Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_style:            Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_similarity_boost: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_speaker_boost:    Mapped[bool | None]  = mapped_column(nullable=True)

    book:    Mapped["Book"]                  = relationship(back_populates="characters")
    aliases: Mapped[list["CharacterAlias"]]  = relationship(back_populates="character", cascade="all, delete-orphan")


class CharacterAlias(Base):
    __tablename__ = "character_aliases"

    id:           Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    alias:        Mapped[str] = mapped_column(String)

    character: Mapped["Character"] = relationship(back_populates="aliases")