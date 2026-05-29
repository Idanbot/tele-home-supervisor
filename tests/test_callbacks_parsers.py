from tele_home_supervisor.handlers import callbacks


class TestParseAlertsPayload:
    def test_valid_payload(self) -> None:
        assert callbacks._parse_alerts_payload("alerts:ack:rule1") == ("ack", "rule1")

    def test_valid_resolve(self) -> None:
        assert callbacks._parse_alerts_payload("alerts:resolve:rule2") == (
            "resolve",
            "rule2",
        )

    def test_too_few_parts(self) -> None:
        assert callbacks._parse_alerts_payload("alerts:ack") is None

    def test_too_many_parts(self) -> None:
        assert callbacks._parse_alerts_payload("alerts:ack:rule1:extra") is None

    def test_empty_action(self) -> None:
        assert callbacks._parse_alerts_payload("alerts::rule1") is None

    def test_empty_rule_id(self) -> None:
        assert callbacks._parse_alerts_payload("alerts:ack:") is None
