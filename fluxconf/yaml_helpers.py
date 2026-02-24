from __future__ import annotations

from typing import Any

import yaml


class YamlDumper(yaml.Dumper):
    """A YAML dumper that shows lists inline if they contain only simple scalars."""

    def represent_sequence(self, tag: str, sequence: Any, flow_style: bool | None = None) -> Any:
        if isinstance(sequence, list) and all(
            not isinstance(item, dict | list) for item in sequence
        ):
            flow_style = True
        return super().represent_sequence(tag, sequence, flow_style)

    def represent_mapping(self, tag: str, mapping: Any, flow_style: bool | None = None) -> Any:
        flow_style = False
        return super().represent_mapping(tag, mapping, flow_style)


def config_dict_to_yaml(config_dict: dict[str, Any], schema_url: str | None = None) -> str:
    """Convert a config dict to a YAML string with an optional schema header.

    Args:
        config_dict: The configuration dictionary to serialise.
        schema_url: If provided, a ``# yaml-language-server`` header is prepended.

    Returns:
        A YAML string, optionally prefixed with a schema comment line.
    """
    body = yaml.dump(config_dict, Dumper=YamlDumper, sort_keys=True)
    if schema_url:
        header = f"# yaml-language-server: $schema={schema_url}"
        return "\n".join([header, body])
    return str(body)
