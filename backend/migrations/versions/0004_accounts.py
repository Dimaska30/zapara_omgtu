"""Add accounts, departmental membership and opaque sessions."""
from alembic import op

revision = "0004_accounts"
down_revision = "0003_dictionary_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE zapara.departments (
      id uuid PRIMARY KEY, name text NOT NULL UNIQUE,
      source_chair_oid text UNIQUE,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE zapara.users (
      id uuid PRIMARY KEY, email text NOT NULL, display_name text NOT NULL,
      password_hash text, activated_at timestamptz, disabled_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(), last_login_at timestamptz
    );
    CREATE UNIQUE INDEX users_email_unique ON zapara.users(lower(email));
    CREATE TABLE zapara.system_admins (
      user_id uuid PRIMARY KEY REFERENCES zapara.users(id),
      created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz
    );
    CREATE TABLE zapara.memberships (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES zapara.users(id),
      department_id uuid NOT NULL REFERENCES zapara.departments(id),
      role text NOT NULL CHECK (role IN ('admin','planner','viewer')),
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','revoked')),
      can_override_source_conflict boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id, department_id)
    );
    CREATE TABLE zapara.teacher_links (
      user_id uuid NOT NULL REFERENCES zapara.users(id),
      person_id text NOT NULL CHECK (person_id ~ '^[0-9]{1,20}$'),
      lecturer_oid text NOT NULL CHECK (lecturer_oid ~ '^[0-9]{1,20}$'),
      verified_by uuid REFERENCES zapara.users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, person_id), UNIQUE(person_id), UNIQUE(lecturer_oid)
    );
    CREATE TABLE zapara.account_tokens (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES zapara.users(id),
      kind text NOT NULL CHECK (kind IN ('invitation','password_reset')),
      token_hash bytea NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
      created_by uuid REFERENCES zapara.users(id), created_at timestamptz NOT NULL DEFAULT now(),
      used_at timestamptz, revoked_at timestamptz
    );
    CREATE UNIQUE INDEX account_tokens_active_uq ON zapara.account_tokens(user_id,kind)
      WHERE used_at IS NULL AND revoked_at IS NULL;
    CREATE TABLE zapara.sessions (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES zapara.users(id),
      token_hash bytea NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz
    );
    CREATE TABLE zapara.login_limits (
      key_hash bytea PRIMARY KEY, failures integer NOT NULL DEFAULT 0,
      blocked_until timestamptz, last_attempt_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE zapara.account_audit (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      actor_id uuid REFERENCES zapara.users(id), target_id uuid REFERENCES zapara.users(id),
      department_id uuid REFERENCES zapara.departments(id), action text NOT NULL,
      details jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE zapara.account_audit, zapara.login_limits, zapara.sessions,
      zapara.account_tokens, zapara.teacher_links, zapara.memberships,
      zapara.system_admins, zapara.users, zapara.departments;
    """)
