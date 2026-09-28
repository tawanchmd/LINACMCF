"""v5.9 Phase 2: additive center-scoped workspace state.

Revision ID: 20260928_02
Revises: 20260927_01
"""
from alembic import op
import sqlalchemy as sa

revision="20260928_02"
down_revision="20260927_01"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table(
        "center_states",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("center_id",sa.Integer(),nullable=False),
        sa.Column("payload",sa.Text(),nullable=False),
        sa.Column("updated_at",sa.DateTime(),server_default=sa.func.now(),nullable=False),
        sa.ForeignKeyConstraint(["center_id"],["centers.id"],ondelete="CASCADE"),
        sa.UniqueConstraint("center_id"),
    )
    op.create_index("ix_center_states_center_id","center_states",["center_id"],unique=True)

def downgrade():
    op.drop_index("ix_center_states_center_id",table_name="center_states")
    op.drop_table("center_states")
