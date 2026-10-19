"""Absolute imports also work when PyInstaller executes this file as __main__."""
from arknights_unpacker.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
