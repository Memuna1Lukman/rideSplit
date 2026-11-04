from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import ST_Distance, ST_DWithin
from geoalchemy2.shape import to_shape
from sqlalchemy import cast, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models, oauth, schemas
from ..database import get_db

router = APIRouter(
    prefix="/drivers",
    tags=["Drivers"]
)


def serialize_driver_profile(profile: models.DriverProfile) -> schemas.DriverProfileDetailOut:
    location_data = None
    if profile.current_location is not None:
        point = to_shape(profile.current_location)
        location_data = schemas.LocationOut(latitude=point.y, longitude=point.x)

    return schemas.DriverProfileDetailOut(
        user_id=profile.user_id,
        vehicle_type=profile.vehicle_type,
        plate_number=profile.plate_number,
        capacity=profile.capacity,
        status=profile.status,
        current_location=location_data,
        location_updated_at=profile.location_updated_at,
    )


@router.post("/me/location", response_model=schemas.DriverProfileDetailOut)
def update_driver_location(
    location_data: schemas.LocationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_driver),
):
    profile = current_user.driver_profile
    point_wkt = WKTElement(
        f"POINT({location_data.longitude} {location_data.latitude})",
        srid=4326,
    )
    now = datetime.now(timezone.utc)
    profile.current_location = point_wkt
    profile.location_updated_at = now
    history_entry = models.DriverLocationHistory(
        driver_id=current_user.id,
        location=point_wkt,
        recorded_at=now
    )
    db.add(history_entry)

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update location",
        )

    db.refresh(profile)
    return serialize_driver_profile(profile)


@router.get("/me", response_model=schemas.DriverProfileDetailOut)
def get_driver_profile(current_user: models.User = Depends(oauth.get_current_driver)):
    profile = current_user.driver_profile
    return serialize_driver_profile(profile)


@router.post("/me/status", response_model=schemas.DriverProfileOut)
def update_driver_status(
    status_data: schemas.DriverStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_driver),
):
    profile = current_user.driver_profile
    if status_data.status == models.DriverStatus.available:
        active_job = (
            db.query(models.RideRequest)
            .filter(
                models.RideRequest.driver_id == current_user.id,
                models.RideRequest.status.in_(
                    [models.RequestStatus.accepted, models.RequestStatus.in_progress]
                ),
            )
            .first()
        )
        if active_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Driver cannot be available while a ride is active",
            )
    profile.status = status_data.status
    try:
        db.commit()
        db.refresh(profile)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update status",
        )

    return profile


@router.get("/nearby", response_model=list[schemas.DriverNearbyOut])
def get_nearby_drivers(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Pickup latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Pickup longitude"),
    radius_km: float = Query(default=5.0, gt=0, le=50.0, description="Search radius in km"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    # Geography distances are calculated in meters, which matches radius_meters.
    pickup_point = cast(
        func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326),
        Geography(geometry_type="POINT", srid=4326),
    )
    radius_meters = radius_km * 1000.0
    distance_expr = ST_Distance(models.DriverProfile.current_location,pickup_point)
    nearby_drivers = db.query(models.DriverProfile,distance_expr.label("distance_meters")).filter(
        models.DriverProfile.status == models.DriverStatus.available,
        models.DriverProfile.current_location.isnot(None),
        ST_DWithin(models.DriverProfile.current_location,pickup_point,radius_meters)
    ).order_by(distance_expr.asc()).limit(limit).all()
    results = []
    for profile,distance in nearby_drivers:
        shape = to_shape(profile.current_location)
        results.append(schemas.DriverNearbyOut(
            driver_id = profile.user_id,
            vehicle_type=profile.vehicle_type,
            plate_number=profile.plate_number,
            capacity=profile.capacity,
            distance_meters=round(float(distance),2),
            latitude=shape.y,
            longitude=shape.x
        ))
    return results