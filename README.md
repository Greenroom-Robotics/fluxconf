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

## Quick start

`ConfigIO` is a generic base class for reading and writing YAML-backed Pydantic models. Subclass it, set `file_name` and `config_type`, and you get type-safe read/write out of the box.

```python
from pydantic import BaseModel
from fluxconf import ConfigIO

class AppConfig(BaseModel):
    name: str = "my-app"
    debug: bool = False

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig

io = AppConfigIO("~/.config/my-app")
io.write(AppConfig(name="my-app", debug=True))
config = io.read()  # AppConfig(name='my-app', debug=True)
```

## Migrations

Migrations transform stored configuration data when your schema evolves. Instead of breaking existing config files, you define migration steps that update old data to match the new schema.

To use migrations, inherit from `VersionedBaseModel` instead of Pydantic's `BaseModel`. This adds a `version` field that tracks which migrations have been applied.

Migration keys follow the `"N_description"` format — the integer prefix determines execution order and is stored as the `version` in the config file. On `read()`, any pending migrations run automatically and the file is updated on disk.

### JSON Patch migrations

The simplest approach: declare [JSON Patch (RFC 6902)](https://datatracker.ietf.org/doc/html/rfc6902) operations directly. No Python functions needed.

```python
from fluxconf import ConfigIO, VersionedBaseModel

class ServerConfig(VersionedBaseModel):
    host: str = "localhost"
    port: int = 8080

class ServerConfigIO(ConfigIO[ServerConfig]):
    file_name = "server.yml"
    config_type = ServerConfig
    migrations = {
        "1_rename_host": [
            {"op": "move", "from": "/hostname", "path": "/host"},
        ],
        "2_add_port": [
            {"op": "add", "path": "/port", "value": 8080},
        ],
    }
```

Supported operations: `add`, `remove`, `replace`, `move`, `copy`, and `test`.

### Python function migrations

When you need conditional logic or complex transforms, use a Python function. Each function receives the raw config dict and must return the updated dict.

```python
from fluxconf import ConfigIO, VersionedBaseModel

class UserConfig(VersionedBaseModel):
    full_name: str = ""
    email: str = ""

def merge_name_fields(data: dict) -> dict:
    first = data.pop("first_name", "")
    last = data.pop("last_name", "")
    if first or last:
        data["full_name"] = f"{first} {last}".strip()
    return data

class UserConfigIO(ConfigIO[UserConfig]):
    file_name = "user.yml"
    config_type = UserConfig
    migrations = {
        "1_merge_name": merge_name_fields,
    }
```

Python functions and JSON Patches can be mixed freely in the same `migrations` dict.

### Directory-based migrations

For projects with many migrations, store each one as a separate file in a directory instead of inlining them all in the class definition.

```
myapp/migrations/
    1_rename_host.json
    2_merge_name.py
    3_add_defaults.py
    _helpers.py           # skipped (starts with _)
```

Only files with an integer prefix are loaded. Files starting with `_` or without an integer prefix are silently skipped, so helper modules can live alongside migration files.

**`.json` files** contain a JSON array of patch operations:

`myapp/migrations/1_rename_host.json`
```json
[
    {"op": "move", "from": "/hostname", "path": "/host"}
]
```

**`.py` files with a `patch` attribute** are equivalent to `.json` files but written in Python:

`myapp/migrations/3_add_defaults.py`
```python
patch = [
    {"op": "add", "path": "/port", "value": 8080},
    {"op": "add", "path": "/retries", "value": 3},
]
```

**`.py` files with a `migrate` function** offer full flexibility:

`myapp/migrations/2_merge_name.py`
```python
def migrate(data: dict) -> dict:
    first = data.pop("first_name", "")
    last = data.pop("last_name", "")
    if first or last:
        data["full_name"] = f"{first} {last}".strip()
    return data
```

If a `.py` file defines both `migrate` and `patch`, the `migrate` function takes precedence.

Point `migrations_dir` at the directory to load them:

```python
from pathlib import Path
from fluxconf import ConfigIO, VersionedBaseModel

class AppConfigIO(ConfigIO[AppConfig]):
    file_name = "app.yml"
    config_type = AppConfig
    migrations_dir = Path(__file__).parent / "migrations"
```

`migrations` and `migrations_dir` can be used together — fluxconf merges them, raising `ValueError` on key collisions.

### Error handling

**`MigrationError`** is raised when a migration function or patch fails. It carries two attributes:

- `last_successful_migration` — the version of the last migration that completed successfully (or the stored version if none succeeded)
- `original_error` — the underlying exception

**`ValueError`** is raised when the stored version is ahead of the latest known migration. This typically means the config file was written by a newer version of the software than the one currently running.

## License

[MIT License](https://github.com/Greenroom-Robotics/fluxconf/blob/master/LICENSE)
