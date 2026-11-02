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
