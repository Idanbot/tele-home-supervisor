"""Tests for alerting module."""

from tele_home_supervisor import alerting


class TestNormalizeMetric:
    """Tests for normalize_metric function."""

    def test_valid_metric(self) -> None:
        assert alerting.normalize_metric("disk_used") == "disk_used"
        assert alerting.normalize_metric("load") == "load"
        assert alerting.normalize_metric("mem_used") == "mem_used"

    def test_alias_resolution(self) -> None:
        assert alerting.normalize_metric("disk") == "disk_used"
        assert alerting.normalize_metric("memory") == "mem_used"
        assert alerting.normalize_metric("temperature") == "temp"
        assert alerting.normalize_metric("lan") == "lan_up"

    def test_case_insensitive(self) -> None:
        assert alerting.normalize_metric("DISK_USED") == "disk_used"
        assert alerting.normalize_metric("Mem_Used") == "mem_used"

    def test_invalid_metric(self) -> None:
        assert alerting.normalize_metric("invalid") is None
        assert alerting.normalize_metric("") is None
        assert alerting.normalize_metric("   ") is None

    def test_with_whitespace(self) -> None:
        assert alerting.normalize_metric("  disk_used  ") == "disk_used"


class TestGetMetricDef:
    """Tests for get_metric_def function."""

    def test_returns_metric_def(self) -> None:
        metric_def = alerting.get_metric_def("disk_used")
        assert metric_def is not None
        assert metric_def.name == "disk_used"
        assert metric_def.kind == "number"

    def test_returns_none_for_invalid(self) -> None:
        assert alerting.get_metric_def("invalid") is None


class TestParseDuration:
    """Tests for parse_duration function."""

    def test_seconds(self) -> None:
        assert alerting.parse_duration("30s", 60) == 30
        assert alerting.parse_duration("120s", 60) == 120

    def test_minutes(self) -> None:
        assert alerting.parse_duration("5m", 60) == 300
        assert alerting.parse_duration("10m", 60) == 600

    def test_hours(self) -> None:
        assert alerting.parse_duration("1h", 60) == 3600
        assert alerting.parse_duration("2h", 60) == 7200

    def test_no_unit_defaults_to_minutes(self) -> None:
        assert alerting.parse_duration("5", 60) == 300

    def test_empty_returns_default(self) -> None:
        assert alerting.parse_duration("", 120) == 120
        assert alerting.parse_duration(None, 120) == 120

    def test_invalid_returns_none(self) -> None:
        assert alerting.parse_duration("abc", 60) is None
        assert alerting.parse_duration("5x", 60) is None


class TestParseThreshold:
    """Tests for parse_threshold function."""

    def test_numeric_threshold(self) -> None:
        # parse_threshold takes (metric, raw) and returns (value, error)
        value, err = alerting.parse_threshold("disk_used", "90")
        assert err is None
        assert value == 90.0
        value, err = alerting.parse_threshold("load", "50.5")
        assert err is None
        assert value == 50.5

    def test_boolean_true(self) -> None:
        value, err = alerting.parse_threshold("lan_up", "true")
        assert err is None
        assert value is True
        value, err = alerting.parse_threshold("wan_up", "yes")
        assert err is None
        assert value is True

    def test_boolean_false(self) -> None:
        value, err = alerting.parse_threshold("lan_up", "false")
        assert err is None
        assert value is False
        value, err = alerting.parse_threshold("wan_up", "no")
        assert err is None
        assert value is False

    def test_invalid_metric_returns_error(self) -> None:
        value, err = alerting.parse_threshold("invalid_metric", "90")
        assert value is None
        assert err is not None

    def test_invalid_value_returns_error(self) -> None:
        value, err = alerting.parse_threshold("disk_used", "abc")
        assert value is None
        assert err is not None


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_seconds(self) -> None:
        assert alerting.format_duration(30) == "30s"
        assert alerting.format_duration(59) == "59s"

    def test_minutes(self) -> None:
        assert alerting.format_duration(60) == "1m"
        assert alerting.format_duration(300) == "5m"

    def test_hours(self) -> None:
        assert alerting.format_duration(3600) == "1h"
        assert alerting.format_duration(7200) == "2h"

    def test_mixed(self) -> None:
        # 5400s = 90m, not evenly divisible by 3600
        assert alerting.format_duration(5400) == "90m"


class TestFormatThreshold:
    """Tests for format_threshold function."""

    def test_numeric(self) -> None:
        # format_threshold takes (metric, value)
        result = alerting.format_threshold("disk_used", 90.0)
        assert "90" in result

    def test_boolean(self) -> None:
        assert alerting.format_threshold("lan_up", True) == "true"
        assert alerting.format_threshold("lan_up", False) == "false"


class TestMetricDefs:
    """Tests for METRIC_DEFS constant."""

    def test_all_required_metrics_exist(self) -> None:
        required = ["disk_used", "load", "mem_used", "temp", "lan_up", "wan_up"]
        for metric in required:
            assert metric in alerting.METRIC_DEFS

    def test_metric_def_has_required_fields(self) -> None:
        for name, metric_def in alerting.METRIC_DEFS.items():
            assert metric_def.name == name
            assert metric_def.label
            assert metric_def.kind in ("number", "bool", "event")
            assert isinstance(metric_def.default_duration_s, int)
