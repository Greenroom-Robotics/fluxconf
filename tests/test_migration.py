import pytest

from fluxconf.migration import MigrationError, run_migrations


class TestRunMigrations:
    def test_migrations_run_in_version_order(self):
        """Migrations should execute in ascending version order regardless of dict ordering."""
        call_order: list[str] = []

        def migrate_1_0_0(data):
            call_order.append("1.0.0")
            data["a"] = 1
            return data

        def migrate_1_1_0(data):
            call_order.append("1.1.0")
            data["b"] = 2
            return data

        def migrate_2_0_0(data):
            call_order.append("2.0.0")
            data["c"] = 3
            return data

        # Deliberately unordered keys
        migrations = {
            "2.0.0": migrate_2_0_0,
            "1.0.0": migrate_1_0_0,
            "1.1.0": migrate_1_1_0,
        }

        result = run_migrations({}, migrations, "2.0.0")

        assert call_order == ["1.0.0", "1.1.0", "2.0.0"]
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3
        assert result["version"] == "2.0.0"

    def test_skips_already_applied_migrations(self):
        """Migrations at or below the stored version should not run."""
        call_order: list[str] = []

        def migrate_1_0_0(data):
            call_order.append("1.0.0")
            return data

        def migrate_1_1_0(data):
            call_order.append("1.1.0")
            data["new_field"] = True
            return data

        def migrate_2_0_0(data):
            call_order.append("2.0.0")
            return data

        migrations = {
            "1.0.0": migrate_1_0_0,
            "1.1.0": migrate_1_1_0,
            "2.0.0": migrate_2_0_0,
        }

        result = run_migrations({"version": "1.0.0"}, migrations, "2.0.0")

        assert "1.0.0" not in call_order
        assert call_order == ["1.1.0", "2.0.0"]
        assert result["new_field"] is True
        assert result["version"] == "2.0.0"

    def test_rollback_on_failure(self):
        """On failure, MigrationError should report the last successful version."""

        def migrate_1_0_0(data):
            data["applied"] = True
            return data

        def migrate_1_1_0(data):
            raise RuntimeError("something broke")

        migrations = {
            "1.0.0": migrate_1_0_0,
            "1.1.0": migrate_1_1_0,
        }

        with pytest.raises(MigrationError) as exc_info:
            run_migrations({}, migrations, "1.1.0")

        assert exc_info.value.last_successful_version == "1.0.0"
        assert isinstance(exc_info.value.original_error, RuntimeError)

    def test_rollback_reports_stored_version_when_first_migration_fails(self):
        """If the very first migration fails, last_successful_version is the stored version."""

        def migrate_1_0_0(data):
            raise ValueError("boom")

        migrations = {"1.0.0": migrate_1_0_0}

        with pytest.raises(MigrationError) as exc_info:
            run_migrations({"version": "0.5.0"}, migrations, "1.0.0")

        assert exc_info.value.last_successful_version == "0.5.0"

    def test_missing_version_field_defaults_to_0_0_0(self):
        """If the data has no version field, it defaults to 0.0.0."""
        called = False

        def migrate_0_1_0(data):
            nonlocal called
            called = True
            return data

        migrations = {"0.1.0": migrate_0_1_0}
        result = run_migrations({"foo": "bar"}, migrations, "0.1.0")

        assert called
        assert result["version"] == "0.1.0"
        assert result["foo"] == "bar"

    def test_noop_when_already_at_target_version(self):
        """No migrations should run if stored version equals target."""
        called = False

        def migrate_1_0_0(data):
            nonlocal called
            called = True
            return data

        migrations = {"1.0.0": migrate_1_0_0}
        result = run_migrations({"version": "1.0.0"}, migrations, "1.0.0")

        assert not called
        assert result["version"] == "1.0.0"

    def test_noop_when_no_applicable_migrations(self):
        """If all migrations are above the target, nothing runs."""

        def migrate_3_0_0(data):
            data["should_not_run"] = True
            return data

        migrations = {"3.0.0": migrate_3_0_0}
        result = run_migrations({"version": "1.0.0"}, migrations, "2.0.0")

        assert "should_not_run" not in result
        assert result["version"] == "2.0.0"

    def test_does_not_mutate_input(self):
        """The original data dict should not be modified."""
        original = {"version": "0.0.0", "key": "original"}

        def migrate_1_0_0(data):
            data["key"] = "modified"
            return data

        migrations = {"1.0.0": migrate_1_0_0}
        result = run_migrations(original, migrations, "1.0.0")

        assert original["key"] == "original"
        assert result["key"] == "modified"

    def test_custom_version_field(self):
        """A custom version_field name should be respected."""

        def migrate_1_0_0(data):
            data["migrated"] = True
            return data

        migrations = {"1.0.0": migrate_1_0_0}
        result = run_migrations(
            {"schema_version": "0.0.0"},
            migrations,
            "1.0.0",
            version_field="schema_version",
        )

        assert result["migrated"] is True
        assert result["schema_version"] == "1.0.0"

    def test_stamps_target_version_even_with_no_migrations(self):
        """The target version should be stamped even when migrations dict is empty."""
        result = run_migrations({"version": "0.0.0"}, {}, "2.0.0")
        assert result["version"] == "2.0.0"

    def test_migration_renames_field(self):
        """Real-world pattern: renaming a config field."""

        def migrate_to_1_1_0(data):
            if "use_ais_web_receiver" in data:
                data["ais_web_receiver_enabled"] = data.pop("use_ais_web_receiver")
            return data

        migrations = {"1.1.0": migrate_to_1_1_0}
        result = run_migrations(
            {"version": "1.0.0", "use_ais_web_receiver": True},
            migrations,
            "1.1.0",
        )

        assert "use_ais_web_receiver" not in result
        assert result["ais_web_receiver_enabled"] is True
        assert result["version"] == "1.1.0"
