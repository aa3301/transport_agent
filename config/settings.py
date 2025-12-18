"""
Application settings and environment configuration.

Purpose:
- Centralize all config (DB, Redis, RabbitMQ, JWT, etc.)
- Load from environment variables for 12-factor app compliance
- Provide sensible defaults for local development
"""
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Configuration
    API_TITLE: str = "Transport Agent API"
    API_VERSION: str = "0.2"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    
    # Database: MySQL async connection string
    # Format: mysql+aiomysql://user:password@host:port/database
    # Example: mysql+aiomysql://root:password@localhost:3306/transport_db
    MYSQL_ASYNC_URL: str = os.getenv(
        "MYSQL_ASYNC_URL",
        "mysql+aiomysql://root:password@localhost:3306/transport_db"
    )
    
    # Redis: for caching and distributed rate limiting
    # Format: redis://host:port/db
    # Example: redis://localhost:6379/0
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # RabbitMQ: for message queues and task distribution
    # Format: amqp://user:password@host:port/vhost
    # Example: amqp://guest:guest@localhost:5672/
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    
    # Kafka: for event streaming (used in production for high-volume events)
    # Format: comma-separated brokers
    # Example: localhost:9092,localhost:9093
    KAFKA_BROKERS: str = os.getenv("KAFKA_BROKERS", "localhost:9092")
    
    # JWT Secret: read from .env (no hard-coded secret)
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change_me_to_secure_value")
    
    # Logging: configure structured logging level
    # Values: DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Rate Limiter: default limits (calls per second)
    RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "120"))
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
    
    # Additional fields
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY", None)
    WEATHER_API_KEY: str | None = os.getenv("WEATHER_API_KEY", None)
    FAISS_K: int = int(os.getenv("FAISS_K", "8"))
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    
    # Use DB flag
    USE_DB: bool = os.getenv("USE_DB", "false").lower() == "true"
    
    class Config:
        env_file = ".env"  # Load from .env file if present
        extra = "allow"  # Optional: allow extra fields if you want to ignore unknowns

# Global settings instance
settings = Settings()
