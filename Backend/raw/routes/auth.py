from fastapi import HTTPException,Depends,status,APIRouter,Response
from fastapi.security import OAuth2PasswordRequestForm
from .. import models,utils,schemas,oauth
from ..database import get_db
from sqlalchemy.orm import Session

from .. import models, oauth, utils
from ..config import settings
from ..database import get_db


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login")
def login_user(
    response:Response,
    user:OAuth2PasswordRequestForm=Depends(),db:Session = Depends(get_db)):
    check_user = db.query(models.User).filter(models.User.email == user.username).first()
    if not check_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail=f"Invalid Credentials")

    verify_password = utils.verify_password(user.password,check_user.password_hash)
    if not verify_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,detail=f"Invalid Credentials")

    
    access_token = oauth.create_token(data={"owner_id": check_user.id})
    # reponse in the cookie form
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=False,  # Set this to True when the application is served over HTTPS.
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return {"message": "Login successful"}




@router.post("/logout")
def logout_user (
    response:Response
):
    response.set_cookie(
        key="access_token",
        value = "",
        httponly= True,
        secure = False,
        samesite="lax",
        max_age=0
        )
    
    return {"message": "Logout successful"}
