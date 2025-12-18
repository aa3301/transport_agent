"""
gRPC server for AgentService.

Delegates Ask RPC to SupervisorAgent.handle_user_query().
"""
import asyncio
import logging
import grpc

# Generated stubs
try:
    from transport_proto import transport_agent_pb2 as pb
    from transport_proto import transport_agent_pb2_grpc as rpc
except Exception:
    pb = None
    rpc = None

from agent.supervisor_agent import SupervisorAgent

logger = logging.getLogger(__name__)
supervisor = SupervisorAgent()

class AgentServicer(rpc.AgentServiceServicer):
    async def Ask(self, request, context):
        try:
            result = await supervisor.handle_user_query(request.query)
            answer = result.get("answer") if isinstance(result, dict) else str(result)
            plan_json = ""
            try:
                import json
                plan_json = json.dumps(result.get("plan", {})) if isinstance(result, dict) else ""
            except Exception:
                plan_json = ""
            return pb.AskResponse(ok=True, answer=answer or "", plan_json=plan_json)
        except Exception as e:
            logger.exception("Ask RPC failed")
            return pb.AskResponse(ok=False, answer=str(e), plan_json="")

async def serve(host="0.0.0.0", port=50052):
    server = grpc.aio.server()
    rpc.add_AgentServiceServicer_to_server(AgentServicer(), server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC Agent server started on %s:%d", host, port)
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())
