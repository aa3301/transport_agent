"""
Fleet service with MySQL backend.

Purpose:
- Replace in-memory fleet_service with async DB-backed CRUD
- Provide transactional bus updates, route queries
- Support concurrent driver location updates safely

Key methods:
- get_bus_status(bus_id): fetch bus from DB
- update_bus_location(bus_id, lat, lon): update GPS atomically
- get_route(route_id): fetch route stops
- fleet_overview(): list all buses

Production notes:
- Use async transactions for multi-step operations (e.g., update bus + notify)
- Implement optimistic locking for concurrent updates if needed
- Add indexes on bus_id, route_id for fast queries
- Monitor query performance and slow logs
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from models.db_models import Bus, Route
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class FleetDBService:
    """DB-backed fleet service using async SQLAlchemy."""
    
    def __init__(self, session: AsyncSession):
        """
        Initialize service with async DB session.
        
        Args:
            session: AsyncSession from dependency injection
        """
        self.session = session
    
    async def get_bus(self, bus_id: str) -> dict | None:
        """
        Fetch bus by ID from database.
        
        Args:
            bus_id: bus identifier
            
        Returns:
            bus dict or None if not found
        """
        try:
            result = await self.session.execute(
                select(Bus).where(Bus.bus_id == bus_id)
            )
            bus = result.scalar_one_or_none()
            return self._bus_to_dict(bus) if bus else None
        except Exception as e:
            logger.error(f"Error fetching bus {bus_id}: {e}")
            return None
    
    async def get_bus_status(self, bus_id: str) -> dict | None:
        """
        Fetch bus status (location, route, status).
        
        Args:
            bus_id: bus identifier
            
        Returns:
            status dict with bus_id, lat, lon, status, route_id, or None
        """
        bus_dict = await self.get_bus(bus_id)
        if not bus_dict:
            return None
        return {
            "bus_id": bus_dict.get("bus_id"),
            "lat": bus_dict.get("lat"),
            "lon": bus_dict.get("lon"),
            "status": bus_dict.get("status", "unknown"),
            "status_message": bus_dict.get("status_message", ""),
            "route_id": bus_dict.get("route_id"),
            "speed_kmph": bus_dict.get("speed_kmph", 0.0),
        }
    
    async def update_bus_location(self, bus_id: str, lat: float, lon: float, speed_kmph: float = 0.0) -> dict | None:
        """
        Update bus GPS location atomically (driver sends update).
        
        Args:
            bus_id: bus identifier
            lat: latitude
            lon: longitude
            speed_kmph: current speed (optional)
            
        Returns:
            updated bus dict or None if bus not found
        """
        try:
            # Begin transaction
            async with self.session.begin():
                result = await self.session.execute(
                    select(Bus).where(Bus.bus_id == bus_id).with_for_update()  # lock row
                )
                bus = result.scalar_one_or_none()
                if not bus:
                    logger.warning(f"Bus {bus_id} not found for location update")
                    return None
                
                # Update GPS and timestamp
                bus.lat = lat
                bus.lon = lon
                bus.speed_kmph = speed_kmph
                bus.updated_at = datetime.utcnow()
                
                await self.session.flush()  # ensure changes are staged
                logger.info(f"Updated location for {bus_id}: ({lat}, {lon})")
                
            return self._bus_to_dict(bus)
        except Exception as e:
            logger.error(f"Error updating location for {bus_id}: {e}")
            return None
    
    async def update_bus_status(self, bus_id: str, status: str, message: str | None = None,
                                speed_kmph: float | None = None) -> dict | None:
        """
        Update bus operational status (on_time, delayed, breakdown).
        
        Args:
            bus_id: bus identifier
            status: new status
            message: optional status message
            
        Returns:
            updated bus dict or None if bus not found
        """
        try:
            async with self.session.begin():
                result = await self.session.execute(
                    select(Bus).where(Bus.bus_id == bus_id).with_for_update()
                )
                bus = result.scalar_one_or_none()
                if not bus:
                    return None
                
                bus.status = status
                if message:
                    bus.status_message = message
                if speed_kmph is not None:
                    bus.speed_kmph = speed_kmph
                bus.updated_at = datetime.utcnow()
                
                await self.session.flush()
                logger.info(f"Updated status for {bus_id}: {status}")
                
            return self._bus_to_dict(bus)
        except Exception as e:
            logger.error(f"Error updating status for {bus_id}: {e}")
            return None
    
    async def get_route(self, route_id: str) -> dict | None:
        """
        Fetch route by ID.
        
        Args:
            route_id: route identifier
            
        Returns:
            route dict with stops or None
        """
        try:
            result = await self.session.execute(
                select(Route).where(Route.route_id == route_id)
            )
            route = result.scalar_one_or_none()
            return self._route_to_dict(route) if route else None
        except Exception as e:
            logger.error(f"Error fetching route {route_id}: {e}")
            return None
    
    async def fleet_overview(self) -> list[dict]:
        """
        Fetch all buses with routes and status.
        
        Returns:
            list of bus dicts with route info
        """
        try:
            result = await self.session.execute(select(Bus))
            buses = result.scalars().all()
            overview = []
            for bus in buses:
                route = None
                if bus.route_id:
                    route = await self.get_route(bus.route_id)
                overview.append({
                    **self._bus_to_dict(bus),
                    "route": route,
                })
            return overview
        except Exception as e:
            logger.error(f"Error fetching fleet overview: {e}")
            return []
    
    async def update_route(self, route_id: str, stops: list[dict]) -> dict | None:
        """
        Create or update a route.
        
        Args:
            route_id: route identifier
            stops: list of stop dicts [{id, name, lat, lon}, ...]
            
        Returns:
            route dict or None on error
        """
        try:
            async with self.session.begin():
                result = await self.session.execute(
                    select(Route).where(Route.route_id == route_id)
                )
                route = result.scalar_one_or_none()
                if route:
                    route.stops = stops
                    route.updated_at = datetime.utcnow()
                else:
                    route = Route(route_id=route_id, stops=stops)
                    self.session.add(route)
                
                await self.session.flush()
                logger.info(f"Updated route {route_id} with {len(stops)} stops")
                
            return self._route_to_dict(route)
        except Exception as e:
            logger.error(f"Error updating route {route_id}: {e}")
            return None
    
    @staticmethod
    def _bus_to_dict(bus: Bus) -> dict:
        """Convert Bus ORM model to dict."""
        return {
            "bus_id": bus.bus_id,
            "lat": bus.lat,
            "lon": bus.lon,
            "speed_kmph": bus.speed_kmph,
            "route_id": bus.route_id,
            "status": bus.status,
            "status_message": bus.status_message,
            "created_at": bus.created_at.isoformat() if bus.created_at else None,
            "updated_at": bus.updated_at.isoformat() if bus.updated_at else None,
        }
    
    @staticmethod
    def _route_to_dict(route: Route) -> dict:
        """Convert Route ORM model to dict."""
        return {
            "route_id": route.route_id,
            "stops": route.stops,
            "created_at": route.created_at.isoformat() if route.created_at else None,
            "updated_at": route.updated_at.isoformat() if route.updated_at else None,
        }

# Legacy in-memory fallback (keep for backward compatibility during migration)
# TODO: Remove after full DB migration
from services.fleet_service import fleet_service as fleet_service_inmem
