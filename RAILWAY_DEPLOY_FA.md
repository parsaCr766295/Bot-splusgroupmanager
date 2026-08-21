# ☁️ راه‌اندازی مدیر گروه سروش‌پلاس روی Railway

این ربات سرویس HTTP نیست و به Public Domain یا متغیر `PORT` نیاز ندارد.

برای ماندگاری SQLite و Session ورود، باید یک Volume روی `/data` متصل شود.

> این راهنما برای Repository **Public** نوشته شده است. اطلاعات حساس فقط باید در Railway Variables و Volume خصوصی نگهداری شوند.

---

## 1. آماده‌سازی GitHub Public

قبل از Push مطمئن شوید این موارد Commit نشده‌اند:

```text
.env
data/
session/
*.session
*.db
*.sqlite
*.sqlite3
logs/
```

شماره تلفن، کد ورود، Session، Token، Secret و اطلاعات خصوصی گروه را نیز داخل README یا فایل‌های پروژه ننویسید.

---

## 2. ساخت سرویس

در Railway:

```text
New Project > Deploy from GitHub repo
```

Repository عمومی پروژه را انتخاب کنید.

فایل‌های:

```text
railway.json
Dockerfile
```

Build و اجرای Worker را تنظیم می‌کنند.

در Build موفق باید پیام مربوط به نصب وابستگی `soropy` دیده شود.

این Worker به Public Domain نیاز ندارد.

---

## 3. Variables

در:

```text
Railway > Service > Variables
```

مقادیر واقعی را وارد کنید:

```text
SOROUSH_GROUP_ID=شناسه_دقیق_گروه
SOROUSH_GROUP_TARGET=@username_group
SOROUSH_PHONE=+98xxxxxxxxxx
SOROUSH_BACKEND=websocket

DATABASE_PATH=/data/manager.db
SESSION_DIR=/data/session

CHAT_SCHEDULE_TIMEZONE=+03:30
CHAT_SCHEDULE_CHECK_SECONDS=20
OUTGOING_COMMAND_CHECK_SECONDS=3

CALL_MEMBERS_LIMIT=500
CALL_MEMBERS_BATCH=20
CALL_MEMBERS_DELAY_SECONDS=1.5
```

اگر شناسه عددی رویداد و Username گروه متفاوت‌اند، هر دو متغیر `SOROUSH_GROUP_ID` و `SOROUSH_GROUP_TARGET` را تنظیم کنید.

---

## 4. Volume

از Project Canvas یک Volume بسازید و به همین Service متصل کنید.

Mount Path:

```text
/data
```

Volume را **قبل از ورود اولیه** متصل کنید.

اطلاعات مهم روی Volume:

```text
/data/manager.db
/data/session/
```

جداکردن یا حذف Volume باعث ازدست‌رفتن Session و دیتابیس می‌شود.

---

## 5. ورود اولیه

از Dashboard گزینه `Copy SSH Command` را بگیرید یا از CLI اجرا کنید:

```bash
railway ssh
```

داخل سرویس:

```bash
python -m splus_manager --login-only
```

کد دریافت‌شده از سروش‌پلاس را فقط در Terminal وارد کنید.

پس از موفقیت، از SSH خارج شوید و Deployment را Restart کنید:

```bash
railway restart
```

---

## 6. بررسی اجرا

در Logs باید پیام مشابه زیر دیده شود:

```text
مدیر گروه فعال است
```

سپس داخل گروه:

```text
🤖 وضعیت
```

نسخه Railway فرمان‌هایی را که با همان حساب واردشده ارسال می‌شوند نیز به‌صورت دوره‌ای بررسی می‌کند.

مقدار پیش‌فرض:

```text
OUTGOING_COMMAND_CHECK_SECONDS=3
```

بنابراین فرمان‌هایی مانند `پنل` و `🤖 وضعیت` باید طی چند ثانیه پردازش شوند.

شناسه عددی گروه نیز می‌تواند از روی `SOROUSH_GROUP_TARGET` تشخیص داده و در Log ثبت شود.

---

## 7. فقط یک Replica

تعداد Replica را روی:

```text
1
```

نگه دارید.

اجرای هم‌زمان یک Session در چند Replica ممکن است باعث:

- قطع اتصال
- تداخل Session
- دریافت تکراری رویداد
- پاسخ تکراری
- خرابی نشست

شود.

---

## 8. عیب‌یابی سریع

اگر `پنل` یا `🤖 وضعیت` پاسخ نداد:

1. `SOROUSH_GROUP_ID` را بررسی کنید.
2. `SOROUSH_GROUP_TARGET` را بررسی کنید.
3. مطمئن شوید حساب در گروه ادمین است.
4. Logs اتصال WebSocket را بررسی کنید.
5. `OUTGOING_COMMAND_CHECK_SECONDS` را بررسی کنید.
6. وجود Session در `/data/session` را بررسی کنید.
7. مطمئن شوید Volume واقعاً روی `/data` Mount شده است.
8. تعداد Replica را روی 1 نگه دارید.

---

## 9. امنیت در GitHub Public

مقادیر واقعی Railway Variables را هرگز در GitHub قرار ندهید.

اگر Secret یا Session قبلاً Commit شده باشد:

1. آن را افشاشده فرض کنید.
2. Credential/Session را تعویض کنید.
3. Git History را بررسی و در صورت نیاز پاک‌سازی کنید.
4. سپس Repository را Public نگه دارید.

فایل `.env.example` فقط باید مقادیر نمونه و غیرواقعی داشته باشد.
