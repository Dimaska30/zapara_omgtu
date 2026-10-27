"""Add isolated schedule cache and queue.

Revision ID: 0002_schedule_cache
Revises: 0001_initial
"""
from alembic import op

revision = "0002_schedule_cache"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE zapara.schedule_windows (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_kind text NOT NULL CHECK (entity_kind IN ('person', 'group', 'auditorium', 'building')),
            external_id text NOT NULL CHECK (external_id ~ '^[0-9]{1,20}$'),
            range_start date NOT NULL,
            range_end date NOT NULL CHECK (range_end = range_start + 6),
            payload jsonb,
            last_success_at timestamptz,
            last_attempt_at timestamptz,
            last_error text,
            last_accessed_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((payload IS NULL) = (last_success_at IS NULL)),
            UNIQUE (entity_kind, external_id, range_start)
        )
    """)
    op.execute("""
        CREATE TABLE zapara.schedule_jobs (
            window_id bigint PRIMARY KEY REFERENCES zapara.schedule_windows(id) ON DELETE CASCADE,
            due_at timestamptz NOT NULL DEFAULT now(),
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running')),
            lease_token uuid,
            locked_until timestamptz,
            failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
            CHECK ((status = 'running') = (lease_token IS NOT NULL AND locked_until IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX schedule_jobs_due_idx ON zapara.schedule_jobs (due_at) WHERE status = 'pending'")
    op.execute("""
        CREATE TABLE zapara.schedule_source_limit (
            source text PRIMARY KEY,
            next_allowed_at timestamptz NOT NULL DEFAULT now(),
            lease_token uuid,
            locked_until timestamptz,
            CHECK ((lease_token IS NULL) = (locked_until IS NULL))
        )
    """)
    op.execute("INSERT INTO zapara.schedule_source_limit (source) VALUES ('omgtu')")


def downgrade() -> None:
    op.execute("DROP TABLE zapara.schedule_source_limit")
    op.execute("DROP TABLE zapara.schedule_jobs")
    op.execute("DROP TABLE zapara.schedule_windows")
