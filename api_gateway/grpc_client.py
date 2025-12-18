"""
gRPC client helpers for API Gateway.

Requires generated stubs from protos/transport_agent.proto:
  pip install grpcio grpcio-tools
  python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto

This module provides simple async wrappers to call FleetService and AgentService.
"""
import asyncio
import logging
import grpc
from typing import Optional

# Generated modules (after running protoc)
try:
    from transport_proto import transport_agent_pb2 as pb
    from transport_proto import transport_agent_pb2_grpc as rpc
except Exception:
    pb = None
    rpc = None

logger = logging.getLogger(__name__)

class GRPCClient:
    def __init__(self, target: str):
        self.target = target
        self.channel: Optional[grpc.aio.Channel] = None
        self.stub = None

    async def connect(self, stub_cls):
        if not pb or not rpc:
            raise RuntimeError("Protobuf stubs not generated. Run protoc as instructed.")
        self.channel = grpc.aio.insecure_channel(self.target)
        self.stub = stub_cls(self.channel)
        # optional: wait for ready
        try:
            await self.channel.channel_ready()
        except Exception:
            logger.warning("gRPC channel not ready to %s", self.target)

    async def close(self):
        if self.channel:
            await self.channel.close()

# Fleet client wrapper
class FleetGRPCClient(GRPCClient):
    def __init__(self, target: str):
        super().__init__(target)
        self.stub: Optional[rpc.FleetServiceStub] = None

    async def connect(self):
        await super().connect(rpc.FleetServiceStub)

    async def update_location(self, bus_id: str, lat: float, lon: float, speed_kmph: float = 0.0):
        req = pb.UpdateLocationRequest(bus_id=bus_id, lat=lat, lon=lon, speed_kmph=speed_kmph)
        resp = await self.stub.UpdateLocation(req)
        return resp

    async def update_status(self, bus_id: str, status: str, message: str = ""):
        req = pb.UpdateStatusRequest(bus_id=bus_id, status=status, message=message)
        resp = await self.stub.UpdateStatus(req)
        return resp

    async def get_bus_status(self, bus_id: str):
        req = pb.GetBusStatusRequest(bus_id=bus_id)
        resp = await self.stub.GetBusStatus(req)
        return resp

# Agent client wrapper
class AgentGRPCClient(GRPCClient):
    def __init__(self, target: str):
        super().__init__(target)
        self.stub: Optional[rpc.AgentServiceStub] = None

    async def connect(self):
        await super().connect(rpc.AgentServiceStub)

    async def ask(self, query: str):
        req = pb.AskRequest(query=query)
        resp = await self.stub.Ask(req)
        return resp
