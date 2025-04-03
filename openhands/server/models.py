from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from .database import Base


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    public_key = Column(String, unique=True, index=True)
    seed_word = Column(String)
    jwt = Column(String, nullable=True)
    pubkey_gen = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.public_key}>'
