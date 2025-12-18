# agent/planner_agent.py
import asyncio
import traceback
import json
from agent.decision_engine import DecisionEngine

# Redis helpers for /ask cache
try:
    from infra.redis_client import redis_get, redis_setex
except Exception:
    redis_get = None
    redis_setex = None

class PlannerAgent:
    """
    Wrapper around DecisionEngine.

    - handle_query(query): returns a dict that MUST contain:
        {
            "answer": "<natural language>",
            "tool_results": [...],  # internal diagnostics
            "context": [...]
        }
      The HTTP layer (8001/8000) will only expose 'answer' to customers.
    """

    def __init__(self):
        try:
            self.engine = DecisionEngine()
        except Exception as e:
            print("[PlannerAgent] DecisionEngine init failed:", e)
            self.engine = None

    async def handle_query(self, query: str):
        """Main entry point for agentic AI planning & execution."""
        if not self.engine:
            return {"error": "DecisionEngine not available"}

        normalized_q = " ".join(query.strip().lower().split())
        cache_key = f"ask:{normalized_q}"

        # 1) Try Redis cache (if available)
        if redis_get is not None:
            try:
                cached = await redis_get(cache_key)
                if cached:
                    print(f"[PlannerAgent][Redis] cache HIT for key={cache_key}")
                    try:
                        cached_obj = json.loads(cached)
                        if isinstance(cached_obj, dict) and cached_obj.get("answer"):
                            return cached_obj
                    except Exception:
                        pass
                else:
                    print(f"[PlannerAgent][Redis] cache MISS for key={cache_key}")
            except Exception as e:
                print(f"[PlannerAgent][Redis] error reading cache for {cache_key}: {e}")

        # 2) Compute fresh answer via DecisionEngine
        try:
            result = await self.engine.ask(query)
            if not isinstance(result, dict):
                result = {"error": "Invalid engine result"}

            # Sanitize tool errors so they don't crash or leak low-level details.
            tool_results = result.get("tool_results", [])
            if not isinstance(tool_results, list):
                tool_results = []

            sanitized_results = []
            for tr in tool_results:
                tr_copy = dict(tr)
                tr_result = tr_copy.get("result", tr_copy.get("output", {}))

                # Common shape: {"error": ..., "result": {...}} -> unwrap or summarize error
                if isinstance(tr_result, dict) and "error" in tr_result and "result" in tr_result:
                    raw_err = tr_result.get("error")
                    inner_res = tr_result.get("result")
                    if raw_err:
                        # summarize error
                        step_tool = tr.get("step", {}).get("tool")
                        summary = f"Tool '{step_tool}' failed."
                        tr_copy["result"] = {"error": summary}
                    else:
                        tr_copy["result"] = inner_res
                # Older shape: {"error": "..."} only
                elif isinstance(tr_result, dict) and tr_result.get("error"):
                    step_tool = tr.get("step", {}).get("tool")
                    summary = f"Tool '{step_tool}' failed."
                    tr_copy["result"] = {"error": summary}
                sanitized_results.append(tr_copy)

            # Ensure 'answer' exists and is clean
            answer = result.get("answer")
            if isinstance(answer, str):
                answer = " ".join(answer.split())  # normalize whitespace
            if not answer:
                # Provide a generic message if DecisionEngine didn't produce one
                answer = "Sorry, I could not find an answer to your question."

            # Attach sanitized tool_results back for internal/debug usage (not exposed at HTTP level)
            result["tool_results"] = sanitized_results
            result["answer"] = answer

            # 3) Store in Redis with 60 sec TTL
            if redis_setex is not None and isinstance(result, dict) and result.get("answer"):
                try:
                    await redis_setex(cache_key, 60, json.dumps(result))
                    print(f"[PlannerAgent][Redis] cached answer for key={cache_key}")
                except Exception as e:
                    print(f"[PlannerAgent][Redis] error caching key={cache_key}: {e}")

            return result
        except Exception as e:
            traceback.print_exc()
            return {"error": str(e)}

# if someone imports PlannerAgent class, they can instantiate; actual singleton is in agents_singleton.py
