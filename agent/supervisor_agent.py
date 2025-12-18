# agent/supervisor_agent.py
import asyncio
import logging
from agent.planner_agent import PlannerAgent
from agent.executor_agent import ExecutorAgent
from agent.notification_agent import NotificationAgent
from agent.admin_agent import AdminAgent
from services.fleet_service import fleet_service  # <-- import it here

logger = logging.getLogger(__name__)

class SupervisorAgent:
    """
    Central orchestrator that coordinates Planner, Executor, Notification, and Admin agents.
    It receives a user query or event, routes it to the right agent, and composes results.
    """

    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.notifier = NotificationAgent()
        self.admin = AdminAgent()
        # Reuse DecisionEngine from PlannerAgent if available
        self.engine = getattr(self.planner, "engine", None)

    async def handle_user_query(self, query: str):
        """
        Use PlannerAgent's natural-language answer as base.
        If ETA >= 30 minutes, append one alternate suggestion.
        Do NOT override with generic 'unable to provide ETA' unless there is truly no data.
        """
        try:
            result = await self.planner.handle_query(query)
            if not result:
                return {"error": "Planner returned no result"}
            if "error" in result:
                return result

            tool_results = result.get("tool_results", [])
            if not isinstance(tool_results, list):
                tool_results = []
            executed = tool_results
            if hasattr(self.executor, "ensure_tool_results"):
                executed = await self.executor.ensure_tool_results(tool_results)

            base_answer = result.get("answer")
            friendly_answer = None
            if isinstance(base_answer, str) and base_answer.strip():
                friendly_answer = " ".join(base_answer.split())

            # extract eta and gps
            eta_entry = None
            gps_entry = None
            for tr in tool_results:
                if not isinstance(tr, dict):
                    continue
                step = tr.get("step") or {}
                if not isinstance(step, dict):
                    continue
                tool_name = (step.get("tool") or "").lower()
                res = tr.get("result")
                if tool_name == "eta" and isinstance(res, dict) and ("eta_sec" in res or "eta" in res):
                    eta_entry = tr
                if tool_name == "gps":
                    gps_entry = tr

            # if we have ETA and planner didn't say anything meaningful, prepend explicit ETA
            if eta_entry:
                eta_res = eta_entry.get("result") or {}
                if not isinstance(eta_res, dict):
                    eta_res = {}
                eta_sec = eta_res.get("eta_sec") or eta_res.get("eta")
                params = (eta_entry.get("step") or {}).get("params") or {}
                if not isinstance(params, dict):
                    params = {}
                bus_id = params.get("bus_id") or (
                    gps_entry.get("result", {}).get("bus_id")
                    if gps_entry and isinstance(gps_entry.get("result"), dict)
                    else None
                ) or "the bus"
                stop_id = params.get("stop_id") or eta_res.get("stop_id") or "the stop"
                try:
                    eta_sec_int = int(eta_sec) if eta_sec is not None else None
                except Exception:
                    eta_sec_int = None

                if eta_sec_int is not None:
                    hours = eta_sec_int // 3600
                    minutes = (eta_sec_int % 3600) // 60
                    if hours > 0:
                        eta_text = f"{hours} hour{'s' if hours != 1 else ''}"
                        if minutes:
                            eta_text += f" {minutes} minute{'s' if minutes != 1 else ''}"
                    elif minutes > 0:
                        eta_text = f"{minutes} minute{'s' if minutes != 1 else ''}"
                    else:
                        eta_text = "a few seconds"
                    eta_sentence = f"Bus {bus_id} is expected to reach stop {stop_id} in about {eta_text}."
                    if not friendly_answer or friendly_answer.lower().startswith("sorry"):
                        friendly_answer = eta_sentence
                    else:
                        friendly_answer = f"{eta_sentence} {friendly_answer}"

                    # append alternate if long ETA
                    if eta_sec_int >= 30 * 60:
                        alt_buses = []
                        main_bus_status = fleet_service.get_bus_status(bus_id) if isinstance(bus_id, str) else None
                        main_route_id = main_bus_status.get("route_id") if isinstance(main_bus_status, dict) else None
                        if main_route_id:
                            for other_bus_id, b in getattr(fleet_service, "buses", {}).items():
                                if other_bus_id == bus_id:
                                    continue
                                if isinstance(b, dict) and b.get("route_id") == main_route_id:
                                    alt_buses.append({"bus_id": other_bus_id, "route_id": main_route_id})
                        if alt_buses:
                            best_alt = alt_buses[0]
                            alt_bus_id = best_alt["bus_id"]
                            alt_route_id = best_alt["route_id"]
                            alt_text = (
                                f" As an alternative, you could consider taking bus {alt_bus_id} on route {alt_route_id}, "
                                f"which may reach stop {stop_id} earlier depending on its schedule."
                            )
                        else:
                            alt_text = (
                                f" Since the current ETA is more than 30 minutes, you may also consider a faster mode "
                                f"such as metro/rail or a cab for most of the journey, and then a short auto/taxi ride near stop {stop_id}."
                            )
                        friendly_answer = f"{friendly_answer}{alt_text}"

            if not friendly_answer:
                friendly_answer = "Sorry, I could not answer your question."

            friendly_answer = " ".join(friendly_answer.split())
            self.notifier.log_event("UserQuery", f"Query handled: {query}")
            return {"answer": friendly_answer, "plan": result, "executed": executed}
        except Exception as e:
            print("[SupervisorAgent] handle_user_query error:", e)
            return {"error": str(e)}

    async def run_background_loops(self):
        """
        Run background tasks:
        - Proactive ETA-based notifications for subscribed users.
        - Periodic fleet health checks.

        This method should be launched once on startup, e.g.:
            supervisor = SupervisorAgent()
            asyncio.create_task(supervisor.run_background_loops())
        """
        # If DecisionEngine is not available, background notifications are skipped.
        if not self.engine:
            print("[SupervisorAgent] DecisionEngine not available; background loops disabled.")
            return

        print("[SupervisorAgent] Background loop started")  # <-- add this once

        while True:
            await asyncio.sleep(60)  # run every 60 seconds; adjust as needed
            print("[SupervisorAgent] Background loop tick")  # <-- add this each iteration

            # 1) Proactive subscription processing: ETA-based notifications
            try:
                await self.notifier.process_subscriptions(self.engine, session=None)
            except Exception as e:
                print(f"[SupervisorAgent] process_subscriptions error: {e}")

            # 2) Fleet/admin health checks (optional)
            try:
                if hasattr(self.admin, "check_fleet_health"):
                    self.admin.check_fleet_health()
            except Exception as e:
                print(f"[SupervisorAgent] check_fleet_health error: {e}")
