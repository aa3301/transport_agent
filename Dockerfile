# multi-stage to keep image small; `service` target runs FastAPI app
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy code
FROM base AS service
COPY . /app
# entrypoint will run gen-protos + migrations then start uvicorn
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh
EXPOSE 8000 8001 8002 8003
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# small target for running workers
FROM base AS worker
COPY . /app
COPY scripts/entrypoint_worker.sh /app/scripts/entrypoint_worker.sh
RUN chmod +x /app/scripts/entrypoint_worker.sh
ENTRYPOINT ["/app/scripts/entrypoint_worker.sh"]
