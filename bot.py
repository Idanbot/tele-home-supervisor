#!/usr/bin/env python3
"""Thin entrypoint that runs the package `tele_home_supervisor`.

This file keeps compatibility for the existing Dockerfile/usage which runs
`python /app/bot.py`.
"""
from tele_home_supervisor.main import run


if __name__ == "__main__":
    run()
