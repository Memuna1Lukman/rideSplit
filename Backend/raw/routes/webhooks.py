"""API routes for users to manage their outbound webhook subscriptions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, oauth, schemas
from ..database import get_db
from ..webhook import generate_endpoint_secret

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/", response_model=schemas.WebhookEndpointCreated, status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    endpoint_data: schemas.WebhookEndpointCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """Subscribe the signed-in user to selected ride-status events."""
    endpoint = models.WebhookEndpoint(
        owner_id=current_user.id,
        url=str(endpoint_data.url),
        events=endpoint_data.events,
        secret=generate_endpoint_secret(),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return schemas.WebhookEndpointCreated(
        id=endpoint.id,
        url=endpoint.url,
        events=endpoint.events,
        is_active=endpoint.is_active,
        secret=endpoint.secret,
    )


@router.get("/", response_model=list[schemas.WebhookEndpointOut])
def list_webhook_endpoints(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """List only the caller's endpoints; secrets are never included."""
    return (
        db.query(models.WebhookEndpoint)
        .filter(models.WebhookEndpoint.owner_id == current_user.id)
        .order_by(models.WebhookEndpoint.id.desc())
        .all()
    )


@router.get("/{endpoint_id}/deliveries", response_model=list[schemas.WebhookDeliveryOut])
def list_webhook_deliveries(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """View delivery attempts for one of the caller's subscriptions."""
    endpoint = db.get(models.WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    return (
        db.query(models.WebhookDelivery)
        .filter(models.WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(models.WebhookDelivery.id.desc())
        .limit(100)
        .all()
    )


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def disable_webhook_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth.get_current_user),
):
    """Disable, rather than erase, an endpoint so its delivery history remains."""
    endpoint = db.get(models.WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    endpoint.is_active = False
    db.commit()
