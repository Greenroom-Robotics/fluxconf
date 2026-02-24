from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]
Migrations = dict[str, MigrationFn]


class VersionedBaseModel(BaseModel):
    """Pydantic base model that includes a ``version`` field.

    Inherit from this instead of ``BaseModel`` when using fluxconf migrations
    so that the migration version is preserved when the config is written back
    to disk via :meth:`ConfigIO.write`.
    """

    version: int = 0


def _migration_prefix(key: str) -> int:
    """Return the integer prefix from a migration key like '1_description'."""
    return int(key.split("_", 1)[0])


class MigrationError(Exception):
    """Raised when a migration function fails.

    Attributes:
        last_successful_migration: The version of the last migration that completed
            successfully, or the stored version if no migrations succeeded.
        original_error: The original exception that caused the failure.
    """

    def __init__(self, message: str, last_successful_migration: int, original_error: Exception):
        super().__init__(message)
        self.last_successful_migration = last_successful_migration
        self.original_error = original_error


def run_migrations(
    data: dict[str, Any],
    migrations: Migrations,
    target_version: int | None = None,
    version_field: str = "version",
) -> dict[str, Any]:
    """Run migrations on a config dict from its stored version up to target_version.

    Migrations are keyed by strings of the form ``"N_description"`` (e.g.
    ``"1_add_roles"``). Only the integer prefix participates in ordering and is stored
    in the config file. Only migrations where ``stored < prefix <= target`` are applied,
    in ascending prefix order.

    Args:
        data: The raw config dict (will not be mutated).
        migrations: Mapping of ``"N_description"`` keys to migration functions.
        target_version: The version to migrate up to (inclusive). Defaults to the maximum
            prefix found in *migrations*, or ``0`` if *migrations* is empty.
        version_field: The key in *data* that stores the current version.

    Returns:
        A new dict with all applicable migrations applied and *version_field* set to
        *target*.

    Raises:
        ValueError: If the stored version is ahead of the latest known migration.
        MigrationError: If a migration function raises. The error carries
            ``last_successful_migration`` so callers can inspect rollback state.
    """
    data = deepcopy(data)
    stored: int = data.get(version_field, 0)
    target: int = (
        target_version
        if target_version is not None
        else (max(_migration_prefix(k) for k in migrations) if migrations else 0)
    )

    if stored > target:
        raise ValueError(
            f"Stored version {stored} is ahead of the latest known migration {target}."
            " The config file may have been written by a newer version of the software."
        )

    applicable = sorted(
        [(key, fn) for key, fn in migrations.items() if stored < _migration_prefix(key) <= target],
        key=lambda item: _migration_prefix(item[0]),
    )

    last_successful: int = stored
    for key, fn in applicable:
        try:
            data = fn(data)
            last_successful = _migration_prefix(key)
        except Exception as exc:
            raise MigrationError(
                f"Migration {key!r} failed: {exc}",
                last_successful_migration=last_successful,
                original_error=exc,
            ) from exc

    data[version_field] = target
    return data


def load_migrations_from_dir(directory: Path | str) -> Migrations:
    """Load migration functions from a directory of ``N_description.py`` files.

    Each file must define a top-level ``migrate(data: dict) -> dict`` function.
    Files whose stem starts with ``_`` or whose prefix is not a valid integer
    are silently skipped (allowing helper modules to coexist in the directory).

    Raises:
        FileNotFoundError: If *directory* does not exist or is not a directory.
        ValueError: If a matching file is missing a callable ``migrate`` attribute.
    """
    import importlib.util

    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations_dir does not exist or is not a directory: {directory}")

    migrations: Migrations = {}

    for path in sorted(directory.iterdir()):
        if path.suffix != ".py":
            continue
        stem = path.stem
        if stem.startswith("_"):
            continue
        # Skip files without an integer prefix (e.g. helper modules)
        prefix_str = stem.split("_", 1)[0]
        if not prefix_str.isdigit():
            continue

        spec = importlib.util.spec_from_file_location(stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load migration file: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        migrate_fn = getattr(module, "migrate", None)
        if migrate_fn is None:
            raise ValueError(f"Migration file {path} does not define a 'migrate' function.")
        if not callable(migrate_fn):
            raise TypeError(f"Migration file {path} defines 'migrate' but it is not callable.")

        migrations[stem] = migrate_fn

    return migrations
