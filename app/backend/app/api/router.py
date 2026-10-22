"""Aggregate platform router mounted under the configured API prefix."""

from fastapi import APIRouter

from app.api.admin.router import router as admin_router
from app.api.auth.router import router as auth_router
from app.api.health import router as health_router
from app.api.llm.router import local_router as llm_local_router
from app.api.llm.router import router as llm_router
from app.api.review_runs.router import router as review_runs_router
from app.api.reviews.router import catalog_router as review_catalog_router
from app.api.reviews.router import router as reviews_router
from app.api.rule_set.router import router as rule_set_router
from app.api.scheduled_reviews.router import router as scheduled_reviews_router
from app.api.scheduled_reviews.router import settings_router as schedule_settings_router
from app.api.sql_connection.router import local_router as sql_connection_local_router
from app.api.sql_connection.router import router as sql_connection_router
from app.api.sql_connection.router import stored_router as sql_connection_stored_router
from app.core.config import get_settings

# kt-scaffold:router-imports

router = APIRouter(prefix=get_settings().api_prefix)
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(rule_set_router)
router.include_router(sql_connection_router)
router.include_router(llm_router)
router.include_router(review_catalog_router)
router.include_router(reviews_router)
router.include_router(review_runs_router)
router.include_router(scheduled_reviews_router)
router.include_router(schedule_settings_router)
# kt-scaffold:router-registration


def local_environment_router(api_prefix: str) -> APIRouter:
    """Settings write and test endpoints that exist only in the local environment.

    sql-review 002-sql-server-connection Requirement 5 and 006-llm-connection Requirement 13:
    nonprod never registers this router, so such a request finds no route there.
    """

    local = APIRouter(prefix=api_prefix)
    local.include_router(sql_connection_local_router)
    local.include_router(llm_local_router)
    return local


def stored_sql_connection_router(api_prefix: str) -> APIRouter:
    """SQL connection write and test endpoints of a nonprod that stores the connection.

    sql-review 002-sql-server-connection Requirement 5: registered only when the deployment
    supplies no complete connection and the settings encryption key exists; the super admin alone
    passes their guard.
    """

    stored = APIRouter(prefix=api_prefix)
    stored.include_router(sql_connection_stored_router)
    return stored
