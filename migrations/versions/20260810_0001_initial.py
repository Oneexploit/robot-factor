"""Initial invoice bot schema.

Revision ID: 20260810_0001
Revises:
Create Date: 2026-08-10
"""

from alembic import op

from robot_factor.models import Base

revision = "20260810_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
