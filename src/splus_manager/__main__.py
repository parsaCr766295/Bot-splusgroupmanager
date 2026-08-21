"""Run the manager after configuring .env environment variables."""
from __future__ import annotations

import asyncio
import os
import threading

from .service import Manager
from .soropy_gateway import SoroPyGateway
from .storage import Store


def main() -> None:
    _load_dotenv()
    group_id = os.getenv("SOROUSH_GROUP_ID")
    phone = os.getenv("SOROUSH_PHONE")
    if not group_id or not phone:
        raise SystemExit("SOROUSH_GROUP_ID و SOROUSH_PHONE را در محیط یا فایل .env تنظیم کنید.")
    try:
        from soropy import SoroushClient
    except ImportError as exc:
        raise SystemExit("ابتدا pip install -e '.[soroush]' را اجرا کنید.") from exc

    # SoroPy v1.x requires the phone when creating its client. OTP is requested
    # interactively and never written into .env or the database.
    session_file = os.getenv("SESSION_NAME", "data/soroush.session")
    session_dir = os.path.dirname(session_file) or None
    client = SoroushClient(
        phone,
        backend=os.getenv("SOROUSH_BACKEND", "websocket"),
        session_dir=session_dir,
    )
    status = client.login(code_callback=lambda: input("کد ورود سروش‌پلاس: ").strip())
    if getattr(status, "value", str(status)) not in {"success", "already_logged_in", "session_restored"}:
        raise SystemExit(f"ورود ناموفق بود: {status}")

    gateway = SoroPyGateway(client, os.getenv("SOROUSH_GROUP_TARGET") or None)
    manager = Manager(
        gateway,
        Store(os.getenv("DATABASE_PATH", "data/manager.db")),
        group_id,
        call_members_limit=int(os.getenv("CALL_MEMBERS_LIMIT", "500")),
        call_batch_size=int(os.getenv("CALL_MEMBERS_BATCH", "20")),
        call_batch_delay=float(os.getenv("CALL_MEMBERS_DELAY_SECONDS", "1.5")),
        schedule_timezone=os.getenv("CHAT_SCHEDULE_TIMEZONE", "+03:30"),
    )

    def on_message(event):
        from .models import Message
        raw = event if isinstance(event, dict) else event.data
        message_id = raw.get("message_id", raw.get("id"))
        if message_id in (None, ""):
            return
        reply_to = raw.get("reply_to_id")
        msg = Message(
            chat_id=str(raw.get("chat_id")), message_id=int(message_id),
            sender_id=str(raw.get("sender_id", raw.get("from_id", ""))), text=raw.get("text", ""),
            reply_to_id=int(reply_to) if str(reply_to).isdigit() else None,
            is_outgoing=bool(raw.get("is_outgoing", False)),
            sender_name=str(raw.get("sender_name", "") or ""),
            sender_username=str(raw.get("sender_username", raw.get("username", "")) or ""),
        )
        gateway.remember_message(msg)
        # SoroPy invokes event handlers from its worker thread.
        asyncio.run(manager.handle(msg))

    # SoroPy emits `new_message`; adapt this short registration if the selected version names it differently.
    client.on("new_message", on_message)
    schedule_stop = threading.Event()

    def schedule_worker():
        interval = max(5.0, float(os.getenv("CHAT_SCHEDULE_CHECK_SECONDS", "20")))
        while not schedule_stop.wait(interval):
            try:
                asyncio.run(manager.scheduled_tick())
            except Exception as exc:
                print(f"خطای زمان‌بندی چت: {exc}")

    threading.Thread(target=schedule_worker, name="chat-schedule", daemon=True).start()
    try:
        asyncio.run(manager.scheduled_tick())
    except Exception as exc:
        print(f"خطای بررسی اولیهٔ زمان‌بندی چت: {exc}")
    print("مدیر گروه فعال است. برای توقف Ctrl+C را فشار دهید.")
    try:
        client.start_monitor(blocking=True)
    finally:
        schedule_stop.set()


def _load_dotenv(path: str = ".env") -> None:
    """Small dependency-free .env reader; existing environment wins."""
    try:
        lines = open(path, encoding="utf-8")
    except FileNotFoundError:
        return
    with lines:
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


if __name__ == "__main__":
    main()
