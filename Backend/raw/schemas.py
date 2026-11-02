from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import DriverStatus, Role


class TokenData(BaseModel):
    id: int | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    role: Role
    vehicle_type: str | None = Field(default=None, min_length=1, max_length=50)
    plate_number: str | None = Field(default=None, min_length=1, max_length=30)
    capacity: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def driver_details_are_complete(self):
        if self.role == Role.driver and not all(
            (self.vehicle_type, self.plate_number, self.capacity)
        ):
            raise ValueError(
                "Drivers must provide vehicle_type, plate_number, and capacity."
            )
        return self


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    phone: str | None
    role: Role
    is_active: bool
    created_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class LocationOut(BaseModel):
    latitude: float
    longitude: float


class LocationUpdate(LocationOut):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DriverStatusUpdate(BaseModel):
    status: DriverStatus


class DriverProfileOut(BaseModel):
    user_id: int
    vehicle_type: str
    plate_number: str
    capacity: int
    status: DriverStatus

    model_config = ConfigDict(from_attributes=True)


class DriverProfileDetailOut(DriverProfileOut):
    current_location: LocationOut | None
    location_updated_at: datetime | None


class DriverNearbyOut(DriverProfileOut):
    distance_meters: float
    latitude: float
    longitude: float
