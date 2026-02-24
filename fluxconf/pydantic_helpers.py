from __future__ import annotations

from typing import Any, Literal, get_origin


def add_literal_fields_to_dict(obj: Any, data: dict[str, Any]) -> None:
    """Restore Literal fields and discriminated-union discriminators into *data*.

    When using ``model_dump(exclude_defaults=True)``, Literal-typed fields and
    discriminator fields are often stripped because their value equals the default.
    This function walks the model tree and re-inserts them so that the serialised
    output always contains the information needed to reconstruct discriminated unions.

    Args:
        obj: A pydantic ``BaseModel`` instance (or any object - non-models are skipped).
        data: The dict produced by ``model_dump()`` that should be patched in-place.
    """
    if not hasattr(obj, "__class__") or not hasattr(obj.__class__, "model_fields"):
        return

    for field_name, field_info in obj.__class__.model_fields.items():
        field_value = getattr(obj, field_name)

        # Direct Literal fields
        if get_origin(field_info.annotation) is Literal:
            data[field_name] = field_value

        # Discriminated union fields
        elif hasattr(field_info, "discriminator") and field_info.discriminator:
            if field_value is not None:
                if field_name not in data:
                    data[field_name] = {}
                discriminator_name = str(field_info.discriminator)
                data[field_name][discriminator_name] = getattr(field_value, discriminator_name)
                add_literal_fields_to_dict(field_value, data[field_name])

        # Nested BaseModel fields
        elif hasattr(field_value, "__class__") and hasattr(field_value.__class__, "model_fields"):
            if field_name not in data:
                data[field_name] = {}
            add_literal_fields_to_dict(field_value, data[field_name])


def add_persistent_fields_to_dict(obj: Any, data: dict[str, Any], field_names: list[str]) -> None:
    """Force specific fields into *data* regardless of whether they match the default.

    This is useful for fields like ``version`` that you always want present in the
    serialised output even when ``exclude_defaults=True`` would normally strip them.

    Args:
        obj: A pydantic ``BaseModel`` instance.
        data: The dict produced by ``model_dump()`` that should be patched in-place.
        field_names: Names of top-level fields to force into *data*.
    """
    for name in field_names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            # Use json-compatible value if available
            if hasattr(obj.__class__, "model_fields") and name in obj.__class__.model_fields:
                json_data = obj.model_dump(mode="json", include={name})
                if name in json_data:
                    data[name] = json_data[name]
                    continue
            data[name] = value
