# fluxconf

[![Tests](https://github.com/Greenroom-Robotics/fluxconf/actions/workflows/tests.yml/badge.svg)](https://github.com/Greenroom-Robotics/fluxconf/actions/workflows/tests.yml)
[![PyPI version](https://badge.fury.io/py/fluxconf.svg)](https://badge.fury.io/py/fluxconf)
![Supported versions](https://img.shields.io/badge/python-3.10+-blue.svg)
[![license](https://img.shields.io/github/license/Greenroom-Robotics/fluxconf.svg)](https://github.com/Greenroom-Robotics/fluxconf/blob/master/LICENSE)

File-backed Pydantic configuration with migration support.

## Installation

```sh
pip install fluxconf
```

or with [uv](https://docs.astral.sh/uv/):

```sh
uv add fluxconf
```

## Usage

### ConfigIO

`ConfigIO` is a generic base class for reading and writing YAML-backed Pydantic models. Subclass it, set `file_name` and `config_type`, and you get type-safe read/write with automatic migration support.

```python
from pydantic import BaseModel
from fluxconf import ConfigIO

class AppConfig(BaseModel):
    name: str = "my-app"
    debug: bool = False
    version: str = "0.0.0"

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig
    config_version = "1.0.0"
    always_include_fields = ["version"]

# Write
io = AppConfigIO("~/.config/my-app")
io.write(AppConfig(name="my-app", debug=True, version="1.0.0"))

# Read
config = io.read()
```

### Migrations

Define migration functions keyed by the version they migrate **to**. Migrations run automatically on `read()` when the stored version is behind `config_version`.

```python
from fluxconf import ConfigIO, run_migrations

def migrate_to_1_1_0(data: dict) -> dict:
    """Rename 'use_foo' → 'foo_enabled'."""
    if "use_foo" in data:
        data["foo_enabled"] = data.pop("use_foo")
    return data

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig
    config_version = "1.1.0"
    always_include_fields = ["version"]
    migrations = {
        "1.1.0": migrate_to_1_1_0,
    }
```

When `io.read()` encounters a file at version `1.0.0`, it runs `migrate_to_1_1_0`, writes the migrated data back to disk, and returns the parsed model.

If a migration fails, a `MigrationError` is raised with the `last_successful_version` so you can inspect what went wrong.

## License

[MIT License](https://github.com/Greenroom-Robotics/fluxconf/blob/master/LICENSE)
