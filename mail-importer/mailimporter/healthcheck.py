from __future__ import annotations

import os
import sys
import time


def main() -> int:
    path = os.environ.get("HEARTBEAT_PATH", "/data/heartbeat")
    max_age = int(os.environ.get("HEARTBEAT_MAX_AGE_SECONDS", "900"))
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        print("no heartbeat file yet", file=sys.stderr)
        return 1
    if age > max_age:
        print(f"heartbeat too old: {age:.0f}s > {max_age}s", file=sys.stderr)
        return 1
    print(f"ok (heartbeat {age:.0f}s old)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
