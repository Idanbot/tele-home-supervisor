from tele_home_supervisor.commands import COMMANDS
from tele_home_supervisor.handlers import dispatch


def test_dispatch_exports_all_registered_command_handlers():
    missing = [spec.handler for spec in COMMANDS if not hasattr(dispatch, spec.handler)]

    assert missing == []
