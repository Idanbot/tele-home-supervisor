"""Runtime globals shared across modules without import cycles."""
from __future__ import annotations

from datetime import datetime

# Track startup time (module import time).
STARTUP_TIME = datetime.now()

