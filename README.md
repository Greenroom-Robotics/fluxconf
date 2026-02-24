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

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig

# Write
io = AppConfigIO("~/.config/my-app")
io.write(AppConfig(name="my-app", debug=True))

# Read
config = io.read()
```

### Migrations

Define migration functions keyed by the integer version they migrate **to**. Migrations run automatically on `read()` when the stored version is behind the latest known migration.

Inherit from `VersionedBaseModel` instead of Pydantic's `BaseModel` so that the `version` field is preserved when the config is written back to disk via `write()`:

```python
from fluxconf import ConfigIO, VersionedBaseModel

class AppConfig(VersionedBaseModel):
    name: str = "my-app"
    debug: bool = False

def migrate_to_v2(data: dict) -> dict:
    """Rename 'use_foo' → 'foo_enabled'."""
    if "use_foo" in data:
        data["foo_enabled"] = data.pop("use_foo")
    return data

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig
    migrations = {
        "2_rename_foo": migrate_to_v2,
    }
```

Migration keys are strings of the form `"N_description"` — the integer prefix determines ordering and is stored in the config file as `version`.

On `read()`, pending migrations are applied in version order, the result is written back to disk, and the parsed model is returned.

If a migration fails, `MigrationError` is raised with `last_successful_migration` (an `int`). If the stored version is **ahead** of all known migrations, a `ValueError` is raised immediately.

#### Directory-based migrations

For larger migration sets, point `migrations_dir` at a directory of individual `N_description.py` files instead of (or in addition to) the inline `migrations` dict:

```
myapp/migrations/
    1_rename_foo.py
    2_add_bar.py
    _helpers.py          # skipped (starts with _)
```

Each file must define a top-level `migrate(data: dict) -> dict` function:

```python
# myapp/migrations/1_rename_foo.py

def migrate(data: dict) -> dict:
    if "use_foo" in data:
        data["foo_enabled"] = data.pop("use_foo")
    return data
```

```python
from pathlib import Path
from fluxconf import ConfigIO

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig
    migrations_dir = Path(__file__).parent / "migrations"
```

Only `.py` files with an integer prefix are loaded. Files starting with `_` or without an integer prefix are silently skipped, so helper modules can live alongside migration files.

`migrations` and `migrations_dir` can be used together — fluxconf merges them, raising `ValueError` on key collisions.

## License

[MIT License](https://github.com/Greenroom-Robotics/fluxconf/blob/master/LICENSE)
