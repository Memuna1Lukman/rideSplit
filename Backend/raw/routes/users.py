from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, oauth, schemas, utils
from ..database import get_db


router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    user = models.User(
        email=str(user_data.email),
        password_hash=utils.get_password_hash(user_data.password),
        full_name=user_data.full_name,
        phone=user_data.phone,
        role=user_data.role,
    )
    if user_data.role == models.Role.driver:
        user.driver_profile = models.DriverProfile(
            vehicle_type=user_data.vehicle_type,
            plate_number=user_data.plate_number,
            capacity=user_data.capacity,
        )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        ) from exc
    return user


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(oauth.get_current_user)):
    return current_user
