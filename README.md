Transport Agent — Run & Deploy (dev / local)

Prerequisites
- Docker & docker-compose
- Python 3.11 (for local dev without Docker)
- protoc + grpcio-tools (for generating gRPC stubs)

Quick start (recommended, local Docker)
1. Copy `.env.example` to `.env` and edit if needed (DB passwords, secrets)
2. Build & start infra + services:
   make build
   make up

3. Generate gRPC stubs (if not done by container):
   make gen-protos
   # or: python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto

4. Run migrations:
   make migrate
   # or: alembic upgrade head

5. Tail logs:
   make logs

Manual local dev (without Docker)
1. Install Python deps:
   python -m pip install -r requirements.txt

2. Start infra (use docker-compose for MySQL/Redis/RabbitMQ/Kafka):
   docker-compose up -d mysql redis rabbitmq zookeeper kafka

3. Generate gRPC stubs:
   python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto

4. Run migrations:
   alembic upgrade head

5. Start services (each in its own terminal):
   uvicorn microservices.agent_service_app:app --port 8001 --reload
   uvicorn microservices.fleet_service_app:app --port 8002 --reload
   uvicorn microservices.notification_service_app:app --port 8003 --reload
   uvicorn api_gateway.main:app --port 8000 --reload

6. Start notification worker:
   python -m workers.notification_worker

Testing endpoints
- API Gateway base: http://localhost:8000
- Ask: POST /ask  (JSON: { "query": "When will B1 reach S1?" })
- Driver location: POST /driver/location
- Subscribe: POST /subscribe

Notes / Troubleshooting
- Protobuf stubs must be generated prior to running gRPC servers/clients.
- If Alembic fails, ensure MYSQL_ASYNC_URL points to a running MySQL instance.
- Check RabbitMQ management UI at http://localhost:15672 (guest/guest).
- Check Kafka/Zookeeper via logs in docker-compose output.

Security & Production
- Replace simple JWT secret with real auth provider (OIDC/JWKS).
- Use TLS for gRPC and HTTPS for external gateway.
- Use Kubernetes and deploy separate replicas for each microservice.
- Configure monitoring (Prometheus, OpenTelemetry) and logging sink (ELK/Datadog).

For any step you want automated next (docker-compose improvements, CI), tell me which and I'll add the files.
