import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
import logging
# Fix Passlib + Bcrypt >= 4.0.0 compatibility on Python 3.12
import passlib.handlers.bcrypt

# Silently trap passlib's internal bcrypt initialization check crash
try:
    passlib.handlers.bcrypt.bcrypt.detect_wrap_bug = lambda secret, bug_hash: False
except Exception:
    pass

from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# Secret key and algorithm configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "SUPER_SECRET_CHANGE_THIS_IN_PRODUCTION_12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Hardcoded admin credentials for initial setup
# In production, pull these from your SQL database
DEMO_USERS_DB = {
    "admin": {
        "username": "admin",
        # Default password hashed: "admin123"
        "hashed_password": pwd_context.hash("admin123"),
        "full_name": "System Administrator",
        "role": "admin"
    }
}


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    full_name: str


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    username: str
    full_name: Optional[str] = None
    role: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    user = DEMO_USERS_DB.get(token_data.username)
    if user is None:
        raise credentials_exception

    return User(
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"]
    )