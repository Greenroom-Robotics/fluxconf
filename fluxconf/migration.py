from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonpatch as jsonpatch_lib
from pydantic import BaseModel

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]
JsonPatchOp = dict[str, Any]
JsonPatch = list[JsonPatchOp]
Migration = MigrationFn | JsonPatch
Migrations = dict[str, Migration]


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


def _apply_json_patch(data: dict[str, Any], patch: JsonPatch) -> dict[str, Any]:
    """Apply a JSON Patch (RFC 6902) to *data* and return the result."""
    result: dict[str, Any] = jsonpatch_lib.JsonPatch(patch).apply(data)
    return result


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
    in the config file. Each migration value can be either a callable
    ``(dict) -> dict`` or a JSON Patch (list of RFC 6902 operation dicts).

    Only migrations where ``stored < prefix <= target`` are applied,
    in ascending prefix order.

    Args:
        data: The raw config dict (will not be mutated).
        migrations: Mapping of ``"N_description"`` keys to migration callables or
            JSON Patch operation lists.
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
        [
            (key, migration)
            for key, migration in migrations.items()
            if stored < _migration_prefix(key) <= target
        ],
        key=lambda item: _migration_prefix(item[0]),
    )

    last_successful: int = stored
    for key, migration in applicable:
        if not callable(migration) and not isinstance(migration, list):
            exc = TypeError(
                f"Migration {key!r} must be a callable or a list of JSON Patch operations,"
                f" got {type(migration).__name__}"
            )
            raise MigrationError(
                f"Migration {key!r} failed: {exc}",
                last_successful_migration=last_successful,
                original_error=exc,
            )
        try:
            if callable(migration):
                data = migration(data)
            else:
                data = _apply_json_patch(data, migration)
            last_successful = _migration_prefix(key)
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(
                f"Migration {key!r} failed: {exc}",
                last_successful_migration=last_successful,
                original_error=exc,
            ) from exc

    data[version_field] = target
    return data


def load_migrations_from_dir(directory: Path | str) -> Migrations:
    """Load migrations from a directory of ``N_description.py`` or ``N_description.json`` files.

    Python files must define either a top-level ``migrate(data: dict) -> dict`` function
    or a ``patch`` attribute containing a list of JSON Patch operations. If both exist,
    ``migrate`` takes precedence.

    JSON files must contain a top-level JSON array of RFC 6902 patch operations.

    Files whose stem starts with ``_`` or whose prefix is not a valid integer
    are silently skipped (allowing helper modules to coexist in the directory).

    Raises:
        FileNotFoundError: If *directory* does not exist or is not a directory.
        ValueError: If a matching ``.py`` file defines neither ``migrate`` nor ``patch``.
        TypeError: If a ``patch`` attribute or ``.json`` file does not contain a list.
        ValueError: If two files resolve to the same migration key (e.g. ``1_foo.py``
            and ``1_foo.json``).
    """
    import importlib.util

    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations_dir does not exist or is not a directory: {directory}")

    migrations: Migrations = {}

    for path in sorted(directory.iterdir()):
        if path.suffix not in (".py", ".json"):
            continue
        stem = path.stem
        if stem.startswith("_"):
            continue
        # Skip files without an integer prefix (e.g. helper modules)
        prefix_str = stem.split("_", 1)[0]
        if not prefix_str.isdigit():
            continue

        if stem in migrations:
            raise ValueError(
                f"Duplicate migration key {stem!r}: multiple files resolve to the same key"
            )

        if path.suffix == ".json":
            with open(path) as f:
                patch = json.load(f)
            if not isinstance(patch, list):
                raise TypeError(
                    f"Migration file {path} must contain a JSON array of patch operations,"
                    f" got {type(patch).__name__}"
                )
            migrations[stem] = patch

        else:  # .py
            spec = importlib.util.spec_from_file_location(stem, path)
            if spec is None or spec.loader is None:
                raise ValueError(f"Cannot load migration file: {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            migrate_fn = getattr(module, "migrate", None)
            patch_attr = getattr(module, "patch", None)

            if migrate_fn is not None:
                if not callable(migrate_fn):
                    raise TypeError(
                        f"Migration file {path} defines 'migrate' but it is not callable."
                    )
                migrations[stem] = migrate_fn
            elif patch_attr is not None:
                if not isinstance(patch_attr, list):
                    raise TypeError(
                        f"Migration file {path} defines 'patch' but it is not a list,"
                        f" got {type(patch_attr).__name__}"
                    )
                migrations[stem] = patch_attr
            else:
                raise ValueError(
                    f"Migration file {path} defines neither a 'migrate' function"
                    " nor a 'patch' list."
                )

    return migrations
