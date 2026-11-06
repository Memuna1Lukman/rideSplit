from datetime import datetime, timezone

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models, oauth, schemas
from ..database import get_db
from ..webhook import deliver_webhook_delivery, enqueue_event

router = APIRouter(prefix="/requests", tags=["Requests"])
logger = logging.getLogger(__name__)


def location_to_point(location: schemas.Location) -> WKTElement:
    """Convert API latitude/longitude into the PostGIS POINT(lon lat) format."""
    return WKTElement(
        f"POINT({location.longitude} {location.latitude})",
        srid=4326,
    )


def serialize_ride_request(ride_request: models.RideRequest) -> schemas.RideRequestOut:
    """Convert PostGIS points back into the latitude/longitude API shape."""
    pickup = to_shape(ride_request.pickup_location)
    dropoff = to_shape(ride_request.dropoff_location)
    return schemas.RideRequestOut(
        id=ride_request.id,
        passenger_id=ride_request.passenger_id,
        driver_id=ride_request.driver_id,
        pickup=schemas.LocationOut(latitude=pickup.y, longitude=pickup.x),
        dropoff=schemas.LocationOut(latitude=dropoff.y, longitude=dropoff.x),
        status=ride_request.status,
        requested_at=ride_request.requested_at,
        accepted_at=ride_request.accepted_at,
        completed_at=ride_request.completed_at,
    )


def schedule_ride_webhooks(
    background_tasks: BackgroundTasks,
    db: Session,
    event_type: str,
    ride: schemas.RideRequestOut,
) -> None:
    """Save delivery jobs, then send them after the API response is returned.

    The ride has already committed when this function is called.  Therefore a
    broken webhook URL is only a notification problem, never a ride problem.
    """
    owner_ids = [ride.passenger_id]
    if ride.driver_id is not None:
        owner_ids.append(ride.driver_id)
    try:
        delivery_ids = enqueue_event(
            db,
            owner_ids=owner_ids,
            event_type=event_type,
            # mode="json" converts datetimes/enums into JSON-safe values.
            data=ride.model_dump(mode="json"),
        )
    except Exception:
        # Notifications should never turn a completed ride action into a 500.
        db.rollback()
        logger.exception("Unable to queue webhook event %s", event_type)
        return
    for delivery_id in delivery_ids:
        background_tasks.add_task(deliver_webhook_delivery, delivery_id)


@router.post("/", response_model=schemas.RideRequestOut, status_code=status.HTTP_201_CREATED)
def create_ride_request(
    request_data: schemas.RideRequestCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., min_length=1, max_length=255),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """Create a pending ride request for the authenticated passenger."""
    if current_user.role != models.Role.passenger:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only passenger accounts can create ride requests",
        )

    existing_request = (
        db.query(models.RideRequest)
        .filter(
            models.RideRequest.passenger_id == current_user.id,
            models.RideRequest.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing_request is not None:
        return serialize_ride_request(existing_request)

    ride_request = models.RideRequest(
        passenger_id=current_user.id,
        idempotency_key=idempotency_key,
        pickup_location=location_to_point(request_data.pickup),
        dropoff_location=location_to_point(request_data.dropoff),
        status=models.RequestStatus.pending,
    )
    db.add(ride_request)

    try:
        # Flush assigns the primary key before the commit expires ORM attributes,
        # allowing a successful commit to be returned even if refresh fails.
        db.flush()
        response = schemas.RideRequestOut(
            id=ride_request.id,
            passenger_id=ride_request.passenger_id,
            driver_id=ride_request.driver_id,
            pickup=schemas.LocationOut(
                latitude=request_data.pickup.latitude,
                longitude=request_data.pickup.longitude,
            ),
            dropoff=schemas.LocationOut(
                latitude=request_data.dropoff.latitude,
                longitude=request_data.dropoff.longitude,
            ),
            status=ride_request.status,
            requested_at=ride_request.requested_at,
            accepted_at=ride_request.accepted_at,
            completed_at=ride_request.completed_at,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A concurrent retry may have committed the same key after the lookup.
        existing_request = (
            db.query(models.RideRequest)
            .filter(
                models.RideRequest.passenger_id == current_user.id,
                models.RideRequest.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing_request is not None:
            return serialize_ride_request(existing_request)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create the ride request",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create the ride request",
        ) from exc

    schedule_ride_webhooks(background_tasks, db, "request.created", response)

    try:
        db.refresh(ride_request)
    except SQLAlchemyError:
        return response

    return serialize_ride_request(ride_request)



@router.get("/{request_id}", response_model=schemas.RideRequestOut)
def get_ride(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    ride_request = db.get(models.RideRequest, request_id)
    if ride_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found",
        )

    is_passenger = current_user.id == ride_request.passenger_id
    is_assigned_driver = current_user.id == ride_request.driver_id
    if not (is_passenger or is_assigned_driver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to view this ride request",
        )
    return serialize_ride_request(ride_request)



@router.post("/{request_id}/accept", response_model=schemas.RideRequestOut)
def accept_ride_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_driver),
):
    """Assign the pending request to the authenticated available driver."""
    # Locking the row prevents two drivers from accepting the same request at
    # the same time. The second driver waits, then sees that it is no longer pending.
    ride_request = (
        db.query(models.RideRequest)
        .filter(models.RideRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if ride_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found",
        )
    if ride_request.status != models.RequestStatus.pending:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride request is no longer available to accept",
        )

    profile = (
        db.query(models.DriverProfile)
        .filter(models.DriverProfile.user_id == current_user.id)
        .with_for_update()
        .first()
    )
    if profile is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A driver profile is required",
        )
    if profile.status != models.DriverStatus.available:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only available drivers can accept a ride request",
        )

    ride_request.driver_id = current_user.id
    ride_request.status = models.RequestStatus.accepted
    ride_request.accepted_at = datetime.now(timezone.utc)
    profile.status = models.DriverStatus.busy

    try:
        db.commit()
        db.refresh(ride_request)
    except IntegrityError as exc:
        # The database also prevents a driver from having two active rides.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver already has an active ride request",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to accept the ride request",
        ) from exc

    response = serialize_ride_request(ride_request)
    schedule_ride_webhooks(background_tasks, db, "request.accepted", response)
    return response


@router.post("/{request_id}/start", response_model=schemas.RideRequestOut)
def start_trip(
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_driver),
):
    """Move the authenticated driver's accepted ride into progress."""
    ride_request = (
        db.query(models.RideRequest)
        .filter(models.RideRequest.id == request_id)
        .with_for_update()
        .first()
    )

    # Use ``or`` here: it short-circuits, so driver_id is never read when
    # there is no matching row.  ``|`` is a bitwise operator, not boolean OR.
    if ride_request is None or ride_request.driver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found",
        )
    if ride_request.status != models.RequestStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an accepted ride can be started",
        )

    ride_request.status = models.RequestStatus.in_progress
    try:
        db.commit()
        db.refresh(ride_request)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to start the ride",
        ) from exc

    response = serialize_ride_request(ride_request)
    schedule_ride_webhooks(background_tasks, db, "request.started", response)
    return response


@router.post("/{request_id}/complete", response_model=schemas.RideRequestOut)
def complete_trip(
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_driver),
):
    """Complete an in-progress ride and make its driver available again."""
    ride_request = (
        db.query(models.RideRequest)
        .filter(models.RideRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if ride_request is None or ride_request.driver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found",
        )
    if ride_request.status != models.RequestStatus.in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an in-progress ride can be completed",
        )

    # Lock the driver's profile too, because this transaction changes both
    # the ride and the driver's availability.
    profile = (
        db.query(models.DriverProfile)
        .filter(models.DriverProfile.user_id == current_user.id)
        .with_for_update()
        .first()
    )
    if profile is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A driver profile is required",
        )

    ride_request.status = models.RequestStatus.completed
    ride_request.completed_at = datetime.now(timezone.utc)
    # A driver may choose to go offline while finishing their current ride.
    # Completing it must not silently put that driver back into the pool.
    if profile.status != models.DriverStatus.offline:
        profile.status = models.DriverStatus.available
    try:
        db.commit()
        db.refresh(ride_request)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete the ride",
        ) from exc

    response = serialize_ride_request(ride_request)
    schedule_ride_webhooks(background_tasks, db, "request.completed", response)
    return response


@router.post("/{request_id}/cancel", response_model=schemas.RideRequestOut)
def cancel_ride_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """Let the owning passenger cancel a pending or accepted ride."""
    ride_request = (
        db.query(models.RideRequest)
        .filter(models.RideRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if ride_request is None or ride_request.passenger_id != current_user.id:
        # A 404 does not reveal another passenger's ride IDs.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found",
        )
    if ride_request.status not in (
        models.RequestStatus.pending,
        models.RequestStatus.accepted,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a pending or accepted ride can be cancelled",
        )

    # An accepted ride made its driver busy. Lock and release that profile in
    # the same transaction so the driver can accept another ride afterwards.
    profile = None
    if ride_request.driver_id is not None:
        profile = (
            db.query(models.DriverProfile)
            .filter(models.DriverProfile.user_id == ride_request.driver_id)
            .with_for_update()
            .first()
        )
        if profile is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assigned driver profile no longer exists",
            )

    ride_request.status = models.RequestStatus.cancelled
    # Keep an explicit offline choice.  Otherwise an accepted ride being
    # cancelled correctly releases its still-online driver for new work.
    if profile is not None and profile.status != models.DriverStatus.offline:
        profile.status = models.DriverStatus.available
    try:
        db.commit()
        db.refresh(ride_request)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to cancel the ride request",
        ) from exc

    response = serialize_ride_request(ride_request)
    schedule_ride_webhooks(background_tasks, db, "request.cancelled", response)
    return response
