from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from fluxconf.migration import Migrations, run_migrations
from fluxconf.pydantic_helpers import add_literal_fields_to_dict, add_persistent_fields_to_dict
from fluxconf.yaml_helpers import config_dict_to_yaml

T = TypeVar("T", bound=BaseModel)


class ConfigIO(Generic[T]):
    """File-backed configuration manager with migration support.

    Subclasses must set ``file_name`` and ``config_type`` as class variables.

    Example::

        class LookoutConfigIO(ConfigIO[LookoutConfig]):
            file_name = "lookout.yml"
            config_type = LookoutConfig
            config_version = "1.1.0"
            migrations = {"1.1.0": migrate_to_1_1_0}
    """

    file_name: ClassVar[str]
    config_type: ClassVar[type]

    schema_url: ClassVar[str] = ""
    config_version: ClassVar[str] = "0.0.0"
    migrations: ClassVar[Migrations] = {}
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

    def read(self) -> T:
        """Read the config file, run any pending migrations, and return the parsed model.

        If migrations are applied the file is written back to disk with the updated data.
        """
        raw = self._read_raw()

        if self.migrations and self.config_version != "0.0.0":
            migrated = run_migrations(raw, self.migrations, self.config_version)
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
