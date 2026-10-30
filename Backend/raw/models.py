import enum

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


# ---------------------------------------------------------------- enums
class Role(str, enum.Enum):
    driver = "DRIVER"
    passenger = "PASSENGER"


class DriverStatus(str, enum.Enum):
    offline = "OFFLINE"
    available = "AVAILABLE"
    busy = "BUSY"


class RequestStatus(str, enum.Enum):
    pending = "PENDING"
    offered = "OFFERED"
    accepted = "ACCEPTED"
    in_progress = "IN_PROGRESS"
    completed = "COMPLETED"
    cancelled = "CANCELLED"
    expired = "EXPIRED"


class OfferStatus(str, enum.Enum):
    sent = "SENT"
    accepted = "ACCEPTED"
    rejected = "REJECTED"
    expired = "EXPIRED"


class DeliveryStatus(str, enum.Enum):
    pending = "PENDING"
    delivered = "DELIVERED"
    failed = "FAILED"


def pg_enum(enum_cls, name):
    """Store the VALUES ("DRIVER") in Postgres instead of the member names
    ("driver"), so raw SQL like status = 'ACCEPTED' matches what is stored."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


# ---------------------------------------------------------------- tables
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)  # never store the raw password
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    role = Column(pg_enum(Role, "user_role"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    driver_profile = relationship("DriverProfile", back_populates="user", uselist=False)


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    # user_id is both the primary key and the foreign key (1:1 with users)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    vehicle_type = Column(String, nullable=False)
    plate_number = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False, default=1)
    status = Column(
        pg_enum(DriverStatus, "driver_status"),
        nullable=False,
        default=DriverStatus.offline,  # drivers start offline until they go online
    )
    current_location = Column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True), nullable=True
    )
    location_updated_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, default=0)  # optimistic locking

    user = relationship("User", back_populates="driver_profile")

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        Index(
            "ix_driver_profiles_available",
            "status",
            postgresql_where=text("status = 'AVAILABLE'"),
        ),
    )


class RideRequest(Base):
    __tablename__ = "ride_requests"

    id = Column(Integer, primary_key=True)
    passenger_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # empty until accepted
    pickup_location = Column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    dropoff_location = Column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    status = Column(
        pg_enum(RequestStatus, "request_status"),
        nullable=False,
        default=RequestStatus.pending,
        index=True,
    )
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, default=0)  # optimistic locking

    # two FKs point at users, so each relationship must say which one it uses
    passenger = relationship("User", foreign_keys=[passenger_id])
    driver = relationship("User", foreign_keys=[driver_id])

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        # DB-level guard: a driver can never hold two active jobs
        Index(
            "one_active_job_per_driver",
            "driver_id",
            unique=True,
            postgresql_where=text("status IN ('ACCEPTED', 'IN_PROGRESS')"),
        ),
    )


class RideOffer(Base):
    __tablename__ = "ride_offers"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("ride_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(pg_enum(OfferStatus, "offer_status"), nullable=False, default=OfferStatus.sent)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("request_id", "driver_id", name="uq_offer_request_driver"),)


class DriverLocationHistory(Base):
    __tablename__ = "driver_location_history"

    id = Column(BigInteger, primary_key=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    location = Column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    events = Column(ARRAY(String), nullable=False, default=list)  # e.g. ["request.accepted"]
    is_active = Column(Boolean, nullable=False, default=True)
    secret = Column(String, nullable=False)  # used for the HMAC signature


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)
    endpoint_id = Column(Integer, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(pg_enum(DeliveryStatus, "delivery_status"), nullable=False, default=DeliveryStatus.pending)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), server_default=func.now())
    last_response_code = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())