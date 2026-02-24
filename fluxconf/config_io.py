from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from fluxconf.migration import (
    Migrations,
    VersionedBaseModel,
    _migration_prefix,
    load_migrations_from_dir,
    run_migrations,
)
from fluxconf.pydantic_helpers import add_literal_fields_to_dict, add_persistent_fields_to_dict
from fluxconf.yaml_helpers import YamlDumper, config_dict_to_yaml

T = TypeVar("T", bound=BaseModel)


class ConfigIO(Generic[T]):
    """File-backed configuration manager with migration support.

    Subclasses must set ``file_name`` and ``config_type`` as class variables.

    Example::

        class LookoutConfigIO(ConfigIO[LookoutConfig]):
            file_name = "lookout.yml"
            config_type = LookoutConfig
            migrations_dir = Path(__file__).parent / "migrations"
    """

    file_name: ClassVar[str]
    config_type: ClassVar[type]

    schema_url: ClassVar[str] = ""
    migrations: ClassVar[Migrations] = {}
    migrations_dir: ClassVar[Path | str | None] = None
    always_include_fields: ClassVar[list[str]] = []

    def __init__(self, config_directory: str | Path) -> None:
        if str(config_directory).startswith("~"):
            self.config_directory = Path(config_directory).expanduser()
        else:
            self.config_directory = Path(config_directory)

    def get_path(self) -> Path:
        """Return the full path to the configuration file."""
        return self.config_directory / self.file_name

    def parse(self, config: dict[str, Any]) -> T:
        """Parse a raw dict into the typed config model.

        Override this for custom parsing (e.g. variant loading).
        """
        return self.config_type(**(config or {}))  # type: ignore[no-any-return]

    def _latest_version(self) -> int:
        """Return the highest migration version, or 0 if there are no migrations."""
        effective = self._effective_migrations()
        if not effective:
            return 0
        return max(_migration_prefix(k) for k in effective)

    def _effective_migrations(self) -> Migrations:
        """Return merged migrations from inline dict and migrations_dir."""
        effective: Migrations = dict(self.migrations)
        if self.migrations_dir is not None:
            dir_migrations = load_migrations_from_dir(self.migrations_dir)
            collisions = effective.keys() & dir_migrations.keys()
            if collisions:
                raise ValueError(
                    f"Migration key collision between inline migrations and "
                    f"migrations_dir: {sorted(collisions)}"
                )
            effective.update(dir_migrations)
        return effective

    def read(self) -> T:
        """Read the config file, run any pending migrations, and return the parsed model.

        If migrations are applied the file is written back to disk with the updated data.
        """
        raw = self._read_raw()
        effective = self._effective_migrations()
        if effective:
            migrated = run_migrations(raw, effective)
            if migrated != raw:
                self._write_raw(migrated)
                raw = migrated

        try:
            return self.parse(raw)
        except ValidationError as exc:
            path = self.get_path()
            raise ValueError(f"Failed to parse {path}: {exc}") from exc

    def write(self, config: T, include_defaults: bool = False) -> None:
        """Serialise *config* and write it to disk as YAML."""
        if isinstance(config, VersionedBaseModel):
            latest = self._latest_version()
            if config.version < latest:
                config.version = latest

        path = self.get_path()
        os.makedirs(path.parent, exist_ok=True)

        config_dict: dict[str, Any] = config.model_dump(
            mode="json", exclude_defaults=not include_defaults
        )

        if not include_defaults:
            add_literal_fields_to_dict(config, config_dict)

        if self.always_include_fields:
            add_persistent_fields_to_dict(config, config_dict, self.always_include_fields)

        data = config_dict_to_yaml(config_dict, schema_url=self.schema_url or None)
        with open(path, "w") as stream:
            stream.write(data)

    def serialise(self, config: T) -> str:
        """Serialise *config* to a YAML string without writing to disk."""
        config_dict: dict[str, Any] = config.model_dump(mode="json")
        return yaml.dump(config_dict, Dumper=YamlDumper, sort_keys=True)

    # -- Low-level helpers ---------------------------------------------------

    def _read_raw(self) -> dict[str, Any]:
        """Read the YAML file and return the raw dict."""
        path = self.get_path()
        with open(path) as stream:
            result = yaml.safe_load(stream)
        return result or {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        """Write a raw dict to disk as YAML (used for migration write-back)."""
        path = self.get_path()
        os.makedirs(path.parent, exist_ok=True)
        content = config_dict_to_yaml(data, schema_url=self.schema_url or None)
        with open(path, "w") as stream:
            stream.write(content)
