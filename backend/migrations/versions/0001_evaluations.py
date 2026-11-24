"""Create the benchmark result table; LangGraph owns its checkpoint tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_evaluations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("evaluation_runs")
