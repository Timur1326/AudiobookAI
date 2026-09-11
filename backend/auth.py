"""
JWT authentication utilities.
"""
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.database import get_db

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. JWTs would otherwise be signed with a predictable "
        "value, letting anyone forge a valid login token. Generate one with:\n"
        '  python3 -c "import secrets; print(secrets.token_hex(32))"\n'
        "and add it to .env as SECRET_KEY=<value>."
    )

ALGORITHM   = "HS256"
TOKEN_TTL   = 60 * 24 * 7  # 7 days in minutes

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer      = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the given password."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the bcrypt hash."""
    return pwd_context.verify(plain, hashed)


def create_token(user_id: int) -> str:
    """Create a signed JWT for the given user, valid for TOKEN_TTL minutes."""
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_TTL)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    """FastAPI dependency — returns current User or raises 401."""
    from backend.models import User

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def get_owned_book(
    book: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """FastAPI dependency — returns the Book with slug `book` if it belongs to the caller.

    Raises 404 both when the book doesn't exist and when it belongs to someone else,
    so ownership can't be probed by guessing slugs. Use in any endpoint under
    /books/{book}/... that reads or mutates a specific book's data.
    """
    from backend.models import Book

    db_book = db.query(Book).filter(Book.slug == book, Book.user_id == current_user.id).first()
    if not db_book:
        raise HTTPException(status_code=404, detail=f"Book '{book}' not found")
    return db_book


def get_owned_scene(
    scene_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """FastAPI dependency — returns the Scene with id `scene_id` if its book belongs to the caller."""
    from backend.models import Book, Chapter, Scene

    scene = (
        db.query(Scene)
        .join(Chapter, Scene.chapter_id == Chapter.id)
        .join(Book, Chapter.book_id == Book.id)
        .filter(Scene.id == scene_id, Book.user_id == current_user.id)
        .first()
    )
    if not scene:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    return scene