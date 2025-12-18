"""
gRPC server for FleetService.

Run side-by-side with HTTP server or replace HTTP internal calls with gRPC.
Requires generated Python gRPC stubs (transport_proto.*).
"""
import asyncio
import logging
import grpc
from concurrent import futures

# Generated stubs
try:
    from transport_proto import transport_agent_pb2 as pb
    from transport_proto import transport_agent_pb2_grpc as rpc
except Exception:
    pb = None
    rpc = None

# DB session and service
from core.db import AsyncSession, get_db_session, engine
from services.fleet_db_service import FleetDBService

logger = logging.getLogger(__name__)

class FleetServicer(rpc.FleetServiceServicer):
    """Implements FleetService RPCs by delegating to FleetDBService."""

    def __init__(self):
        pass

    async def UpdateLocation(self, request, context):
        # open async DB session per RPC
        async with engine.connect() as conn:
            async with conn.begin():
                session = AsyncSession(bind=conn)
                svc = FleetDBService(session)
                bus = await svc.update_bus_location(request.bus_id, request.lat, request.lon, speed_kmph=request.speed_kmph)
                if bus:
                    return pb.UpdateLocationResponse(ok=True, message="updated", bus={})
                return pb.UpdateLocationResponse(ok=False, message="not found", bus={})

    async def UpdateStatus(self, request, context):
        async with engine.connect() as conn:
            async with conn.begin():
                session = AsyncSession(bind=conn)
                svc = FleetDBService(session)
                updated = await svc.update_bus_status(request.bus_id, request.status, request.message)
                if updated:
                    return pb.UpdateStatusResponse(ok=True, message="updated")
                return pb.UpdateStatusResponse(ok=False, message="not found")

    async def GetBusStatus(self, request, context):
        async with engine.connect() as conn:
            session = AsyncSession(bind=conn)
            svc = FleetDBService(session)
            status = await svc.get_bus_status(request.bus_id)
            if status:
                # flatten dict values into strings for proto map<string,string>
                return pb.GetBusStatusResponse(ok=True, status={k: str(v) for k,v in status.items() if v is not None})
            return pb.GetBusStatusResponse(ok=False, status={})

    async def FleetOverview(self, request, context):
        async with engine.connect() as conn:
            session = AsyncSession(bind=conn)
            svc = FleetDBService(session)
            overview = await svc.fleet_overview()
            # Note: converting list of dicts into repeated map not directly supported;
            # here we return ok and empty maps (use repeated message in proto for richer data)
            return pb.FleetOverviewResponse(ok=True)

async def serve(host="0.0.0.0", port=50051):
    server = grpc.aio.server()
    rpc.add_FleetServiceServicer_to_server(FleetServicer(), server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC Fleet server started on %s:%d", host, port)
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())
