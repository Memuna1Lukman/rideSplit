from datetime import datetime
from typing import Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import DriverStatus, PaymentStatus, RequestStatus, Role


class TokenData(BaseModel):
    id: Optional[int] = None


class UserCreate(BaseModel):
    """Public data accepted when a user registers."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: Role


class UserOut(BaseModel):
    """Safe representation of a user returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    phone: Optional[str]
    role: Role
    is_active: bool
    created_at: Optional[datetime]


# A GPS coordinate always has latitude and longitude.  Keeping this in one
# schema means every route uses the same validation rules.
class Location(BaseModel):
    latitude: float = Field(
        ge=-90.0,
        le=90.0,
        description="North/south GPS coordinate, from -90 to 90.",
    )
    longitude: float = Field(
        ge=-180.0,
        le=180.0,
        description="East/west GPS coordinate, from -180 to 180.",
    )


class LocationUpdate(Location):
    """A driver's new current GPS position."""


class LocationOut(Location):
    """GPS coordinates sent back to the client."""


class DriverStatusUpdate(BaseModel):
    status: DriverStatus


class DriverProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    vehicle_type: str
    plate_number: str
    capacity: int
    status: DriverStatus


class DriverProfileDetailOut(DriverProfileOut):
    current_location: Optional[LocationOut] = None
    location_updated_at: Optional[datetime] = None


class DriverNearbyOut(BaseModel):
    driver_id: int
    vehicle_type: str
    plate_number: str
    capacity: int
    distance_meters: float
    latitude: float
    longitude: float


class RideRequestCreate(BaseModel):
    """The pickup and destination a passenger submits to request a ride."""

    pickup: Location
    dropoff: Location


class RideRequestOut(BaseModel):
    """A ride request returned after it has been stored."""

    id: int
    passenger_id: int
    driver_id: Optional[int]
    pickup: LocationOut
    dropoff: LocationOut
    status: RequestStatus
    requested_at: Optional[datetime]
    accepted_at: Optional[datetime]
    completed_at: Optional[datetime]


class PaymentIntentOut(BaseModel):
    """The fields a client needs to confirm a PaymentIntent with Stripe."""

    payment_id: int
    amount: int
    currency: str
    status: PaymentStatus
    client_secret: Optional[str] = None


# These are the event names this version of RideSplit knows how to send.  A
# fixed list prevents a typo in a subscription from silently doing nothing.
WEBHOOK_EVENT_TYPES = {
    "request.created",
    "request.accepted",
    "request.started",
    "request.completed",
    "request.cancelled",
}


class WebhookEndpointCreate(BaseModel):
    """The destination and ride events a user wants to receive."""

    # AnyHttpUrl accepts http for local learning/testing and https for production.
    # Production deployments should allow only public HTTPS addresses.
    url: AnyHttpUrl
    events: list[str] = Field(min_length=1, max_length=10)

    @field_validator("events")
    @classmethod
    def validate_events(cls, events: list[str]) -> list[str]:
        unique_events = list(dict.fromkeys(events))
        unknown = set(unique_events) - WEBHOOK_EVENT_TYPES
        if unknown:
            raise ValueError(f"Unknown webhook event(s): {', '.join(sorted(unknown))}")
        return unique_events


class WebhookEndpointOut(BaseModel):
    """Safe endpoint data.  The signing secret is deliberately excluded."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    events: list[str]
    is_active: bool


class WebhookEndpointCreated(WebhookEndpointOut):
    # This is the one and only response that includes the secret.  The caller
    # must save it now; later GET responses intentionally never reveal it.
    secret: str


class WebhookDeliveryOut(BaseModel):
    """A small audit trail that helps users debug webhook deliveries."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    payload: dict
    status: str
    attempts: int
    next_attempt_at: Optional[datetime]
    last_response_code: Optional[int]
    created_at: Optional[datetime]
