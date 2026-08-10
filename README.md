# Robot Factor

ربات حرفه‌ای صدور فاکتور فارسی برای تلگرام و روبیکا، با هستهٔ مشترک، PDF راست‌چین،
ثبت مشتری و کالا، کنترل دسترسی دو شریک و تاریخچهٔ تغییرناپذیر فاکتورها.

## قابلیت‌های نسخهٔ فعلی

- اتصال رسمی به Telegram Bot API و Rubika Bot API از طریق webhook
- یک جریان مکالمهٔ یکسان روی هر دو پیام‌رسان
- allow-list بر اساس شناسهٔ ثابت کاربر، نه username
- فاکتور و پیش‌فاکتور با شماره‌گذاری مستقل و اتمیک
- ثبت مشتری، کالای کاتالوگی یا کالای دستی
- محاسبهٔ صحیح تخفیف ردیف، تخفیف کلی، مالیات، حمل، پرداخت و مانده
- توزیع متناسب تخفیف کلی بین اقلام پیش از محاسبه مالیات
- ذخیره snapshot نام، قیمت و واحد کالا در هر فاکتور
- PDF فارسی A4 با لوگو، مهر، اطلاعات بانکی و واحد ریال/تومان
- API مدیریت امن برای اطلاعات شرکت، کالا، مشتری و فاکتور
- PostgreSQL در production و SQLite برای توسعه
- ثبت رویدادهای تکراری برای جلوگیری از پردازش دوباره webhook
- Docker، migration، health check و تست‌های خودکار

> این پروژه فاکتور فروش/PDF تولید می‌کند. اتصال به سامانه‌های مالیاتی یا صدور
> صورتحساب الکترونیکی رسمی، ماژول جداگانه و نیازمند اطلاعات حقوقی کسب‌وکار است.

## اجرای محلی

Python 3.12 تا 3.14 پشتیبانی می‌شود؛ تصویر Docker از Python 3.13 استفاده می‌کند.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
robot-factor init-db
robot-factor serve
```

سپس وضعیت سرویس در `http://localhost:8000/healthz` قابل بررسی است. در محیط توسعه،
Swagger در `http://localhost:8000/docs` فعال است.

## تنظیم دسترسی دو شریک

در `.env` شناسه‌ها را به شکل زیر قرار دهید:

```dotenv
ADMIN_IDENTITIES=telegram:123456789,telegram:987654321,rubika:u0123,rubika:u0456
```

اگر هر شریک در هر دو پیام‌رسان کار می‌کند، چهار identity خواهیم داشت. توکن‌ها و کلیدها
نباید commit شوند. فایل `.env` در `.gitignore` قرار دارد.

## پیکربندی فروشگاه

هدر `X-Admin-Key` باید برابر `ADMIN_API_KEY` باشد. نمونهٔ ویرایش اطلاعات شرکت:

```powershell
$headers = @{ "X-Admin-Key" = "YOUR_ADMIN_API_KEY" }
$body = @{
  brand_name = "زغال نمونه"
  legal_name = "شرکت نمونه"
  phone = "02100000000"
  website = "https://example.com"
  money_unit = "تومان"
  invoice_prefix = "CH"
  proforma_prefix = "PCH"
  card_number = "0000000000000000"
  account_holder = "نام صاحب حساب"
} | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri http://localhost:8000/api/v1/company -Headers $headers -ContentType "application/json" -Body $body
```

ثبت یک کالا:

```powershell
$product = @{
  sku = "CHARCOAL-LEMON-A"
  name = "زغال لیمو ممتاز"
  grade = "درجه یک"
  packaging = "کارتن ۸ کیلوگرمی"
  unit = "کارتن"
  weight_per_package = 8
  default_unit_price = 250000
  vat_rate = 0
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/products -Headers $headers -ContentType "application/json" -Body $product
```

برای لوگو و مهر، فایل‌ها را در پوشهٔ `branding` قرار دهید و مسیر داخل کانتینر، مانند
`/app/branding/logo.png` و `/app/branding/stamp.png`، را در پروفایل شرکت ذخیره کنید.

## اتصال webhookها

سرور باید دامنهٔ عمومی و HTTPS داشته باشد. بعد از تنظیم `PUBLIC_BASE_URL` و توکن‌ها:

```powershell
robot-factor set-webhooks
```

این فرمان webhook تلگرام را همراه secret header و دو endpoint رسمی روبیکا برای
`ReceiveUpdate` و `ReceiveInlineMessage` ثبت می‌کند.

## اجرای Docker

در `.env` علاوه بر مقادیر امنیتی، رمز PostgreSQL را قرار دهید:

```dotenv
POSTGRES_PASSWORD=a-long-random-password
APP_ENV=production
```

سپس:

```powershell
docker compose up -d --build
docker compose exec app robot-factor set-webhooks
```

در production بهتر است سرویس پشت Caddy، Nginx یا reverse proxy موجود وب‌سایت قرار گیرد
تا TLS و دامنه مدیریت شوند. مسیرهای `data` و دیتابیس باید backup روزانه داشته باشند.

## تست و کنترل کیفیت

```powershell
pytest
ruff check .
```

تست‌ها محاسبات مالی، تغییرناپذیری فاکتور، جریان کامل مکالمه، parsing هر دو پلتفرم و
خروجی HTML راست‌چین را پوشش می‌دهند.
