# RideSplit backend

FastAPI backend for a ride-sharing application. It currently provides account
registration, cookie-based login/logout, driver profiles, driver availability,
driver location updates, and nearby-driver queries. The database is PostgreSQL
with PostGIS support.

## What you need

- Python 3.12+
- PostgreSQL with the `postgis` extension enabled
- A `.env` file in this folder:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE
# Optional: use this for Alembic migrations if your provider offers a direct URL.
DATABASE_URL_DIRECT=
SECRET_KEY=replace-with-a-long-random-value
ACCESS_TOKEN_EXPIRE_MINUTES=30
# Optional webhook delivery settings (the defaults below are used if omitted).
WEBHOOK_TIMEOUT_SECONDS=5
WEBHOOK_MAX_ATTEMPTS=5
WEBHOOK_RETRY_BASE_SECONDS=30
# Stripe test credentials for the payment endpoints.
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
# Fare amounts are in cents; the server calculates the final fare from distance.
PAYMENT_CURRENCY=usd
RIDE_BASE_FARE_CENTS=500
RIDE_PER_KM_CENTS=150
```

Never commit `.env`; it contains credentials.

## Run it locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn raw.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to use the interactive API documentation.

## Current endpoints

- `POST /users` — create a passenger or driver account. Driver accounts must
  include vehicle type, plate number, and capacity.
- `POST /auth/login` — form login using `username` (email) and `password`;
  writes an HTTP-only cookie.
- `POST /auth/logout` — clears the login cookie.
- `GET /users/me` — returns the logged-in user.
- `GET /drivers/me`, `POST /drivers/me/status`, `POST /drivers/me/location`
  — driver-only profile, availability, and location actions.
- `GET /drivers/nearby` — authenticated lookup for available drivers near a
  latitude/longitude.
- `POST /webhooks`, `GET /webhooks`, `DELETE /webhooks/{id}` — create, view,
  and disable outbound webhook subscriptions.
- `GET /webhooks/{id}/deliveries` — view recent delivery attempts.
- `POST /payment/{ride_id}` — create or retrieve the logged-in passenger's
  Stripe PaymentIntent for a completed ride.
- `POST /payment/webhook` — Stripe webhook receiver that verifies event
  signatures and synchronizes payment status.

## Webhooks, step by step

A webhook lets RideSplit notify another server when a ride changes.  It is an
**outbound** HTTP `POST`; it is not a browser notification and it is not a
WebSocket.

1. Start the included learning receiver in a second terminal:

   ```bash
   cd Backend
   uvicorn examples.webhook_receiver:app --port 8001 --reload
   ```

2. While logged in, create a subscription in `/docs` with `POST /webhooks`:

   ```json
   {
     "url": "http://127.0.0.1:8001/webhooks/rides",
     "events": ["request.completed"]
   }
   ```

3. The response includes a `secret` exactly once.  Stop the receiver, start it
   again with that secret, then create another ride and complete it:

   ```bash
   WEBHOOK_SECRET='paste-the-secret-here' uvicorn examples.webhook_receiver:app --port 8001 --reload
   ```

4. The receiver terminal prints the JSON event.  You can inspect its record in
   `GET /webhooks/{id}/deliveries`.  A `DELIVERED` status means the receiver
   returned an HTTP 2xx response.

RideSplit sends these events: `request.created`, `request.accepted`,
`request.started`, `request.completed`, and `request.cancelled`.

### How signing and retries work

Each endpoint has its own random secret.  RideSplit sends the exact JSON body
along with these headers:

```text
X-RideSplit-Event: request.completed
X-RideSplit-Timestamp: 1762430400
X-RideSplit-Signature: sha256=<HMAC-SHA256(timestamp + "." + body)>
```

The receiving application must calculate the same HMAC from the **raw** body
and compare it securely before trusting the payload.  The included
`examples/webhook_receiver.py` shows this in a small, commented example.

When a destination does not return 2xx, RideSplit retries up to five times with
exponential delays (30 seconds, 60 seconds, 120 seconds, and so on).  Start the
retry worker alongside the API in production:

```bash
cd Backend
python -m raw.webhook_worker
```

### Production checklist

- Use HTTPS endpoints only and prevent requests to private/internal network
  addresses at your deployment/network layer (this prevents SSRF).
- Keep endpoint secrets private; never log or return them after creation.
- Verify the signature and reject stale timestamps in every receiver.
- Treat each event `id` as idempotent: save it and ignore duplicates.
- Keep webhook calls short and asynchronous.  A failed receiver must never
  cancel or roll back a completed ride.

## Build next

1. Add automated tests for account creation, login, driver authorization, and
   nearby-driver search using a test Postgres/PostGIS database.
2. Build ride-request endpoints: create, offer to drivers, accept, start,
   complete, and cancel. Enforce each status transition in one place.
3. Add authorization rules so only the passenger who created a ride and the
   assigned driver can view or change it.
4. Add payment, notifications/webhooks, rate limiting, monitoring, and a
   production deployment configuration.
5. Set cookie `secure=True`, configure the real frontend origin, and use HTTPS
   before deploying.
