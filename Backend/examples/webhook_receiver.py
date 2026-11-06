"""A tiny local webhook receiver used to see and verify RideSplit events.

Run from Backend after installing the normal requirements:
    uvicorn examples.webhook_receiver:app --port 8001 --reload

When you create a RideSplit webhook endpoint, copy the returned ``secret``
into WEBHOOK_SECRET below.  Then subscribe to:
    http://127.0.0.1:8001/webhooks/rides
"""

import hashlib
import hmac
import os
import time

from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "replace-me-with-the-returned-secret")


def is_valid_signature(timestamp: str, body: bytes, received_signature: str) -> bool:
    """Recreate RideSplit's HMAC and compare it safely with the received one."""
    signed_value = timestamp.encode("utf-8") + b"." + body
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), signed_value, hashlib.sha256
    ).hexdigest()
    # compare_digest avoids timing leaks that a normal == comparison can have.
    return hmac.compare_digest(expected, received_signature)


@app.post("/webhooks/rides")
async def receive_ride_webhook(request: Request):
    # Read raw bytes first.  Parsing JSON first could change whitespace/order,
    # making it impossible to verify the exact body that RideSplit signed.
    body = await request.body()
    timestamp = request.headers.get("X-RideSplit-Timestamp", "")
    signature = request.headers.get("X-RideSplit-Signature", "")
    if not timestamp or not is_valid_signature(timestamp, body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # A valid old message might be a replay.  Five minutes is a reasonable
    # small acceptance window; choose one that matches your system's clocks.
    try:
        is_too_old = abs(time.time() - int(timestamp)) > 300
    except ValueError:
        is_too_old = True
    if is_too_old:
        raise HTTPException(status_code=401, detail="Stale webhook timestamp")

    # This is safe only after validation.  In a real system, save payload["id"]
    # in a database and ignore it if you have processed the same event before.
    payload = await request.json()
    print("Received RideSplit event:", payload)
    return {"received": True}
