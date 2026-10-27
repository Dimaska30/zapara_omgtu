"""Add source dictionary cache and shared worker scheduling state.

Revision ID: 0003_dictionary_cache
Revises: 0002_schedule_cache
"""
from alembic import op

revision = "0003_dictionary_cache"
down_revision = "0002_schedule_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE zapara.dictionary_cache (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            kind text NOT NULL CHECK (kind IN ('groups', 'lecturers', 'buildings', 'auditoriums')),
            scope text NOT NULL DEFAULT '' CHECK (scope = '' OR scope ~ '^[0-9]{1,20}$'),
            payload jsonb,
            last_success_at timestamptz,
            last_attempt_at timestamptz,
            last_error text,
            last_accessed_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((payload IS NULL) = (last_success_at IS NULL)),
            UNIQUE (kind, scope)
        )
    """)
    op.execute("""
        CREATE TABLE zapara.dictionary_jobs (
            cache_id bigint PRIMARY KEY REFERENCES zapara.dictionary_cache(id) ON DELETE CASCADE,
            due_at timestamptz NOT NULL DEFAULT now(),
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running')),
            lease_token uuid,
            locked_until timestamptz,
            failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
            CHECK ((status = 'running') = (lease_token IS NOT NULL AND locked_until IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX dictionary_jobs_due_idx ON zapara.dictionary_jobs (due_at) WHERE status = 'pending'")
    op.execute("ALTER TABLE zapara.schedule_source_limit ADD COLUMN last_job_kind text NOT NULL DEFAULT 'dictionary' CHECK (last_job_kind IN ('schedule', 'dictionary'))")


def downgrade() -> None:
    op.execute("ALTER TABLE zapara.schedule_source_limit DROP COLUMN last_job_kind")
    op.execute("DROP TABLE zapara.dictionary_jobs")
    op.execute("DROP TABLE zapara.dictionary_cache")
