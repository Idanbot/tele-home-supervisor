"""Helper utilities for running subprocess/CLI commands.

Provides an async `run_cmd` wrapper and `get_docker_cmd`.
"""

from __future__ import annotations

import asyncio
import shutil
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


async def run_cmd(cmd: list[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Run a command asynchronously and return (returncode, stdout, stderr).

    Args:
        cmd: Command and arguments as a list (e.g., ["ls", "-la"])
        timeout: Maximum time in seconds to wait for command completion

    Returns:
        Tuple of (return_code, stdout, stderr) where:
        - return_code: 0 for success, 124 for timeout, 127 for not found, 1 for other errors
        - stdout: Command standard output, decoded and stripped
        - stderr: Command standard error, decoded and stripped

    Example:
        >>> rc, out, err = await run_cmd(["echo", "hello"], timeout=5)
        >>> print(f"Return code: {rc}, Output: {out}")
        Return code: 0, Output: hello
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return (
                process.returncode or 0,
                stdout.decode().strip(),
                stderr.decode().strip(),
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            logger.warning("Command timed out after %ds: %s", timeout, " ".join(cmd))
            return 124, "", "timeout"
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0] if cmd else "")
        return 127, "", "not found"
    except Exception as e:
        logger.debug(f"run_cmd failed: {e}")
        return 1, "", str(e)


def get_docker_cmd() -> Optional[str]:
    """Return a path to the docker binary or None if not found.

    Searches for the Docker CLI in common locations, then falls back to PATH.

    Returns:
        Full path to docker binary if found, None otherwise.

    Note:
        Prefers explicit paths over PATH to ensure consistent behavior.
    """
    candidates = ["/usr/local/bin/docker", "/usr/bin/docker"]
    for c in candidates:
        if shutil.which(c) or (shutil.which(c.split("/")[-1]) and c):
            # prefer the explicit path if available in filesystem
            return c if shutil.which(c) else shutil.which(c.split("/")[-1])
    # fallback to PATH
    which = shutil.which("docker")
    return which
