"""The small, reusable webhook delivery service.

Routes call :func:`enqueue_event` after a ride transaction commits.  It saves
delivery jobs in PostgreSQL first, then a background task makes the HTTP call.
Saving first is important: a temporary receiver outage cannot undo a ride.
"""

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .database import SessionLocal

logger = logging.getLogger(__name__)


def generate_endpoint_secret() -> str:
    """Return a random value the receiver uses to verify RideSplit messages."""
    return secrets.token_urlsafe(32)


def _json_body(payload: dict[str, Any]) -> bytes:
    """Create deterministic bytes: the exact bytes that are also HMAC-signed."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signature(secret: str, timestamp: str, body: bytes) -> str:
    """Sign ``timestamp.body`` so receivers can detect altered/replayed events."""
    signed_value = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed_value, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def enqueue_event(
    db: Session, *, owner_ids: Iterable[int], event_type: str, data: dict[str, Any]
) -> list[int]:
    """Save one delivery job per subscribed endpoint and return its IDs.

    This function does *not* contact the receiver.  It only writes short,
    reliable database records, which is safe to do during an API request.
    """
    owner_ids = set(owner_ids)
    if not owner_ids:
        return []

    endpoints = db.scalars(
        select(models.WebhookEndpoint).where(
            models.WebhookEndpoint.owner_id.in_(owner_ids),
            models.WebhookEndpoint.is_active.is_(True),
            models.WebhookEndpoint.events.any(event_type),
        )
    ).all()
    if not endpoints:
        return []

    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    deliveries = [
        models.WebhookDelivery(endpoint_id=endpoint.id, event_type=event_type, payload=payload)
        for endpoint in endpoints
    ]
    db.add_all(deliveries)
    db.commit()
    return [delivery.id for delivery in deliveries]


def deliver_webhook_delivery(delivery_id: int) -> None:
    """Attempt a single delivery using a fresh database session.

    A fresh session keeps the HTTP request entirely separate from the request
    that changed the ride.  If the HTTP call fails, the ride remains correct.
    """
    db = SessionLocal()
    try:
        delivery = db.get(models.WebhookDelivery, delivery_id)
        if delivery is None or delivery.status == models.DeliveryStatus.delivered:
            return
        endpoint = db.get(models.WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.is_active:
            return
        if delivery.attempts >= settings.webhook_max_attempts:
            delivery.status = models.DeliveryStatus.failed
            db.commit()
            return

        body = _json_body(delivery.payload)
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RideSplit-Webhooks/1.0",
            "X-RideSplit-Event": delivery.event_type,
            "X-RideSplit-Timestamp": timestamp,
            "X-RideSplit-Signature": _signature(endpoint.secret, timestamp, body),
        }

        response_code = None
        try:
            # content=body avoids serialising the JSON a second, different way.
            response = httpx.post(
                endpoint.url,
                content=body,
                headers=headers,
                timeout=settings.webhook_timeout_seconds,
                follow_redirects=False,
            )
            response_code = response.status_code
            succeeded = 200 <= response.status_code < 300
        except httpx.HTTPError as exc:
            # Network errors are normal for webhooks; record and retry them.
            logger.warning("Webhook delivery %s failed: %s", delivery_id, exc)
            succeeded = False

        delivery.attempts += 1
        delivery.last_response_code = response_code
        if succeeded:
            delivery.status = models.DeliveryStatus.delivered
        elif delivery.attempts >= settings.webhook_max_attempts:
            delivery.status = models.DeliveryStatus.failed
        else:
            # 30s, 60s, 120s...  A worker will pick this job up when it is due.
            delay = settings.webhook_retry_base_seconds * (2 ** (delivery.attempts - 1))
            delivery.status = models.DeliveryStatus.pending
            delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Unexpected error delivering webhook %s", delivery_id)
    finally:
        db.close()


def deliver_due_webhooks() -> int:
    """Deliver every pending job whose retry time has arrived; used by worker."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        ids = db.scalars(
            select(models.WebhookDelivery.id).where(
                models.WebhookDelivery.status == models.DeliveryStatus.pending,
                models.WebhookDelivery.next_attempt_at <= now,
            )
        ).all()
    finally:
        db.close()

    for delivery_id in ids:
        deliver_webhook_delivery(delivery_id)
    return len(ids)
