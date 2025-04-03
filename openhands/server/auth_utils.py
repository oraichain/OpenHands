from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .schemas import TokenData

# Move these to environment variables in production
SECRET_KEY = 'your-secret-key-here'  # Change this!
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='api/auth/login')


def verify_seed_word(plain_seed_word: str, hashed_seed_word: str) -> bool:
    return pwd_context.verify(plain_seed_word, hashed_seed_word)


def get_seed_word_hash(seed_word: str) -> str:
    return pwd_context.hash(seed_word)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        public_key: str = payload.get('sub')
        if public_key is None:
            raise credentials_exception
        token_data = TokenData(public_key=public_key)
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.public_key == token_data.public_key).first()
    if user is None:
        raise credentials_exception
    return user
