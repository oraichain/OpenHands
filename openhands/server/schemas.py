from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserBase(BaseModel):
    public_key: str
    pubkey_gen: str


class UserCreate(UserBase):
    seed_word: str


class UserLogin(BaseModel):
    public_key: str
    seed_word: str


class UserResponse(UserBase):
    id: int
    created_at: datetime
    jwt: Optional[str] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'


class TokenData(BaseModel):
    public_key: str


class SignatureVerification(BaseModel):
    message: str
    signature: str


class SignatureResponse(BaseModel):
    user: Optional[UserResponse] = None
    seed_word: Optional[str] = None
    jwt: Optional[str] = None
    public_key: str
