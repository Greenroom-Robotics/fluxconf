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

    def test_non_py_files_are_skipped(self, tmp_path):
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
        with pytest.raises(ValueError, match="does not define a 'migrate' function"):
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
