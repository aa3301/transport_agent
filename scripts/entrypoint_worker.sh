#!/usr/bin/env bash
set -euo pipefail

if [ -d "./protos" ]; then
  echo "Generating gRPC stubs..."
  python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto || true
fi

if [ -f "alembic.ini" ]; then
  echo "Running alembic migrations..."
  alembic upgrade head || true
fi

# start notification worker
exec python -m workers.notification_worker
