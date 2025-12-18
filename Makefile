.PHONY: build up down gen-protos migrate logs

build:
	docker-compose build

up:
	docker-compose up -d
	# generate protos and run migrations in api_gateway container (example)
	sleep 3
	docker-compose exec api_gateway bash -lc "python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto || true"
	docker-compose exec api_gateway alembic upgrade head || true

down:
	docker-compose down

gen-protos:
	python -m grpc_tools.protoc -I./protos --python_out=./transport_proto --grpc_python_out=./transport_proto protos/transport_agent.proto

migrate:
	alembic upgrade head

logs:
	docker-compose logs -f
