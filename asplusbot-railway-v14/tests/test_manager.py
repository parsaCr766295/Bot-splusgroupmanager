import asyncio
from datetime import datetime, timedelta, timezone

from splus_manager.models import Message
from splus_manager.service import Manager
from splus_manager.service import _chat_id_matches
from splus_manager.soropy_gateway import SoroPyGateway
from splus_manager.storage import Store


class FakeGateway:
    def __init__(self):
        self.admins = {"admin"}
        self.messages = {2: Message("group", 2, "member", "hello")}
        self.deleted, self.banned, self.muted, self.sent = [], [], [], []
        self.members = [
            {"id": "member", "name": "عضو نمونه", "username": "sample"},
            {"id": "no_username", "name": "بدون نام کاربری", "username": ""},
        ]
        self.reject_formatted_mentions = False
        self.default_permissions_calls = []
        self.permissions_success = True
    async def is_group_admin(self, chat_id, user_id): return user_id in self.admins
    async def get_message(self, chat_id, message_id): return self.messages.get(message_id)
    async def delete_message(self, chat_id, message_id): self.deleted.append(message_id)
    async def restrict_member(self, chat_id, user_id, duration): self.muted.append((user_id, duration))
    async def ban_member(self, chat_id, user_id): self.banned.append(user_id)
    async def send_message(self, chat_id, text):
        if self.reject_formatted_mentions and "](@" in text:
            raise RuntimeError("BAD_REQUEST")
        self.sent.append(text)
    async def list_members(self, chat_id, limit=500): return self.members[:limit]
    async def inspect_message(self, message): return message
    async def set_default_permissions(self, chat_id, permissions):
        self.default_permissions_calls.append(dict(permissions))
        return self.permissions_success


def run(coro): return asyncio.run(coro)


def test_mtproto_numeric_group_id_matches_resolved_entity_id():
    assert _chat_id_matches("-1000023793981", {"23793981"})
    assert _chat_id_matches("@TestGroups", {"testgroups"})


def test_manager_accepts_resolved_numeric_group_alias(tmp_path):
    gateway = FakeGateway()
    manager = Manager(
        gateway,
        Store(str(tmp_path / "db.sqlite")),
        "@TestGroups",
        managed_chat_aliases={"23793981"},
    )
    run(manager.handle(Message("-1000023793981", 1, "admin", "🤖 وضعیت")))
    assert gateway.sent[-1].startswith("🤖 پنل وضعیت مدیر گروه")


def test_non_admin_cannot_ban(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "member", "🚫 مسدود کردن", 2)))
    assert gateway.banned == []


def test_warning_limit_mutes_member(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    for message_id in range(3, 6):
        run(manager.handle(Message("group", message_id, "admin", "⚠️ اخطار", 2)))
    assert gateway.muted == [("member", timedelta(minutes=60))]


def test_anti_link_deletes_and_logs(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "⚙️ تنظیمات ضدلینک=روشن")))
    run(manager.handle(Message("group", 4, "member", "https://example.com")))
    assert gateway.deleted == [4]


def test_admin_can_add_and_trigger_auto_reply(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "اضافه کردن جواب سلام | درود دوست من")))
    run(manager.handle(Message("group", 4, "member", "سلام")))
    assert gateway.sent[-1] == "درود دوست من"


def test_non_admin_cannot_add_reply(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "member", "افزودن جواب سلام | جواب")))
    run(manager.handle(Message("group", 4, "member", "سلام")))
    assert "جواب" not in gateway.sent


def test_call_members_uses_username_mentions_and_custom_text(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "صدا زدن اعضا جلسه شروع شد")))
    assert "جلسه شروع شد" in gateway.sent[0]
    assert "بخش 1 از 1" in gateway.sent[0]
    assert "[عضو نمونه](@sample)" in gateway.sent[0]
    assert "بدون نام کاربری" in gateway.sent[0]
    assert gateway.sent[-1] == "✅ فراخوان 2 عضو در 1 بخش انجام شد."


def test_tag_replied_member(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "تگ لطفاً پاسخ بده", 2)))
    assert gateway.sent == ["[عضو نمونه](@sample) لطفاً پاسخ بده"]


def test_bad_request_retries_tag_as_plain_username(tmp_path):
    gateway = FakeGateway()
    gateway.reject_formatted_mentions = True
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "تگ لطفاً پاسخ بده", 2)))
    assert gateway.sent == ["@sample لطفاً پاسخ بده"]


def test_empty_member_list_explains_server_limitation(tmp_path):
    gateway = FakeGateway()
    gateway.members = []
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "صدا زدن اعضا")))
    assert "فهرست اعضای این گروه" in gateway.sent[0]


class EmptyParticipantsClient:
    def get_participants(self, chat_id, limit=200):
        return []


def test_gateway_uses_recent_senders_when_server_list_is_empty():
    gateway = SoroPyGateway(EmptyParticipantsClient())
    gateway.remember_message(Message("group", 1, "42", "سلام", sender_name="علی"))
    members = run(gateway.list_members("group"))
    assert members == [{"id": "42", "name": "علی", "username": "", "source": "observed"}]


def test_large_group_is_sent_in_multiple_batches(tmp_path):
    gateway = FakeGateway()
    gateway.members = [
        {"id": str(index), "name": f"عضو {index}", "username": f"user{index}"}
        for index in range(45)
    ]
    manager = Manager(
        gateway,
        Store(str(tmp_path / "db.sqlite")),
        "group",
        call_batch_size=20,
        call_batch_delay=0,
    )
    run(manager.handle(Message("group", 3, "admin", "صدا زدن اعضا جلسه شروع شد")))
    batch_messages = [text for text in gateway.sent if text.startswith("📣")]
    assert len(batch_messages) == 3
    assert "بخش 1 از 3" in batch_messages[0]
    assert "بخش 3 از 3" in batch_messages[2]
    assert gateway.sent[-1] == "✅ فراخوان 45 عضو در 3 بخش انجام شد."


def test_all_locks_admin_only_blocks_member_but_allows_admin(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل همه فقط ادمین")))
    run(manager.handle(Message("group", 4, "member", "پیام معمولی")))
    run(manager.handle(Message("group", 5, "admin", "پیام مدیر")))
    assert gateway.deleted == [4]


def test_completely_locked_send_blocks_admin_normal_message(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل ارسال کاملاً قفل")))
    run(manager.handle(Message("group", 4, "admin", "پیام معمولی مدیر")))
    assert gateway.deleted == [4]


def test_media_and_forward_locks_use_message_metadata(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل رسانه فقط ادمین")))
    run(manager.handle(Message("group", 4, "admin", "قفل فوروارد فقط ادمین")))
    run(manager.handle(Message("group", 5, "member", content_type="photo")))
    run(manager.handle(Message("group", 6, "member", "فوروارد", is_forwarded=True)))
    assert gateway.deleted == [5, 6]


def test_lock_settings_persist_and_status_lists_all_modes(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل لینک کاملاً قفل")))
    restarted = Manager(gateway, Store(path), "group")
    run(restarted.handle(Message("group", 4, "admin", "قفل وضعیت")))
    assert "لینک و آیدی: کاملاً قفل" in gateway.sent[-1]
    assert "فوروارد: آزاد" in gateway.sent[-1]


def test_telegram_style_media_permission_is_applied_server_side(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "دسترسی رسانه خاموش")))
    assert gateway.default_permissions_calls[-1]["send_media"] is False
    assert gateway.default_permissions_calls[-1]["send_messages"] is True
    assert gateway.sent[-1] == "رسانه و فایل: قفل شد 🔒"


def test_short_lock_and_unlock_permission_commands(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل نظرسنجی")))
    run(manager.handle(Message("group", 4, "admin", "بازکردن نظرسنجی")))
    assert gateway.default_permissions_calls[0]["send_polls"] is False
    assert gateway.default_permissions_calls[1]["send_polls"] is True


def test_advanced_permissions_persist_and_show_status(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 3, "admin", "دسترسی افزودن عضو خاموش")))
    restarted = Manager(gateway, Store(path), "group")
    run(restarted.handle(Message("group", 4, "admin", "دسترسی‌ها")))
    assert "🔒 افزودن عضو" in gateway.sent[-1]
    assert "✅ ارسال پیام" in gateway.sent[-1]


def test_failed_server_permission_change_is_not_saved(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    gateway.permissions_success = False
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 3, "admin", "قفل استیکر")))
    gateway.permissions_success = True
    restarted = Manager(gateway, Store(path), "group")
    run(restarted.handle(Message("group", 4, "admin", "دسترسی‌ها")))
    assert "✅ استیکر" in gateway.sent[-1]


def test_ad_filter_deletes_link_and_username_but_exempts_admin(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "حذف تبلیغات لینک روشن")))
    run(manager.handle(Message("group", 4, "admin", "حذف تبلیغات آیدی روشن")))
    run(manager.handle(Message("group", 5, "member", "عضویت: https://example.com")))
    run(manager.handle(Message("group", 6, "member", "پیام به @sample_shop")))
    run(manager.handle(Message("group", 7, "admin", "https://admin.example")))
    assert gateway.deleted == [5, 6]


def test_ad_filter_detects_phone_forward_and_promotional_phrases(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "حذف تبلیغات همه روشن")))
    run(manager.handle(Message("group", 4, "member", "تماس 09123456789")))
    run(manager.handle(Message("group", 5, "member", "خبر", is_forwarded=True)))
    run(manager.handle(Message("group", 6, "member", "فروش ویژه با تخفیف عالی")))
    assert gateway.deleted == [4, 5, 6]


def test_ad_keyword_filter_avoids_single_common_word(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "حذف تبلیغات کلمات روشن")))
    run(manager.handle(Message("group", 4, "member", "این کانال امروز به‌روزرسانی شد")))
    assert gateway.deleted == []


def test_ad_filter_settings_persist_and_show_status(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 3, "admin", "حذف تبلیغات شماره روشن")))
    restarted = Manager(gateway, Store(path), "group")
    run(restarted.handle(Message("group", 4, "admin", "حذف تبلیغات وضعیت")))
    assert "✅ شماره تماس" in gateway.sent[-1]
    assert "⭕ لینک و لینک دعوت" in gateway.sent[-1]


def test_manual_chat_close_and_open_change_real_permission(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 3, "admin", "چت بسته")))
    run(manager.handle(Message("group", 4, "admin", "چت باز")))
    assert gateway.default_permissions_calls[0]["send_messages"] is False
    assert gateway.default_permissions_calls[1]["send_messages"] is True


def test_overnight_chat_schedule_closes_and_reopens(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    store.save_chat_schedule(
        "group", enabled=True, close_time="23:00", open_time="07:00",
        timezone="+00:00", last_state=None,
    )
    manager = Manager(gateway, store, "group", schedule_timezone="+00:00")
    changed = run(manager.scheduled_tick(datetime(2026, 8, 20, 23, 30, tzinfo=timezone.utc)))
    repeated = run(manager.scheduled_tick(datetime(2026, 8, 20, 23, 40, tzinfo=timezone.utc)))
    reopened = run(manager.scheduled_tick(datetime(2026, 8, 21, 7, 30, tzinfo=timezone.utc)))
    assert (changed, repeated, reopened) == (True, False, True)
    assert gateway.default_permissions_calls[0]["send_messages"] is False
    assert gateway.default_permissions_calls[1]["send_messages"] is True


def test_chat_schedule_command_accepts_persian_digits_and_persists(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group", schedule_timezone="+03:30")
    run(manager.handle(Message("group", 3, "admin", "چت خودکار ۲۳:۰۰ تا ۰۷:۰۰")))
    schedule = store.chat_schedule("group")
    assert schedule["enabled"] is True
    assert schedule["close_time"] == "23:00"
    assert schedule["open_time"] == "07:00"


def test_chat_schedule_can_be_disabled(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    store.save_chat_schedule(
        "group", enabled=True, close_time="23:00", open_time="07:00",
        timezone="+03:30",
    )
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 3, "admin", "چت خودکار خاموش")))
    assert store.chat_schedule("group")["enabled"] is False


def test_emergency_chat_closes_immediately(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 3, "admin", "چت اضطراری ۳۰دقیقه")))
    assert gateway.default_permissions_calls[-1]["send_messages"] is False
    assert store.chat_schedule("group")["emergency_until"] is not None
    assert "برای 30 دقیقه بسته شد" in gateway.sent[-1]


def test_expired_emergency_reopens_without_regular_schedule(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    store.save_chat_schedule(
        "group", enabled=False, close_time="23:00", open_time="07:00",
        timezone="+00:00", last_state="emergency",
        emergency_until="2026-08-20T10:00:00+00:00",
    )
    manager = Manager(gateway, store, "group", schedule_timezone="+00:00")
    changed = run(manager.scheduled_tick(datetime(2026, 8, 20, 10, 1, tzinfo=timezone.utc)))
    assert changed is True
    assert gateway.default_permissions_calls[-1]["send_messages"] is True
    assert store.chat_schedule("group")["emergency_until"] is None


def test_cancel_emergency_reopens_chat(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 3, "admin", "چت اضطراری ۲ساعت")))
    run(manager.handle(Message("group", 4, "admin", "چت اضطراری لغو")))
    assert gateway.default_permissions_calls[-1]["send_messages"] is True
    assert store.chat_schedule("group")["emergency_until"] is None


def test_flood_deletes_message_after_configured_limit(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 10, "admin", "ضداسپم روشن")))
    for message_id in range(11, 17):
        run(manager.handle(Message("group", message_id, "member", f"پیام {message_id}")))
    assert gateway.deleted == [16]


def test_duplicate_spam_deletes_third_identical_message(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 10, "admin", "ضداسپم روشن")))
    for message_id in range(11, 14):
        run(manager.handle(Message("group", message_id, "member", "پیام تکراری")))
    assert gateway.deleted == [13]


def test_excess_mentions_and_repeated_characters_are_deleted(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 10, "admin", "ضداسپم روشن")))
    mentions = " ".join(f"@user{index}" for index in range(6))
    run(manager.handle(Message("group", 11, "member", mentions)))
    run(manager.handle(Message("group", 12, "other", "ا" * 13)))
    assert gateway.deleted == [11, 12]


def test_admin_is_exempt_from_anti_spam(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 10, "admin", "ضداسپم روشن")))
    for message_id in range(11, 20):
        run(manager.handle(Message("group", message_id, "admin", "تکرارررررررررررررر")))
    assert gateway.deleted == []


def test_word_filter_add_enable_match_and_admin_exemption(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 10, "admin", "فیلتر افزودن کلمه بد")))
    run(manager.handle(Message("group", 11, "admin", "فیلتر روشن")))
    run(manager.handle(Message("group", 12, "member", "این یک کلمه بد است")))
    run(manager.handle(Message("group", 13, "admin", "این یک کلمه بد است")))
    assert gateway.deleted == [12]
    assert store.list_filter_words("group") == ["کلمه بد"]


def test_single_word_filter_observes_word_boundaries(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 10, "admin", "فیلتر افزودن بد")))
    run(manager.handle(Message("group", 11, "admin", "فیلتر روشن")))
    run(manager.handle(Message("group", 12, "member", "بدون مشکل")))
    run(manager.handle(Message("group", 13, "member", "این بد است")))
    assert gateway.deleted == [13]


def test_spam_numeric_settings_persist_and_show_status(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 10, "admin", "ضداسپم سرعت 7 در 20")))
    run(manager.handle(Message("group", 11, "admin", "ضداسپم منشن 8")))
    restarted = Manager(gateway, Store(path), "group")
    run(restarted.handle(Message("group", 12, "admin", "ضداسپم وضعیت")))
    assert "بیش از 7 پیام در 20 ثانیه" in gateway.sent[-1]
    assert "بیش از 8 آیدی" in gateway.sent[-1]


def test_link_processing_logs_all_links_without_deleting_message(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 20, "admin", "پردازش لینک روشن")))
    run(manager.handle(Message(
        "group", 21, "member",
        "🔗 گروه https://splus.ir/example و سایت https://example.com/page",
    )))
    reports = store.recent_links("group", 10)
    assert [item["link_type"] for item in reports] == ["website", "group_channel"]
    assert gateway.deleted == []


def test_link_processing_is_off_by_default(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 20, "member", "https://example.com")))
    assert store.recent_links("group") == []


def test_link_report_command_lists_sender_message_and_type(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 20, "admin", "پردازش لینک روشن")))
    run(manager.handle(Message("group", 21, "member", "t.me/sample_channel")))
    run(manager.handle(Message("group", 22, "admin", "پردازش لینک گزارش")))
    assert "گروه/کانال" in gateway.sent[-1]
    assert "عضو: member" in gateway.sent[-1]
    assert "پیام: 21" in gateway.sent[-1]
    assert "t.me/sample_channel" in gateway.sent[-1]


def test_link_processing_setting_persists(tmp_path):
    path = str(tmp_path / "db.sqlite")
    gateway = FakeGateway()
    manager = Manager(gateway, Store(path), "group")
    run(manager.handle(Message("group", 20, "admin", "پردازش لینک روشن")))
    restarted_store = Store(path)
    restarted = Manager(gateway, restarted_store, "group")
    run(restarted.handle(Message("group", 21, "member", "www.example.org/test")))
    assert restarted_store.recent_links("group")[0]["link"] == "www.example.org/test"


def test_help_command_displays_all_command_sections(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 30, "admin", "📋 راهنما")))
    help_text = gateway.sent[-1]
    assert "مدیریت اعضا" in help_text
    assert "ضداسپم" in help_text
    assert "پردازش لینک" in help_text
    assert "فیلتر افزودن" in help_text


def test_plain_help_command_uses_same_guide(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 30, "admin", "راهنما")))
    assert gateway.sent[-1].startswith("📋 راهنمای دستورات ربات")


def test_support_is_public_and_explains_when_not_configured(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 40, "member", "📞 پشتیبانی")))
    assert "هنوز راه ارتباط" in gateway.sent[-1]
    assert "مجوز ادمین" not in gateway.sent[-1]


def test_admin_sets_support_and_member_can_view_it(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 40, "admin", "پشتیبانی تنظیم @group_support")))
    run(manager.handle(Message("group", 41, "member", "پشتیبانی")))
    assert "@group_support" in gateway.sent[-1]
    assert store.support_contact("group") == "@group_support"


def test_non_admin_cannot_change_support_contact(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 40, "member", "پشتیبانی تنظیم @attacker")))
    assert store.support_contact("group") == ""
    assert "مجوز ادمین" in gateway.sent[-1]


def test_help_is_available_to_members(tmp_path):
    gateway = FakeGateway()
    manager = Manager(gateway, Store(str(tmp_path / "db.sqlite")), "group")
    run(manager.handle(Message("group", 40, "member", "📋 راهنما")))
    assert gateway.sent[-1].startswith("📋 راهنمای دستورات ربات")


def test_support_description_alias_works_for_member(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    store.save_support_contact("group", "@real_support")
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 50, "member", "ارتباط با پشتیبانی")))
    assert "@real_support" in gateway.sent[-1]


def test_support_markdown_table_text_is_recognized(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    store.save_support_contact("group", "https://example.com/support")
    manager = Manager(gateway, store, "group")
    table = """| 📞 پشتیبانی |
| ----------- |

| ارتباط با پشتیبانی |
| ------------------ |"""
    run(manager.handle(Message("group", 51, "member", table)))
    assert "https://example.com/support" in gateway.sent[-1]


def test_support_setting_command_is_not_mistaken_for_public_request(tmp_path):
    gateway = FakeGateway()
    store = Store(str(tmp_path / "db.sqlite"))
    manager = Manager(gateway, store, "group")
    run(manager.handle(Message("group", 52, "member", "پشتیبانی تنظیم @wrong")))
    assert store.support_contact("group") == ""
    assert "مجوز ادمین" in gateway.sent[-1]
