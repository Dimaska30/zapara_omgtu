"""Support concurrent administrative membership changes."""
from alembic import op
revision='0007_membership_version'
down_revision='0006_schedule_alerts'
branch_labels=None
depends_on=None

def upgrade() -> None:
    op.execute('ALTER TABLE zapara.memberships ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK(version>0)')

def downgrade() -> None:
    op.execute('ALTER TABLE zapara.memberships DROP COLUMN version')
