"""Track schedule conflict state for deduplicated notifications."""
from alembic import op

revision = "0006_schedule_alerts"
down_revision = "0005_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE zapara.schedule_alerts (
      subject_kind text NOT NULL CHECK(subject_kind IN ('slot','substitution')),
      subject_id uuid NOT NULL,
      resource_kind text NOT NULL CHECK(resource_kind IN ('person','group','auditorium')),
      resource_id text NOT NULL,
      active boolean NOT NULL DEFAULT true,
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(subject_kind,subject_id,resource_kind,resource_id)
    )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE zapara.schedule_alerts')
