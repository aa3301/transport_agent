"""
Redis client and cache helpers.

Purpose:
- Provide async Redis connection and caching utilities
- Support ETA/weather cache, distributed rate limiting
- Handle connection pooling and error gracefully

Usage:
- cache_eta(bus_id, stop_id, eta_seconds, ttl=300)
- get_eta(bus_id, stop_id)
- increment_rate_limit(key, limit, window)

Production notes:
- Use Redis connection pool for performance
- Monitor memory and eviction policies
- Implement cache warming for frequently accessed data
- Set appropriate TTLs (ETA: 5min, weather: 30min)
"""
import json
import logging
import os
from config.settings import settings
from typing import Optional
import redis.asyncio as redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_client: redis.Redis | None = None

def get_redis() -> redis.Redis | None:
    """
    Lazily create and return a Redis client.
    If anything fails, return None so rest of code can silently fallback.
    """
    global redis_client
    if redis_client is None:
        try:
            print(f"[redis_client] Creating Redis client for URL={REDIS_URL}")  # NEW: log creation
            redis_client = redis.Redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        except Exception as e:
            print(f"[redis_client] Failed to create Redis client: {e}")
            redis_client = None
    return redis_client

async def get(key: str):
    """
    Async GET helper. Returns None on any failure or missing key.
    """
    client = get_redis()
    if not client:
        print(f"[redis_client] GET skipped for {key}: no client")  # NEW
        return None
    try:
        value = await client.get(key)
        print(f"[redis_client] GET {key} -> {value}")  # NEW
        return value
    except Exception as e:
        print(f"[redis_client] GET error for {key}: {e}")
        return None

async def setex(key: str, ttl_sec: int, value: str):
    """
    Async SETEX helper. Sets 'key' to 'value' with TTL (seconds).
    Returns True on success, False on any failure.
    """
    client = get_redis()
    if not client:
        print(f"[redis_client] SETEX skipped for {key}: no client")  # NEW
        return False
    try:
        await client.setex(key, ttl_sec, value)
        print(f"[redis_client] SETEX {key} ttl={ttl_sec} value={value}")  # NEW
        return True
    except Exception as e:
        print(f"[redis_client] SETEX error for {key}: {e}")
        return False

class RedisClient:
    """Async Redis client wrapper."""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Initialize async Redis connection."""
        try:
            self.redis = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf8",
                decode_responses=True,
            )
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis = None
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        if not self.redis:
            return None
        try:
            return await self.redis.get(key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None
    
    async def set(self, key: str, value: str, ttl: int = 300) -> bool:
        """Set key-value with TTL (seconds)."""
        if not self.redis:
            return False
        try:
            await self.redis.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete a key."""
        if not self.redis:
            return False
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            return False
    
    async def incr(self, key: str, ttl: int = 60) -> int:
        """
        Increment counter (used for rate limiting).
        TTL is set only on first increment.
        """
        if not self.redis:
            return 0
        try:
            pipe = self.redis.pipeline()
            await pipe.incr(key).execute()
            # Set TTL only if this is the first increment (TTL not set)
            ttl_check = await self.redis.ttl(key)
            if ttl_check == -1:  # -1 means no TTL set
                await self.redis.expire(key, ttl)
            result = await self.redis.get(key)
            return int(result) if result else 0
        except Exception as e:
            logger.error(f"Redis INCR error: {e}")
            return 0
    
    async def cache_eta(self, bus_id: str, stop_id: str, eta_seconds: int, ttl: int = 300) -> bool:
        """
        Cache ETA for a bus-stop pair.
        
        Args:
            bus_id: bus identifier
            stop_id: stop identifier
            eta_seconds: estimated arrival time in seconds
            ttl: cache lifetime in seconds (default 5min)
            
        Returns:
            True if cached, False otherwise
        """
        key = f"eta:{bus_id}:{stop_id}"
        value = json.dumps({"eta_sec": eta_seconds, "cached_at": datetime.utcnow().isoformat()})
        return await self.set(key, value, ttl=ttl)
    
    async def get_eta(self, bus_id: str, stop_id: str) -> Optional[dict]:
        """
        Retrieve cached ETA.
        
        Args:
            bus_id: bus identifier
            stop_id: stop identifier
            
        Returns:
            ETA dict or None if not cached
        """
        key = f"eta:{bus_id}:{stop_id}"
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except:
                return None
        return None
    
    async def cache_weather(self, lat: float, lon: float, weather_data: dict, ttl: int = 1800) -> bool:
        """
        Cache weather for coordinates.
        
        Args:
            lat: latitude
            lon: longitude
            weather_data: weather info dict
            ttl: cache lifetime in seconds (default 30min)
            
        Returns:
            True if cached, False otherwise
        """
        key = f"weather:{lat}:{lon}"
        value = json.dumps(weather_data)
        return await self.set(key, value, ttl=ttl)
    
    async def get_weather(self, lat: float, lon: float) -> Optional[dict]:
        """
        Retrieve cached weather.
        
        Args:
            lat: latitude
            lon: longitude
            
        Returns:
            weather dict or None if not cached
        """
        key = f"weather:{lat}:{lon}"
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except:
                return None
        return None

# Global Redis client instance
redis_client = RedisClient()

from datetime import datetime

async def redis_get(key: str):
    """
    Compatibility helper: use underlying async Redis client to GET a key.
    Returns None if Redis is not configured or on any error.
    """
    try:
        # Many projects store the real client as redis_client.client; fall back to redis_client itself.
        client = getattr(redis_client, "client", None) or redis_client
        if not client:
            logger.info("[redis_client] GET skipped for %s: no client", key)
            return None
        if hasattr(client, "get"):
            val = await client.get(key)
            logger.info("[redis_client] GET %s -> %s", key, val)
            return val
        logger.warning("[redis_client] GET not supported on %s", type(client))
        return None
    except Exception as e:
        logger.error("[redis_client] GET error for %s: %s", key, e)
        return None

async def redis_setex(key: str, ttl_sec: int, value: str):
    """
    Compatibility helper: use underlying async Redis client to SET a key with TTL.
    Supports either:
      - client.setex(key, ttl, value), or
      - client.set(key, value, ttl)  # positional TTL (no 'ex' kwarg)
    Returns True on success, False on any error.
    """
    try:
        client = getattr(redis_client, "client", None) or redis_client
        if not client:
            logger.info("[redis_client] SETEX skipped for %s: no client", key)
            return False

        if hasattr(client, "setex"):
            # Preferred: standard Redis SETEX.
            await client.setex(key, ttl_sec, value)
        elif hasattr(client, "set"):
            # Fallback: your RedisClient.set(key, value, ttl) without 'ex=' keyword.
            await client.set(key, value, ttl_sec)  # IMPORTANT: no ex=, TTL as positional arg
        else:
            logger.warning("[redis_client] SETEX not supported on %s", type(client))
            return False

        logger.info("[redis_client] SETEX %s ttl=%s value=%s", key, ttl_sec, value)
        return True
    except Exception as e:
        logger.error("[redis_client] SETEX error for %s: %s", key, e)
        return False
