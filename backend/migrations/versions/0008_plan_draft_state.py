"""Store filter state alongside saved planning drafts."""
from alembic import op

revision = "0008_plan_draft_state"
down_revision = "0007_membership_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE zapara.plans ADD COLUMN settings jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE zapara.plans DROP COLUMN settings")
