from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    created_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, session: Session = Depends(get_db)):
    try:
        user = auth_service.register_user(session, req.username, req.password)
    except auth_service.UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    session.commit()
    return {"id": user.id, "username": user.username}


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, session: Session = Depends(get_db)):
    try:
        user = auth_service.authenticate(session, req.username, req.password)
    except auth_service.InvalidCredentialsError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    session.commit()
    return {"access_token": auth_service.create_access_token(user), "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    req: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    try:
        auth_service.change_password(session, user, req.current_password, req.new_password)
    except auth_service.InvalidCredentialsError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    session.commit()
