"""Add departmental draft plans, slots and selected substitutions."""
from alembic import op

revision = "0005_plans"
down_revision = "0004_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE zapara.plans (
      id uuid PRIMARY KEY, department_id uuid NOT NULL REFERENCES zapara.departments(id),
      owner_id uuid NOT NULL REFERENCES zapara.users(id),
      kind text NOT NULL CHECK(kind IN ('consultation','retake','meeting','substitution')),
      title text NOT NULL DEFAULT '', status text NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft','confirmed','cancelled','archived')),
      version integer NOT NULL DEFAULT 1 CHECK(version>0),
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX plans_department_idx ON zapara.plans(department_id,status,updated_at DESC);
    CREATE TABLE zapara.plan_grants (
      plan_id uuid NOT NULL REFERENCES zapara.plans(id), user_id uuid NOT NULL REFERENCES zapara.users(id),
      permission text NOT NULL CHECK(permission IN ('edit','confirm')),
      granted_by uuid NOT NULL REFERENCES zapara.users(id), PRIMARY KEY(plan_id,user_id)
    );
    CREATE TABLE zapara.plan_slots (
      id uuid PRIMARY KEY, plan_id uuid NOT NULL REFERENCES zapara.plans(id),
      event_date date NOT NULL, slot_number smallint NOT NULL CHECK(slot_number>0),
      starts_at time NOT NULL, ends_at time NOT NULL, timezone text NOT NULL DEFAULT 'Asia/Omsk',
      status text NOT NULL DEFAULT 'selected' CHECK(status IN ('selected','confirmed','cancelled')),
      CHECK(ends_at>starts_at), UNIQUE(plan_id,event_date,slot_number)
    );
    CREATE TABLE zapara.slot_resources (
      slot_id uuid NOT NULL REFERENCES zapara.plan_slots(id),
      kind text NOT NULL CHECK(kind IN ('person','group','auditorium')),
      external_id text NOT NULL CHECK(external_id ~ '^[0-9]{1,20}$'),
      display_name text NOT NULL DEFAULT '', PRIMARY KEY(slot_id,kind,external_id)
    );
    CREATE TABLE zapara.substitutions (
      id uuid PRIMARY KEY, slot_id uuid NOT NULL REFERENCES zapara.plan_slots(id),
      original_person_id text NOT NULL CHECK(original_person_id ~ '^[0-9]{1,20}$'),
      substitute_person_id text NOT NULL CHECK(substitute_person_id ~ '^[0-9]{1,20}$'),
      source_snapshot jsonb NOT NULL, status text NOT NULL DEFAULT 'selected'
        CHECK(status IN ('selected','confirmed','cancelled')),
      confirmed_by uuid REFERENCES zapara.users(id), confirmed_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(), CHECK(original_person_id<>substitute_person_id),
      CHECK(status<>'confirmed' OR confirmed_at IS NOT NULL)
    );
    CREATE TABLE zapara.plan_activity (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      plan_id uuid NOT NULL REFERENCES zapara.plans(id), actor_id uuid NOT NULL REFERENCES zapara.users(id),
      action text NOT NULL, details jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE zapara.notifications (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES zapara.users(id),
      plan_id uuid NOT NULL REFERENCES zapara.plans(id), kind text NOT NULL,
      payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), read_at timestamptz
    );
    CREATE INDEX notifications_user_idx ON zapara.notifications(user_id,created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE zapara.notifications, zapara.plan_activity, zapara.substitutions, zapara.slot_resources, zapara.plan_slots, zapara.plan_grants, zapara.plans")
