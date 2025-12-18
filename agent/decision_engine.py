# agent/decision_engine.py
"""
DecisionEngine (Week-4)

Responsibilities:
- Build RAG context using local mock data (data/buses.json + data/routes.json)
- Encode queries using a multilingual SentenceTransformer and search with FAISS
- Ask LLM (Groq) for a plan (list of tool steps) OR fallback to a simple planner
- Execute the plan sequentially: gps -> weather -> eta (as requested)
- Compose a final user-friendly answer using LLM (if available) or fallback text
"""

import os
import json
import re
import traceback
from typing import List, Dict, Any, Optional
from math import radians, sin, cos, sqrt, atan2

import numpy as np

from config.settings import settings

# optional Groq client
try:
    from groq import Groq
except Exception:
    Groq = None

# sentence-transformers + faiss
# In CI or lightweight environments, installing the full
# sentence-transformers stack (with PyTorch) can be heavy or fail.
# Instead of crashing import, we fall back to a tiny dummy encoder
# so tests and non-ML environments can still run.
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:
    SentenceTransformer = None  # type: ignore

try:
    import faiss
except Exception:
    faiss = None  # we'll handle lack of faiss gracefully

# tools (use the project's tools; these should exist)
from tools import gps_simulator, eta_calculator, weather
from services.fleet_service import fleet_service

# Optional Redis client for caching
try:
    from infra.redis_client import redis_client
except Exception:
    redis_client = None


# ---------------------------
# Helpers for loading docs
# ---------------------------
def _load_context_docs(data_dir: str = "data") -> List[str]:
    """Load small textual docs from local mock files to build RAG context."""
    docs: List[str] = []
    try:
        buses_p = os.path.join(data_dir, "buses.json")
        if os.path.exists(buses_p):
            with open(buses_p, "r", encoding="utf-8") as f:
                buses = json.load(f)
            for bid, b in buses.items():
                # short summary per bus
                docs.append(f"Bus {bid}: {json.dumps(b)}")

        routes_p = os.path.join(data_dir, "routes.json")
        if os.path.exists(routes_p):
            with open(routes_p, "r", encoding="utf-8") as f:
                routes = json.load(f)
            for rid, r in routes.items():
                docs.append(f"Route {rid}: {json.dumps(r)}")
    except Exception:
        # if anything fails, we'll still return at least 1 doc
        traceback.print_exc()
    # domain hints
    docs.append("Heavy rain often causes delays on major roads.")
    docs.append("If a bus reports breakdown, notify admin and suggest alternatives.")
    if not docs:
        docs = ["No context available."]
    return docs


def _load_routes_raw(data_dir: str = "data") -> Dict[str, Any]:
    """Load raw routes JSON for direct lat/lon lookup."""
    routes_p = os.path.join(data_dir, "routes.json")
    if os.path.exists(routes_p):
        try:
            with open(routes_p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            traceback.print_exc()
    return {}


# ---------------------------
# DecisionEngine
# ---------------------------
class DecisionEngine:
    def __init__(self):
        # 1) Encoder: multilingual SentenceTransformer (configurable)
        # If the real library is unavailable (e.g. in CI), use a
        # deterministic dummy encoder so the rest of the pipeline and
        # tests can still run without heavy ML dependencies.
        if SentenceTransformer is not None:
            embed_name = getattr(settings, "EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            try:
                self.encoder = SentenceTransformer(embed_name)
            except Exception as e:
                print("Failed to load configured embedding model:", e)
                self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
        else:
            print("sentence-transformers not available; using dummy encoder for DecisionEngine.")
            class _DummyEncoder:
                def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
                    if isinstance(texts, str):
                        texts = [texts]
                    # simple deterministic hashing into a fixed-size vector
                    vecs = []
                    for t in texts:
                        seed = abs(hash(t)) % (10 ** 6)
                        rng = np.random.default_rng(seed)
                        vecs.append(rng.standard_normal(384, dtype="float32"))
                    arr = np.stack(vecs, axis=0)
                    return arr
            self.encoder = _DummyEncoder()

        # 2) Build RAG docs & in-memory embeddings (FAISS index optional)
        #    We always compute embeddings so we can measure similarity
        #    for guardrails, even if FAISS is not installed.
        self.docs = _load_context_docs()
        self.index = None
        self.embeddings = None
        try:
            embs = self.encoder.encode(self.docs, convert_to_numpy=True, show_progress_bar=False)
            if embs.ndim == 1:
                embs = np.expand_dims(embs, 0)
            self.embeddings = np.asarray(embs, dtype="float32")
        except Exception as e:
            print("Embedding computation for RAG failed:", e)
            self.embeddings = None

        if faiss is not None and self.embeddings is not None:
            try:
                dim = self.embeddings.shape[1]
                self.index = faiss.IndexFlatL2(dim)
                self.index.add(self.embeddings)
            except Exception as e:
                print("FAISS index build failed:", e)
                self.index = None
        elif faiss is None:
            print("FAISS not available; RAG similarity will use pure NumPy.")

        # 3) LLM client (Groq) optional
        self.client = None
        if Groq is not None and getattr(settings, "GROQ_API_KEY", None):
            try:
                self.client = Groq(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                print("Groq init failed, falling back to rule-based planner:", e)
                self.client = None

        self.routes_raw = _load_routes_raw()  # <-- new: keep parsed routes structure

    # ---------------------------
    # RAG retrieval
    # ---------------------------
    def retrieve_context(self, query: str, k: Optional[int] = None) -> List[str]:
        """Return top-k relevant docs for the query. Fallback to top-k docs if FAISS missing."""
        if k is None:
            k = int(getattr(settings, "FAISS_K", 3))
        if self.index is None:
            # No FAISS index – fall back to simple top-k (or caller can
            # use retrieve_with_scores for similarity-aware ranking).
            return self.docs[:k]
        try:
            q_emb = self.encoder.encode([query], convert_to_numpy=True)
            q_emb = np.asarray(q_emb, dtype="float32")
            D, I = self.index.search(q_emb, k)
            results = []
            for idx in I[0]:
                if 0 <= idx < len(self.docs):
                    results.append(self.docs[idx])
            return results
        except Exception as e:
            print("retrieve_context error:", e)
            return self.docs[:k]

    def retrieve_with_scores(self, query: str, k: Optional[int] = None) -> List[tuple[str, float]]:
        """Return (doc, cosine_similarity) pairs for the query.

        This powers a simple relevance guardrail: callers can inspect the
        maximum similarity and decide to abstain ("No information
        available") when nothing is close enough.
        """
        if k is None:
            k = int(getattr(settings, "FAISS_K", 3))
        if not self.docs:
            return []
        if self.embeddings is None:
            # If we couldn't pre-compute embeddings, just return the first
            # k docs with a dummy similarity of 1.0 so callers can still
            # function (they may choose their own guardrail policy).
            return [(d, 1.0) for d in self.docs[:k]]
        try:
            q_emb = self.encoder.encode([query], convert_to_numpy=True)
            q_emb = np.asarray(q_emb, dtype="float32")
            q_vec = q_emb[0]
            doc_vecs = self.embeddings
            # Cosine similarity between query and each doc
            doc_norms = np.linalg.norm(doc_vecs, axis=1)
            q_norm = float(np.linalg.norm(q_vec)) or 1.0
            sims = np.dot(doc_vecs, q_vec) / (doc_norms * q_norm + 1e-8)
            # Highest similarity first
            top_idx = np.argsort(-sims)[:k]
            return [(self.docs[i], float(sims[i])) for i in top_idx]
        except Exception as e:
            print("retrieve_with_scores error:", e)
            return [(d, 1.0) for d in self.docs[:k]]

    # ---------------------------
    # Main public API
    # ---------------------------
    async def ask(self, user_query: str) -> Dict[str, Any]:
        """
        Execute tools (gps/weather/eta) and ALWAYS try to return a numeric ETA
        when the question is 'when will bus X reach stop Y?'.
        """
        try:
            # ---------- Guardrail 1: basic input sanitation ----------
            query = (user_query or "").strip()
            if not query:
                return {
                    "answer": "No information available.",
                    "tool_results": [],
                    "context": [],
                }

            # ---------- Guardrail 2: domain / intent filter ----------
            # If the question does not look like a transport question at all
            # (no mention of buses, routes, stops, ETA, etc.), do not try to
            # fabricate an answer – respond with a neutral fallback.
            if not self._is_transport_query(query):
                return {
                    "answer": (
                        "I am a transport assistant and only answer questions about "
                        "buses, routes and stops. No information is available for this question."
                    ),
                    "tool_results": [],
                    "context": [],
                }

            # ---------- Guardrail 3: basic entity validation ----------
            # If the user mentions specific bus/route IDs that do not exist in
            # the in-memory fleet data, fail fast instead of hallucinating.
            invalid_reason = self._validate_referenced_entities(query)
            if invalid_reason:
                return {
                    "answer": invalid_reason,
                    "tool_results": [],
                    "context": [],
                }

            # ---------- Guardrail 4: RAG relevance threshold ----------
            # Use embedding similarity between query and RAG docs. If even the
            # best match is below a configurable threshold, abstain.
            pairs = self.retrieve_with_scores(query, k=int(getattr(settings, "FAISS_K", 3)))
            context_docs = [p[0] for p in pairs]
            max_sim = max((p[1] for p in pairs), default=0.0)
            min_sim = float(getattr(settings, "RAG_MIN_SIM", 0.35))
            if context_docs and max_sim < min_sim:
                return {
                    "answer": "I could not find reliable information for this question in my current data.",
                    "tool_results": [],
                    "context": [],
                }
            context = context_docs or self.retrieve_context(query, k=int(getattr(settings, "FAISS_K", 3)))

            # Build a planner prompt instructing the LLM to return a JSON plan
            planner_prompt = (
                "You are a multilingual transport assistant planner.\n"
                "Return ONLY valid JSON with a top-level key 'plan' which is a list of steps.\n"
                "Each step: {\"tool\": \"gps|weather|eta|none\", \"params\": { ... }}\n"
                "- gps expects {\"bus_id\": \"B2\"}\n"
                "- weather expects {\"lat\": 12.3, \"lon\": 45.6} or empty to use bus location\n"
                "- eta expects {\"bus_id\": \"B2\", \"stop_id\": \"S1\"}\n\n"
                f"CONTEXT:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                f"USER: {query}\n\nReturn JSON only."
            )

            plan = None
            if self.client:
                try:
                    resp = self.client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": planner_prompt}],
                        temperature=0.0,
                    )
                    text = None
                    try:
                        text = resp.choices[0].message.content
                    except Exception:
                        text = getattr(resp.choices[0], "text", None)
                    if text:
                        # attempt to parse JSON directly; tolerant parsing for wrapped text
                        try:
                            decoded = json.loads(text)
                            plan = decoded.get("plan")
                        except Exception:
                            # use module-level `re` (avoid local import which causes UnboundLocalError)
                            m = re.search(r"\{.*\}", text, flags=re.S)
                            if m:
                                try:
                                    decoded = json.loads(m.group(0))
                                    plan = decoded.get("plan")
                                except Exception:
                                    plan = None
                except Exception as e:
                    print("Groq planner call failed:", e, traceback.format_exc())
                    plan = None

            if not plan:
                plan = self._fallback_plan(user_query)

            tool_results: List[Dict[str, Any]] = []
            last_bus_loc = None
            last_weather = None

            for step in plan:
                tool_name = step.get("tool")
                params = step.get("params") if isinstance(step.get("params"), dict) else {}
                result = None
                try:
                    if tool_name == "gps":
                        # Use gps_simulator ONLY for live position (it already calls 8002/bus/status).
                        bus_id = params.get("bus_id") or self._extract_bus_id(user_query)
                        if bus_id:
                            live = gps_simulator.get_bus_location(bus_id)
                            if live:
                                result = {
                                    "bus_id": live.get("bus_id", bus_id),
                                    "lat": live.get("lat"),
                                    "lon": live.get("lon"),
                                    "speed_kmph": live.get("speed_kmph", 20.0),
                                }
                            else:
                                result = {"error": f"No GPS data for bus {bus_id}"}
                            last_bus_loc = result if isinstance(result, dict) else None
                        else:
                            result = {"error": "No bus_id provided for gps tool"}

                    elif tool_name == "weather":
                        # Weather lookup with optional Redis cache
                        lat = params.get("lat")
                        lon = params.get("lon")

                        if (lat is None or lon is None) and last_bus_loc and isinstance(last_bus_loc, dict):
                            lat = last_bus_loc.get("lat")
                            lon = last_bus_loc.get("lon")

                        if lat is not None and lon is not None:
                            cache_key = None
                            if redis_client:
                                # Rounded coords to reduce key explosion
                                key_lat = round(float(lat), 3)
                                key_lon = round(float(lon), 3)
                                cache_key = f"weather:{key_lat}:{key_lon}"
                                try:
                                    cached = await redis_client.get(cache_key)
                                    if cached:
                                        result = json.loads(cached)
                                        print(f"[DecisionEngine][Redis] Weather cache hit: {cache_key}")
                                        last_weather = result if isinstance(result, dict) else None
                                        tool_results.append({"step": step, "result": result})
                                        continue  # use cached result
                                except Exception:
                                    # Cache errors should not break logic
                                    pass

                            # Cache miss or Redis unavailable -> fetch fresh
                            if hasattr(weather, "get_weather_by_coords"):
                                result = weather.get_weather_by_coords(lat, lon)
                            else:
                                try:
                                    result = weather.get_weather(city="Kolkata")
                                except Exception:
                                    result = {"condition": "unknown"}
                            last_weather = result if isinstance(result, dict) else None

                            # Store in cache
                            if redis_client and cache_key and isinstance(result, dict):
                                try:
                                    await redis_client.setex(cache_key, 300, json.dumps(result))
                                    print(f"[DecisionEngine][Redis] Weather cache set: {cache_key}")
                                except Exception:
                                    pass
                        else:
                            result = {"error": "No coordinates available for weather tool"}

                    elif tool_name == "eta":
                        # ETA computation with optional Redis cache
                        bus_id = params.get("bus_id") or self._extract_bus_id(user_query)
                        stop_id = params.get("stop_id") or params.get("stop") or "S1"

                        cache_key = None
                        if redis_client and bus_id and stop_id:
                            cache_key = f"eta:{bus_id}:{stop_id}"
                            try:
                                cached = await redis_client.get(cache_key)
                                if cached:
                                    result = json.loads(cached)
                                    print(f"[DecisionEngine][Redis] ETA cache hit: {cache_key}")
                                    tool_results.append({"step": step, "result": result})
                                    continue  # use cached ETA
                            except Exception:
                                pass

                        stop_lat, stop_lon = None, None
                        route_stop = None

                        # 1) Try to get route_id from local fleet_service for stop lookup
                        route_id = None
                        if bus_id:
                            status = fleet_service.get_bus_status(bus_id)
                            route_id = status.get("route_id") if isinstance(status, dict) else None
                            if route_id:
                                route = fleet_service.get_route(route_id)
                                for s in (route.get("stops") or []):
                                    if s.get("stop_id") == stop_id:
                                        route_stop = s
                                        break
                        if route_stop:
                            stop_lat = route_stop.get("lat")
                            stop_lon = route_stop.get("lon")

                        # 2) Fallback: use routes_raw
                        if stop_lat is None:
                            stop_coords = self._find_stop_coords(stop_id)
                            if stop_coords:
                                stop_lat = stop_coords.get("lat")
                                stop_lon = stop_coords.get("lon")

                        # 3) Fallback: regex from context
                        if stop_lat is None and stop_id:
                            for d in context:
                                if isinstance(d, str) and stop_id in d:
                                    nums = re.findall(r"[-+]?\d*\.\d+|\d+", d)
                                    if len(nums) >= 2:
                                        stop_lat, stop_lon = float(nums[0]), float(nums[1])
                                        break

                        bus_lat, bus_lon = None, None
                        if last_bus_loc and isinstance(last_bus_loc, dict):
                            bus_lat = last_bus_loc.get("lat")
                            bus_lon = last_bus_loc.get("lon")

                        # 4) Fallback: ask gps_simulator again if needed
                        if (bus_lat is None or bus_lon is None) and bus_id:
                            live = gps_simulator.get_bus_location(bus_id)
                            if live:
                                bus_lat = live.get("lat")
                                bus_lon = live.get("lon")

                        if not (bus_id and bus_lat is not None and bus_lon is not None and stop_lat is not None and stop_lon is not None):
                            result = {"eta_sec": 20 * 60, "stop_id": stop_id, "fallback": True}
                        else:
                            dist_km = self._haversine_km(bus_lat, bus_lon, stop_lat, stop_lon)
                            speed = None
                            if last_bus_loc and isinstance(last_bus_loc, dict):
                                speed = last_bus_loc.get("speed_kmph")
                            try:
                                speed = float(speed) if speed is not None else 25.0
                            except Exception:
                                speed = 25.0

                            if dist_km < 0.1:
                                eta_sec = 2 * 60
                            else:
                                eta_sec = eta_calculator.calculate_eta_seconds(
                                    bus_lat, bus_lon, stop_lat, stop_lon, speed_kmph=speed
                                )

                            weather_delay = 0
                            if last_weather and isinstance(last_weather, dict):
                                weather_delay = (
                                    last_weather.get("expected_delay_sec")
                                    or last_weather.get("delay")
                                    or 0
                                )

                            result = {
                                "eta_sec": int(eta_sec) + int(weather_delay),
                                "distance_km": round(dist_km, 2),
                                "speed_kmph": speed,
                                "stop_id": stop_id,
                                "stop": {"lat": stop_lat, "lon": stop_lon},
                            }

                            # Store in ETA cache
                            if redis_client and cache_key:
                                try:
                                    await redis_client.setex(cache_key, 60, json.dumps(result))
                                    print(f"[DecisionEngine][Redis] ETA cache set: {cache_key}")
                                except Exception:
                                    pass

                    else:
                        result = {"info": "no-op"}

                except Exception as e:
                    if tool_name == "eta":
                        result = {"eta_sec": 20 * 60, "fallback": True}
                    else:
                        result = {"error": str(e)}

                tool_results.append({"step": step, "result": result})

            # Compose final answer with LLM if available
            final_answer = None
            if self.client:
                try:
                    compose_prompt = (
                        "You are a helpful multilingual transport assistant. Produce a short, customer-friendly answer.\n\n"
                        f"User: {user_query}\n\n"
                        f"Context: {json.dumps(context, ensure_ascii=False)}\n\n"
                        f"Tool results: {json.dumps(tool_results, ensure_ascii=False)}\n\n"
                        "Return only the final answer, do NOT include explanation, reasoning, JSON or intermediate data."
                    )
                    resp2 = self.client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": compose_prompt}],
                        temperature=0.2,
                    )
                    final_text = None
                    try:
                        final_text = resp2.choices[0].message.content
                    except Exception:
                        final_text = getattr(resp2.choices[0], "text", None)
                    if final_text:
                        final_answer = final_text.strip()
                except Exception as e:
                    print("Groq compose failed:", e, traceback.format_exc())

            # Fallback textual answer if LLM unavailable
            if not final_answer:
                eta_sec = None
                eta_stop = None
                for tr in tool_results:
                    step = tr.get("step") or {}
                    if step.get("tool") == "eta" and isinstance(tr.get("result"), dict):
                        eta_res = tr["result"]
                        eta_sec = eta_res.get("eta_sec") or eta_res.get("eta")
                        eta_stop = eta_res.get("stop_id")
                        break
                if eta_sec is not None:
                    try:
                        eta_sec = int(eta_sec)
                        hours = eta_sec // 3600
                        minutes = (eta_sec % 3600) // 60
                        if hours > 0:
                            eta_text = f"{hours} hour{'s' if hours != 1 else ''}"
                            if minutes:
                                eta_text += f" {minutes} minute{'s' if minutes != 1 else ''}"
                        elif minutes > 0:
                            eta_text = f"{minutes} minute{'s' if minutes != 1 else ''}"
                        else:
                            eta_text = "a few seconds"
                        final_answer = f"The bus is expected to reach stop {eta_stop or ''} in about {eta_text}."
                    except Exception:
                        final_answer = "No information available."
                else:
                    final_answer = "No information available."

            return {"answer": final_answer, "tool_results": tool_results, "context": context}
        except Exception as e:
            print("DecisionEngine.ask error:", e, traceback.format_exc())
            return {
                "answer": "Sorry, something went wrong when answering your question.",
                "tool_results": [],
                "context": [],
            }

    # ---------------------------
    # Fallback planner & utils
    # ---------------------------
    def _fallback_plan(self, query: str) -> List[Dict[str, Any]]:
        q = query.lower()
        plan: List[Dict[str, Any]] = []
        bus_m = re.search(r"\b[Bb]\d+\b", query)
        bus_id = bus_m.group(0) if bus_m else None

        route_m = re.search(r"\b[Rr]\d+\b", query)
        route_id = route_m.group(0).upper() if route_m else None

        # If user asks about when/arrive/eta/delay -> weather + eta sequence
        if any(k in q for k in ["when", "arrive", "eta", "reach", "late", "delay"]):
            plan.append({"tool": "weather", "params": {}})
            plan.append({"tool": "eta", "params": {"bus_id": bus_id, "stop_id": "S1"}})

        # If user asks about weather explicitly
        if any(k in q for k in ["weather", "rain", "sunny", "haze", "temperature"]):
            if bus_id:
                plan.append({"tool": "gps", "params": {"bus_id": bus_id}})
                plan.append({"tool": "weather", "params": {}})
            elif route_id:
                plan.append({"tool": "weather", "params": {"route_id": route_id}})
            else:
                plan.append({"tool": "weather", "params": {}})

        # Detect a route id like R1, R2, etc. (for route-level weather)
        if "where" in q or "location" in q or "status" in q or bus_m:
            plan.append({"tool": "gps", "params": {"bus_id": bus_id}})

        if not plan:
            plan.append({"tool": "none", "params": {}})

        return plan

    @staticmethod
    def _extract_bus_id(text: str) -> Optional[str]:
        m = re.search(r"\b[Bb]\d+\b", text)
        return m.group(0) if m else None

    def _find_stop_coords(self, stop_id: str) -> Optional[Dict[str, float]]:
        if not stop_id or not self.routes_raw:
            return None
        for route in self.routes_raw.values():
            for stop in route.get("stops", []):
                if stop.get("stop_id") == stop_id:
                    lat = stop.get("lat")
                    lon = stop.get("lon")
                    if lat is not None and lon is not None:
                        return {"lat": float(lat), "lon": float(lon)}
        return None

    def _haversine_km(self, lat1, lon1, lat2, lon2) -> float:
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    # ---------------------------
    # Guardrail helpers
    # ---------------------------
    def _is_transport_query(self, query: str) -> bool:
        """Heuristic intent filter for transport-related questions.

        This is intentionally simple and rule-based so it is cheap and
        predictable. If this returns False we treat the query as out of
        scope for the transport assistant.
        """
        q = query.lower()
        keywords = [
            "bus",
            "buses",
            "route",
            "stop",
            "station",
            "eta",
            "when",
            "arrive",
            "reach",
            "delay",
            "traffic",
            "driver",
            "location",
        ]
        if any(k in q for k in keywords):
            return True

        # Also accept explicit IDs like B2, R1, S3 as transport queries.
        if re.search(r"\b[Bb]\d+\b", query) or re.search(r"\b[Rr]\d+\b", query) or re.search(r"\b[Ss]\d+\b", query):
            return True

        return False

    def _extract_entities(self, text: str) -> Dict[str, list[str]]:
        """Extract bus_ids, route_ids, stop_ids mentioned in free text."""
        buses = {m.group(0).upper() for m in re.finditer(r"\b[Bb]\d+\b", text)}
        routes = {m.group(0).upper() for m in re.finditer(r"\b[Rr]\d+\b", text)}
        stops = {m.group(0).upper() for m in re.finditer(r"\b[Ss]\d+\b", text)}
        return {
            "buses": sorted(buses),
            "routes": sorted(routes),
            "stops": sorted(stops),
        }

    def _validate_referenced_entities(self, query: str) -> Optional[str]:
        """Business-logic guardrail: ensure referenced buses/routes exist.

        If the user asks about a specific bus_id or route_id that we do not
        know about in the in-memory fleet_service, it's safer to say "No
        information available" than to fabricate an answer.
        """
        try:
            entities = self._extract_entities(query)

            # Check buses
            for bus_id in entities["buses"]:
                if bus_id not in getattr(fleet_service, "buses", {}):
                    return f"No information available: I could not find any bus with ID {bus_id} in the current fleet data."

            # Check routes
            for route_id in entities["routes"]:
                if route_id not in getattr(fleet_service, "routes", {}):
                    return f"No information available: I could not find any route with ID {route_id} in the current fleet data."

            return None
        except Exception:
            # Guardrail must never crash the pipeline; on error we simply
            # skip validation and allow normal processing to continue.
            return None
