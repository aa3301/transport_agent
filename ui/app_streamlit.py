"""
Streamlit UI for Transport Agent — Updated for gRPC/microservices gateway.

Communicates with API Gateway (http://localhost:8000) which routes to microservices.
Includes JWT token generation and authentication.
"""
import streamlit as st
import requests
import jwt
import json
from datetime import datetime, timedelta

# Configuration
API_GATEWAY_URL = st.text_input("API Gateway URL", "http://127.0.0.1:8000", key="gateway_url")
JWT_SECRET = st.text_input("JWT Secret (for testing)", "change_me_to_secure_value", type="password", key="jwt_secret")

# Page title
st.title("🚌 Transport Agent — Multi-Agent System")

# Sidebar: generate test JWT token
st.sidebar.header("🔐 Authentication")
st.sidebar.markdown("**Generate a test JWT token for testing:**")
test_user_id = st.sidebar.text_input("User ID", "u1", key="user_id")
test_role = st.sidebar.selectbox("Role", ["user", "driver", "admin"], key="role")

if st.sidebar.button("Generate JWT Token"):
    payload = {
        "sub": test_user_id,
        "role": test_role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    # auto-fill token input so requests use it
    st.session_state["token_input"] = token
    st.sidebar.success(f"Token generated!")
    st.sidebar.code(token, language="text") # Show token clearly for copying
    st.sidebar.info("Token auto-filled in the field below.")

# Helper to make auth headers
def get_auth_headers(token: str = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

# Get token from session or input
token = st.sidebar.text_input("Bearer Token (paste here)", key="token_input", type="password")

# ==================== USER QUERIES ====================
st.header("📋 Ask the Agent (NLP)")
st.markdown("Ask a natural-language question about bus arrival, status, etc.")
query = st.text_input("Natural language question", "When will B1 reach S1?")

if st.button("🔍 Ask"):
    if not query.strip():
        st.warning("Type a question first")
    else:
        with st.spinner("Contacting Agent Service via Gateway..."):
            try:
                resp = requests.post(
                    f"{API_GATEWAY_URL}/ask",
                    json={"query": query},
                    headers=get_auth_headers(token),
                    timeout=30
                )
                resp.raise_for_status()
                result = resp.json()
                
                if result.get("ok"):
                    st.success("✅ Query processed!")
                    st.markdown(f"**Answer:** {result.get('data', 'No answer')}")
                else:
                    st.error(f"Error: {result.get('error', {}).get('message', 'Unknown error')}")
            except requests.exceptions.RequestException as e:
                st.error(f"API Error: {str(e)}")
            except Exception as e:
                st.error(f"Error: {str(e)}")

# ==================== DRIVER OPERATIONS ====================
st.header("🚗 Driver Operations")

col1, col2 = st.columns(2)

# Update Location
with col1:
    st.subheader("📍 Update Location")
    with st.form("driver_location_form"):
        driver_bus_id = st.text_input("Bus ID", "B1", key="driver_bus_id")
        driver_lat = st.number_input("Latitude", value=22.5726, key="driver_lat")
        driver_lon = st.number_input("Longitude", value=88.3639, key="driver_lon")
        driver_speed = st.number_input("Speed (km/h)", value=20.0, key="driver_speed")
        
        if st.form_submit_button("📤 Send Location"):
            payload = {
                "bus_id": driver_bus_id,
                "lat": driver_lat,
                "lon": driver_lon,
                "speed_kmph": driver_speed
            }
            with st.spinner("Updating location..."):
                try:
                    resp = requests.post(
                        f"{API_GATEWAY_URL}/driver/location",
                        json=payload,
                        headers=get_auth_headers(token),
                        timeout=10
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("ok"):
                        st.success("✅ Location updated!")
                    else:
                        st.error(f"Error: {result.get('error')}")
                except Exception as e:
                    st.error(f"API Error: {str(e)}")

# Update Status
with col2:
    st.subheader("⚠️ Update Status")
    with st.form("driver_status_form"):
        status_bus_id = st.text_input("Bus ID", "B1", key="status_bus_id")
        status_value = st.selectbox("Status", ["on_time", "delayed", "breakdown", "maintenance"], key="status_value")
        status_message = st.text_input("Message (optional)", "Traffic jam", key="status_message")
        
        if st.form_submit_button("📤 Send Status"):
            payload = {
                "bus_id": status_bus_id,
                "status": status_value,
                "message": status_message
            }
            with st.spinner("Updating status..."):
                try:
                    resp = requests.post(
                        f"{API_GATEWAY_URL}/driver/status",
                        json=payload,
                        headers=get_auth_headers(token),
                        timeout=10
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("ok"):
                        st.success("✅ Status updated!")
                    else:
                        st.error(f"Error: {result.get('error')}")
                except Exception as e:
                    st.error(f"API Error: {str(e)}")

# ==================== USER SUBSCRIPTIONS ====================
st.header("🔔 Subscriptions")

col1, col2 = st.columns(2)

# Subscribe
with col1:
    st.subheader("➕ Subscribe to Bus")
    with st.form("subscribe_form"):
        sub_user_id = st.text_input("User ID", "u1", key="sub_user_id")
        sub_bus_id = st.text_input("Bus ID", "B1", key="sub_bus_id")
        sub_stop_id = st.text_input("Stop ID", "S1", key="sub_stop_id")
        sub_notify_sec = st.number_input("Notify before (sec)", value=300, key="sub_notify_sec")
        sub_channel = st.selectbox("Channel", ["console", "email", "sms", "webhook"], key="sub_channel")
        
        if st.form_submit_button("➕ Subscribe"):
            payload = {
                "user_id": sub_user_id,
                "bus_id": sub_bus_id,
                "stop_id": sub_stop_id,
                "notify_before_sec": int(sub_notify_sec),
                "channel": sub_channel
            }
            with st.spinner("Subscribing..."):
                try:
                    resp = requests.post(
                        f"{API_GATEWAY_URL}/subscribe",
                        json=payload,
                        headers=get_auth_headers(token),
                        timeout=10
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("ok"):
                        st.success("✅ Subscribed!")
                    else:
                        st.error(f"Error: {result.get('error')}")
                except Exception as e:
                    st.error(f"API Error: {str(e)}")

# Unsubscribe
with col2:
    st.subheader("➖ Unsubscribe")
    with st.form("unsubscribe_form"):
        unsub_user_id = st.text_input("User ID", "u1", key="unsub_user_id")
        unsub_bus_id = st.text_input("Bus ID", "B1", key="unsub_bus_id")
        unsub_stop_id = st.text_input("Stop ID", "S1", key="unsub_stop_id")
        
        if st.form_submit_button("➖ Unsubscribe"):
            with st.spinner("Unsubscribing..."):
                try:
                    resp = requests.delete(
                        f"{API_GATEWAY_URL}/unsubscribe",
                        params={
                            "user_id": unsub_user_id,
                            "bus_id": unsub_bus_id,
                            "stop_id": unsub_stop_id
                        },
                        headers=get_auth_headers(token),
                        timeout=10
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("ok"):
                        st.success("✅ Unsubscribed!")
                    else:
                        st.error(f"Error: {result.get('error')}")
                except Exception as e:
                    st.error(f"API Error: {str(e)}")

# ==================== ADMIN PANEL ====================
st.header("👨‍💼 Admin Panel")

if st.checkbox("Show Admin Functions (require admin role)"):
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Fleet Overview")
        if st.button("📈 Refresh Fleet"):
            with st.spinner("Fetching fleet..."):
                try:
                    resp = requests.get(
                        f"{API_GATEWAY_URL}/admin/fleet/overview",
                        headers=get_auth_headers(token),
                        timeout=10
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("ok"):
                        buses = result.get("data", [])
                        st.json(buses)
                    else:
                        st.error(f"Error: {result.get('error')}")
                except Exception as e:
                    st.error(f"API Error: {str(e)}")
    
    with col2:
        st.subheader("🛣️ Update Route")
        with st.form("update_route_form"):
            route_id = st.text_input("Route ID", "R1", key="route_id")
            stops_json = st.text_area("Stops (JSON array)", '[{"id":"S1","name":"Office","lat":22.57,"lon":88.37}]', key="stops_json")
            
            if st.form_submit_button("🔄 Update Route"):
                try:
                    stops = json.loads(stops_json)
                    payload = {"route_id": route_id, "stops": stops}
                    with st.spinner("Updating route..."):
                        try:
                            resp = requests.post(
                                f"{API_GATEWAY_URL}/admin/route/update",
                                json=payload,
                                headers=get_auth_headers(token),
                                timeout=10
                            )
                            resp.raise_for_status()
                            result = resp.json()
                            if result.get("ok"):
                                st.success(f"✅ Route {route_id} updated!")
                            else:
                                st.error(f"Error: {result.get('error')}")
                        except Exception as e:
                            st.error(f"API Error: {str(e)}")
                except json.JSONDecodeError:
                    st.error("Invalid JSON for stops")

# ==================== HEALTH CHECK ====================
st.sidebar.divider()
st.sidebar.header("🏥 Health Check")

if st.sidebar.button("Check Gateway Health"):
    try:
        resp = requests.get(f"{API_GATEWAY_URL}/health", timeout=5)
        if resp.status_code == 200:
            st.sidebar.success("✅ Gateway is healthy!")
            st.sidebar.json(resp.json())
        else:
            st.sidebar.warning(f"⚠️ Gateway returned {resp.status_code}")
    except Exception as e:
        st.sidebar.error(f"❌ Gateway unreachable: {str(e)}")

# Footer
st.markdown("---")
st.caption("Transport Agent v0.2 — Multi-Agent Microservices with gRPC + HTTP Gateway")
st.caption("For production, replace JWT secret, configure real auth provider, and enable TLS/HTTPS.")
