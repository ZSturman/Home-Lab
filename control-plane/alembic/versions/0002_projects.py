"""Project Hub: projects and reconciliation_items tables."""

from alembic import op

from app.models import Base

revision = "0002_projects"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all only creates tables that do not already exist, so this is
    # safe to run against a database that already has the 0001 tables.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["reconciliation_items"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["projects"].drop(bind=bind, checkfirst=True)
