from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyCookie
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import models, schemas
from .config import settings
from .database import get_db


oauth2_scheme = APIKeyCookie(name="access_token", auto_error=False)


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_token(token: str, credential_exception: HTTPException) -> schemas.TokenData:
    try:
        if token.startswith("Bearer "):
            token = token.removeprefix("Bearer ")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("owner_id")
        if not isinstance(user_id, int):
            raise credential_exception
        return schemas.TokenData(id=user_id)
    except JWTError as exc:
        raise credential_exception from exc


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credential_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credential_exception
    token_data = verify_token(token, credential_exception)
    user = db.get(models.User, token_data.id)
    if user is None or not user.is_active:
        raise credential_exception
    return user


def get_current_driver(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if current_user.role != models.Role.driver or current_user.driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A driver account is required",
        )
    return current_user
