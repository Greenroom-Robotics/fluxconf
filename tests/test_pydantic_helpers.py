from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from fluxconf.pydantic_helpers import (
    add_literal_fields_to_dict,
    add_persistent_fields_to_dict,
)


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------
class PlainNested(BaseModel):
    """A nested model with no Literal/discriminator fields."""

    host: str = "localhost"
    port: int = 8080


class Endpoint(BaseModel):
    address: str = "127.0.0.1"
    port: int = 11811


class DeepNested(BaseModel):
    """Nested models all the way down, none carrying a Literal."""

    endpoint: Endpoint = Field(default_factory=Endpoint)
    extra: PlainNested = Field(default_factory=PlainNested)


class LiteralNested(BaseModel):
    mode: Literal["fast", "slow"] = "fast"
    value: int = 10


class Cat(BaseModel):
    kind: Literal["cat"] = "cat"
    indoor: bool = True


class Dog(BaseModel):
    kind: Literal["dog"] = "dog"
    breed: str = "labrador"


class Owner(BaseModel):
    name: str = "owner"
    pet: Annotated[Union[Cat, Dog], Field(discriminator="kind")] = Field(default_factory=Cat)


class Config(BaseModel):
    """Top-level config mixing plain-nested, deep-nested and literal-nested fields."""

    name: str
    plain: PlainNested = Field(default_factory=PlainNested)
    deep: DeepNested = Field(default_factory=DeepNested)
    literal: LiteralNested = Field(default_factory=LiteralNested)


def _dumped(model: BaseModel) -> dict:
    """Round-trip exactly as ConfigIO.serialise does (json-mode, defaults excluded)."""
    return model.model_dump(mode="json", exclude_defaults=True)


# ---------------------------------------------------------------------------
# Regression: no empty-dict artifacts for all-default nested models
# ---------------------------------------------------------------------------
class TestNoEmptyDictArtifacts:
    def test_all_default_nested_models_are_not_re_added(self):
        """Nested models with no Literal fields that were dropped as default must
        not be re-inserted as empty ``{}`` artifacts -- while a nested model that
        does carry a Literal is still restored."""
        config = Config(name="custom")
        data = _dumped(config)
        assert data == {"name": "custom"}  # only the non-default field

        add_literal_fields_to_dict(config, data)

        # `plain` and `deep` carry no Literal -> pruned (no {} artifacts).
        # `literal` carries a Literal mode -> restored.
        assert data == {"name": "custom", "literal": {"mode": "fast"}}

    def test_deeply_nested_all_default_pruned(self):
        config = DeepNested()
        data = _dumped(config)  # {} - everything is default
        add_literal_fields_to_dict(config, data)
        assert data == {}  # no endpoint:{} / extra:{} shells

    def test_no_empty_values_anywhere(self):
        config = Config(name="x")
        data = _dumped(config)
        add_literal_fields_to_dict(config, data)

        def assert_no_empty(d):
            for key, value in d.items():
                assert value != {}, f"empty dict left at {key!r}"
                if isinstance(value, dict):
                    assert_no_empty(value)

        assert_no_empty(data)


# ---------------------------------------------------------------------------
# Preserved behaviour: Literal / discriminator restoration still works
# ---------------------------------------------------------------------------
class TestLiteralRestorationStillWorks:
    def test_top_level_literal_restored(self):
        config = LiteralNested(value=99)  # mode left at its "fast" default
        data = _dumped(config)
        assert "mode" not in data  # stripped by exclude_defaults
        add_literal_fields_to_dict(config, data)
        assert data["mode"] == "fast"  # restored
        assert data["value"] == 99

    def test_nested_literal_restored_and_parent_kept(self):
        """A nested model IS kept when it carries a Literal, even at all-defaults."""
        config = Config(name="x")  # literal.mode is default "fast"
        data = _dumped(config)
        add_literal_fields_to_dict(config, data)
        assert data["literal"] == {"mode": "fast"}

    def test_discriminator_restored(self):
        owner = Owner(name="alice", pet=Dog(breed="poodle"))
        data = _dumped(owner)
        add_literal_fields_to_dict(owner, data)
        assert data["pet"]["kind"] == "dog"
        assert data["pet"]["breed"] == "poodle"

    def test_discriminator_restored_for_all_default_variant(self):
        """Even an all-default discriminated pet keeps its discriminator."""
        owner = Owner(name="bob")  # pet defaults to Cat(indoor=True)
        data = _dumped(owner)
        add_literal_fields_to_dict(owner, data)
        assert data["pet"] == {"kind": "cat"}


# ---------------------------------------------------------------------------
# Preserved behaviour: existing non-default content is never dropped
# ---------------------------------------------------------------------------
class TestExistingContentPreserved:
    def test_non_default_nested_content_kept(self):
        config = Config(name="x", plain=PlainNested(port=9999))
        data = _dumped(config)
        assert data["plain"] == {"port": 9999}
        add_literal_fields_to_dict(config, data)
        # Still present and unchanged (must not be deleted by the empty-prune).
        assert data["plain"] == {"port": 9999}

    def test_partial_deep_content_kept(self):
        config = DeepNested(endpoint=Endpoint(address="10.0.0.1"))
        data = _dumped(config)
        assert data == {"endpoint": {"address": "10.0.0.1"}}
        add_literal_fields_to_dict(config, data)
        assert data == {"endpoint": {"address": "10.0.0.1"}}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_non_model_object_is_noop(self):
        data: dict = {}
        add_literal_fields_to_dict("not a model", data)
        add_literal_fields_to_dict(42, data)
        assert data == {}

    def test_optional_nested_none_is_skipped(self):
        class WithOptional(BaseModel):
            maybe: PlainNested | None = None

        config = WithOptional()
        data = _dumped(config)
        add_literal_fields_to_dict(config, data)
        assert data == {}  # None field adds nothing

    def test_idempotent(self):
        config = Owner(name="alice", pet=Dog(breed="poodle"))
        data = _dumped(config)
        add_literal_fields_to_dict(config, data)
        once = {**data}
        add_literal_fields_to_dict(config, data)
        assert data == once


# ---------------------------------------------------------------------------
# add_persistent_fields_to_dict (unchanged, covered for completeness)
# ---------------------------------------------------------------------------
class TestPersistentFields:
    def test_forces_default_field_into_output(self):
        config = Config(name="x")  # everything else default
        data = _dumped(config)
        add_persistent_fields_to_dict(config, data, ["name"])
        assert data["name"] == "x"

    def test_missing_field_ignored(self):
        config = Config(name="x")
        data = _dumped(config)
        add_persistent_fields_to_dict(config, data, ["does_not_exist"])
        assert "does_not_exist" not in data
