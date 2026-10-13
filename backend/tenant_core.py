"""Pure tenant authorization policies, not yet wired into production routes."""

from collections.abc import Iterable

PLATFORM_ADMIN_ROLE = "admin"
TENANT_ADMIN_ROLE = "tenant_admin"


def tenant_feature_enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def tenant_access_allowed(
    *,
    feature_enabled: bool,
    actor_role: str,
    actor_tenant_id: int | None,
    resource_tenant_id: int | None,
) -> bool:
    if not feature_enabled:
        return True
    if actor_role == PLATFORM_ADMIN_ROLE:
        return True
    return actor_tenant_id is not None and actor_tenant_id == resource_tenant_id


def effective_modules(
    *,
    feature_enabled: bool,
    actor_role: str,
    user_modules: Iterable[str],
    plan_modules: Iterable[str],
) -> frozenset[str] | None:
    user_permissions = frozenset(user_modules)
    if not feature_enabled:
        return user_permissions
    if actor_role == PLATFORM_ADMIN_ROLE:
        return None
    return user_permissions.intersection(plan_modules)
