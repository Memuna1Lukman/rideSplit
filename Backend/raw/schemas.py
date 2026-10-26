from pydantic import BaseModel,EmailStr
from typing import Optional
from datetime import datetime


class TokenData(BaseModel):
    id: Optional[int]= None