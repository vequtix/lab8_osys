"""Entrypoint delegating to app.cli.main."""

import sys

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
