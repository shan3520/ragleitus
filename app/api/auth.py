from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
import hashlib
import hmac
import base64
import time
import secrets

# Simple HMAC-based token scheme for tests (keeps implementation self-contained)
SECRET = "test-secret-key"
TOKEN_TTL = 3600  # seconds

USERS: dict[str, dict] = {}

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    username: str

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(salt: str, password: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _sign_payload(payload: str) -> str:
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _verify_signature(payload: str, signature: str) -> bool:
    expected = _sign_payload(payload)
    return hmac.compare_digest(expected, signature)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest):
    if req.username in USERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    salt = secrets.token_hex(8)
    USERS[req.username] = {"salt": salt, "password": _hash_password(salt, req.password)}
    return {"username": req.username}


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = USERS.get(req.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if _hash_password(user["salt"], req.password) != user["password"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    ts = str(int(time.time()))
    payload = f"{req.username}:{ts}"
    sig = _sign_payload(payload)
    token = f"{req.username}.{ts}.{sig}"
    return {"access_token": token, "token_type": "bearer"}


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
    username, ts, sig = parts
    payload = f"{username}:{ts}"
    if not _verify_signature(payload, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    try:
        if int(time.time()) - int(ts) > TOKEN_TTL:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token timestamp")
    if username not in USERS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {"username": username}


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)) -> dict:
    return {"username": user["username"]}
