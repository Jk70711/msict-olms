# MSICT Online Library Management System (OLMS)

A full-featured Django-based Library Management System for the Military Science and Information and Communications Technology (MSICT) college, backed by Oracle 23ai.

---

## Features

- **Role-Based Access Control** – Admin, Librarian, Member roles with per-role dashboards
- **User Management** – Auto-generated usernames/passwords, virtual library card with QR code
- **OTP Authentication** – Forgot password flow via SMS (BEEM Africa) and email (Gmail SMTP)
- **Book Catalog** – Hardcopy and softcopy (free PDF / special borrow), cover images, MARC XML
- **Circulation** – Borrow request → approval → issue → return, renewals, reservations queue
- **Overdue & Fines** – Automatic overdue marking, fine calculation (TZS/day), POS fine collection
- **Public OPAC** – Unauthenticated catalog search with federated search to external libraries
- **Reports** – Members, books, circulation, fines, CSV export, admin SQL console
- **Acquisitions** – Vendors, budgets, purchase orders, serials/subscriptions, ILL, ERM
- **Notifications** – SMS via BEEM Africa API, email via Gmail SMTP
- **Cron Jobs** – Daily overdue check and due-date reminders via management commands
- **Audit Logs** – Every login attempt and key action logged

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Framework | Django 5.1.3 |
| Database | Oracle 23ai (python-oracledb 2.4.1) |
| Frontend | Bootstrap 5 + Bootstrap Icons |
| Image handling | Pillow 10.4.0 |
| QR Code | qrcode 7.4.2 |
| PDF Generation | reportlab 4.2.2 |
| SMS | BEEM Africa API |
| Email | Gmail SMTP |
| Config | python-decouple |

---

## Prerequisites

1. **Python 3.11+**
2. **Oracle 23ai** database running locally (or remote)
3. **Oracle Instant Client** (if using thin mode – not required for `python-oracledb` thick mode)
4. Oracle user `olms_user` with DBA or sufficient privileges

### Create Oracle User

```sql
-- Connect as SYSDBA
ALTER SESSION SET CONTAINER = freepdb1;
CREATE USER olms_user IDENTIFIED BY 12345;
GRANT CONNECT, RESOURCE, CREATE VIEW TO olms_user;
GRANT UNLIMITED TABLESPACE TO olms_user;
```

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd OLMS

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual values (see below)

# 5. Create required directories
mkdir -p media/book_covers media/user_photos media/ebooks static

# 6. Run migrations
python manage.py migrate

# 7. Seed initial data (categories, courses, system preferences)
python manage.py seed_data

# 8. Create the default admin account
python manage.py create_admin

# 9. Collect static files (production)
python manage.py collectstatic --noinput

# 10. Run the development server
python manage.py runserver
```

Open your browser at **http://localhost:8000**

Default admin credentials:
- **Username:** `admin`
- **Password:** `Jonas@26`
- ⚠️ Change this password immediately after first login!

librarian credentials:
- **Username:** `kasubi`
- **Password:** `Msict@26`
- ⚠️ Change this password immediately after first login!

member credentials:
- **Username:** `DIT-0425-00236`
- **Password:** `134052`
- ⚠️ Change this password immediately after first login!

olms-docker-ora
 ✔ olms-web            Built                                                                                0.0s 
 ✔ Container olms_web  Created                                                                              0.0s 
Attaching to olms_web
---

## Environment Variables (`.env`)

```ini
SECRET_KEY=your-django-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Oracle Database
DB_NAME=localhost:1521/freepdb1
DB_USER=olms_user
DB_PASSWORD=12345

# Email (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=jk7college@gmail.com
EMAIL_HOST_PASSWORD=your-gmail-app-password

# BEEM Africa SMS API
BEEM_API_KEY=your-beem-api-key
BEEM_SECRET_KEY=your-beem-secret-key
BEEM_SENDER_NAME=MSICT
```

> **Gmail Setup:** Use an **App Password** (not your account password).  
> Go to Google Account → Security → 2-Step Verification → App Passwords.

---

## Cron Jobs (Linux)

Add to crontab with `crontab -e`:

```cron
# Check for overdue books every day at 01:00 AM
0 1 * * * /path/to/venv/bin/python /path/to/OLMS/manage.py overdue_check >> /var/log/olms_overdue.log 2>&1

# Send due-date reminders every day at 08:00 AM
0 8 * * * /path/to/venv/bin/python /path/to/OLMS/manage.py send_notifications >> /var/log/olms_notify.log 2>&1
```

---

## URL Structure

| URL Prefix | Module |
|------------|--------|
| `/` | Public OPAC (home, catalog search, book detail) |
| `/login/`, `/logout/` | Authentication |
| `/forgot-password/` | OTP-based password reset |
| `/dashboard/` | Role-based redirect (member/librarian/admin) |
| `/catalog/` | Book & copy management (librarian/admin) |
| `/circulation/` | Borrow/return/fine management |
| `/reports/` | Reports & analytics |
| `/acquisitions/` | Vendors, budgets, POs, subscriptions, ILL, ERM |
| `/django-admin/` | Django built-in admin site |

---

## Project Structure

```
OLMS/
├── OLMS/               # Project settings, URLs, WSGI
├── accounts/           # Custom user model, auth, OTP, virtual card
├── catalog/            # Books, copies, categories, courses, external libraries
├── circulation/        # Borrow requests, transactions, fines, notifications
├── acquisitions/       # Vendors, budgets, POs, subscriptions, ILL, ERM
├── reports/            # Reports dashboard and CSV/SQL exports
├── public/             # Public OPAC views
├── templates/          # All HTML templates (Bootstrap 5)
├── static/             # CSS, JS, images
├── media/              # User uploads (book covers, photos, ebooks)
├── schema.sql          # Oracle DDL reference schema
├── requirements.txt    # Python dependencies
└── .env                # Environment variables (not committed)
```

---

## Oracle Schema

A complete DDL reference is provided in `schema.sql`. Django's ORM creates the actual tables via migrations.  
Use `schema.sql` for:
- Manual review of table structure
- Setting up the Oracle user and granting privileges
- Recreating the schema from scratch without running Django migrations

---

## License

Internal use only – MSICT College. All rights reserved.
