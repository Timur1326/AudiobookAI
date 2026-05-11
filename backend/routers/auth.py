"""Auth router: user registration, login, and current-user endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.auth import create_token, hash_password, verify_password, get_current_user
from backend.database import get_db
from backend.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email:    EmailStr
    password: str


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account and return a JWT token."""
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=str(body.email), password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    user_id: int = user.id  # type: ignore[assignment]
    return {"id": user_id, "email": user.email, "token": create_token(user_id)}


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email/password and return a JWT token."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, str(user.password)):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id: int = user.id  # type: ignore[assignment]
    return {"id": user_id, "email": user.email, "token": create_token(user_id)}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return {"id": current_user.id, "email": current_user.email, "created_at": current_user.created_at}