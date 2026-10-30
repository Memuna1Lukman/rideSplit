# Real-Time Geo-Aware Dispatch & Service Marketplace

A backend-first dispatch engine that matches service providers (drivers, delivery agents) to nearby requests based on location, availability and capacity, in the style of Uber or DoorDash.

> **Status:** Week 1 of 5, geospatial foundation.
> **Goal of Week 1:** A working API that stores provider locations in PostGIS and returns the nearest available providers quickly, with proof (benchmarks) that it is fast.

---

## 1. Project Roadmap

| Week | Focus | Key Learning |
|------|-------|--------------|
| **1** | PostGIS schema, location update API, proximity queries | Geospatial data, spatial indexes (GiST) |
| 2 | WebSocket layer, live driver position streaming, matching logic | WebSockets, connection management |
| 3 | React dashboard with a live map | Frontend state, Leaflet/Mapbox, WebSocket client |
| 4 | Concurrency control (locking), Redis cache and Redis GEO | Race conditions, transactions, caching |
| 5 | Load testing, CI/CD, deployment, query optimization | Measuring, profiling, DevOps |

This README covers **Week 1 requirements** in detail. Later weeks are summarized only.

---

## 2. Week 1 Scope

### In scope
- Project setup with Docker Compose (FastAPI app and PostGIS database)
- Database schema using the PostGIS `geography` type
- Database migrations with Alembic
- REST API for providers and location updates
- Proximity ("nearby providers") query using `ST_DWithin` and `ST_Distance`
- A GiST spatial index, with measured before/after query times
- A seed script that generates 50,000 random providers
- Automated tests for the main endpoints
- A short written summary of benchmark results

### Out of scope for Week 1
- WebSockets (Week 2)
- Matching and assignment logic (Weeks 2 and 4)
- Frontend (Week 3)
- Redis, locking, Kubernetes (Weeks 4 and 5)

---

## 3. Tech Stack (Week 1)

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ |
| API framework | FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 with PostGIS 3 (`postgis/postgis` Docker image) |
| ORM / Geo | SQLAlchemy 2.0 and GeoAlchemy2 |
| Migrations | Alembic |
| Testing | pytest, httpx |
| Tooling | Docker, Docker Compose, Ruff (lint/format) |

---

## 4. Functional Requirements

### FR-1: Provider management
- Create a provider with a name, initial location, capacity and status.
- Fetch a provider by ID.
- Update a provider's status: `available`, `busy` or `offline`.

### FR-2: Location updates
- A provider can send its latest location (`lat`, `lng`).
- The system stores only the **current** location on the provider row and updates `last_seen_at`.
- Invalid coordinates are rejected with a `422` error.
  - Latitude must be between -90 and 90.
  - Longitude must be between -180 and 180.

### FR-3: Nearby provider search
- Given a point (`lat`, `lng`) and a `radius_km`, return providers within that radius.
- Only return providers with status `available` and spare capacity (`current_load < capacity`).
- Results are sorted by distance, nearest first.
- Support a `limit` parameter (default 10, max 50).
- Each result includes the distance in meters.

### FR-4: Health check
- `GET /health` confirms the API is running and can reach the database.

---

## 5. API Specification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service and database health |
| `POST` | `/providers` | Create a provider |
| `GET` | `/providers/{id}` | Get a provider |
| `PATCH` | `/providers/{id}/status` | Change status |
| `PUT` | `/providers/{id}/location` | Update current location |
| `GET` | `/providers/nearby` | Find nearby available providers |

### Example: create a provider
```http
POST /providers
{
  "name": "Kwame",
  "lat": 6.6885,
  "lng": -1.6244,
  "capacity": 3
}
```

### Example: nearby search
```http
GET /providers/nearby?lat=6.6885&lng=-1.6244&radius_km=3&limit=10
```

Response:
```json
[
  { "id": "…", "name": "Kwame", "distance_m": 412.7, "lat": 6.6912, "lng": -1.6231 }
]
```

---

## 6. Database Design

### Table: `providers`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, primary key | |
| `name` | text, not null | |
| `status` | enum (`available`, `busy`, `offline`) | default `offline` |
| `capacity` | integer, not null | max concurrent jobs, must be ≥ 1 |
| `current_load` | integer, not null | default 0, must be ≤ `capacity` |
| `location` | `geography(Point, 4326)` | **GiST index required** |
| `last_seen_at` | timestamptz | updated on each location update |
| `version` | integer | default 0, reserved for optimistic locking in Week 4 |
| `created_at` / `updated_at` | timestamptz | |

### Table: `service_requests` (schema only in Week 1)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID, primary key | |
| `location` | `geography(Point, 4326)` | pickup location |
| `status` | enum (`pending`, `assigned`, `completed`, `cancelled`) | |
| `assigned_provider_id` | UUID, nullable, FK to `providers` | |
| `created_at` | timestamptz | |

### Required indexes
- GiST index on `providers.location`
- B-tree index on `providers.status`

### Core query pattern
```sql
SELECT id, name,
       ST_Distance(location, ST_MakePoint(:lng, :lat)::geography) AS distance_m
FROM providers
WHERE status = 'available'
  AND current_load < capacity
  AND ST_DWithin(location, ST_MakePoint(:lng, :lat)::geography, :radius_m)
ORDER BY distance_m
LIMIT :limit;
```

Note that PostGIS uses **(longitude, latitude)** order, not (lat, lng). Mixing these up is the most common geospatial bug.

---

## 7. Non-Functional Requirements

- **Performance target:** Nearby search on 50,000 providers should be fast enough to be a hot-path query. Record your actual p50 and p95 numbers. Do not assume a target; measure it.
- **Validation:** All input validated with Pydantic models.
- **Configuration:** Secrets and DB URLs come from environment variables (`.env`), never hard-coded.
- **Reproducibility:** `docker compose up` must bring up the entire system from a fresh clone.
- **Code quality:** Ruff passes with no errors; endpoints have type hints.

---

## 8. Suggested Project Structure

```
.
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   └── services/
├── alembic/
├── scripts/
│   └── seed_providers.py
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## 9. Week 1 Task Checklist

### Setup
- [ ] Create the GitHub repository and this README
- [ ] Write `docker-compose.yml` with the `postgis/postgis` image and the API service
- [ ] Confirm PostGIS works: `CREATE EXTENSION postgis; SELECT PostGIS_Version();`
- [ ] Add `/health` endpoint

### Database
- [ ] Define models with SQLAlchemy and GeoAlchemy2
- [ ] Create the first Alembic migration (including the PostGIS extension and the GiST index)
- [ ] Add a `CHECK` constraint so `current_load <= capacity`

### API
- [ ] `POST /providers` and `GET /providers/{id}`
- [ ] `PUT /providers/{id}/location`
- [ ] `PATCH /providers/{id}/status`
- [ ] `GET /providers/nearby`

### Data and benchmarking
- [ ] Write `seed_providers.py` to insert 50,000 providers around a city
- [ ] Run `EXPLAIN ANALYZE` on the nearby query **without** the GiST index
- [ ] Add the index, run again, and save both outputs in `docs/benchmarks.md`
- [ ] Compare results using different radii (1 km, 5 km, 20 km)

### Testing
- [ ] Test provider creation and validation errors
- [ ] Test that location updates change the nearby results
- [ ] Test that `offline` and full-capacity providers are excluded
- [ ] Test that results are sorted by distance

---

## 10. Definition of Done (Week 1)

Week 1 is complete when all of these are true:

1. `docker compose up` starts the API and database from scratch.
2. All endpoints in section 5 work and are covered by passing tests.
3. 50,000 providers can be seeded with one command.
4. `docs/benchmarks.md` shows query plans and timings before and after the spatial index.
5. You can explain, in your own words, why `ST_DWithin` with a GiST index is faster than computing distances for every row.

---

## 11. Learning Notes for Upcoming Weeks

You are learning WebSockets and webhooks through this project. Here is where they fit.

### WebSockets (Week 2)
Before starting Week 2, understand:
- How a WebSocket differs from a normal HTTP request (persistent, two-way connection)
- FastAPI's `WebSocket` class: `accept()`, `receive_json()`, `send_json()`
- A **connection manager** pattern: tracking which clients are connected and broadcasting to them
- Handling disconnects cleanly (`WebSocketDisconnect`)
- Why scaling to several backend servers breaks in-memory connection tracking, and how Redis Pub/Sub solves it (Week 4)

### Webhooks (optional extension)
Webhooks are not naturally part of the matching engine, but you can add them as an extension: when a request's status changes (for example `assigned` or `completed`), the system sends an HTTP `POST` to a URL the customer registered. Learn:
- What a webhook is (your server calls someone else's URL when an event happens)
- Signing payloads with HMAC so receivers can verify them
- Retries with backoff when the receiver is down
- Idempotency, so retries don't cause duplicate actions

### Concurrency (Week 4)
Study ahead:
- What a race condition is, with a "two requests, one provider" example
- Database transactions and isolation levels
- Pessimistic locking (`SELECT … FOR UPDATE`) versus optimistic locking (the `version` column)

---

## 12. Recommended Resources

- PostGIS documentation: `ST_DWithin`, `ST_Distance`, geography vs geometry
- GeoAlchemy2 documentation
- FastAPI documentation: WebSockets, testing, dependencies
- PostgreSQL documentation: `EXPLAIN`, indexes, transaction isolation
- Locust or k6 documentation (for Week 5)

---

## 13. Results (fill in as you build)

| Metric | Without index | With GiST index |
|--------|---------------|-----------------|
| Rows in table | 50,000 | 50,000 |
| Nearby query (1 km), p50 | _TBD_ | _TBD_ |
| Nearby query (5 km), p50 | _TBD_ | _TBD_ |
| Nearby query (20 km), p50 | _TBD_ | _TBD_ |

Only record numbers you measured yourself.