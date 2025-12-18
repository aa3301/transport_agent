# Smart Transport Assistant – System Design & Flows

## 1. Introduction

This document describes the end-to-end design of the Smart Transport Assistant application:

- Microservices architecture (Auth, Fleet, Agent, Notifications).
- Agentic AI (Gen-AI) flow for answering user questions (`/ask`).
- Use of Redis (Memurai) and RabbitMQ.
- Role-specific flows: User, Driver, Admin.
- Edge cases and error handling.

You can convert this markdown into a Word document or PPT by copying sections.

---

## 2. High-Level System Architecture

### 2.1 Components

- **Front-end**
  - Streamlit UI (`ui_app.py`).
- **Microservices**
  - Auth service – FastAPI (port 8004).
  - Fleet service (Driver + Admin) – FastAPI (port 8002).
  - Agent service (Ask + Subscribe/Unsubscribe) – FastAPI (port 8001).
  - Notification API (Recent notifications) – FastAPI (port 8003).
- **Shared infrastructure**
  - Redis (Memurai) – cache/state store.
  - RabbitMQ – async message bus.
  - Notification worker – consumes from RabbitMQ and calls `tools.notifier`.

### 2.2 Diagram 1: Overall System (Textual Description)

Use this description to draw a diagram:

**Top row (Clients)**

- Boxes:
  - “User (Passenger) – Streamlit UI”.
  - “Driver – Streamlit UI (driver view)”.
  - “Admin – Streamlit UI (admin view)”.

Arrows from each to:

**Middle row (Microservices)**

- Box 1: “Auth Service (8004)”
  - Handles: `/auth/signup/start`, `/auth/signup/verify`, `/auth/login/start`, `/auth/login/verify`, `/auth/me`.
- Box 2: “Fleet Service (8002)”
  - Handles:
    - Driver: `/driver/location`, `/driver/status`.
    - Admin: `/admin/fleet/overview`, `/admin/route/update`, `/route`.
- Box 3: “Agent Service (8001)”
  - Handles: `/ask`, `/subscribe`, `/unsubscribe`.
- Box 4: “Notification API (8003)”
  - Handles: `/notifications/recent`.

**Bottom row (Infrastructure)**

- Box: “Redis (Memurai)”
  - Used by:
    - Auth (OTP + sessions).
    - Agent/DecisionEngine (ask cache, weather cache, ETA cache).
- Box: “RabbitMQ”
  - Queues:
    - `notifications`.
    - `bus_location`.
    - `bus_status`.
- Box: “Notification Worker”
  - Consumes from `notifications`.
  - Calls `tools.notifier.send_notification(...)`.

**Typical flows:**

- UI ↔ Auth for signup/login/session.
- UI ↔ Agent for ask/subscribe/unsubscribe.
- UI ↔ Fleet for driver/admin actions.
- Agent/Fleet/Auth → NotificationService → RabbitMQ → Worker → Notifier.

---

## 3. Agentic AI Flow for `/ask` (Gen-AI)

### 3.1 Overview

The Agent service exposes `/ask` and delegates to:

- `PlannerAgent.handle_query(query)`:
  - Caches answers in Redis for 60 seconds.
  - Calls `DecisionEngine.ask` on cache miss.
- `DecisionEngine.ask(user_query)`:
  - Builds context via RAG (FAISS + SentenceTransformer).
  - Plans tool calls (gps, weather, eta) via Groq LLM or fallback planner.
  - Executes tools sequentially.
  - Composes final answer via Groq LLM or fallback logic.

### 3.2 Diagram 2: Agentic AI Flow (Textual Description)

Use this to build a detailed flow diagram.

**Step 1 – UI → Agent `/ask`**

- User enters question in UI, e.g.:
  - “When will bus B1 reach stop S1?”
- UI sends `POST /ask` to Agent service with JSON:
  - `{ "query": "When will bus B1 reach stop S1?" }`.

**Step 2 – PlannerAgent + Redis Ask Cache**

- `PlannerAgent.handle_query(query)`:
  - Normalize query to lowercase + trimmed spaces:
    - `"where will bus b1 reach stop s1?"`.
  - Cache key:
    - `ask:where will bus b1 reach stop s1?`.
  - Check Redis via `redis_get(cache_key)`:
    - If HIT:
      - Parse cached JSON.
      - Return `{answer, tool_results, context}` immediately.
    - If MISS:
      - Proceed to DecisionEngine.

**Step 3 – DecisionEngine: Context Retrieval (RAG)**

- Load docs from:
  - `data/buses.json`, `data/routes.json` into `docs[]`.
- Use SentenceTransformer (`EMBEDDING_MODEL`, default `all-MiniLM-L6-v2`) to embed docs.
- Use FAISS index (if available) to retrieve top‑k relevant docs:
  - `retrieve_context(query, k=FAISS_K)`.
- If FAISS not available:
  - Just return first `k` docs.

**Step 4 – Planning (LLM or Fallback)**

- Construct `planner_prompt` containing:
  - Instructions to return JSON:
    - `{"plan": [{"tool":"gps|weather|eta|none", "params": {...}}, ...]}`.
  - Domain context (routes, buses).
  - User query.
- If Groq is available:
  - Call `Groq.chat.completions.create` with `llama-3.3-70b-versatile`.
  - Parse JSON from LLM, extract `plan`.
  - On error/failure: plan remains `None`.
- If `plan` is empty/None:
  - Use `_fallback_plan(query)`:
    - Simple rule-based heuristic:
      - “when / ETA / reach / delay” → `weather` + `eta`.
      - Mentions of weather → `gps` + `weather`.
      - “where/location/status” → `gps`.

**Step 5 – Tool Execution (gps, weather, eta)**

Loop through each `step` in `plan`:

1. **gps tool**
   - Determine `bus_id` from params or regex in user query.
   - Call `gps_simulator.get_bus_location(bus_id)`:
     - Under the hood uses Fleet service (via HTTP) to get:
       - latest `lat`, `lon`, `speed_kmph`, `route_id`.
   - Result example:
     - `{"bus_id": "B1", "lat": ..., "lon": ..., "speed_kmph": 22.5}`.
   - Save as `last_bus_loc`.

2. **weather tool** (with Redis cache)
   - Determine `lat, lon` from params or `last_bus_loc`.
   - Build cache key:
     - `weather:<lat_round_3dp>:<lon_round_3dp>`.
   - Redis:
     - If `redis_client.get(cache_key)` HIT:
       - Use cached weather, no external calls.
     - Else:
       - Call `weather.get_weather_by_coords(lat, lon)` (or fallback).
       - Save to Redis with TTL 300s via `setex`.
   - Save as `last_weather`.

3. **eta tool** (with Redis cache)
   - Determine `bus_id` and `stop_id` from params or defaults.
   - Cache key:
     - `eta:<bus_id>:<stop_id>`.
   - Redis:
     - If HIT:
       - Use cached ETA result.
     - Else:
       - Extract stop coordinates:
         - Try `fleet_service.get_bus_status(bus_id)` → `route_id` → `fleet_service.get_route(route_id)` → stops.
         - Fallback to `routes_raw` lookup.
         - Fallback to regex search in context.
       - Get bus coords:
         - From `last_bus_loc`, else re‑query `gps_simulator`.
       - Compute distance via `_haversine_km`.
       - Compute ETA via `eta_calculator.calculate_eta_seconds(...)`.
       - Adjust for `last_weather` delay if available.
       - Store in Redis `eta:<bus_id>:<stop_id>` with TTL 60s.

- All step results pushed into `tool_results[]`.

**Step 6 – Answer Composition**

- If Groq client exists:
  - Build `compose_prompt` with:
    - User query.
    - Context.
    - Tool results.
  - Ask LLM to produce a short, user-friendly text (no JSON).
  - Use as `final_answer`.
- If no LLM or call fails:
  - Extract `eta_sec` and `stop_id` from `tool_results` (eta step).
  - Convert seconds to hours/minutes.
  - Build answer:
    - “The bus is expected to reach stop S1 in about 5 minutes.”

**Step 7 – Store in Redis and Return**

- PlannerAgent:
  - Wraps `result = {"answer": final_answer, "tool_results": [...], "context": [...]}`.
  - Calls `redis_setex(cache_key, 60, json.dumps(result))`.
- Returns `result` to HTTP `/ask` endpoint.
- UI displays only `answer`.

---

## 4. Role-Based Flows & Microservice Interactions

### 4.1 User (Passenger)

- **Signup/Login**
  - Streamlit → Auth service → OTP via notifier.
  - Redis mirrors OTPs and sessions.
- **Ask**
  - Streamlit → Agent `/ask` → PlannerAgent/DecisionEngine + Redis cache.
- **Subscribe/Unsubscribe**
  - Streamlit → Agent `/subscribe` → `subscription_service` (in-memory/DB).
  - ETA notifications triggered by `NotificationAgent.process_subscriptions`:
    - Uses `DecisionEngine` to calculate ETA.
    - Calls `notification_service.notify` (which goes via RabbitMQ + worker).

### 4.2 Driver

- **Update Location**
  - Streamlit → Fleet `/driver/location`:
    - Updates `fleet_service.buses`.
    - Best-effort publish `bus_location` event to RabbitMQ.
- **Update Status**
  - Streamlit → Fleet `/driver/status`:
    - Updates `fleet_service.buses` status and message.
    - Publishes `bus_status` event to RabbitMQ.

### 4.3 Admin

- **Fleet Overview**
  - Streamlit → Fleet `/admin/fleet/overview`.
  - Uses `fleet_service.fleet_overview()` (in-memory buses/routes).
- **Route Update**
  - Streamlit → Fleet `/admin/route/update`.
  - Updates `fleet_service.routes` (and DB if enabled).
  - Ensures DecisionEngine and `/ask` use latest stops.

### 4.4 Notifications

- Source triggers:
  - Auth (OTP).
  - Agent (subscribe, ETA, unsubscribe).
  - Admin broadcasts (via `notify_all` if used).
- Path:
  - `notification_service.notify` → `rabbitmq_client.publish_notification` → RabbitMQ `notifications` queue → `notification_worker` → `tools.notifier`.
- Logs:
  - `sent_notifications` in NotificationService → `/notifications/recent` → UI.

---

## 5. Redis – What, Where, and Why

### 5.1 Keys and TTLs

- **`auth:signup:<user_id>`**
  - Pending signup OTP data (`user_id`, phone, role, otp, ts).
  - TTL: 5 minutes.
- **`auth:login:<user_id>`**
  - Pending login OTP data.
  - TTL: 5 minutes.
- **`auth:session:<token>`**
  - Session data (`user_id`, role, ts).
  - TTL: 30 days.
- **`ask:<normalized_query>`**
  - Cached `/ask` result (`answer`, `tool_results`, `context`).
  - TTL: 60 seconds.
- **`weather:<lat_round_3dp>:<lon_round_3dp>`**
  - Cached weather result.
  - TTL: 5 minutes.
- **`eta:<bus_id>:<stop_id>`**
  - Cached ETA result.
  - TTL: 60 seconds.

### 5.2 Read/Write Pattern

- **Writes**
  - Auth: on OTP creation and session creation.
  - Agent: on `/ask` result, weather calls, eta calls.
- **Reads (first)**
  - Auth: on OTP verify and `/auth/me`.
  - Agent: on `/ask` (PlannerAgent cache).
  - DecisionEngine: on `weather` and `eta` tools.

---

## 6. RabbitMQ – Notifications and Events

### 6.1 Queues

- `notifications` – user notifications (OTP, subscribe, ETA, unsubscribe).
- `bus_location` – bus GPS updates (future consumer).
- `bus_status` – status updates (future consumer).

### 6.2 Flow

1. Any service calls:

   ```python
   await notification_service.notify(user_id, message, channel="sms|console", phone=None or "+91...")
   ```

2. `NotificationService.notify`:
   - Tries:
     - `rabbitmq_client.publish_notification(user_id, message, channel, phone)`.
     - Appends entry to `sent_notifications`.
   - Fallback:
     - Calls `tools.notifier.send_notification` directly if RabbitMQ fails.

3. `notification_worker.py`:
   - Connects to RabbitMQ.
   - Consumes messages from `notifications` queue.
   - For each:
     - Calls `tools.notifier.send_notification(user_id, message, channel, phone)`.
     - Logs result.

4. UI:
   - Uses `/notifications/recent` to read `sent_notifications` and display user‑friendly log.

---

## 7. Scalability Note (10k Users)

- **Architecture is scalable**:
  - Microservices separated.
  - Redis for state/cache.
  - RabbitMQ for async work.
- To support ~10k concurrent users robustly:
  - Introduce a proper database (MySQL/Postgres) for:
    - Users.
    - Sessions.
    - Fleet data.
    - Subscriptions.
  - Use Redis as a cache front, not primary store.
  - Run multiple instances of each microservice:
    - Behind a load balancer.
    - With proper process manager / orchestrator (Gunicorn/Uvicorn workers, Docker, Kubernetes, etc.).
- Current implementation is a functional prototype / PoC with:
  - In‑memory primary stores.
  - Single instances per service.
  - Twilio suspended (console fallback for SMS).
- With DB + horizontal scaling added, this design can be extended to 10k+ users.

---

## 8. Summary

- **User journey**:
  - Sign up → OTP via notifier → login → home → ask/subscribe/unsubscribe → receive notifications.
- **Driver journey**:
  - Login → update location/status continuously.
- **Admin journey**:
  - Login → monitor fleet overview → update route definitions.
- **AI journey**:
  - `/ask` → PlannerAgent → Redis cache → DecisionEngine → tools (gps/weather/eta) → LLM fallback → answer.
- **Infrastructure**:
  - Redis optimizes repeated queries and OTP/session handling.
  - RabbitMQ decouples notification sending and supports scaling workers.

You can now convert this markdown to a .docx or PPT, and use the diagram descriptions to draw clean diagrams for your client.
