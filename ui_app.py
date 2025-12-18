import streamlit as st
import requests
import json

# --- Basic theming ---
st.set_page_config(page_title="Smart Transport Assistant", layout="wide")
st.markdown(
    """
    <style>
    body {
        background-color: #f5f7fb;
    }
    .main > div {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.1);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

AUTH_BASE = "http://localhost:8004"
AGENT_BASE = "http://localhost:8001"
FLEET_BASE = "http://localhost:8002"
NOTIF_BASE = "http://localhost:8003"  # notifications microservice (or proxy)


# ---------------- Error helper ----------------

def friendly_error(exc: Exception) -> str:
    """
    Convert backend 'status: {"detail": "..."}' style errors into
    short English messages for end-users.
    """
    msg = str(exc)
    # Try to split "CODE: BODY"
    parts = msg.split(":", 1)
    if len(parts) == 2:
        _, body = parts[0].strip(), parts[1].strip()
        try:
            data = json.loads(body)
            detail = data.get("detail")
            if isinstance(detail, str):
                # Map known details to nicer text
                if "user_id already exists" in detail:
                    return "This User ID is already registered. Please choose a different User ID or log in."
                if "user_id must be" in detail:
                    return detail
                if "phone must be" in detail:
                    return detail
                if "No pending signup" in detail:
                    return "No active signup found. Please start signup again."
                if "No pending login" in detail:
                    return "No active login found. Please start login again."
                if "OTP expired" in detail:
                    return "Your OTP has expired. Please request a new one."
                if "Invalid OTP" in detail:
                    return "The OTP you entered is incorrect. Please try again."
                if "Bus not found" in detail:
                    return "Bus not found. Please check the Bus ID."
                return detail
        except Exception:
            pass
    # Fallback: plain text
    return msg


# ---------------- HTTP helpers ----------------

def api_post(url: str, json: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(url, json=json, headers=headers)
    if resp.status_code >= 400:
        raise Exception(f"{resp.status_code}: {resp.text}")
    return resp.json()


def api_get(url: str, token: str | None = None, params: dict | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code >= 400:
        raise Exception(f"{resp.status_code}: {resp.text}")
    return resp.json()


# ---------------- Session init ----------------

if "page" not in st.session_state:
    st.session_state.page = "landing"

if "auth" not in st.session_state:
    st.session_state.auth = {"session_token": None, "user_id": None, "role": None}


# ---------------- Pages ----------------

def page_landing():
    st.markdown("### Smart Transport Assistant")
    st.write("Easily track buses, get ETA updates, and manage your routes.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign up as new user", use_container_width=True):
            st.session_state.page = "signup"
    with col2:
        if st.button("Log in", use_container_width=True):
            st.session_state.page = "login"


def page_signup():
    st.markdown("### Create account")

    with st.form("signup_form", clear_on_submit=False):
        user_id = st.text_input("User ID (3–12 chars, letters/numbers/_)")
        phone = st.text_input("Mobile (e.g. +919748331232)")
        role = st.selectbox("Role", ["user", "admin", "driver"])
        name = st.text_input("Name (will be stored in DB)")

        email = None
        bus_id = None
        # Email only matters for end-users; for others it is ignored.
        if role == "user":
            email = st.text_input("Email (OTP will also be printed for this)")
        # For drivers, bind this account to a specific bus at signup time.
        if role == "driver":
            bus_id = st.text_input("Bus ID for this driver (will be locked to this account)")

        submitted = st.form_submit_button("Send OTP")

    if submitted:
        try:
            payload = {
                "user_id": user_id.strip(),
                "phone": phone.strip(),
                "role": role,
                "name": name.strip() if name else None,
                "email": email.strip() if email else None,
                "bus_id": bus_id.strip() if bus_id else None,
            }
            _ = api_post(f"{AUTH_BASE}/auth/signup/start", payload)
            st.success("OTP sent. Please check your SMS or console log and enter it on the next screen.")
            st.session_state.signup_user_id = user_id.strip()
            st.session_state.signup_phone = phone.strip()
            if email:
                st.session_state.signup_email = email.strip()
            # Remember role so we can show driver-specific fields on verify
            st.session_state.signup_role = role
            st.session_state.page = "signup_verify"
        except Exception as e:
            st.error(friendly_error(e))


def page_signup_verify():
    st.markdown("### Verify signup OTP")
    user_id = st.session_state.get("signup_user_id")
    phone = st.session_state.get("signup_phone")
    email = st.session_state.get("signup_email")
    role = st.session_state.get("signup_role")

    if not user_id:
        st.warning("No pending signup. Please start again.")
        if st.button("Back to signup"):
            st.session_state.page = "signup"
        return

    st.write(f"User ID: **{user_id}**")
    if phone:
        st.write(f"OTP was sent to mobile: **{phone}**")
    if email:
        st.write(f"Same OTP was also logged for email: **{email}** (see console)")

    with st.form("signup_verify_form"):
        otp = st.text_input("Enter 4-digit OTP", max_chars=4)
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Verify OTP")
        with col2:
            back = st.form_submit_button("Back")

    if submitted:
        try:
            payload = {"user_id": user_id, "otp": otp.strip()}
            resp = api_post(f"{AUTH_BASE}/auth/signup/verify", payload)
            token = resp["session_token"]
            user = resp["user"]
            st.session_state.auth = {
                "session_token": token,
                "user_id": user["user_id"],
                "role": user["role"],
            }
            # Cache driver's bus_id locally so driver UI doesn't need to
            # ask for it again when updating status/location.
            if user.get("role") == "driver" and user.get("bus_id"):
                st.session_state.driver_bus_id = user.get("bus_id")
            st.success("Signup complete. Redirecting to home...")
            st.session_state.page = "home"
        except Exception as e:
            st.error(friendly_error(e))

    if back:
        st.session_state.page = "signup"


def page_login():
    st.markdown("### Log in")

    with st.form("login_form"):
        user_id = st.text_input("User ID")
        submitted = st.form_submit_button("Send OTP")

    if submitted:
        try:
            _ = api_post(f"{AUTH_BASE}/auth/login/start", {"user_id": user_id.strip()})
            st.success("OTP sent. Please check your SMS or console and enter it on the next screen.")
            st.session_state.login_user_id = user_id.strip()
            st.session_state.page = "login_verify"
        except Exception as e:
            st.error(friendly_error(e))


def page_login_verify():
    st.markdown("### Verify login OTP")
    user_id = st.session_state.get("login_user_id")

    if not user_id:
        st.warning("No pending login. Please start again.")
        if st.button("Back to login"):
            st.session_state.page = "login"
        return

    st.write(f"User ID: **{user_id}**")

    with st.form("login_verify_form"):
        otp = st.text_input("Enter 4-digit OTP", max_chars=4)
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Verify OTP")
        with col2:
            back = st.form_submit_button("Back")

    if submitted:
        try:
            resp = api_post(f"{AUTH_BASE}/auth/login/verify", {"user_id": user_id, "otp": otp.strip()})
            token = resp["session_token"]
            user = resp["user"]
            st.session_state.auth = {
                "session_token": token,
                "user_id": user["user_id"],
                "role": user["role"],
            }
            # When a driver logs in again, restore bound bus_id from user info
            if user.get("role") == "driver" and user.get("bus_id"):
                st.session_state.driver_bus_id = user.get("bus_id")
            st.success("Login successful. Redirecting to home...")
            st.session_state.page = "home"
        except Exception as e:
            st.error(friendly_error(e))

    if back:
        st.session_state.page = "login"


def section_user(user_id: str, token: str):
    st.subheader("User: Bus notifications")

    # --- Subscribe form ---
    with st.form("subscribe_form"):
        bus_id = st.text_input("Bus ID (e.g. B1)")
        stop_id = st.text_input("Stop ID (e.g. S1)")
        notify_before = st.number_input("Notify before (seconds)", min_value=60, max_value=3600, value=300, step=60)
        submitted = st.form_submit_button("Subscribe for SMS alerts")
    if submitted:
        try:
            payload = {
                "user_id": user_id,
                "bus_id": bus_id.strip(),
                "stop_id": stop_id.strip(),
                "notify_before_sec": int(notify_before),
                "channel": "sms",
            }
            # Send subscription to Agent service (in-memory notifications + DB sync)
            resp = api_post(f"{AGENT_BASE}/subscribe", payload)
            # Try to extract a message from response
            data = resp.get("data") or resp
            msg = data.get("message") or "You have been subscribed successfully. You will receive SMS alerts."
            st.success(msg)
        except Exception as e:
            st.error(friendly_error(e))

    st.markdown("### Unsubscribe from notifications")

    # --- Unsubscribe form ---
    with st.form("unsubscribe_form"):
        ubus_id = st.text_input("Bus ID to unsubscribe", key="unsub_bus")
        ustop_id = st.text_input("Stop ID to unsubscribe", key="unsub_stop")
        unsub = st.form_submit_button("Unsubscribe")
    if unsub:
        try:
            params = {
                "user_id": user_id,
                "bus_id": ubus_id.strip(),
                "stop_id": ustop_id.strip(),
            }
            # Use Agent service unsubscribe endpoint (keeps background loops happy)
            resp = requests.post(f"{AGENT_BASE}/unsubscribe", params=params)
            if resp.status_code >= 400:
                raise Exception(f"{resp.status_code}: {resp.text}")
            data = resp.json()
            data_obj = data.get("data") or data
            msg = data_obj.get("message", "You have been unsubscribed successfully.")
            st.success(msg)
        except Exception as e:
            st.error(friendly_error(e))

    st.markdown("#### Recent notifications")
    try:
        notif = api_get(f"{NOTIF_BASE}/notifications/recent")
        data = notif.get("data") or notif.get("notifications") or []
        # Show newest first
        for n in reversed(data):
            st.write(f"- [{n.get('channel')}] {n.get('user_id')}: {n.get('message')}")
    except Exception as e:
        st.info(f"Could not load notifications: {e}")


def section_driver(user_id: str, token: str):
    st.subheader("Driver: Update bus status / location")

    driver_bus_id = st.session_state.get("driver_bus_id")
    if not driver_bus_id:
        st.warning("No bus is linked to this driver account. Please complete driver signup again or contact admin.")
        return

    st.info(f"This driver is assigned to bus ID: **{driver_bus_id}**")

    st.markdown("**Update Location**")
    with st.form("driver_location_form"):
        lat = st.number_input("Latitude", value=22.5705)
        lon = st.number_input("Longitude", value=88.3605)
        submitted = st.form_submit_button("Update Location")
    if submitted:
        try:
            payload = {"bus_id": driver_bus_id, "lat": float(lat), "lon": float(lon)}
            api_post(f"{FLEET_BASE}/driver/location", payload)  # <-- changed path
            st.success("Location updated.")
        except Exception as e:
            st.error(friendly_error(e))

    st.markdown("**Update Status**")
    with st.form("driver_status_form"):
        status = st.text_input("Status (e.g. delayed, breakdown, running late)")
        msg = st.text_input("Status message (optional)", "")
        speed = st.number_input("Speed (km/h)", min_value=0.0, max_value=200.0, value=30.0, step=1.0)
        submitted2 = st.form_submit_button("Update Status")
    if submitted2:
        try:
            payload = {
                "bus_id": driver_bus_id,
                "status": status.strip(),
                "message": msg.strip(),
                "speed_kmph": float(speed),
            }
            api_post(f"{FLEET_BASE}/driver/status", payload)     # <-- changed path
            st.success("Status updated.")
        except Exception as e:
            st.error(friendly_error(e))


def section_admin(user_id: str, token: str):
    st.subheader("Admin: Fleet overview")

    try:
        # Backend returns ok([...]) so overview["data"] is the list
        # Use /admin/fleet/overview to match routes_admin.py mounting
        overview = api_get(f"{FLEET_BASE}/admin/fleet/overview")
        data = overview.get("data") or overview
        if isinstance(data, list) and data:
            st.write("Below is the current status of all buses:")
            # Hide nested 'route' column from table to keep it readable
            simplified = []
            for b in data:
                if not isinstance(b, dict):
                    continue
                simplified.append({
                    "Bus ID": b.get("bus_id"),
                    "Route ID": b.get("route_id"),
                    "Latitude": b.get("lat"),
                    "Longitude": b.get("lon"),
                    "Status": b.get("status", "unknown"),
                    "Status message": b.get("status_message", ""),
                })
            st.table(simplified)
        else:
            st.info("No buses found in the fleet overview.")
    except Exception as e:
        # Show friendly message instead of raw JSON
        st.error(friendly_error(e))

    st.markdown("**Update route definition**")
    with st.form("route_update_form"):
        route_id = st.text_input("Route ID (e.g. R1)")
        stops_json = st.text_area(
            "Stops JSON (list of {stop_id, name, lat, lon})",
            '[{"stop_id":"S1","name":"Stop 1","lat":22.5705,"lon":88.3605}]',
            height=120,
        )
        submitted = st.form_submit_button("Update Route")
    if submitted:
        import json as _json
        try:
            stops = _json.loads(stops_json)
            payload = {"route_id": route_id.strip(), "stops": stops}
            # Call admin route-update endpoint
            resp = api_post(f"{FLEET_BASE}/admin/route/update", payload)
            data = resp.get("data") or resp
            # Only show the human‑friendly message, no JSON s
            # tructure
            msg = data.get("message") or f"Route {route_id} updated successfully."
            st.success(msg)
        except Exception as e:
            # Friendly error, still no JSON
            st.error(friendly_error(e))


def page_home():
    # Top bar: logout and back buttons
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown("### Transport Assistant Home")
    with col2:
        if st.button("Back"):
            st.session_state.page = "landing"
            st.session_state.auth = {"session_token": None, "user_id": None, "role": None}
            return
    with col3:
        if st.button("Log out"):
            st.session_state.auth = {"session_token": None, "user_id": None, "role": None}
            st.session_state.page = "landing"
            return

    auth = st.session_state.auth
    token = auth.get("session_token")
    user_id = auth.get("user_id")
    role = auth.get("role")

    if not token:
        st.warning("You are not logged in.")
        if st.button("Go to login"):
            st.session_state.page = "login"
        return

    # Verify session
    try:
        me = api_get(f"{AUTH_BASE}/auth/me", token=token)
        st.sidebar.write(f"Logged in as: **{me['user']['user_id']}** ({me['user']['role']})")
    except Exception as e:
        st.error(f"Session error: {e}")
        if st.button("Go to login"):
            st.session_state.page = "login"
        return

    # ASK box
    st.markdown("#### Ask the assistant")
    with st.form("ask_form"):
        query = st.text_input("Your question")
        ask_submit = st.form_submit_button("Ask")
    if ask_submit and query.strip():
        try:
            resp = api_post(f"{AGENT_BASE}/ask", {"query": query.strip()})
            st.write("**Answer:**")
            st.success(resp.get("answer"))
        except Exception as e:
            st.error(str(e))

    st.markdown("---")

    if role == "user":
        section_user(user_id, token)
    elif role == "driver":
        section_driver(user_id, token)
    elif role == "admin":
        section_admin(user_id, token)


# ---------------- Router ----------------

page = st.session_state.page

if page == "landing":
    page_landing()
elif page == "signup":
    page_signup()
elif page == "signup_verify":
    page_signup_verify()
elif page == "login":
    page_login()
elif page == "login_verify":
    page_login_verify()
elif page == "home":
    page_home()