"""Project Hub: resources table (repo-onboarding external-mutation contract)."""

from alembic import op

from app.models import Base

revision = "0003_resources"
down_revision = "0002_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all only creates tables that do not already exist, so this is
    # safe to run against a database that already has the 0001/0002 tables.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["resources"].drop(bind=bind, checkfirst=True)
