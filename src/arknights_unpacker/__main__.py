from __future__ import annotations

import sys


def main() -> int:
    if "--worker-server" in sys.argv:
        from .jobs import worker_server_entry
        return worker_server_entry(sys.argv[sys.argv.index("--worker-server") + 1])
    if "--worker" in sys.argv:
        from .jobs import worker_entry
        return worker_entry(sys.argv[sys.argv.index("--worker") + 1])
    from .bootstrap import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
