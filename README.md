# Real-Time Dispatch & Service Marketplace

A real-time platform that matches passengers (requestors) with nearby available drivers based on location, availability and capacity. Built to learn WebSockets, webhooks, geospatial queries and concurrency control.

> Status: in development (3-week build). Update the checkboxes at the bottom as you go.

---

## 1. Scope

### In scope (MVP)
- Register / login with a role: `passenger` or `driver`
- Drivers go online/offline and stream their location
- Passengers create a ride request (pickup + dropoff)
- Server finds nearby available drivers (PostGIS) and offers the request
- A driver accepts; the request can never be accepted twice (no double-booking)
- Live map dashboard (React + Leaflet) showing drivers and requests
- Outbound webhooks fired on request status changes
- Redis for caching and pub/sub
- Docker Compose for local development
- Basic load test (Locust or k6)

### Out of scope (do not attempt)
- Payments, ratings, surge pricing
- Turn-by-turn routing / ETA (use straight-line distance)
- Native mobile apps
- Kubernetes (stretch goal only)
- Multi-region deployment

---

## 2. Tech Stack

| Layer | Tool |
|---|---|
| API | FastAPI + Uvicorn |
| DB | PostgreSQL 16 + PostGIS 3 |
| ORM / migrations | SQLAlchemy 2.0 (async) + GeoAlchemy2 + Alembic |
| Cache / pub-sub | Redis 7 |
| Real-time | FastAPI native WebSockets |
| Frontend | React + Vite + Leaflet (react-leaflet) |
| Auth | JWT (access tokens) |
| Infra | Docker, Docker Compose |
| Testing | pytest, pytest-asyncio, httpx, Locust/k6 |

---

## 3. Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop (runs Postgres+PostGIS and Redis)
- Git

> PostGIS is NOT installed with pip. It is a PostgreSQL extension that lives on the database server. Use the `postgis/postgis` Docker image, then run `CREATE EXTENSION postgis;`.

---

## 4. Setup

### 4.1 Start Postgres (PostGIS) and Redis

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: dispatch
      POSTGRES_PASSWORD: dispatch
      POSTGRES_DB: dispatch
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
volumes:
  pgdata:
```

```bash
docker compose up -d
```

### 4.2 Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

`requirements.txt`:

```
fastapi
uvicorn[standard]        # includes websockets support
sqlalchemy[asyncio]>=2.0
asyncpg
geoalchemy2
alembic
pydantic-settings
redis
pyjwt
bcrypt
httpx
python-multipart
pytest
pytest-asyncio
locust
```

### 4.3 Environment variables (`backend/.env`)

```
DATABASE_URL=postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=change-me
JWT_EXPIRE_MINUTES=60
MATCH_RADIUS_KM=5
OFFER_TIMEOUT_SECONDS=15
WEBHOOK_SIGNING_SECRET=change-me-too
```

### 4.4 Frontend

```bash
cd frontend
npm create vite@latest . -- --template react
npm install react-leaflet leaflet axios
npm run dev
```

---

## 5. Database Schema

First migration must run: `CREATE EXTENSION IF NOT EXISTS postgis;`

Use `geography(Point, 4326)` so distances are in meters and `ST_DWithin` takes meters.

### users
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | text UNIQUE NOT NULL | |
| password_hash | text NOT NULL | |
| full_name | text NOT NULL | |
| phone | text | |
| role | enum(`passenger`,`driver`) NOT NULL | |
| is_active | bool default true | |
| created_at | timestamptz | |

### driver_profiles (1:1 with users where role = driver)
| Column | Type | Notes |
|---|---|---|
| user_id | UUID PK, FK users.id | |
| vehicle_type | text | e.g. car, bike |
| plate_number | text | |
| capacity | int default 1 | max concurrent jobs / seats |
| status | enum(`offline`,`available`,`busy`) | default offline |
| current_location | geography(Point,4326) | nullable until first update |
| location_updated_at | timestamptz | |
| version | int default 0 | optimistic locking |

Indexes:
- `GIST (current_location)`
- partial index on `status = 'available'`

### ride_requests
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| passenger_id | UUID FK users.id | |
| driver_id | UUID FK users.id, nullable | set on accept |
| pickup_location | geography(Point,4326) | |
| dropoff_location | geography(Point,4326) | |
| status | enum(`pending`,`offered`,`accepted`,`in_progress`,`completed`,`cancelled`,`expired`) | |
| requested_at | timestamptz | |
| accepted_at | timestamptz | |
| completed_at | timestamptz | |
| version | int default 0 | optimistic locking |

Indexes: `GIST (pickup_location)`, `(status)`, `(passenger_id)`, `(driver_id)`.

Constraint (prevents double-booking at the DB level):
```sql
CREATE UNIQUE INDEX one_active_job_per_driver
ON ride_requests (driver_id)
WHERE status IN ('accepted','in_progress');
```

### ride_offers (who was offered which request)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| request_id | UUID FK | |
| driver_id | UUID FK | |
| status | enum(`sent`,`accepted`,`rejected`,`expired`) | |
| sent_at / responded_at | timestamptz | |

### driver_location_history (optional, good for load testing)
| Column | Type |
|---|---|
| id | bigserial PK |
| driver_id | UUID FK |
| location | geography(Point,4326) |
| recorded_at | timestamptz |

### webhook_endpoints
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| owner_id | UUID FK users.id | |
| url | text | |
| secret | text | used for HMAC signature |
| events | text[] | e.g. `{request.accepted,request.completed}` |
| is_active | bool | |

### webhook_deliveries
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| endpoint_id | UUID FK | |
| event_type | text | |
| payload | jsonb | |
| status | enum(`pending`,`delivered`,`failed`) | |
| attempts | int | |
| next_attempt_at | timestamptz | retry with backoff |
| last_response_code | int | |

---

## 6. Key Queries

Nearby available drivers (5 km radius, nearest first):

```sql
SELECT user_id,
       ST_Distance(current_location, :pickup) AS meters
FROM driver_profiles
WHERE status = 'available'
  AND ST_DWithin(current_location, :pickup, :radius_m)
ORDER BY current_location <-> :pickup
LIMIT 10;
```

Accept a request safely (no race conditions):

```sql
BEGIN;
SELECT * FROM ride_requests
WHERE id = :id AND status IN ('pending','offered')
FOR UPDATE SKIP LOCKED;
-- if no row returned: someone else got it -> return 409
UPDATE ride_requests SET status='accepted', driver_id=:driver, accepted_at=now()
WHERE id=:id;
UPDATE driver_profiles SET status='busy', version=version+1 WHERE user_id=:driver;
COMMIT;
```

---

## 7. API Endpoints (planned)

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | /auth/register | public | create user with role |
| POST | /auth/login | public | get JWT |
| GET | /me | any | current user |
| POST | /drivers/me/status | driver | go online/offline |
| POST | /drivers/me/location | driver | update position |
| GET | /drivers/nearby?lat&lng&radius_km | any | proximity query |
| POST | /requests | passenger | create ride request |
| GET | /requests/{id} | owner | status |
| POST | /requests/{id}/accept | driver | accept (locked) |
| POST | /requests/{id}/start | driver | begin trip |
| POST | /requests/{id}/complete | driver | finish trip |
| POST | /requests/{id}/cancel | passenger | cancel |
| POST | /webhooks | any | register endpoint |
| GET | /webhooks/deliveries | owner | delivery log |

## 8. WebSocket Protocol (planned)

Connect: `ws://localhost:8000/ws?token=<JWT>`

Server -> client messages:
```json
{"type":"driver.location","driver_id":"...","lat":0,"lng":0}
{"type":"request.offer","request_id":"...","pickup":{"lat":0,"lng":0}}
{"type":"request.status","request_id":"...","status":"accepted"}
```
Client -> server:
```json
{"type":"location.update","lat":0,"lng":0}
{"type":"offer.respond","request_id":"...","accept":true}
```

Scaling note: each backend node only holds its own sockets. Publish events to Redis pub/sub so every node can forward them to its connected clients.

## 9. Webhooks (what to learn)

- Outbound: when a request changes status, POST JSON to every registered URL
- Sign the body with HMAC-SHA256 using the endpoint secret, send in `X-Signature`
- Retry failures with exponential backoff, log every attempt in `webhook_deliveries`
- Test with https://webhook.site or a tiny local receiver endpoint

---

## 10. Suggested Folder Structure

```
backend/
  app/
    main.py
    core/        (config, security, db)
    models/      (SQLAlchemy models)
    schemas/     (Pydantic)
    routers/     (auth, drivers, requests, webhooks, ws)
    services/    (matching, webhook_dispatcher, redis_pubsub)
  alembic/
  tests/
frontend/
  src/
docker-compose.yml
README.md
```

---

## 11. Build Checklist (3 weeks)

**Week 1 - Foundation**
- [ ] Docker Compose (PostGIS + Redis)
- [ ] Models + Alembic migration + GiST indexes
- [ ] Register/login with roles + JWT + role guards
- [ ] Driver location update + nearby query endpoint
- [ ] Create/accept request with row locking

**Week 2 - Real-time**
- [ ] WebSocket manager (auth, connect/disconnect)
- [ ] Driver location streaming + offers + status events
- [ ] Redis pub/sub bridge between nodes
- [ ] Outbound webhooks with signature + retries

**Week 3 - UI, proof, ship**
- [ ] React + Leaflet live map
- [ ] Request/accept UI for both roles
- [ ] Concurrency test (many drivers accept same request, exactly one wins)
- [ ] Load test + measured numbers
- [ ] Deploy (single VM or Render/Fly) + short demo GIF

## 12. Metrics to Measure (before putting them on a resume)

- p50/p95 latency of `/drivers/nearby` with N seeded drivers
- Double-allocations under concurrent accept test (target: 0)
- WebSocket connections held per node