"""Run once by the `migrate` service: wait for dependencies, apply migrations,
create the storage bucket, and seed data."""

import subprocess
import sys
import time

from app.core.storage import ensure_bucket


def wait_for(name: str, fn, attempts: int = 30, delay: float = 2.0) -> None:
    for i in range(1, attempts + 1):
        try:
            fn()
            print(f"[bootstrap] {name}: ready")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[bootstrap] {name}: not ready ({e.__class__.__name__}), retry {i}/{attempts}")
            time.sleep(delay)
    sys.exit(f"[bootstrap] {name}: gave up")


def main() -> None:
    wait_for("storage", ensure_bucket)
    print("[bootstrap] applying migrations (control database, then every company database)")
    subprocess.run([sys.executable, "-m", "app.tenants", "migrate"], check=True)
    print("[bootstrap] seeding")
    subprocess.run([sys.executable, "-m", "app.seed"], check=True)
    print("[bootstrap] done")


if __name__ == "__main__":
    main()
