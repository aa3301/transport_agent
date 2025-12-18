#!/usr/bin/env bash
set -euo pipefail
# Usage inside container:
# SERVICE_MODULE environment variable must point to "module:app" (uvicorn target)
SERVICE_MODULE=${SERVICE_MODULE:-"microservices.agent_service_app:app"}

# generate gRPC stubs if protos exist
if [ -d "./protos" ]; then
  echo "Generating gRPC stubs..."
  python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto || true
fi

# run alembic migrations (if alembic present)
if [ -f "alembic.ini" ]; then
  echo "Running alembic migrations..."
  alembic upgrade head || true
fi

# start uvicorn with SERVICE_MODULE (use port mapping via env)
PORT=${PORT:-8000}
exec uvicorn ${SERVICE_MODULE} --host 0.0.0.0 --port ${PORT} --workers 1
