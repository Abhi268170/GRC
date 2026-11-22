"""Import every model module so Base.metadata is complete (used by Alembic)."""

from app.models import assessment, framework, library, master_data, outputs, platform, run, tenancy
from app.models.assessment import *  # noqa: F403
from app.models.base import Base
from app.models.framework import *  # noqa: F403
from app.models.library import *  # noqa: F403
from app.models.master_data import *  # noqa: F403
from app.models.outputs import *  # noqa: F403
from app.models.platform import *  # noqa: F403
from app.models.run import *  # noqa: F403
from app.models.tenancy import *  # noqa: F403

# Which database each table lives in (see TENANT_DATABASE_PLAN.md). Tables in neither set exist
# in both: the library (a company database holds copies of the assessments it has run),
# master data (mirrored), users, jobs, notifications and AI usage.
CONTROL_ONLY_TABLES = frozenset({"tenant", "login_directory"})
TENANT_ONLY_TABLES = frozenset(
    m.__tablename__ for module in (run, outputs) for m in vars(module).values()
    if isinstance(m, type) and issubclass(m, Base) and m is not Base
)

__all__ = ["Base", "assessment", "framework", "library", "master_data", "outputs", "platform", "run", "tenancy"]
