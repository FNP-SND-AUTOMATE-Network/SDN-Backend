from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from prisma import Prisma
from jose import jwt, JWTError
from passlib.context import CryptContext
import os

app = FastAPI(title="NMS Backend (FastAPI + Prisma)")

db = Prisma()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
http_bearer = HTTPBearer(auto_error=True)

# ==== ENV ====
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# ==== Utils ====
def get_password_hash(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(sub: str, extra: dict | None = None,
                        expires_delta: Optional[timedelta] = None) -> str:
    to_encode = {"sub": sub}
    if extra:
        to_encode.update(extra)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(http_bearer)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("email")  # we put email in token below
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.user.find_unique(where={"email": email})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

# ==== Schemas ====
class HealthOut(BaseModel):
    status: str = "ok"

@app.get("/health", response_model=HealthOut)
async def health():
    return HealthOut()

# Register
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: Optional[str] = None
    surname: Optional[str] = None
    # หากใช้ enum Role ใน Prisma ฟิลด์นี้พิมพ์เป็น Literal["VIEWER","ENGINEER","ADMIN"] ก็ได้
    role: Optional[str] = None  # default VIEWER if None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: Optional[str] = None
    surname: Optional[str] = None
    role: Optional[str] = None
    createdAt: datetime

@app.post("/auth/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn):
    email_norm = body.email.lower()
    exists = await db.user.find_unique(where={"email": email_norm})
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    hashed = get_password_hash(body.password)
    data = {
        "email": email_norm,
        "password": hashed,
        "name": body.name,
        "surname": body.surname,
    }
    # รองรับทั้งกรณี role เป็น enum หรือ string
    if body.role:
        data["role"] = body.role

    user = await db.user.create(data=data)
    # ซ่อน password
    return UserOut(**user.dict(exclude={"password"}))

# Login (ใช้ JSON body)
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

@app.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn):
    email_norm = body.email.lower()
    user = await db.user.find_unique(where={"email": email_norm})
    if not user or not verify_password(body.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        sub=str(user.id),
        extra={"email": user.email, "role": (user.role if hasattr(user, "role") else None)},
    )
    return TokenOut(access_token=token, expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60)

# Me (protected)
@app.get("/users/me", response_model=UserOut)
async def me(current = Depends(get_current_user)):
    return UserOut(**current.dict(exclude={"password"}))

# (ตัวอย่างที่คุณมีเดิมก็ยังใช้ได้: list users ทั้งหมด)
@app.get("/users", response_model=list[UserOut])
async def list_users(_=Depends(get_current_user)):  # ป้องกันการเปิดข้อมูลโดยไม่ล็อกอิน
    users = await db.user.find_many()
    return [UserOut(**u.dict(exclude={"password"})) for u in users]
