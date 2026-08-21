from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import AccessMode, Action, GroupSettings


class Store:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    chat_id TEXT PRIMARY KEY, warning_limit INTEGER NOT NULL DEFAULT 3,
                    warning_action TEXT NOT NULL DEFAULT 'mute', mute_minutes INTEGER NOT NULL DEFAULT 60,
                    welcome_text TEXT NOT NULL DEFAULT '', anti_link INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id TEXT NOT NULL, user_id TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, user_id));
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, chat_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, target_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reply_rules (
                    chat_id TEXT NOT NULL, trigger TEXT NOT NULL COLLATE NOCASE,
                    response TEXT NOT NULL, created_by TEXT NOT NULL,
                    PRIMARY KEY(chat_id, trigger));
                CREATE TABLE IF NOT EXISTS group_permissions (
                    chat_id TEXT NOT NULL, permission TEXT NOT NULL,
                    allowed INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(chat_id, permission));
                CREATE TABLE IF NOT EXISTS ad_filters (
                    chat_id TEXT NOT NULL, filter_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, filter_name));
                CREATE TABLE IF NOT EXISTS chat_schedule (
                    chat_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    close_time TEXT NOT NULL DEFAULT '23:00',
                    open_time TEXT NOT NULL DEFAULT '07:00',
                    timezone TEXT NOT NULL DEFAULT '+03:30',
                    last_state TEXT,
                    emergency_until TEXT);
                CREATE TABLE IF NOT EXISTS spam_options (
                    chat_id TEXT NOT NULL, option_name TEXT NOT NULL,
                    option_value TEXT NOT NULL,
                    PRIMARY KEY(chat_id, option_name));
                CREATE TABLE IF NOT EXISTS filter_words (
                    chat_id TEXT NOT NULL, phrase TEXT NOT NULL COLLATE NOCASE,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY(chat_id, phrase));
                CREATE TABLE IF NOT EXISTS link_processing (
                    chat_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS link_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    link TEXT NOT NULL,
                    link_type TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS support_settings (
                    chat_id TEXT PRIMARY KEY,
                    contact_text TEXT NOT NULL DEFAULT '');
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
            for name in ("forward_mode", "link_mode", "media_mode", "send_mode"):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE settings ADD COLUMN {name} TEXT NOT NULL DEFAULT 'free'"
                    )
            schedule_columns = {row[1] for row in db.execute("PRAGMA table_info(chat_schedule)")}
            if "emergency_until" not in schedule_columns:
                db.execute("ALTER TABLE chat_schedule ADD COLUMN emergency_until TEXT")

    def settings(self, chat_id: str) -> GroupSettings:
        with self._conn() as db:
            row = db.execute("SELECT * FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            return GroupSettings()
        return GroupSettings(
            warning_limit=row["warning_limit"],
            warning_action=Action(row["warning_action"]),
            mute_minutes=row["mute_minutes"],
            welcome_text=row["welcome_text"],
            anti_link=bool(row["anti_link"]),
            forward_mode=AccessMode(row["forward_mode"]),
            link_mode=AccessMode(row["link_mode"]),
            media_mode=AccessMode(row["media_mode"]),
            send_mode=AccessMode(row["send_mode"]),
        )

    def save_settings(self, chat_id: str, settings: GroupSettings) -> None:
        with self._conn() as db:
            db.execute("""INSERT INTO settings(
                chat_id,warning_limit,warning_action,mute_minutes,welcome_text,anti_link,
                forward_mode,link_mode,media_mode,send_mode
            ) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                warning_limit=excluded.warning_limit, warning_action=excluded.warning_action,
                mute_minutes=excluded.mute_minutes, welcome_text=excluded.welcome_text,
                anti_link=excluded.anti_link, forward_mode=excluded.forward_mode,
                link_mode=excluded.link_mode, media_mode=excluded.media_mode,
                send_mode=excluded.send_mode""",
                (
                    chat_id, settings.warning_limit, settings.warning_action,
                    settings.mute_minutes, settings.welcome_text, int(settings.anti_link),
                    settings.forward_mode, settings.link_mode,
                    settings.media_mode, settings.send_mode,
                ))

    def add_warning(self, chat_id: str, user_id: str) -> int:
        with self._conn() as db:
            db.execute("INSERT INTO warnings(chat_id,user_id,count) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1", (chat_id, user_id))
            return db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()[0]

    def remove_warning(self, chat_id: str, user_id: str) -> int:
        """Remove one warning, never allowing a negative warning count."""
        with self._conn() as db:
            row = db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            count = max(0, (row[0] if row else 0) - 1)
            if count:
                db.execute("UPDATE warnings SET count=? WHERE chat_id=? AND user_id=?", (count, chat_id, user_id))
            else:
                db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            return count

    def reset_warnings(self, chat_id: str, user_id: str) -> None:
        with self._conn() as db:
            db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    def warning_count(self, chat_id: str, user_id: str) -> int:
        with self._conn() as db:
            row = db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return int(row[0]) if row else 0

    def list_warnings(self, chat_id: str) -> list[tuple[str, int]]:
        with self._conn() as db:
            rows = db.execute(
                "SELECT user_id,count FROM warnings WHERE chat_id=? AND count>0 ORDER BY count DESC,user_id", (chat_id,),
            ).fetchall()
        return [(str(row["user_id"]), int(row["count"])) for row in rows]

    def log(self, chat_id: str, actor_id: str, target_id: str | None, action: Action, detail: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as db:
            db.execute("INSERT INTO audit_log(created_at,chat_id,actor_id,target_id,action,detail) VALUES(?,?,?,?,?,?)", (now, chat_id, actor_id, target_id, action, detail))

    def save_reply(self, chat_id: str, trigger: str, response: str, actor_id: str) -> None:
        with self._conn() as db:
            db.execute("INSERT INTO reply_rules(chat_id,trigger,response,created_by) VALUES(?,?,?,?) ON CONFLICT(chat_id,trigger) DO UPDATE SET response=excluded.response,created_by=excluded.created_by", (chat_id, trigger.casefold(), response, actor_id))

    def remove_reply(self, chat_id: str, trigger: str) -> bool:
        with self._conn() as db:
            return bool(db.execute("DELETE FROM reply_rules WHERE chat_id=? AND trigger=?", (chat_id, trigger.casefold())).rowcount)

    def find_reply(self, chat_id: str, text: str) -> str | None:
        with self._conn() as db:
            row = db.execute("SELECT response FROM reply_rules WHERE chat_id=? AND trigger=?", (chat_id, text.strip().casefold())).fetchone()
        return row[0] if row else None

    def list_replies(self, chat_id: str) -> list[str]:
        with self._conn() as db:
            return [row[0] for row in db.execute("SELECT trigger FROM reply_rules WHERE chat_id=? ORDER BY trigger", (chat_id,))]

    def permissions(self, chat_id: str, defaults: dict[str, bool]) -> dict[str, bool]:
        result = dict(defaults)
        with self._conn() as db:
            rows = db.execute(
                "SELECT permission,allowed FROM group_permissions WHERE chat_id=?",
                (chat_id,),
            )
            for row in rows:
                if row["permission"] in result:
                    result[row["permission"]] = bool(row["allowed"])
        return result

    def save_permissions(self, chat_id: str, permissions: dict[str, bool]) -> None:
        with self._conn() as db:
            db.executemany(
                """INSERT INTO group_permissions(chat_id,permission,allowed) VALUES(?,?,?)
                ON CONFLICT(chat_id,permission) DO UPDATE SET allowed=excluded.allowed""",
                [(chat_id, key, int(value)) for key, value in permissions.items()],
            )

    def ad_filters(self, chat_id: str, defaults: dict[str, bool]) -> dict[str, bool]:
        result = dict(defaults)
        with self._conn() as db:
            rows = db.execute(
                "SELECT filter_name,enabled FROM ad_filters WHERE chat_id=?",
                (chat_id,),
            )
            for row in rows:
                if row["filter_name"] in result:
                    result[row["filter_name"]] = bool(row["enabled"])
        return result

    def save_ad_filters(self, chat_id: str, filters: dict[str, bool]) -> None:
        with self._conn() as db:
            db.executemany(
                """INSERT INTO ad_filters(chat_id,filter_name,enabled) VALUES(?,?,?)
                ON CONFLICT(chat_id,filter_name) DO UPDATE SET enabled=excluded.enabled""",
                [(chat_id, key, int(value)) for key, value in filters.items()],
            )

    def chat_schedule(self, chat_id: str, timezone: str = "+03:30") -> dict[str, object]:
        with self._conn() as db:
            row = db.execute("SELECT * FROM chat_schedule WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            return {
                "enabled": False, "close_time": "23:00", "open_time": "07:00",
                "timezone": timezone, "last_state": None, "emergency_until": None,
            }
        return {
            "enabled": bool(row["enabled"]), "close_time": row["close_time"],
            "open_time": row["open_time"], "timezone": row["timezone"],
            "last_state": row["last_state"], "emergency_until": row["emergency_until"],
        }

    def save_chat_schedule(
        self, chat_id: str, *, enabled: bool, close_time: str,
        open_time: str, timezone: str, last_state: str | None = None,
        emergency_until: str | None = None,
    ) -> None:
        with self._conn() as db:
            db.execute(
                """INSERT INTO chat_schedule(
                    chat_id,enabled,close_time,open_time,timezone,last_state,emergency_until
                ) VALUES(?,?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                enabled=excluded.enabled,close_time=excluded.close_time,
                open_time=excluded.open_time,timezone=excluded.timezone,
                last_state=excluded.last_state,emergency_until=excluded.emergency_until""",
                (chat_id, int(enabled), close_time, open_time, timezone, last_state, emergency_until),
            )

    def save_chat_schedule_state(self, chat_id: str, state: str) -> None:
        with self._conn() as db:
            db.execute("UPDATE chat_schedule SET last_state=? WHERE chat_id=?", (state, chat_id))

    def save_chat_emergency(self, chat_id: str, until_iso: str | None) -> None:
        with self._conn() as db:
            db.execute(
                "UPDATE chat_schedule SET emergency_until=?,last_state=NULL WHERE chat_id=?",
                (until_iso, chat_id),
            )

    def spam_options(self, chat_id: str, defaults: dict[str, bool | int]) -> dict[str, bool | int]:
        result = dict(defaults)
        with self._conn() as db:
            rows = db.execute(
                "SELECT option_name,option_value FROM spam_options WHERE chat_id=?",
                (chat_id,),
            )
            for row in rows:
                key = row["option_name"]
                if key not in result:
                    continue
                value = row["option_value"]
                result[key] = value == "1" if isinstance(defaults[key], bool) else int(value)
        return result

    def save_spam_options(self, chat_id: str, options: dict[str, bool | int]) -> None:
        with self._conn() as db:
            db.executemany(
                """INSERT INTO spam_options(chat_id,option_name,option_value) VALUES(?,?,?)
                ON CONFLICT(chat_id,option_name) DO UPDATE SET option_value=excluded.option_value""",
                [
                    (chat_id, key, "1" if value is True else "0" if value is False else str(value))
                    for key, value in options.items()
                ],
            )

    def add_filter_word(self, chat_id: str, phrase: str, actor_id: str) -> None:
        with self._conn() as db:
            db.execute(
                """INSERT INTO filter_words(chat_id,phrase,created_by) VALUES(?,?,?)
                ON CONFLICT(chat_id,phrase) DO UPDATE SET created_by=excluded.created_by""",
                (chat_id, phrase.casefold(), actor_id),
            )

    def remove_filter_word(self, chat_id: str, phrase: str) -> bool:
        with self._conn() as db:
            return bool(db.execute(
                "DELETE FROM filter_words WHERE chat_id=? AND phrase=?",
                (chat_id, phrase.casefold()),
            ).rowcount)

    def clear_filter_words(self, chat_id: str) -> int:
        with self._conn() as db:
            return db.execute("DELETE FROM filter_words WHERE chat_id=?", (chat_id,)).rowcount

    def list_filter_words(self, chat_id: str) -> list[str]:
        with self._conn() as db:
            return [row[0] for row in db.execute(
                "SELECT phrase FROM filter_words WHERE chat_id=? ORDER BY phrase",
                (chat_id,),
            )]

    def link_processing_enabled(self, chat_id: str) -> bool:
        with self._conn() as db:
            row = db.execute(
                "SELECT enabled FROM link_processing WHERE chat_id=?", (chat_id,),
            ).fetchone()
        return bool(row[0]) if row else False

    def save_link_processing(self, chat_id: str, enabled: bool) -> None:
        with self._conn() as db:
            db.execute(
                """INSERT INTO link_processing(chat_id,enabled) VALUES(?,?)
                ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled""",
                (chat_id, int(enabled)),
            )

    def record_link(
        self, chat_id: str, message_id: int, sender_id: str,
        link: str, link_type: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as db:
            db.execute(
                """INSERT INTO link_reports(
                    created_at,chat_id,message_id,sender_id,link,link_type
                ) VALUES(?,?,?,?,?,?)""",
                (now, chat_id, str(message_id), sender_id, link, link_type),
            )

    def recent_links(self, chat_id: str, limit: int = 10) -> list[dict[str, str]]:
        safe_limit = max(1, min(int(limit), 50))
        with self._conn() as db:
            rows = db.execute(
                """SELECT created_at,message_id,sender_id,link,link_type
                FROM link_reports WHERE chat_id=? ORDER BY id DESC LIMIT ?""",
                (chat_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def support_contact(self, chat_id: str) -> str:
        with self._conn() as db:
            row = db.execute(
                "SELECT contact_text FROM support_settings WHERE chat_id=?", (chat_id,),
            ).fetchone()
        return str(row[0]) if row else ""

    def save_support_contact(self, chat_id: str, contact_text: str) -> None:
        with self._conn() as db:
            db.execute(
                """INSERT INTO support_settings(chat_id,contact_text) VALUES(?,?)
                ON CONFLICT(chat_id) DO UPDATE SET contact_text=excluded.contact_text""",
                (chat_id, contact_text),
            )
