from __future__ import annotations

from typing import Annotated, Literal, Union

import pytest
import yaml
from pydantic import BaseModel, Field

from fluxconf import ConfigIO, VersionedBaseModel


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class SimpleConfig(BaseModel):
    name: str = "default"
    enabled: bool = True
    count: int = 0
    version: str = "0.0.0"


class NestedInner(BaseModel):
    mode: Literal["fast"] = "fast"
    value: int = 10


class NestedConfig(BaseModel):
    name: str = "test"
    inner: NestedInner = Field(default_factory=NestedInner)
    version: str = "0.0.0"


class CatConfig(BaseModel):
    kind: Literal["cat"] = "cat"
    indoor: bool = True


class DogConfig(BaseModel):
    kind: Literal["dog"] = "dog"
    breed: str = "labrador"


class PetOwnerConfig(BaseModel):
    name: str = "owner"
    pet: Annotated[Union[CatConfig, DogConfig], Field(discriminator="kind")] = Field(
        default_factory=CatConfig
    )
    version: str = "0.0.0"


# ---------------------------------------------------------------------------
# ConfigIO subclasses for testing
# ---------------------------------------------------------------------------


class SimpleConfigIO(ConfigIO[SimpleConfig]):
    file_name = "simple.yml"
    config_type = SimpleConfig
    always_include_fields = ["version"]


class NestedConfigIO(ConfigIO[NestedConfig]):
    file_name = "nested.yml"
    config_type = NestedConfig


class SchemaConfigIO(ConfigIO[SimpleConfig]):
    file_name = "with_schema.yml"
    config_type = SimpleConfig
    schema_url = "https://example.com/schema.json"


class MigratingConfig(VersionedBaseModel):
    name: str = "default"
    enabled: bool = True


class MigratingConfigIO(ConfigIO[MigratingConfig]):
    file_name = "migrating.yml"
    config_type = MigratingConfig
    migrations = {
        "1_ensure_name": lambda data: {**data, "name": data.get("name", "default")},
        "2_rename_active": lambda data: {
            k: v
            for k, v in {**data, "enabled": data.get("active", data.get("enabled", True))}.items()
            if k != "active"
        },
    }


class PetConfigIO(ConfigIO[PetOwnerConfig]):
    file_name = "pets.yml"
    config_type = PetOwnerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path):
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: read/write round-trip
# ---------------------------------------------------------------------------


class TestReadWriteRoundTrip:
    def test_basic_round_trip(self, config_dir):
        io = SimpleConfigIO(config_dir)
        original = SimpleConfig(name="hello", enabled=False, count=42, version="1.0.0")
        io.write(original)

        loaded = io.read()
        assert loaded.name == "hello"
        assert loaded.enabled is False
        assert loaded.count == 42
        assert loaded.version == "1.0.0"

    def test_write_creates_parent_directories(self, config_dir):
        nested_dir = config_dir / "a" / "b" / "c"
        io = SimpleConfigIO(nested_dir)
        io.write(SimpleConfig(version="1.0.0"))

        assert io.get_path().exists()

    def test_exclude_defaults_by_default(self, config_dir):
        io = SimpleConfigIO(config_dir)
        config = SimpleConfig(name="custom", version="1.0.0")
        io.write(config)

        raw = io._read_raw()
        # "name" is non-default so it should be present
        assert raw["name"] == "custom"
        # "enabled" and "count" are defaults so should be absent
        assert "enabled" not in raw
        assert "count" not in raw

    def test_include_defaults(self, config_dir):
        io = SimpleConfigIO(config_dir)
        config = SimpleConfig(name="custom", version="1.0.0")
        io.write(config, include_defaults=True)

        raw = io._read_raw()
        assert raw["enabled"] is True
        assert raw["count"] == 0

    def test_get_path(self, config_dir):
        io = SimpleConfigIO(config_dir)
        assert io.get_path() == config_dir / "simple.yml"

    def test_read_nonexistent_raises(self, config_dir):
        io = SimpleConfigIO(config_dir)
        with pytest.raises(FileNotFoundError):
            io.read()


# ---------------------------------------------------------------------------
# Tests: migration on read
# ---------------------------------------------------------------------------


class TestMigrationOnRead:
    def test_migration_applied_on_read(self, config_dir):
        """Legacy config with 'active' field gets migrated to 'enabled'."""
        io = MigratingConfigIO(config_dir)
        path = io.get_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write a legacy config with no version and the old field name
        old_data = {"name": "test", "active": False}
        with open(path, "w") as f:
            yaml.dump(old_data, f)

        config = io.read()
        assert config.enabled is False
        assert config.version == 2  # migrated to latest

        # File should have been written back with migrated data
        raw = io._read_raw()
        assert "active" not in raw
        assert raw["enabled"] is False

    def test_no_writeback_when_no_migration_needed(self, config_dir):
        """If data is already at target version, no writeback should occur."""
        io = MigratingConfigIO(config_dir)
        path = io.get_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        current_data = {"name": "test", "enabled": True, "version": 2}
        with open(path, "w") as f:
            yaml.dump(current_data, f)

        mtime_before = path.stat().st_mtime
        io.read()
        mtime_after = path.stat().st_mtime

        assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# Tests: always_include_fields
# ---------------------------------------------------------------------------


class TestAlwaysIncludeFields:
    def test_version_included_even_at_default(self, config_dir):
        """The 'version' field should always appear in output when listed in always_include_fields."""
        io = SimpleConfigIO(config_dir)
        # version="0.0.0" matches the default, but should still be in output
        config = SimpleConfig(name="test", version="0.0.0")
        io.write(config)

        raw = io._read_raw()
        assert "version" in raw
        assert raw["version"] == "0.0.0"

    def test_version_included_when_non_default(self, config_dir):
        io = SimpleConfigIO(config_dir)
        config = SimpleConfig(name="test", version="1.0.0")
        io.write(config)

        raw = io._read_raw()
        assert raw["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# Tests: literal field restoration
# ---------------------------------------------------------------------------


class TestLiteralFieldRestoration:
    def test_literal_field_in_nested_model(self, config_dir):
        """Literal 'mode' in nested model should survive exclude_defaults."""
        io = NestedConfigIO(config_dir)
        config = NestedConfig(name="custom")
        io.write(config)

        raw = io._read_raw()
        assert raw["inner"]["mode"] == "fast"

    def test_discriminator_field_restored(self, config_dir):
        """Discriminator 'kind' should be present after exclude_defaults serialisation."""
        io = PetConfigIO(config_dir)
        config = PetOwnerConfig(name="alice", pet=DogConfig(breed="poodle"))
        io.write(config)

        raw = io._read_raw()
        assert raw["pet"]["kind"] == "dog"
        assert raw["pet"]["breed"] == "poodle"

    def test_round_trip_with_discriminated_union(self, config_dir):
        io = PetConfigIO(config_dir)
        original = PetOwnerConfig(name="bob", pet=CatConfig(indoor=False))
        io.write(original)

        loaded = io.read()
        assert isinstance(loaded.pet, CatConfig)
        assert loaded.pet.indoor is False


# ---------------------------------------------------------------------------
# Tests: schema header
# ---------------------------------------------------------------------------


class TestSchemaHeader:
    def test_schema_url_in_yaml_output(self, config_dir):
        io = SchemaConfigIO(config_dir)
        io.write(SimpleConfig(name="test"))

        content = io.get_path().read_text()
        assert "# yaml-language-server: $schema=https://example.com/schema.json" in content

    def test_no_schema_header_when_empty(self, config_dir):
        io = SimpleConfigIO(config_dir)
        io.write(SimpleConfig(name="test", version="1.0.0"))

        content = io.get_path().read_text()
        assert "yaml-language-server" not in content
