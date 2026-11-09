from __future__ import annotations

import sys


def main() -> int:
    from .jobs import worker_command

    if (result := worker_command(sys.argv)) is not None:
        return result
    from .bootstrap import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
