"""
Initial database schema: buses, routes, subscriptions, drivers, users.

Revision ID: 001
Created: 2024-01-01 (example)
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Create initial tables."""
    # Buses table
    op.create_table(
        "buses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bus_id", sa.String(50), unique=True, index=True, nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("speed_kmph", sa.Float(), default=0.0),
        sa.Column("route_id", sa.String(50), nullable=True, index=True),
        sa.Column("status", sa.String(50), default="on_time", index=True),
        sa.Column("status_message", sa.String(500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    
    # Routes table
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.String(50), unique=True, index=True, nullable=False),
        sa.Column("stops", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    
    # Subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(100), index=True, nullable=False),
        sa.Column("bus_id", sa.String(50), index=True, nullable=False),
        sa.Column("stop_id", sa.String(50), nullable=False),
        sa.Column("notify_before_sec", sa.Integer(), default=300),
        sa.Column("policy", sa.JSON(), nullable=True),
        sa.Column("channel", sa.String(50), default="console"),
        sa.Column("is_active", sa.Boolean(), default=True, index=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    
    # Drivers table
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.String(50), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("bus_id", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    
    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(100), unique=True, index=True, nullable=False),
        sa.Column("role", sa.String(50), default="user", index=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("users")
    op.drop_table("drivers")
    op.drop_table("subscriptions")
    op.drop_table("routes")
    op.drop_table("buses")
