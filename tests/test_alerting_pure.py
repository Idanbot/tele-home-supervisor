from tele_home_supervisor import alerting
from tele_home_supervisor.models.alerts import AlertRule, AlertState


class TestParseBool:
    def test_true_values(self) -> None:
        for v in ("true", "yes", "1", "on", "True", "YES", "ON"):
            assert alerting._parse_bool(v) is True

    def test_false_values(self) -> None:
        for v in ("false", "no", "0", "off", "False", "NO", "OFF"):
            assert alerting._parse_bool(v) is False

    def test_unknown_returns_none(self) -> None:
        assert alerting._parse_bool("maybe") is None
        assert alerting._parse_bool("") is None

    def test_whitespace_stripped(self) -> None:
        assert alerting._parse_bool("  yes  ") is True
        assert alerting._parse_bool("  off  ") is False


class TestFormatList:
    def test_empty_list(self) -> None:
        assert alerting._format_list([]) == "none"

    def test_within_limit(self) -> None:
        assert alerting._format_list(["a", "b"]) == "a, b"

    def test_exactly_at_limit(self) -> None:
        assert alerting._format_list(["a", "b", "c"]) == "a, b, c"

    def test_over_limit(self) -> None:
        result = alerting._format_list(["a", "b", "c", "d", "e"], limit=3)
        assert result == "a, b, c +2 more"

    def test_custom_limit(self) -> None:
        result = alerting._format_list(["a", "b", "c", "d"], limit=2)
        assert result == "a, b +2 more"


class TestParseTempValue:
    def test_integer_temp(self) -> None:
        assert alerting._parse_temp_value("45") == 45.0

    def test_float_temp(self) -> None:
        assert alerting._parse_temp_value("45.5") == 45.5

    def test_negative_temp(self) -> None:
        assert alerting._parse_temp_value("-10.3") == -10.3

    def test_with_unit(self) -> None:
        assert alerting._parse_temp_value("45C") == 45.0
        assert alerting._parse_temp_value("72.5F") == 72.5

    def test_empty_returns_none(self) -> None:
        assert alerting._parse_temp_value("") is None
        assert alerting._parse_temp_value(None) is None

    def test_no_digits_returns_none(self) -> None:
        assert alerting._parse_temp_value("abc") is None


class TestCompare:
    def test_equal(self) -> None:
        assert alerting._compare("=", 10, 10) is True
        assert alerting._compare("==", 10, 10) is True
        assert alerting._compare("=", 10, 20) is False

    def test_not_equal(self) -> None:
        assert alerting._compare("!=", 10, 20) is True
        assert alerting._compare("!=", 10, 10) is False

    def test_greater(self) -> None:
        assert alerting._compare(">", 20, 10) is True
        assert alerting._compare(">", 10, 20) is False

    def test_greater_equal(self) -> None:
        assert alerting._compare(">=", 10, 10) is True
        assert alerting._compare(">=", 20, 10) is True
        assert alerting._compare(">=", 5, 10) is False

    def test_less(self) -> None:
        assert alerting._compare("<", 5, 10) is True
        assert alerting._compare("<", 10, 5) is False

    def test_less_equal(self) -> None:
        assert alerting._compare("<=", 10, 10) is True
        assert alerting._compare("<=", 5, 10) is True
        assert alerting._compare("<=", 20, 10) is False

    def test_none_returns_false(self) -> None:
        assert alerting._compare(">", None, 10) is False
        assert alerting._compare(">", 10, None) is False

    def test_string_equality(self) -> None:
        assert alerting._compare("=", "up", "up") is True
        assert alerting._compare("!=", "up", "down") is True

    def test_string_numeric_comparison(self) -> None:
        assert alerting._compare(">", "20", "10") is True

    def test_unknown_operator(self) -> None:
        assert alerting._compare("~", 10, 10) is False


class TestIsActive:
    def test_never_triggered(self) -> None:
        state = AlertState()
        assert alerting._is_active(state) is False

    def test_triggered_never_cleared(self) -> None:
        state = AlertState(last_triggered_at=100.0)
        assert alerting._is_active(state) is True

    def test_triggered_and_cleared(self) -> None:
        state = AlertState(last_triggered_at=100.0, last_cleared_at=200.0)
        assert alerting._is_active(state) is False

    def test_re_triggered_after_clear(self) -> None:
        state = AlertState(last_triggered_at=200.0, last_cleared_at=100.0)
        assert alerting._is_active(state) is True


class TestFormatThreshold:
    def test_percent(self) -> None:
        assert alerting.format_threshold("disk_used", 75) == "75%"

    def test_bool_true(self) -> None:
        assert alerting.format_threshold("lan_up", True) == "true"

    def test_bool_false(self) -> None:
        assert alerting.format_threshold("lan_up", False) == "false"

    def test_temp(self) -> None:
        assert alerting.format_threshold("temp", 45.5) == "45.5C"

    def test_none_returns_na(self) -> None:
        assert alerting.format_threshold("disk_used", None) == "n/a"

    def test_unknown_metric_returns_na(self) -> None:
        assert alerting.format_threshold("nonexistent", 50) == "n/a"


class TestBuildAlertMessage:
    def test_event_alert(self) -> None:
        rule = AlertRule(
            id="r1",
            chat_id=123,
            metric="lan_up",
            operator="=",
            threshold=True,
            duration_s=0,
        )
        mv = alerting.AlertMetricValue(value=True, display="up", is_event=True)
        msg = alerting._build_alert_message(rule, mv, recovered=False)
        assert "<b>ALERT</b>" in msg
        assert "r1" in msg

    def test_recovery_message(self) -> None:
        rule = AlertRule(
            id="r2",
            chat_id=123,
            metric="disk_used",
            operator=">",
            threshold=80,
            duration_s=0,
        )
        mv = alerting.AlertMetricValue(value=50, display="50%")
        msg = alerting._build_alert_message(rule, mv, recovered=True)
        assert "<b>RECOVERED</b>" in msg

    def test_threshold_alert(self) -> None:
        rule = AlertRule(
            id="r3",
            chat_id=123,
            metric="disk_used",
            operator=">",
            threshold=80,
            duration_s=0,
        )
        mv = alerting.AlertMetricValue(value=90, display="90%")
        msg = alerting._build_alert_message(rule, mv, recovered=False)
        assert "<b>ALERT</b>" in msg
        assert "disk_used" in msg
