"""Helper utilities for running subprocess/CLI commands.

Provides a small `run_cmd` wrapper and `get_docker_cmd` which centralizes
how we detect the docker binary. This makes testing and changes easier.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional, Tuple


def run_cmd(cmd: list[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "not found"


def get_docker_cmd() -> Optional[str]:
    """Return a path to the docker binary or None if not found."""
    candidates = ["/usr/local/bin/docker", "/usr/bin/docker"]
    for c in candidates:
        if shutil.which(c) or (shutil.which(c.split('/')[-1]) and c):
            # prefer the explicit path if available in filesystem
            return c if shutil.which(c) else shutil.which(c.split('/')[-1])
    # fallback to PATH
    which = shutil.which("docker")
    return which
