# agent/executor_agent.py
import traceback
from tools import gps_simulator, eta_calculator, weather  # reuse your Phase-1 tools

class ExecutorAgent:
    """
    Executor that verifies and (re-)executes tool steps from Planner results.
    Note: For production, heavy repeat calls (gps/eta/weather) should consult Redis cache
    and use idempotent tool wrappers to avoid rate limits / cost.
    """

    def __init__(self):
        pass

    async def ensure_tool_results(self, tool_results):
        """
        tool_results: list of {"step": {...}, "result": {...}|None}
        Return: same structure with missing results filled where possible.
        """
        final = []
        for tr in tool_results:
            step = tr.get("step", {})
            result = tr.get("result")
            try:
                tool = step.get("tool")
                params = step.get("params") or {}
                if result is None:
                    # try to call tool directly
                    if tool == "gps":
                        bus_id = params.get("bus_id")
                        if bus_id:
                            result = gps_simulator.get_bus_location(bus_id)
                    elif tool == "eta":
                        bus_id = params.get("bus_id")
                        stop_id = params.get("stop_id")
                        if bus_id and stop_id:
                            # best-effort: call gps then eta (we don't have DB of stops here)
                            bus = gps_simulator.get_bus_location(bus_id)
                            if bus:
                                # fallback: mock stop coords or use bus coords + delta
                                stop_lat = bus["lat"] + 0.005
                                stop_lon = bus["lon"] + 0.005
                                eta = eta_calculator.calculate_eta_seconds(bus["lat"], bus["lon"], stop_lat, stop_lon, speed_kmph=bus.get("speed_kmph",20))
                                result = {"eta_sec": int(eta), "stop": {"lat": stop_lat, "lon": stop_lon}}
                    elif tool == "weather":
                        lat = params.get("lat")
                        lon = params.get("lon")
                        if lat is None or lon is None:
                            # try to take last-known GPS in preceding steps
                            # simple approach: find last gps result in tool_results (not yet processed)
                            for prev in final[::-1]:
                                if prev.get("step",{}).get("tool") == "gps" and prev.get("result"):
                                    b = prev["result"]
                                    lat, lon = b.get("lat"), b.get("lon")
                                    break
                        if lat is not None and lon is not None:
                            # weather.get_weather_by_coords preferred if available; else generic get_weather
                            if hasattr(weather, "get_weather_by_coords"):
                                result = weather.get_weather_by_coords(lat, lon)
                            else:
                                try:
                                    result = weather.get_weather(lat, lon)
                                except Exception:
                                    result = {"condition":"unknown"}
                    else:
                        result = {"info":"no-op"}
            except Exception as e:
                traceback.print_exc()
                result = {"error": str(e)}
            final.append({"step": step, "result": result})
        return final
