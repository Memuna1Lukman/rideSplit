"""Stripe PaymentIntent creation and reconciliation for completed rides."""

from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models, oauth, schemas
from ..config import settings
from ..database import get_db


router = APIRouter(prefix="/payment", tags=["Payments"])
stripe.api_key = settings.stripe_secret_key


def payment_status_for(stripe_status: str | None) -> models.PaymentStatus:
    """Map Stripe's broader set of statuses to our persisted status enum."""
    return {
        "requires_action": models.PaymentStatus.requires_action,
        "processing": models.PaymentStatus.processing,
        "succeeded": models.PaymentStatus.succeeded,
        "canceled": models.PaymentStatus.cancelled,
        "payment_failed": models.PaymentStatus.failed,
    }.get(stripe_status, models.PaymentStatus.pending)


def stripe_value(payment_intent, name: str, default=None):
    """Read a value from either a Stripe object or a test double dictionary."""
    if isinstance(payment_intent, dict):
        return payment_intent.get(name, default)
    return getattr(payment_intent, name, default)


def charge_id_for(payment_intent) -> str | None:
    charge = stripe_value(payment_intent, "latest_charge")
    if isinstance(charge, dict):
        return charge.get("id")
    return charge if isinstance(charge, str) else getattr(charge, "id", None)


def sync_payment(payment: models.Payment, payment_intent, event_type: str | None = None) -> None:
    """Copy non-sensitive Stripe state into the local reconciliation record."""
    stripe_status = stripe_value(payment_intent, "status")
    # A failed PaymentIntent normally returns to ``requires_payment_method``.
    # Preserve the event's more useful outcome rather than calling that merely
    # "pending" in our local audit record.
    payment.status = (
        models.PaymentStatus.failed
        if event_type == "payment_intent.payment_failed"
        else payment_status_for(stripe_status)
    )
    payment.stripe_charge_id = charge_id_for(payment_intent)
    last_error = stripe_value(payment_intent, "last_payment_error")
    payment.failure_reason = (
        last_error.get("message")
        if isinstance(last_error, dict)
        else getattr(last_error, "message", None)
    )
    if payment.status == models.PaymentStatus.succeeded and payment.paid_at is None:
        payment.paid_at = datetime.now(timezone.utc)


def calculate_ride_price(db: Session, ride: models.RideRequest) -> int:
    """Return the fare in cents, calculated exclusively on the server."""
    distance_meters = db.scalar(
        db.query(func.ST_Distance(ride.pickup_location, ride.dropoff_location)).statement
    )
    if distance_meters is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to calculate the ride fare",
        )
    distance_km = float(distance_meters) / 1_000
    return max(
        settings.ride_base_fare_cents,
        round(settings.ride_base_fare_cents + distance_km * settings.ride_per_km_cents),
    )


def payment_response(payment: models.Payment, payment_intent) -> schemas.PaymentIntentOut:
    return schemas.PaymentIntentOut(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        client_secret=stripe_value(payment_intent, "client_secret"),
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Verify Stripe's signature and reconcile PaymentIntent lifecycle events."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook"
        ) from exc

    event_type = stripe_value(event, "type")
    if event_type not in {
        "payment_intent.processing",
        "payment_intent.requires_action",
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "payment_intent.canceled",
    }:
        return {"received": True}

    data = stripe_value(event, "data", {})
    payment_intent = stripe_value(data, "object", {})
    intent_id = stripe_value(payment_intent, "id")
    if not intent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing PaymentIntent")

    payment = (
        db.query(models.Payment)
        .filter(models.Payment.stripe_payment_intent_id == intent_id)
        .first()
    )
    # A test-mode event from another application, or a delayed event for a
    # deleted record, must not make Stripe retry indefinitely.
    if payment is None:
        return {"received": True}

    try:
        sync_payment(payment, payment_intent, event_type)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update payment status",
        ) from exc
    return {"received": True}


@router.post("/{ride_id}", response_model=schemas.PaymentIntentOut)
def create_payment_intent(
    ride_id: int,
    current_user: models.User = Depends(oauth.get_current_user),
    db: Session = Depends(get_db),
):
    """Create (or return) the passenger's Stripe PaymentIntent for a completed ride."""
    if current_user.role != models.Role.passenger:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only passenger accounts can pay for rides",
        )

    ride = (
        db.query(models.RideRequest)
        .filter(
            models.RideRequest.id == ride_id,
            models.RideRequest.passenger_id == current_user.id,
        )
        .first()
    )
    if ride is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride request not found")
    if ride.status != models.RequestStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A ride can only be paid after it is completed",
        )

    existing = db.query(models.Payment).filter(models.Payment.ride_request_id == ride.id).first()
    if existing is not None:
        try:
            intent = stripe.PaymentIntent.retrieve(existing.stripe_payment_intent_id)
            sync_payment(existing, intent)
            db.commit()
        except stripe.StripeError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retrieve payment from Stripe",
            ) from exc
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to update payment status",
            ) from exc
        return payment_response(existing, intent)

    amount = calculate_ride_price(db, ride)
    try:
        # Stripe also deduplicates concurrent/retried API calls for this ride.
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=settings.payment_currency,
            automatic_payment_methods={"enabled": True},
            metadata={"ride_id": str(ride.id), "passenger_id": str(current_user.id)},
            idempotency_key=f"ridesplit-payment-{ride.id}",
        )
    except stripe.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create payment with Stripe",
        ) from exc

    payment = models.Payment(
        ride_request_id=ride.id,
        passenger_id=current_user.id,
        amount=amount,
        currency=settings.payment_currency,
        stripe_payment_intent_id=stripe_value(intent, "id"),
    )
    sync_payment(payment, intent)
    db.add(payment)
    try:
        db.commit()
        db.refresh(payment)
    except IntegrityError as exc:
        # A parallel request created the one record permitted per ride.  Its
        # Stripe intent is the same due to the idempotency key above.
        db.rollback()
        payment = db.query(models.Payment).filter(models.Payment.ride_request_id == ride.id).first()
        if payment is not None:
            return payment_response(payment, intent)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save payment",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save payment",
        ) from exc

    return payment_response(payment, intent)
