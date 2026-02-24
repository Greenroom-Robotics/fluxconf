from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from packaging.version import Version

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]
Migrations = dict[str, MigrationFn]


class MigrationError(Exception):
    """Raised when a migration function fails.

    Attributes:
        last_successful_version: The version of the last migration that completed successfully,
            or the stored version if no migrations succeeded.
        original_error: The original exception that caused the failure.
    """

    def __init__(self, message: str, last_successful_version: str, original_error: Exception):
        super().__init__(message)
        self.last_successful_version = last_successful_version
        self.original_error = original_error


def run_migrations(
    data: dict[str, Any],
    migrations: Migrations,
    target_version: str,
    version_field: str = "version",
) -> dict[str, Any]:
    """Run migrations on a config dict from its stored version up to target_version.

    Migrations are keyed by the version they migrate *to*. Only migrations where
    ``stored_version < migration_version <= target_version`` are applied, in ascending
    version order. A deepcopy snapshot is taken after each successful migration so that
    failures roll back to the last good state.

    Args:
        data: The raw config dict (will not be mutated).
        migrations: Mapping of version strings to migration functions.
        target_version: The version to migrate up to (inclusive).
        version_field: The key in *data* that stores the current version.

    Returns:
        A new dict with all applicable migrations applied and *version_field* set to
        *target_version*.

    Raises:
        MigrationError: If a migration function raises. The error carries
            ``last_successful_version`` so callers can inspect rollback state.
    """
    data = deepcopy(data)
    stored_version = Version(data.get(version_field, "0.0.0"))
    target = Version(target_version)

    # Filter and sort applicable migrations
    applicable: list[tuple[Version, MigrationFn]] = []
    for ver_str, fn in migrations.items():
        ver = Version(ver_str)
        if stored_version < ver <= target:
            applicable.append((ver, fn))
    applicable.sort(key=lambda item: item[0])

    if not applicable:
        data[version_field] = target_version
        return data

    last_successful_version = str(stored_version)

    for ver, fn in applicable:
        try:
            data = fn(data)
            last_successful_version = str(ver)
        except Exception as exc:
            raise MigrationError(
                f"Migration to {ver} failed: {exc}",
                last_successful_version=last_successful_version,
                original_error=exc,
            ) from exc

    data[version_field] = target_version
    return data
