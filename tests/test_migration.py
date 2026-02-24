import json

import pytest

from fluxconf.migration import MigrationError, load_migrations_from_dir, run_migrations


class TestRunMigrations:
    def test_migrations_run_in_version_order(self):
        """Migrations should execute in ascending prefix order regardless of dict ordering."""
        call_order: list[int] = []

        def migrate_1(data):
            call_order.append(1)
            data["a"] = 1
            return data

        def migrate_2(data):
            call_order.append(2)
            data["b"] = 2
            return data

        def migrate_3(data):
            call_order.append(3)
            data["c"] = 3
            return data

        # Deliberately unordered keys
        migrations = {
            "3_third": migrate_3,
            "1_first": migrate_1,
            "2_second": migrate_2,
        }

        result = run_migrations({}, migrations)

        assert call_order == [1, 2, 3]
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3
        assert result["version"] == 3

    def test_skips_already_applied_migrations(self):
        """Migrations at or below the stored version should not run."""
        call_order: list[int] = []

        def migrate_1(data):
            call_order.append(1)
            return data

        def migrate_2(data):
            call_order.append(2)
            data["new_field"] = True
            return data

        def migrate_3(data):
            call_order.append(3)
            return data

        migrations = {
            "1_first": migrate_1,
            "2_second": migrate_2,
            "3_third": migrate_3,
        }

        result = run_migrations({"version": 1}, migrations)

        assert 1 not in call_order
        assert call_order == [2, 3]
        assert result["new_field"] is True
        assert result["version"] == 3

    def test_rollback_on_failure(self):
        """On failure, MigrationError should report the last successful migration."""

        def migrate_1(data):
            data["applied"] = True
            return data

        def migrate_2(data):
            raise RuntimeError("something broke")

        migrations = {
            "1_first": migrate_1,
            "2_second": migrate_2,
        }

        with pytest.raises(MigrationError) as exc_info:
            run_migrations({}, migrations, 2)

        assert exc_info.value.last_successful_migration == 1
        assert isinstance(exc_info.value.original_error, RuntimeError)

    def test_rollback_reports_stored_version_when_first_migration_fails(self):
        """If the very first migration fails, last_successful_migration is the stored version."""

        def migrate_1(data):
            raise ValueError("boom")

        migrations = {"1_first": migrate_1}

        with pytest.raises(MigrationError) as exc_info:
            run_migrations({"version": 0}, migrations, 1)

        assert exc_info.value.last_successful_migration == 0

    def test_missing_version_field_defaults_to_zero(self):
        """If the data has no version field, it defaults to 0 and all migrations run."""
        called = False

        def migrate_1(data):
            nonlocal called
            called = True
            return data

        migrations = {"1_first": migrate_1}
        result = run_migrations({"foo": "bar"}, migrations)

        assert called
        assert result["version"] == 1
        assert result["foo"] == "bar"

    def test_noop_when_already_at_target_version(self):
        """No migrations should run if stored version equals target."""
        called = False

        def migrate_1(data):
            nonlocal called
            called = True
            return data

        migrations = {"1_first": migrate_1}
        result = run_migrations({"version": 1}, migrations)

        assert not called
        assert result["version"] == 1

    def test_noop_when_no_applicable_migrations(self):
        """If all migrations are above the target, nothing runs."""

        def migrate_3(data):
            data["should_not_run"] = True
            return data

        migrations = {"3_third": migrate_3}
        result = run_migrations({"version": 1}, migrations, 2)

        assert "should_not_run" not in result
        assert result["version"] == 2

    def test_does_not_mutate_input(self):
        """The original data dict should not be modified."""
        original = {"version": 0, "key": "original"}

        def migrate_1(data):
            data["key"] = "modified"
            return data

        migrations = {"1_first": migrate_1}
        result = run_migrations(original, migrations)

        assert original["key"] == "original"
        assert result["key"] == "modified"

    def test_custom_version_field(self):
        """A custom version_field name should be respected."""

        def migrate_1(data):
            data["migrated"] = True
            return data

        migrations = {"1_first": migrate_1}
        result = run_migrations(
            {"schema_version": 0},
            migrations,
            version_field="schema_version",
        )

        assert result["migrated"] is True
        assert result["schema_version"] == 1

    def test_migration_renames_field(self):
        """Real-world pattern: renaming a config field."""

        def migrate_to_2(data):
            if "use_ais_web_receiver" in data:
                data["ais_web_receiver_enabled"] = data.pop("use_ais_web_receiver")
            return data

        migrations = {"2_rename_receiver_key": migrate_to_2}
        result = run_migrations(
            {"version": 1, "use_ais_web_receiver": True},
            migrations,
        )

        assert "use_ais_web_receiver" not in result
        assert result["ais_web_receiver_enabled"] is True
        assert result["version"] == 2

    def test_raises_if_stored_version_is_newer_than_latest_migration(self):
        """Should raise ValueError when the config is ahead of all known migrations."""
        migrations = {"1_first": lambda data: data}
        with pytest.raises(ValueError, match="ahead of"):
            run_migrations({"version": 5}, migrations)


class TestJsonPatchMigrations:
    def test_add_operation(self):
        patch = [{"op": "add", "path": "/new_field", "value": "hello"}]
        result = run_migrations({}, {"1_add": patch})
        assert result["new_field"] == "hello"
        assert result["version"] == 1

    def test_replace_operation(self):
        patch = [{"op": "replace", "path": "/name", "value": "updated"}]
        result = run_migrations({"name": "original"}, {"1_replace": patch})
        assert result["name"] == "updated"

    def test_remove_operation(self):
        patch = [{"op": "remove", "path": "/old_field"}]
        result = run_migrations({"old_field": "bye"}, {"1_remove": patch})
        assert "old_field" not in result

    def test_move_operation(self):
        patch = [{"op": "move", "from": "/old_name", "path": "/new_name"}]
        result = run_migrations({"old_name": "value"}, {"1_move": patch})
        assert "old_name" not in result
        assert result["new_name"] == "value"

    def test_copy_operation(self):
        patch = [{"op": "copy", "from": "/source", "path": "/dest"}]
        result = run_migrations({"source": 42}, {"1_copy": patch})
        assert result["source"] == 42
        assert result["dest"] == 42

    def test_test_operation_passes(self):
        patch = [
            {"op": "test", "path": "/name", "value": "expected"},
            {"op": "add", "path": "/verified", "value": True},
        ]
        result = run_migrations({"name": "expected"}, {"1_test": patch})
        assert result["verified"] is True

    def test_test_operation_fails(self):
        patch = [
            {"op": "test", "path": "/name", "value": "wrong"},
            {"op": "add", "path": "/verified", "value": True},
        ]
        with pytest.raises(MigrationError):
            run_migrations({"name": "actual"}, {"1_test": patch})

    def test_multiple_operations_in_one_patch(self):
        patch = [
            {"op": "add", "path": "/added", "value": True},
            {"op": "move", "from": "/old", "path": "/new"},
        ]
        result = run_migrations({"old": "data"}, {"1_multi": patch})
        assert result["added"] is True
        assert result["new"] == "data"
        assert "old" not in result

    def test_nested_paths(self):
        patch = [{"op": "replace", "path": "/database/host", "value": "newhost"}]
        result = run_migrations(
            {"database": {"host": "oldhost", "port": 5432}}, {"1_nested": patch}
        )
        assert result["database"]["host"] == "newhost"
        assert result["database"]["port"] == 5432

    def test_mixed_function_and_patch_in_version_order(self):
        call_order: list[int] = []

        def fn_migrate(data):
            call_order.append(1)
            data["from_fn"] = True
            return data

        patch = [{"op": "add", "path": "/from_patch", "value": True}]

        migrations = {
            "2_patch": patch,
            "1_fn": fn_migrate,
        }
        result = run_migrations({}, migrations)

        assert call_order == [1]
        assert result["from_fn"] is True
        assert result["from_patch"] is True
        assert result["version"] == 2

    def test_empty_patch_is_noop(self):
        result = run_migrations({"key": "value"}, {"1_empty": []})
        assert result["key"] == "value"
        assert result["version"] == 1

    def test_invalid_patch_raises_migration_error(self):
        patch = [{"op": "replace", "path": "/nonexistent", "value": "x"}]
        with pytest.raises(MigrationError):
            run_migrations({}, {"1_bad": patch})

    def test_does_not_mutate_input(self):
        original = {"version": 0, "key": "original"}
        patch = [{"op": "replace", "path": "/key", "value": "modified"}]
        result = run_migrations(original, {"1_patch": patch})
        assert original["key"] == "original"
        assert result["key"] == "modified"

    def test_rollback_tracking_when_patch_fails(self):
        def fn_migrate(data):
            data["step1"] = True
            return data

        bad_patch = [{"op": "remove", "path": "/nonexistent"}]

        migrations = {
            "1_fn": fn_migrate,
            "2_bad_patch": bad_patch,
        }
        with pytest.raises(MigrationError) as exc_info:
            run_migrations({}, migrations)

        assert exc_info.value.last_successful_migration == 1

    def test_invalid_migration_type_raises_migration_error(self):
        migrations = {"1_bad": "not a callable or list"}  # type: ignore[dict-item]
        with pytest.raises(MigrationError, match="must be a callable or a list"):
            run_migrations({}, migrations)


class TestLoadMigrationsFromDir:
    def test_single_file_loads_correctly(self, tmp_path):
        (tmp_path / "1_add_field.py").write_text(
            "def migrate(data):\n    data['added'] = True\n    return data\n"
        )
        migrations = load_migrations_from_dir(tmp_path)
        assert "1_add_field" in migrations
        result = migrations["1_add_field"]({"x": 1})
        assert result["added"] is True

    def test_multiple_files_all_discovered(self, tmp_path):
        (tmp_path / "1_first.py").write_text("def migrate(data): return data\n")
        (tmp_path / "2_second.py").write_text("def migrate(data): return data\n")
        (tmp_path / "3_third.py").write_text("def migrate(data): return data\n")
        migrations = load_migrations_from_dir(tmp_path)
        assert set(migrations.keys()) == {"1_first", "2_second", "3_third"}

    def test_files_starting_with_underscore_are_skipped(self, tmp_path):
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_helpers.py").write_text("")
        (tmp_path / "1_real.py").write_text("def migrate(data): return data\n")
        migrations = load_migrations_from_dir(tmp_path)
        assert list(migrations.keys()) == ["1_real"]

    def test_non_py_non_json_files_are_skipped(self, tmp_path):
        (tmp_path / "1_migration.txt").write_text("def migrate(data): return data\n")
        (tmp_path / "notes.md").write_text("# notes")
        (tmp_path / "1_real.py").write_text("def migrate(data): return data\n")
        migrations = load_migrations_from_dir(tmp_path)
        assert list(migrations.keys()) == ["1_real"]

    def test_files_without_integer_prefix_are_skipped(self, tmp_path):
        (tmp_path / "helper_utils.py").write_text("def migrate(data): return data\n")
        (tmp_path / "utils_shared.py").write_text("def migrate(data): return data\n")
        (tmp_path / "1_real.py").write_text("def migrate(data): return data\n")
        migrations = load_migrations_from_dir(tmp_path)
        assert list(migrations.keys()) == ["1_real"]

    def test_missing_migrate_function_raises_value_error(self, tmp_path):
        (tmp_path / "1_bad.py").write_text("# no migrate function here\n")
        with pytest.raises(ValueError, match="defines neither"):
            load_migrations_from_dir(tmp_path)

    def test_non_callable_migrate_raises_type_error(self, tmp_path):
        (tmp_path / "1_bad.py").write_text("migrate = 'not a function'\n")
        with pytest.raises(TypeError, match="not callable"):
            load_migrations_from_dir(tmp_path)

    def test_nonexistent_directory_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_migrations_from_dir(tmp_path / "does_not_exist")

    def test_string_path_accepted(self, tmp_path):
        (tmp_path / "1_add.py").write_text("def migrate(data): return data\n")
        migrations = load_migrations_from_dir(str(tmp_path))
        assert "1_add" in migrations

    def test_empty_directory_returns_empty_dict(self, tmp_path):
        migrations = load_migrations_from_dir(tmp_path)
        assert migrations == {}

    def test_end_to_end_with_run_migrations(self, tmp_path):
        (tmp_path / "1_add_field.py").write_text(
            "def migrate(data):\n    data['new'] = 'hello'\n    return data\n"
        )
        (tmp_path / "2_rename_field.py").write_text(
            "def migrate(data):\n    data['renamed'] = data.pop('new')\n    return data\n"
        )
        migrations = load_migrations_from_dir(tmp_path)
        result = run_migrations({}, migrations)
        assert result["renamed"] == "hello"
        assert "new" not in result
        assert result["version"] == 2

    # --- JSON file tests ---

    def test_json_file_loads_correctly(self, tmp_path):
        patch = [{"op": "add", "path": "/added", "value": True}]
        (tmp_path / "1_add_field.json").write_text(json.dumps(patch))
        migrations = load_migrations_from_dir(tmp_path)
        assert "1_add_field" in migrations
        assert migrations["1_add_field"] == patch

    def test_json_file_end_to_end_with_run_migrations(self, tmp_path):
        patch = [
            {"op": "add", "path": "/new_field", "value": "hello"},
        ]
        (tmp_path / "1_add.json").write_text(json.dumps(patch))
        migrations = load_migrations_from_dir(tmp_path)
        result = run_migrations({"existing": True}, migrations)
        assert result["new_field"] == "hello"
        assert result["existing"] is True
        assert result["version"] == 1

    def test_json_file_with_non_array_raises_type_error(self, tmp_path):
        (tmp_path / "1_bad.json").write_text('{"op": "add"}')
        with pytest.raises(TypeError, match="JSON array"):
            load_migrations_from_dir(tmp_path)

    def test_py_file_with_patch_attribute(self, tmp_path):
        (tmp_path / "1_patch.py").write_text(
            'patch = [{"op": "add", "path": "/added", "value": True}]\n'
        )
        migrations = load_migrations_from_dir(tmp_path)
        assert "1_patch" in migrations
        assert isinstance(migrations["1_patch"], list)

    def test_py_file_with_both_migrate_and_patch_prefers_migrate(self, tmp_path):
        (tmp_path / "1_both.py").write_text(
            "def migrate(data):\n"
            "    data['from_fn'] = True\n"
            "    return data\n"
            'patch = [{"op": "add", "path": "/from_patch", "value": True}]\n'
        )
        migrations = load_migrations_from_dir(tmp_path)
        assert callable(migrations["1_both"])

    def test_py_file_with_non_list_patch_raises_type_error(self, tmp_path):
        (tmp_path / "1_bad.py").write_text('patch = "not a list"\n')
        with pytest.raises(TypeError, match="not a list"):
            load_migrations_from_dir(tmp_path)

    def test_mixed_py_and_json_files_in_same_directory(self, tmp_path):
        (tmp_path / "1_fn.py").write_text(
            "def migrate(data):\n    data['a'] = 1\n    return data\n"
        )
        patch = [{"op": "add", "path": "/b", "value": 2}]
        (tmp_path / "2_patch.json").write_text(json.dumps(patch))
        migrations = load_migrations_from_dir(tmp_path)
        result = run_migrations({}, migrations)
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["version"] == 2

    def test_duplicate_stem_raises_value_error(self, tmp_path):
        (tmp_path / "1_foo.py").write_text("def migrate(data): return data\n")
        (tmp_path / "1_foo.json").write_text('[{"op": "add", "path": "/x", "value": 1}]')
        with pytest.raises(ValueError, match="Duplicate migration key"):
            load_migrations_from_dir(tmp_path)
