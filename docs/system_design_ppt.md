# Smart Transport Assistant – Presentation Outline (PPT)

---

## Slide 1 – Title

**Title:** Smart Transport Assistant  
**Subtitle:** Microservices + Agentic AI + Redis + RabbitMQ  
**Presenter:** [Your Name]  
**Version:** v0.2 (Prototype / PoC)

---

## Slide 2 – Agenda

- System overview & architecture
- Agentic AI flow for `/ask`
- End-to-end application flow:
  - User, Driver, Admin journeys
- Redis & RabbitMQ design
- Edge cases & reliability
- Scalability and next steps

---

## Slide 3 – High-Level Architecture (Big Picture)

**Diagram description:**

Draw a 3-layer diagram.

**Top layer – Clients**

- Box: **User (Passenger)** – Streamlit UI  
- Box: **Driver** – Streamlit UI (Driver tab)  
- Box: **Admin** – Streamlit UI (Admin tab)

**Middle layer – Microservices**

Four boxes, left to right:

1. **Auth Service (8004)**  
   - `/auth/signup/*`, `/auth/login/*`, `/auth/me`
2. **Agent Service (8001)**  
   - `/ask`, `/subscribe`, `/unsubscribe`
3. **Fleet Service (8002)**  
   - `/driver/location`, `/driver/status`, `/admin/fleet/overview`, `/admin/route/update`, `/route`
4. **Notification API (8003)**  
   - `/notifications/recent`

**Bottom layer – Infrastructure**

- Box: **Redis (Memurai)**  
  - For OTPs, sessions, ask cache, weather, ETA.
- Box: **RabbitMQ**  
  - Queues: `notifications`, `bus_location`, `bus_status`.
- Box: **Notification Worker**  
  - Consumes `notifications` queue → `tools.notifier` (SMS/console).

**Arrows (high-level):**

- Clients → Auth: signup/login/session.
- Clients → Agent: ask/subscribe/unsubscribe.
- Clients → Fleet: driver/admin features.
- Auth/Agent/Fleet → NotificationService → RabbitMQ → Worker → Notifier.
- Auth/Agent ↔ Redis.

Add a caption:  
“Microservices are stateless; Redis holds hot state; RabbitMQ decouples async work.”

---

## Slide 4 – Tech Stack

- **Frontend:** Streamlit (Python)
- **API / Microservices:** FastAPI (Auth, Fleet, Agent, Notifications)
- **Agentic AI:**
  - PlannerAgent + DecisionEngine
  - SentenceTransformer + FAISS (RAG)
  - Groq LLM (optional, with fallbacks)
- **Infra:**
  - Redis (Memurai) for caching
  - RabbitMQ + aio-pika + worker
- **Notifications:** `tools.notifier` (Twilio integration / console fallback)
- **Security:** JWT-based (in gateway / UI app)

---

## Slide 5 – Agentic AI Flow (Overview)

**Title:** Agentic AI Flow for `/ask` Endpoint

- User asks natural language questions (e.g. *“When will B1 reach S1?”*).
- PlannerAgent:
  - Checks Redis for cached answer.
  - If miss, calls DecisionEngine.
- DecisionEngine:
  - Retrieves context via RAG (buses + routes).
  - Plans tools (gps, weather, eta) via LLM or fallback.
  - Executes tools in order.
  - Composes final answer using LLM or rule-based logic.
- Result is cached for 60 seconds in Redis.

---

## Slide 6 – Diagram: Agentic AI Flow (Detailed)

**Draw this as a left-to-right pipeline.**

1. **Box A – UI (Streamlit)**  
   Label: “User enters question”  
   Example: “When will bus B1 reach stop S1?”

   Arrow: `POST /ask {"query": "..."} →`

2. **Box B – PlannerAgent (Agent Service 8001)**  

   Inside Box B, draw three mini-boxes stacked:

   - **B1: Redis Ask Cache**
     - Normalize query → `ask:<normalized_query>`.
     - `redis_get(key)`:
       - If HIT → return cached `{answer,tool_results,context}`.
       - If MISS → proceed to DecisionEngine.

   - **B2: DecisionEngine – Retrieve Context (RAG)**
     - Input: user query.
     - Access: `data/buses.json`, `data/routes.json`.
     - SentenceTransformer → embeddings.
     - FAISS → top‑k docs as `context[]`.

   - **B3: DecisionEngine – Plan & Execute Tools**
     - **Planning:**
       - Groq LLM (if available) builds `plan = [{"tool":"gps|weather|eta|none","params":{...}},...]`.
       - Else `_fallback_plan`.
     - **Execution (loop):**
       - gps → `gps_simulator` (via Fleet 8002).
       - weather:
         - Check Redis (`weather:lat:lon`); if miss, call `weather.get_weather_by_coords`.
       - eta:
         - Check Redis (`eta:bus_id:stop_id`); if miss:
           - Use `fleet_service` + routes to get stop coords.
           - Use bus coords from gps.
           - Compute distance and ETA; adjust for weather.
       - Collect `tool_results[]`.

3. **Box C – Answer Composer**

   - If Groq: generate short natural-language answer.  
   - If fallback: format from ETA (seconds → minutes/hours).

4. **Box D – Redis Write & HTTP Response**

   - Set: `redis_setex("ask:<normalized_query>", 60s, result_json)`.
   - Return `{"answer": "...", "tool_results": [...], "context": [...]}`.

5. **Box E – UI**

   - Show only `answer` text to user.

**Annotate caching points:**

- Arrow from PlannerAgent to Redis: “Ask cache, TTL 60s”.
- Arrow from DecisionEngine tools to Redis: “Weather cache TTL 5m; ETA cache TTL 60s”.

---

## Slide 7 – Auth Service Overview

- Endpoints:
  - `/auth/signup/start`, `/auth/signup/verify`
  - `/auth/login/start`, `/auth/login/verify`
  - `/auth/me`
- Data:
  - In-memory:
    - `USERS`, `PENDING_SIGNUPS`, `PENDING_LOGINS`, `SESSIONS`.
  - Redis mirrors:
    - `auth:signup:<user_id>` – OTP signup (5 min).
    - `auth:login:<user_id>` – OTP login (5 min).
    - `auth:session:<token>` – session (30 days).
- Purpose:
  - OTP-based signup/login with resilience via Redis.
  - Role-based access: user, driver, admin.

---

## Slide 8 – Diagram: Signup & Login with Redis

**Draw as a vertical flow.**

1. **User → Streamlit UI**: enters `user_id`, `phone`, `role`.

2. **UI → Auth `/signup/start`**:
   - Validate inputs.
   - Generate OTP.
   - Write:
     - `PENDING_SIGNUPS[user_id] = {...}`
     - Redis: `auth:signup:<user_id>` (TTL 5 min).
   - Call `notifier.send_notification` (OTP).

3. **User → Streamlit UI**: enters OTP.

4. **UI → Auth `/signup/verify`**:
   - Read from Redis:
     - `redis_get("auth:signup:<user_id>")`.
   - If not found → fallback to `PENDING_SIGNUPS[user_id]`.
   - Check:
     - No record → “No pending signup”.
     - Expired → “OTP expired”.
     - Wrong OTP → “Invalid OTP”.
   - On success:
     - Create `USERS[user_id]`.
     - Create `SESSIONS[token]` & Redis `auth:session:<token>` (TTL 30 days).

5. **UI → Auth `/auth/me`**:
   - Header: `Authorization: Bearer <token>`.
   - Auth:
     - Read from Redis `auth:session:<token>`.
     - Fallback to `SESSIONS[token]`.
     - Check expiry.

Show similar mini-flow for login (`/auth/login/start`, `/auth/login/verify`).

---

## Slide 9 – Fleet Service (Driver + Admin)

- Driver:
  - `/driver/location`: update bus lat/lon.
  - `/driver/status`: update bus status and message.
  - Publishes `bus_location` and `bus_status` events to RabbitMQ (best effort).
- Admin:
  - `/admin/fleet/overview`: table of all buses (status + location).
  - `/admin/route/update`: update route definitions (in-memory and DB optional).
- In-memory data:
  - `fleet_service.buses`, `fleet_service.routes`.

---

## Slide 10 – User & Driver Journeys (End-to-End)

**Title:** High-Level User & Driver Flow

Bullet points (can be overlay on architecture diagram):

- User journey:
  1. Sign up / login with OTP via Auth (Redis-backed).
  2. Asks question via `/ask` → Agentic AI + Redis.
  3. Subscribes to bus/stop via `/subscribe`.
  4. Receives ETA notifications when bus approaches (Agent + DecisionEngine + NotificationService + RabbitMQ + Worker).

- Driver journey:
  1. Logs in (optional now; later via Auth).
  2. Updates location `/driver/location` regularly.
  3. Updates status `/driver/status` when issues arise.
  4. These updates feed DecisionEngine + user notifications.

---

## Slide 11 – Notifications: Redis + RabbitMQ + Worker

**Diagram description:**

Draw a pipeline:

1. **Box A – Trigger**:
   - “Auth OTP”, “Subscribe confirm”, “ETA alert”, “Unsubscribe confirm”.

2. **Box B – NotificationService (in service process)**:
   - `notify(user_id, message, channel, phone)`:
     - Append to `sent_notifications` (for `/notifications/recent`).
     - Call `rabbitmq_client.publish_notification(...)`.

3. **Arrow → Box C – RabbitMQ**:
   - Queue: `notifications`.
   - Messages are JSON:
     - `{type:"notification", user_id, message, channel, phone}`.

4. **Arrow → Box D – Notification Worker (separate process)**:
   - Consumes from `notifications`.
   - Calls:
     - `tools.notifier.send_notification(user_id, message, channel, phone)`.
   - Twilio is currently suspended → fallback to console `[SMS][FALLBACK]`.

5. **Box E – UI**:
   - `/notifications/recent`:
     - Reads `sent_notifications` from NotificationService.
     - Displays log of notifications.

Note: Worker can be scaled horizontally for more throughput.

---

## Slide 12 – Redis: Keys & Lifetimes

Summarize in table format:

| Key pattern                     | Used by        | Data                         | TTL       |
|---------------------------------|----------------|------------------------------|-----------|
| `auth:signup:<user_id>`         | Auth           | Signup OTP info              | 5 minutes |
| `auth:login:<user_id>`          | Auth           | Login OTP info               | 5 minutes |
| `auth:session:<token>`          | Auth           | Session (`user_id`, role)    | 30 days   |
| `ask:<normalized_query>`        | PlannerAgent   | Answer + context + tools     | 60 sec    |
| `weather:<lat3>:<lon3>`         | DecisionEngine | Weather data                 | 5 minutes |
| `eta:<bus_id>:<stop_id>`        | DecisionEngine | ETA result                   | 60 sec    |

Explain:

- Reads always try Redis first, then fallback to in-memory.
- Later DB can become the source of truth, with Redis as front cache.

---

## Slide 13 – Edge Cases & Error Handling

- Auth:
  - Duplicate `user_id`.
  - Invalid `user_id` / phone format.
  - No pending OTP / expired OTP / invalid OTP.
  - Invalid / expired session token.
- Agent:
  - GPS / ETA / Weather tool failures:
    - Fallbacks to default ETA or “No information available.”
  - `/unsubscribe` for non-existent subscription → 404.
- Fleet:
  - Invalid bus ID → 404 “Bus not found”.
  - Route not found fallback: best-effort lat/lon detection from routes/context.
- UI:
  - Uses `friendly_error(e)` to convert JSON errors to English messages.

---

## Slide 14 – Scalability & Future Work

- **Scalability design:**
  - Stateless microservices + Redis + RabbitMQ.
  - Horizontal scaling by running multiple instances per service.
  - Worker pool for notifications.
- **To reach 10k+ concurrent users:**
  - Add real database (Postgres/MySQL) for:
    - Users, sessions, routes, buses, subscriptions.
  - Use Redis as cache front, not primary store.
  - Deploy behind load balancers (NGINX, API Gateway, Kubernetes).
  - Production-grade monitoring/logging.
  - Production SMS provider (Twilio or local India provider) with proper configuration.

---

## Slide 15 – Summary

- Microservices:
  - Auth, Fleet, Agent, Notifications — clear separation of concerns.
- Agentic AI:
  - RAG + tools + LLM with robust fallbacks and Redis caching.
- Infra:
  - Redis: fast in-memory cache for sessions, OTP, ask, weather, ETA.
  - RabbitMQ: async notifications with worker.
- UX:
  - Clean Streamlit UI for User, Driver, Admin.
  - Recent notifications log, no raw JSON errors.
- Ready for:
  - Database integration.
  - Horizontal scaling to support thousands of users.

