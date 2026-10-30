from fastapi import Depends,HTTPException,status,APIRouter
from sqlalchemy.orm import Session
from .. import models,schemas,utils,oauth
from sqlalchemy.exc import IntegrityError
from ..database import get_db


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.post("/",response_model=schemas.UserOut,status_code=status.HTTP_201_CREATED)
def create_user(user:schemas.UserCreate,db:Session=Depends(get_db)):
    user_model = user.model_dump(exclude={"password"})
    user_model["password_hash"] = utils.get_password_hash(user.password)
    new_user_obj = models.User(**user_model)
    try:
        db.add(new_user_obj)
        db.commit()
        db.refresh(new_user_obj)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )
    return new_user_obj


@router.get("/me",response_model=schemas.UserOut)
def get_me(db:Session=Depends(get_db),current_user:models.User=Depends(oauth.get_current_user)):
    return current_user
