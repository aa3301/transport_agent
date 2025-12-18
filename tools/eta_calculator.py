# tools/eta_calculator.py
import math

def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*(math.sin(dlambda/2.0)**2)
    return 2 * R * math.asin(math.sqrt(a))

def calculate_eta_seconds(lat1, lon1, lat2, lon2, speed_kmph: float = 20.0, traffic_multiplier: float = 1.0):
    try:
        dist_m = haversine_meters(lat1, lon1, lat2, lon2)
        speed_m_s = max(speed_kmph * 1000.0 / 3600.0, 0.1)
        base_seconds = dist_m / speed_m_s
        return int(base_seconds * traffic_multiplier)
    except Exception:
        return 9999
