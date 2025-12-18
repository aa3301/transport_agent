import re
import secrets
import time
import json
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db_session
from config.settings import settings
from models.db_models import User as DBUser, Driver as DBDriver

app = FastAPI(title="Auth Microservice", version="0.1")

# ---------------- In-memory stores (for dev without Redis) ---------------- #

# user_id -> {user_id, phone, role}
USERS: dict[str, dict] = {}

# user_id -> {user_id, phone, role, otp, ts}
PENDING_SIGNUPS: dict[str, dict] = {}

# user_id -> {user_id, otp, ts}
PENDING_LOGINS: dict[str, dict] = {}

# session_token -> {user_id, role, ts}
SESSIONS: dict[str, dict] = {}

# phone -> set of user_ids (allows same phone for multiple user_ids)
PHONE_TO_USERS: dict[str, set[str]] = {}

# ---------------- Redis helpers ----------------
try:
    # import only the helper functions; they use your existing redis_client internally
    from infra.redis_client import redis_get, redis_setex
except Exception:
    redis_get = None
    redis_setex = None

# ---------------- Models ---------------- #

class SignupStartRequest(BaseModel):
    """Signup payload used by the UI.

    New fields:
    - name: stored in DB users/drivers table
    - email: required only for role="user" (OTP goes to console)
    - bus_id: required only for role="driver" (links driver to a bus)
    """
    # allow 3–12 chars; actual pattern enforced by validate_user_id
    user_id: str = Field(..., min_length=3, max_length=12)
    phone: str
    role: str
    name: Optional[str] = None
    email: Optional[str] = None
    bus_id: Optional[str] = None

class OtpVerifyRequest(BaseModel):
    user_id: str
    otp: str
    # bus_id is no longer required here; for drivers we take the
    # bus_id that was provided during signup_start and stored in
    # PENDING_SIGNUPS.
    bus_id: Optional[str] = None

class LoginStartRequest(BaseModel):
    user_id: str

class LoginVerifyRequest(BaseModel):
    user_id: str
    otp: str

# ---------------- Utils ---------------- #

def validate_user_id(user_id: str) -> None:
    """
    Allow 3–12 characters: letters, digits, underscore.
    Example valid: ABC123, driver_1, adm01
    """
    if not re.fullmatch(r"[A-Za-z0-9_]{3,12}", user_id):
        raise HTTPException(
            status_code=400,
            detail="user_id must be 3-12 characters (letters, numbers, underscore)",
        )

def validate_phone(phone: str) -> None:
    # 12 digits with optional leading + (e.g. +919748331232 or 919748331232)
    if not re.fullmatch(r"\+?\d{12}", phone):
        raise HTTPException(
            status_code=400,
            detail="phone must be country code + 10 digits (e.g. +919876543210)",
        )


def normalize_phone(phone: str) -> str:
    """Normalize phone numbers so +9197... and 9197... are treated the same.

    We strip a leading '+' but otherwise keep the digits as-is. Call this
    *after* validate_phone.
    """
    return phone.lstrip("+")

def validate_role(role: str) -> None:
    if role not in ("admin", "user", "driver"):
        raise HTTPException(status_code=400, detail="role must be one of admin/user/driver")


def validate_email_for_user(role: str, email: Optional[str]) -> None:
    """Basic email validation only when role == "user".

    For admin/driver, email stays optional and is ignored by OTP logic.
    """
    if role != "user":
        return
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email is required for users and must be valid")

def generate_otp() -> str:
    return f"{secrets.randbelow(10000):04d}"

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)

OTP_TTL_SECONDS = 5 * 60       # 5 minutes
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days

def is_expired(ts: int, ttl: int) -> bool:
    return (time.time() - ts) > ttl

# ---------------- Signup ---------------- #

@app.post("/auth/signup/start")
async def signup_start(req: SignupStartRequest):
    """
    Start signup: validate, store pending signup in-memory, send OTP via SMS.

    - user_id must be unique; phone can repeat for many user_ids.
    """
    print(f"[auth_service] /auth/signup/start called with user_id={req.user_id}, phone={req.phone}, role={req.role}")

    # Import notifier inside function and guard errors so startup never breaks
    try:
        from tools import notifier
    except Exception as e:
        print(f"[auth_service] ERROR importing notifier: {e}")
        notifier = None

    validate_user_id(req.user_id)
    validate_phone(req.phone)
    # Normalize phone so +9197... and 9197... are treated identical
    req.phone = normalize_phone(req.phone)
    validate_role(req.role)
    # Only enforce email for end-users; admins/drivers may skip it.
    validate_email_for_user(req.role, req.email)

    # For drivers, bus_id must be provided at signup time so that this
    # driver account is locked to a specific bus.
    if req.role == "driver":
        if not (req.bus_id and req.bus_id.strip()):
            raise HTTPException(status_code=400, detail="bus_id is required for driver signup")

    # Only block if the *same* user_id is already registered in-memory.
    # We also check the DB users table below so that existing users can
    # still log in even after the service is restarted.
    if req.user_id in USERS:
        raise HTTPException(status_code=409, detail="user_id already exists")

    # Enforce uniqueness of phone and (for users) email across:
    # - confirmed users (USERS)
    # - pending signups (PENDING_SIGNUPS)
    # so that the same mobile/email cannot be used to start or
    # verify multiple different accounts.

    # 1) Check against already-verified users
    for u in USERS.values():
        if u.get("phone") == req.phone:
            raise HTTPException(status_code=409, detail="phone already registered with another user_id")
        if req.email and u.get("email") == req.email:
            raise HTTPException(status_code=409, detail="email already registered with another user_id")

    # 2) Check against pending signups (allow same user_id to retry)
    for pending in PENDING_SIGNUPS.values():
        if pending.get("user_id") == req.user_id:
            continue
        if pending.get("phone") == req.phone:
            raise HTTPException(status_code=409, detail="phone already used in another pending signup")
        if req.email and pending.get("email") == req.email:
            raise HTTPException(status_code=409, detail="email already used in another pending signup")

    # Also check DB users table when enabled so that existing users in
    # MySQL cannot sign up again with the same user_id/phone/email after
    # a service restart.
    if settings.USE_DB:
        try:
            async for session in get_db_session():
                if session is None:
                    break
                # 2a) user_id uniqueness in DB
                stmt_uid = select(DBUser).where(DBUser.user_id == req.user_id)
                result_uid = await session.execute(stmt_uid)
                existing_uid = result_uid.scalar_one_or_none()
                if existing_uid:
                    raise HTTPException(status_code=409, detail="user_id already exists")
                # Check both normalized and '+normalized' forms to catch
                # older rows that might still include '+' in DB.
                norm_phone = req.phone
                alt_phone = "+" + norm_phone
                stmt = select(DBUser).where(
                    or_(
                        DBUser.phone.in_([norm_phone, alt_phone]),
                        DBUser.email == (req.email or ""),
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                if existing:
                    raise HTTPException(status_code=409, detail="phone or email already registered")
                break
        except HTTPException:
            raise
        except Exception as e:
            print(f"[auth_service][DB] uniqueness check failed (ignored): {e}")

    otp = generate_otp()
    print(f"[auth_service] Generated OTP {otp} for user_id={req.user_id}")

    # Keep in-memory behavior
    PENDING_SIGNUPS[req.user_id] = {
        "user_id": req.user_id,
        "phone": req.phone,
        "role": req.role,
        "name": (req.name or "").strip(),
        "email": (req.email or "").strip() if req.email else None,
        # bus_id will be provided at OTP verification time for drivers
        "bus_id": (req.bus_id or "").strip() if req.bus_id else None,
        "otp": otp,
        "ts": int(time.time()),
    }

    # Write pending signup to Redis (optional)
    if redis_setex is not None:
        try:
            key = f"auth:signup:{req.user_id}"
            value = json.dumps(PENDING_SIGNUPS[req.user_id])
            await redis_setex(key, OTP_TTL_SECONDS, value)
            print(f"[auth_service][Redis] stored signup OTP for {req.user_id} in {key}")
        except Exception as e:
            print(f"[auth_service][Redis] signup_start setex failed: {e}")

    # Always log OTPs to console for local testing
    print(f"[auth_service] Signup OTP for {req.user_id} (phone={req.phone}): {otp}")
    if req.email:
        print(f"[auth_service] Signup email OTP for {req.user_id} ({req.email}): {otp}")

    # Send OTP to provided phone (or console if notifier/Twilio fails)
    if notifier:
        try:
            notifier.send_notification(
                req.user_id,
                f"Your signup OTP is {otp}",
                channel="sms",
                phone=req.phone,
            )
        except Exception as e:
            print(f"[auth_service] notifier.send_notification failed: {e}")
            print(f"[auth_service][FALLBACK] Signup OTP for {req.user_id} ({req.phone}): {otp}")
    else:
        print(f"[auth_service][FALLBACK] Signup OTP for {req.user_id} ({req.phone}): {otp}")

    # Additionally, if an email is provided (role=user), also send via
    # notifier's email channel when available.
    if notifier and req.email:
        try:
            notifier.send_notification(
                req.user_id,
                f"Your signup OTP (email) is {otp}",
                channel="email",
                phone=None,
            )
        except Exception as e:
            print(f"[auth_service] notifier.send_notification (email) failed: {e}")
            print(f"[auth_service][FALLBACK] Signup email OTP for {req.user_id} ({req.email}): {otp}")
    elif req.email:
        print(f"[auth_service][FALLBACK] Signup email OTP for {req.user_id} ({req.email}): {otp}")

    return {"message": "OTP sent for signup"}

@app.post("/auth/signup/verify")
async def signup_verify(req: OtpVerifyRequest):
    """
    Verify signup OTP, create user in memory, create session.
    """
    pending = None

    # Try Redis first
    if redis_get is not None:
        try:
            key = f"auth:signup:{req.user_id}"
            raw = await redis_get(key)
            if raw:
                print(f"[auth_service][Redis] loaded signup OTP for {req.user_id} from {key}")
                try:
                    pending = json.loads(raw)
                except Exception:
                    pending = None
        except Exception as e:
            print(f"[auth_service][Redis] signup_verify get failed: {e}")

    # Fallback to in-memory
    if pending is None:
        pending = PENDING_SIGNUPS.get(req.user_id)

    if not pending:
        raise HTTPException(status_code=400, detail="No pending signup or OTP expired")

    if is_expired(pending["ts"], OTP_TTL_SECONDS):
        PENDING_SIGNUPS.pop(req.user_id, None)
        raise HTTPException(status_code=400, detail="OTP expired")

    if req.otp != pending.get("otp"):
        raise HTTPException(status_code=400, detail="Invalid OTP")

    # For drivers, use the bus_id that was supplied during signup_start.
    bus_id_for_driver: Optional[str] = None
    if pending.get("role") == "driver":
        bus_id_for_driver = (pending.get("bus_id") or "").strip()
        if not bus_id_for_driver:
            # Should not happen if signup_start enforced bus_id, but guard anyway.
            raise HTTPException(status_code=400, detail="bus_id missing for driver signup; please start again")

    # Create user in in-memory store
    USERS[req.user_id] = {
        "user_id": req.user_id,
        "phone": pending["phone"],
        "role": pending["role"],
        "name": pending.get("name"),
        "email": pending.get("email"),
    }

    # Attach bus_id only for drivers so UI and other services can
    # know which bus this driver controls.
    if bus_id_for_driver:
        USERS[req.user_id]["bus_id"] = bus_id_for_driver

    # Index phone -> user_ids (allows same phone for multiple users)
    PHONE_TO_USERS.setdefault(pending["phone"], set()).add(req.user_id)

    # Remove pending from in-memory (Redis key auto-expires via TTL)
    PENDING_SIGNUPS.pop(req.user_id, None)

    # Persist to DB tables when enabled so that /users and /drivers
    # tables are populated for analytics and administration.
    if settings.USE_DB:
        try:
            async for session in get_db_session():
                if session is None:
                    break
                assert isinstance(session, AsyncSession)

                # Upsert into users table based on user_id
                stmt = select(DBUser).where(DBUser.user_id == req.user_id)
                result = await session.execute(stmt)
                db_user = result.scalar_one_or_none()

                if db_user:
                    db_user.role = pending["role"]
                    db_user.name = pending.get("name")
                    # Email is only meaningful for end-users
                    if pending["role"] == "user":
                        db_user.email = pending.get("email")
                    db_user.phone = pending["phone"]
                else:
                    db_user = DBUser(
                        user_id=req.user_id,
                        role=pending["role"],
                        name=pending.get("name"),
                        email=pending.get("email") if pending["role"] == "user" else None,
                        phone=pending["phone"],
                        is_active=True,
                    )
                    session.add(db_user)

                # For drivers, also maintain drivers table
                if pending["role"] == "driver":
                    bus_id = pending.get("bus_id")
                    stmt_d = select(DBDriver).where(DBDriver.driver_id == req.user_id)
                    res_d = await session.execute(stmt_d)
                    db_driver = res_d.scalar_one_or_none()
                    if db_driver:
                        db_driver.name = pending.get("name")
                        db_driver.phone = pending["phone"]
                        db_driver.bus_id = bus_id
                        db_driver.is_active = True
                    else:
                        db_driver = DBDriver(
                            driver_id=req.user_id,
                            name=pending.get("name"),
                            phone=pending["phone"],
                            bus_id=bus_id,
                            is_active=True,
                        )
                        session.add(db_driver)

                await session.commit()
                break
        except IntegrityError as ie:
            # If a UNIQUE constraint (user_id/email) is hit, log and move on.
            print(f"[auth_service][DB] IntegrityError while upserting user/driver: {ie}")
        except Exception as e:
            print(f"[auth_service][DB] Error while upserting user/driver: {e}")

    # Create session in memory
    token = generate_session_token()
    SESSIONS[token] = {
        "user_id": req.user_id,
        "role": pending["role"],
        "ts": int(time.time()),
    }

    # Mirror session to Redis
    if redis_setex is not None:
        try:
            s_key = f"auth:session:{token}"
            s_val = json.dumps(SESSIONS[token])
            await redis_setex(s_key, SESSION_TTL_SECONDS, s_val)
            print(f"[auth_service][Redis] stored session for {req.user_id} in {s_key}")
        except Exception as e:
            print(f"[auth_service][Redis] setex session failed: {e}")

    return {"session_token": token, "user": USERS[req.user_id]}

# ---------------- Login ---------------- #

@app.post("/auth/login/start")
async def login_start(req: LoginStartRequest):
    """
    Start login: send OTP to existing user's phone.
    """
    print(f"[auth_service] /auth/login/start called with user_id={req.user_id}")
    try:
        from tools import notifier
    except Exception as e:
        print(f"[auth_service] ERROR importing notifier: {e}")
        notifier = None

    validate_user_id(req.user_id)

    # First try in-memory user store
    user = USERS.get(req.user_id)

    # If not found in memory but DB is enabled, try loading from MySQL
    if not user and settings.USE_DB:
        try:
            async for session in get_db_session():
                if session is None:
                    break
                assert isinstance(session, AsyncSession)
                stmt = select(DBUser).where(DBUser.user_id == req.user_id)
                result = await session.execute(stmt)
                db_user = result.scalar_one_or_none()
                if db_user:
                    # Normalize phone so it is consistent with signup
                    phone_norm = normalize_phone(db_user.phone) if db_user.phone else None
                    # If this is a driver, also fetch the bound bus_id
                    bus_id = None
                    if db_user.role == "driver":
                        try:
                            stmt_d = select(DBDriver).where(DBDriver.driver_id == req.user_id)
                            res_d = await session.execute(stmt_d)
                            d = res_d.scalar_one_or_none()
                            if d:
                                bus_id = d.bus_id
                        except Exception as e:
                            print(f"[auth_service][DB] error loading driver for login_start: {e}")

                    user = {
                        "user_id": db_user.user_id,
                        "phone": phone_norm,
                        "role": db_user.role,
                        "name": db_user.name,
                        "email": db_user.email,
                    }
                    if bus_id:
                        user["bus_id"] = bus_id
                    USERS[req.user_id] = user
                break
        except Exception as e:
            print(f"[auth_service][DB] error loading user for login_start: {e}")

    if not user:
        raise HTTPException(status_code=404, detail="user_id not found")

    phone = user.get("phone")
    if not phone:
        raise HTTPException(status_code=500, detail="User has no phone on record")

    otp = generate_otp()
    PENDING_LOGINS[req.user_id] = {
        "user_id": req.user_id,
        "otp": otp,
        "ts": int(time.time()),
    }
    if redis_setex is not None:
        try:
            key = f"auth:login:{req.user_id}"
            value = json.dumps(PENDING_LOGINS[req.user_id])
            await redis_setex(key, OTP_TTL_SECONDS, value)
            print(f"[auth_service][Redis] stored login OTP for {req.user_id} in {key}")
        except Exception as e:
            print(f"[auth_service][Redis] login_start setex failed: {e}")
    if notifier:
        try:
            notifier.send_notification(
                req.user_id,
                f"Your login OTP is {otp}",
                channel="sms",
                phone=phone,
            )
        except Exception as e:
            print(f"[auth_service] notifier.send_notification (login) failed: {e}")
            print(f"[auth_service][FALLBACK] Login OTP for {req.user_id} ({phone}): {otp}")
    else:
        print(f"[auth_service][FALLBACK] Login OTP for {req.user_id} ({phone}): {otp}")

    return {"message": "OTP sent for login"}

@app.post("/auth/login/verify")
async def login_verify(req: LoginVerifyRequest):
    """
    Verify login OTP and create a new session token.
    """
    login = None
    if redis_get is not None:
        try:
            key = f"auth:login:{req.user_id}"
            raw = await redis_get(key)
            if raw:
                print(f"[auth_service][Redis] loaded login OTP for {req.user_id} from {key}")
                try:
                    login = json.loads(raw)
                except Exception:
                    login = None
        except Exception as e:
            print(f"[auth_service][Redis] login_verify get failed: {e}")

    if login is None:
        login = PENDING_LOGINS.get(req.user_id)

    if not login:
        raise HTTPException(status_code=400, detail="No pending login or OTP expired")

    if is_expired(login["ts"], OTP_TTL_SECONDS):
        PENDING_LOGINS.pop(req.user_id, None)
        raise HTTPException(status_code=400, detail="OTP expired")

    if req.otp != login.get("otp"):
        raise HTTPException(status_code=400, detail="Invalid OTP")

    # Ensure user is available in-memory; if not, try loading from DB
    user = USERS.get(req.user_id)
    if not user and settings.USE_DB:
        try:
            async for session in get_db_session():
                if session is None:
                    break
                assert isinstance(session, AsyncSession)
                stmt = select(DBUser).where(DBUser.user_id == req.user_id)
                result = await session.execute(stmt)
                db_user = result.scalar_one_or_none()
                if db_user:
                    phone_norm = normalize_phone(db_user.phone) if db_user.phone else None
                    bus_id = None
                    if db_user.role == "driver":
                        try:
                            stmt_d = select(DBDriver).where(DBDriver.driver_id == req.user_id)
                            res_d = await session.execute(stmt_d)
                            d = res_d.scalar_one_or_none()
                            if d:
                                bus_id = d.bus_id
                        except Exception as e:
                            print(f"[auth_service][DB] error loading driver for login_verify: {e}")

                    user = {
                        "user_id": db_user.user_id,
                        "phone": phone_norm,
                        "role": db_user.role,
                        "name": db_user.name,
                        "email": db_user.email,
                    }
                    if bus_id:
                        user["bus_id"] = bus_id
                    USERS[req.user_id] = user
                break
        except Exception as e:
            print(f"[auth_service][DB] error loading user for login_verify: {e}")

    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    # Clean up in-memory; Redis key will expire by TTL
    PENDING_LOGINS.pop(req.user_id, None)

    # Create session in memory
    token = generate_session_token()
    SESSIONS[token] = {
        "user_id": req.user_id,
        "role": user["role"],
        "ts": int(time.time()),
    }
    if redis_setex is not None:
        try:
            s_key = f"auth:session:{token}"
            s_val = json.dumps(SESSIONS[token])
            await redis_setex(s_key, SESSION_TTL_SECONDS, s_val)
            print(f"[auth_service][Redis] stored session for {req.user_id} in {s_key}")
        except Exception as e:
            print(f"[auth_service][Redis] setex session failed: {e}")

    return {"session_token": token, "user": user}

# ---------------- Session / current user ---------------- #

async def get_current_user(
    authorization: Optional[str] = Header(None),
):
    """
    Extract current user from Authorization: Bearer <token> header
    using in-memory SESSIONS.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    session = None

    # Try Redis first
    if redis_get is not None:
        try:
            s_key = f"auth:session:{token}"
            raw = await redis_get(s_key)
            if raw:
                print(f"[auth_service][Redis] loaded session from {s_key}")
                try:
                    session = json.loads(raw)
                except Exception:
                    session = None
        except Exception as e:
            print(f"[auth_service][Redis] get_current_user get failed: {e}")

    if session is None:
        session = SESSIONS.get(token)

    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if is_expired(session["ts"], SESSION_TTL_SECONDS):
        SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired")

    return {"user_id": session["user_id"], "role": session["role"]}

@app.get("/auth/me")
async def auth_me(current = Depends(get_current_user)):
    """
    Simple endpoint to test session: returns user_id and role.
    """
    return {"user": current}

@app.get("/auth/debug/headers")
async def debug_headers(request: Request):
    """
    DEBUG: return all incoming headers to inspect Authorization.
    """
    return {"headers": dict(request.headers.items())}