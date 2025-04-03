from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth_utils import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    get_seed_word_hash,
    verify_seed_word,
)
from ..database import get_db
from ..eth_utils import (
    generate_mnemonic,
    get_address_from_mnemonic,
    verify_ethereum_signature,
)
from ..models import User
from ..schemas import (
    SignatureResponse,
    SignatureVerification,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)

router = APIRouter(prefix='/api/auth', tags=['auth'])


@router.post('/register', response_model=UserResponse)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    db_user = db.query(User).filter(User.public_key == user.public_key).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Public key already registered',
        )

    # Create new user with hashed seed word
    hashed_seed_word = get_seed_word_hash(user.seed_word)
    db_user = User(
        public_key=user.public_key,
        seed_word=hashed_seed_word,
        pubkey_gen=user.pubkey_gen,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post('/login', response_model=Token)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    # Find user by public key
    user = db.query(User).filter(User.public_key == user_data.public_key).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid credentials',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    # Verify seed word
    if not verify_seed_word(user_data.seed_word, user.seed_word):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid credentials',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': user.public_key}, expires_delta=access_token_expires
    )

    # Update user's JWT
    user.jwt = access_token
    db.commit()

    return {'access_token': access_token, 'token_type': 'bearer'}


@router.post('/verify')
async def verify_token(current_user: User = Depends(get_current_user)):
    return {'status': 'valid', 'public_key': current_user.public_key}


@router.post('/logout')
async def logout(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # Clear JWT from user record
    current_user.jwt = None
    db.commit()
    return {'status': 'success', 'message': 'Logged out successfully'}


@router.post('/verify-signature', response_model=SignatureResponse)
async def verify_signature(
    signature_data: SignatureVerification, db: Session = Depends(get_db)
):
    try:
        # Verify signature and get public key (Ethereum address)
        public_key = verify_ethereum_signature(
            signature_data.message, signature_data.signature
        )

        # Check if user exists
        user = db.query(User).filter(User.public_key == public_key).first()

        if user:
            # User exists, generate new JWT
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                data={'sub': public_key}, expires_delta=access_token_expires
            )

            # Update user's JWT
            user.jwt = access_token
            db.commit()
            db.refresh(user)

            return SignatureResponse(user=user, public_key=public_key, jwt=access_token)
        else:
            # Generate new mnemonic for new user
            mnemonic = generate_mnemonic()
            pubkey_gen = get_address_from_mnemonic(mnemonic)

            # Create access token
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                data={'sub': public_key}, expires_delta=access_token_expires
            )

            # Create new user
            new_user = User(
                public_key=public_key,
                seed_word=get_seed_word_hash(mnemonic),
                pubkey_gen=pubkey_gen,
                jwt=access_token,
            )

            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            return SignatureResponse(
                user=new_user,
                seed_word=mnemonic,  # Only return seed word for new users
                jwt=access_token,
                public_key=public_key,
            )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
