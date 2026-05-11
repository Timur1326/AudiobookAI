"""
JWT authentication utilities.
"""
import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.database import get_db

SECRET_KEY  = os.environ.get("SECRET_KEY", "change-me-in-production")
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


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    """Same as get_current_user but returns None instead of raising 401."""
    if not credentials:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None