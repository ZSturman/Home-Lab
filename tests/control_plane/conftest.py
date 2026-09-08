from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

CONTROL_PLANE_ROOT = Path(__file__).resolve().parents[2] / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE_ROOT))

# Must happen before anything imports app.db (which builds its engine at
# import time) or app.settings (whose Settings() is process-wide cached).
_TMP_DIR = Path(tempfile.mkdtemp(prefix="homeplatform-test-"))
_TMP_DB = _TMP_DIR / "test.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("HOMEPLATFORM_NODE_ID", "pi-control-plane")
os.environ.setdefault("HOMEPLATFORM_WORKSPACE_NODE_ID", "macbook")

from app.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402

_alembic_cfg = AlembicConfig(str(CONTROL_PLANE_ROOT / "alembic.ini"))
_alembic_cfg.set_main_option("script_location", str(CONTROL_PLANE_ROOT / "alembic"))
alembic_command.upgrade(_alembic_cfg, "head")

from app.db import SessionLocal  # noqa: E402
from app.models import CommandRecord, NodeRecord, ProjectRecord, ReconciliationItemRecord  # noqa: E402


@pytest_asyncio.fixture
async def session():
    async with SessionLocal() as db_session:
        # Clean slate per test: one shared sqlite file across the whole
        # session, so tests must not see each other's rows.
        for model in (ReconciliationItemRecord, ProjectRecord, CommandRecord, NodeRecord):
            await db_session.execute(model.__table__.delete())
        await db_session.commit()
        yield db_session


@pytest.fixture
def anyio_backend():
    return "asyncio"
