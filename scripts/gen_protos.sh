#!/usr/bin/env bash
set -euo pipefail
python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto
echo "Protobuf stubs generated in ./transport_proto"
