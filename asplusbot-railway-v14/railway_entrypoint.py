"""Keep Railway alive until the account's persistent SoroPy session exists."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time


def session_directory() -> Path:
    explicit = os.getenv("SESSION_DIR")
    if explicit:
        return Path(explicit)
    session_name = Path(os.getenv("SESSION_NAME", "data/soroush.session"))
    return session_name.parent


def session_is_ready(path: Path, phone: str) -> bool:
    """Check the exact account session and ignore SoroPy tracker files."""
    if not path.is_dir() or not phone:
        return False
    safe_phone = normalize_phone(phone).replace("+", "plus_")
    candidates = (path / safe_phone, path / f"{safe_phone}.session")
    return any(item.is_file() and item.stat().st_size > 0 for item in candidates)


def normalize_phone(phone: str) -> str:
    """Normalize Iranian Soroush numbers without importing runtime packages."""
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "98" + digits[1:]
    elif not digits.startswith("98"):
        raise ValueError("شمارهٔ سروش را به‌شکل +98xxxxxxxxxx وارد کنید.")
    if len(digits) != 12:
        raise ValueError("شمارهٔ سروش را به‌شکل +98xxxxxxxxxx وارد کنید.")
    return "+" + digits


def main() -> None:
    path = session_directory()
    path.mkdir(parents=True, exist_ok=True)
    phone = os.getenv("SOROUSH_PHONE", "").strip()
    if not phone:
        raise SystemExit("متغیر SOROUSH_PHONE را در Variables سرویس Railway تنظیم کنید.")
    if session_is_ready(path, phone):
        raise SystemExit(subprocess.call([sys.executable, "-m", "splus_manager"]))

    print(
        "نشست سروش هنوز ساخته نشده است. با railway ssh وارد سرویس شوید و اجرا کنید:\n"
        "python -m splus_manager --login-only\n"
        "پس از ورود موفق، Deployment را Restart کنید.",
        flush=True,
    )
    while True:
        time.sleep(300)


if __name__ == "__main__":
    main()
