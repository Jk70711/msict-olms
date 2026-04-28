# 📚 MSICT OLMS — Mfumo Kamili wa Maelezo (Kiswahili)
> **Online Library Management System** — Shule ya Teknolojia ya Habari ya Jeshi (MSICT)

---

## 📁 1. MUUNDO WA MRADI (Project Structure)

```
OLMS/                          ← Folda kuu ya mradi wote
│
├── OLMS/                      ← Mipangilio ya Django (settings, urls, wsgi)
│   ├── settings.py            ← Mipangilio yote ya mfumo (DB, email, hosts...)
│   ├── urls.py                ← URL kuu — inaelekeza kwa apps zote
│   ├── wsgi.py                ← Mlango wa seva ya uzalishaji (Gunicorn)
│   └── asgi.py                ← Mlango wa seva ya async (si lazima kwa sasa)
│
├── accounts/                  ← App ya watumiaji (login, watumiaji, OTP...)
├── catalog/                   ← App ya vitabu (vitabu, nakala, rafu, kategoria...)
├── circulation/               ← App ya mikopo (kukopa, kurudisha, faini, uhifadhi...)
├── acquisitions/              ← App ya manunuzi (bajeti, wauzaji, amri za kununua...)
├── reports/                   ← App ya ripoti na takwimu
├── public/                    ← App ya umma (ukurasa wa nyumbani, tafuta vitabu)
│
├── templates/                 ← Templeti zote za HTML zimewekwa hapa
│   ├── base.html              ← Templeti mama — sidebar, topbar, footer
│   ├── accounts/              ← Ukurasa wa login, watumiaji, OTP
│   ├── catalog/               ← Ukurasa wa vitabu, nakala, rafu
│   ├── circulation/           ← Ukurasa wa mikopo, maombi, faini
│   ├── acquisitions/          ← Ukurasa wa manunuzi
│   ├── reports/               ← Ukurasa wa ripoti
│   ├── public/                ← Ukurasa wa umma (nyumbani, tafuta)
│   └── partials/              ← Vipande vya HTML (sidebar nav, modali...)
│
├── static/                    ← Faili za CSS, JS, picha za kudumu
├── media/                     ← Faili zilizopakiwa (picha za vitabu, PDF...)
├── manage.py                  ← Amri ya Django (migrate, runserver...)
├── requirements.txt           ← Maktaba zote za Python zinazohitajika
├── .env                       ← Siri za mfumo (DB password, SECRET_KEY, hosts)
└── .env.example               ← Mfano wa jinsi .env inavyopaswa kuonekana
```

---

## 🏗️ 2. JINSI DJANGO INAVYOFANYA KAZI (Muhtasari)

```
Mtumiaji anabonyeza URL
        ↓
OLMS/urls.py (gatekeeper mkuu)
        ↓
App husika urls.py (e.g. catalog/urls.py)
        ↓
View husika (views.py) — inafanya kazi, inasoma DB
        ↓
Model (models.py) — inawasiliana na Oracle Database
        ↓
Template (HTML) — inonyesha matokeo kwa mtumiaji
```

---

## 👤 3. APP: `accounts` — Watumiaji na Ulinzi

### 📊 Mifano ya Data (models.py)

| Model | Jedwali DB | Maelezo |
|-------|-----------|---------|
| `OLMSUser` | `users` | Mtumiaji mkuu — ana jukumu, army number, jina, nywila |
| `LoginAttempt` | `login_attempts` | Rekodi ya kila jaribio la kuingia |
| `OTPRecord` | `otp_records` | Nambari ya siri ya mara moja (OTP) kwa kubadilisha nywila |
| `UserSession` | `user_sessions` | Rekodi ya kila kipindi cha mtumiaji (login/logout) |
| `VirtualCard` | `virtual_cards` | Kadi ya maktaba ya kidijitali (QR code, barcode) |
| `AuditLog` | `audit_logs` | Historia ya kila kitendo kikubwa kwenye mfumo |
| `SystemPreference` | `system_preferences` | Mipangilio ya mfumo (siku za mkopo, rangi, fonti...) |
| `BlockedIP` | `blocked_ips` | Anwani za IP zilizozuiwa |

### 🔑 Sehemu Muhimu za `OLMSUser`

```python
role = 'admin' | 'librarian' | 'member'   # Jukumu la mtumiaji
member_type = 'student' | 'lecturer' | 'staff'  # Aina ya mwanachama
army_no = CharField  # Nambari ya jeshi (e.g. MT 134513) — LAZIMA
username = CharField  # Jina la kuingia — kinatengenezwa otomatiki
theme = 'light' | 'dark'  # Mandhari ya mtumiaji
```

### 🌐 URL za `accounts`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/login/` | `login` | Ukurasa wa kuingia |
| `/logout/` | `logout` | Kutoka nje |
| `/forgot-password/` | `forgot_password` | Omba OTP kwa kubadilisha nywila |
| `/verify-otp/` | `verify_otp` | Thibitisha OTP |
| `/reset-password/` | `reset_password` | Weka nywila mpya |
| `/dashboard/` | `dashboard` | Elekeza kwa dashboard sahihi kulingana na jukumu |
| `/profile/` | `profile` | Ukurasa wa wasifu wa mtumiaji |
| `/change-password/` | `change_password` | Badilisha nywila |
| `/virtual-card/` | `virtual_card` | Angalia kadi ya maktaba |
| `/users/` | `user_list` | Orodha ya watumiaji wote (librarian/admin) |
| `/users/create/` | `create_user` | Unda mtumiaji mpya |
| `/users/<id>/edit/` | `edit_user` | Hariri mtumiaji |
| `/admin-dashboard/` | `admin_dashboard` | Dashboard ya msimamizi |
| `/admin/audit-logs/` | `audit_logs` | Historia ya vitendo |
| `/admin/preferences/` | `system_preferences` | Mipangilio ya mfumo |
| `/system-appearance/` | `system_appearance` | Badilisha rangi, fonti, mandhari |

### 📄 Templeti za `accounts/`

| Faili | Maelezo |
|-------|---------|
| `login.html` | Ukurasa wa kuingia — dark theme ya Netflix-style |
| `forgot_password.html` | Omba OTP kwa barua pepe |
| `verify_otp.html` | Weka OTP uliopokea |
| `reset_password.html` | Weka nywila mpya |
| `user_list.html` | Orodha ya watumiaji na kichujio |
| `create_user.html` | Fomu ya kuunda mtumiaji |
| `edit_user.html` | Fomu ya kuhariri mtumiaji |
| `user_detail.html` | Maelezo kamili ya mtumiaji mmoja |
| `profile.html` | Wasifu wa mtumiaji aliyeingia |
| `virtual_card.html` | Kadi ya maktaba ya kidijitali |
| `admin_dashboard.html` | Dashboard ya msimamizi mkuu |
| `system_appearance.html` | Badilisha rangi, fonti, mandhari ya mfumo |
| `system_preferences.html` | Mipangilio ya mfumo (siku za mkopo, faini/siku...) |
| `audit_logs.html` | Historia ya vitendo vyote |

---

## 📖 4. APP: `catalog` — Vitabu na Maktaba

### 📊 Mifano ya Data (models.py)

| Model | Jedwali DB | Maelezo |
|-------|-----------|---------|
| `Category` | `categories` | Somo/Aina ya vitabu (e.g. Sayansi, Historia) |
| `Course` | `courses` | Kozi za shule (zinaunganishwa na Category) |
| `Book` | `books` | Taarifa za kitabu (jina, mwandishi, ISBN...) |
| `BookCopy` | `book_copies` | Nakala halisi ya kitabu (hardcopy au softcopy) |
| `BookCourse` | `book_courses` | Uhusiano wa vitabu na kozi (many-to-many) |
| `Shelf` | `shelves` | Rafu ya kimwili kwenye maktaba |
| `InventoryLog` | `inventory_logs` | Historia ya harakati za nakala (imongezwa, imepotea...) |
| `ExternalLibrary` | `external_libraries` | Maktaba za nje (federated search) |
| `News` | `news` | Habari, matangazo, matukio |
| `MediaSlide` | `media_slides` | Picha za carousel, tangazo, logo ya mfumo |
| `DeletedAccessionNumber` | `deleted_accession_numbers` | Nambari za accession zilizofutwa (zinarekodiwa na kutumika tena) |

### 🔑 Aina za Nakala (BookCopy)

```
copy_type:
  hardcopy → Kitabu cha kawaida (kiko kwenye rafu)
  softcopy → Faili ya kidijitali (PDF)

access_type (kwa softcopy tu):
  free    → Mtu yeyote anaweza kupakua bila idhini
  borrow  → Inahitaji ombi na idhini ya mtunzaji
```

### 🌐 URL za `catalog`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/catalog/books/` | `book_list` | Orodha ya vitabu vyote |
| `/catalog/books/create/` | `book_create` | Unda kitabu kipya |
| `/catalog/books/<id>/` | `book_detail` | Maelezo ya kitabu (kwa mtunzaji) |
| `/catalog/books/<id>/edit/` | `book_edit` | Hariri kitabu |
| `/catalog/books/<id>/add-copy/` | `copy_create` | Ongeza nakala kwa kitabu |
| `/catalog/copies/` | `copy_list` | Orodha ya nakala zote |
| `/catalog/copies/<id>/read/` | `serve_softcopy` | Soma PDF online |
| `/catalog/copies/<id>/download/` | `free_softcopy_download` | Pakua PDF bure |
| `/catalog/categories/` | `category_list` | Orodha ya makategoria |
| `/catalog/shelves/` | `shelf_list_all` | Orodha ya rafu zote |
| `/catalog/media-slides/` | `media_slide_list` | Dhibiti picha za carousel |
| `/catalog/news/` | `news_list` | Dhibiti habari na matangazo |

### 📄 Templeti za `catalog/`

| Faili | Maelezo |
|-------|---------|
| `librarian_dashboard.html` | Dashboard ya mtunzaji — takwimu, maombi, vitabu vipya |
| `book_list.html` | Orodha ya vitabu na kichujio |
| `book_create_form.html` | Fomu ya kuunda kitabu kipya |
| `book_detail.html` | Maelezo ya kitabu (kwa mtunzaji) |
| `book_edit_form.html` | Fomu ya kuhariri kitabu |
| `copy_add_form.html` | Fomu ya kuongeza nakala (hardcopy au softcopy) |
| `copy_list.html` | Orodha ya nakala zote |
| `shelf_list_all.html` | Orodha ya rafu zote na ujazo wao |
| `category_list.html` | Dhibiti makategoria |
| `media_slide_list.html` | Dhibiti picha za carousel na logo |
| `news_list.html` | Dhibiti habari |

---

## 🔄 5. APP: `circulation` — Mikopo na Shughuli

### 📊 Mifano ya Data (models.py)

| Model | Jedwali DB | Maelezo |
|-------|-----------|---------|
| `BorrowRequest` | `borrow_requests` | Ombi la kukopa (pending → approved/rejected) |
| `BorrowingTransaction` | `borrowing_transactions` | Mkopo ulioidhinishwa (borrowed → returned/overdue) |
| `Reservation` | `reservations` | Uhifadhi wa nafasi kwa kitabu kilichokopwa |
| `Fine` | `fines` | Faini ya kuchelewa kurudisha |
| `Notification` | `notifications` | Arifa zilizotumwa (SMS au barua pepe) |

### 🌐 URL za `circulation`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/circulation/member-dashboard/` | `member_dashboard` | Dashboard ya mwanachama |
| `/circulation/borrow/` | `borrow_catalog` | Tafuta na omba kukopa |
| `/circulation/borrow/request/<id>/` | `submit_borrow_request` | Tuma ombi la kukopa |
| `/circulation/borrow/approve/<id>/` | `approve_borrow_request` | Idhinisha ombi (mtunzaji) |
| `/circulation/borrow/reject/<id>/` | `reject_borrow_request` | Kataa ombi (mtunzaji) |
| `/circulation/return-desk/` | `return_desk` | Rudisha kitabu (desk ya mtunzaji) |
| `/circulation/renew/<id>/` | `renew_transaction` | Ongeza muda wa mkopo |
| `/circulation/reserve/<book_id>/` | `reserve_book` | Hifadhi nafasi ya kitabu |
| `/circulation/requests/` | `all_requests` | Maombi yote (kwa mtunzaji) |
| `/circulation/overdue/` | `overdue_list` | Vitabu vilivyochelewa |
| `/circulation/fines/` | `fine_list` | Orodha ya faini |
| `/circulation/my-borrowings/msict/` | `member_msict_borrowings` | Mikopo yangu (kwa mwanachama) |
| `/circulation/softcopy-library/` | `softcopy_library` | Maktaba ya kidijitali |
| `/circulation/reservations/` | `reservation_list` | Orodha ya uhifadhi |

### 📄 Templeti za `circulation/`

| Faili | Maelezo |
|-------|---------|
| `member_dashboard.html` | Dashboard ya mwanachama — mikopo yangu, maombi |
| `borrow_catalog.html` | Tafuta vitabu na tuma ombi |
| `all_requests.html` | Maombi yote yanayosubiri idhini |
| `overdue_list.html` | Vitabu vilivyopita tarehe ya kurudisha |
| `fine_list.html` | Faini zote na hali ya malipo |
| `member_msict_borrowings.html` | Mikopo yangu binafsi |
| `softcopy_library.html` | Vitabu vya kidijitali nilivyokopa |
| `reservation_list.html` | Uhifadhi wote |

---

## 🛒 6. APP: `acquisitions` — Manunuzi ya Vitabu

### 📊 Mifano ya Data

| Model | Jedwali DB | Maelezo |
|-------|-----------|---------|
| `Vendor` | `vendors` | Muuzaji wa vitabu |
| `Budget` | `budgets` | Bajeti ya mwaka wa fedha |
| `Fund` | `funds` | Mgawanyo wa bajeti |
| `PurchaseOrder` | `purchase_orders` | Agizo la kununua vitabu |
| `PurchaseOrderItem` | `purchase_order_items` | Vitabu binafsi kwenye agizo |
| `Invoice` | `invoices` | Ankara kutoka kwa muuzaji |
| `ILLRequest` | `ill_requests` | Ombi la kukopa kutoka maktaba nyingine (ILL) |

### 🌐 URL za `acquisitions`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/acquisitions/vendors/` | `vendor_list` | Orodha ya wauzaji |
| `/acquisitions/budgets/` | `budget_list` | Orodha ya bajeti |
| `/acquisitions/orders/` | `purchase_order_list` | Maagizo ya kununua |
| `/acquisitions/orders/create/` | `purchase_order_create` | Unda agizo jipya |
| `/acquisitions/ill/` | `ill_request_list` | Maombi ya ILL |

---

## 📊 7. APP: `reports` — Ripoti na Takwimu

### 🌐 URL za `reports`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/reports/` | `reports_home` | Ukurasa mkuu wa ripoti |
| `/reports/members/` | `report_members` | Ripoti ya wanachama |
| `/reports/books/` | `report_books` | Ripoti ya vitabu |
| `/reports/circulation/` | `report_circulation` | Ripoti ya mikopo |
| `/reports/fines/` | `report_fines` | Ripoti ya faini |
| `/reports/export/members/csv/` | `export_members_csv` | Pakua wanachama kama CSV |
| `/reports/export/books/csv/` | `export_books_csv` | Pakua vitabu kama CSV |
| `/reports/sql/` | `sql_report` | Ripoti maalum kwa SQL |

---

## 🌍 8. APP: `public` — Kurasa za Umma (Bila Kuingia)

### 🌐 URL za `public`

| URL | Jina | Maelezo |
|-----|------|---------|
| `/` | `home` | Ukurasa wa nyumbani — carousel, takwimu, vitabu vipya |
| `/catalog/` | `catalog_search` | Tafuta vitabu (pagination ya kurasa 12/ukurasa) |
| `/catalog/autocomplete/` | `catalog_autocomplete` | API ya utambuzi wa haraka wa jina la kitabu |
| `/books/<id>/` | `book_detail_public` | Maelezo ya kitabu kwa umma |
| `/api/book/<id>/modal/` | `book_modal_data` | Data ya kitabu kwa modal popup |

---

## 🔄 9. MTIRIRIKO WA VITENDO (Flow of Actions)

### ✅ Kukopa Kitabu cha Kawaida (Hardcopy)

```
1. Mwanachama → /catalog/ → tafuta kitabu
2. Mwanachama → /books/<id>/ → angalia maelezo ya kitabu
3. Mwanachama → /circulation/borrow/ → tafuta na chagua nakala
4. Mwanachama → /circulation/borrow/request/<copy_id>/ → tuma OMBI
   [BorrowRequest inaundwa, hali = 'pending']
5. Mtunzaji → /catalog/librarian-dashboard/ au /circulation/requests/
   → anaona ombi jipya
6. Mtunzaji → approve → /circulation/borrow/approve/<request_id>/
   [BorrowingTransaction inaundwa, hali = 'borrowed']
   [BookCopy hali inabadilika → 'borrowed']
   [Arifa ya SMS/barua pepe inatumwa kwa mwanachama]
7. Mwanachama anakwenda maktaba, apata kitabu
8. Mwanachama → anarudisha kwenye desk ya mtunzaji
9. Mtunzaji → /circulation/return-desk/ → scanisha au weka nambari
   [BorrowingTransaction hali → 'returned']
   [BookCopy hali → 'available']
   [Kama kuna uhifadhi → arifa inatumwa kwa mwanachama anayesubiri]
```

### ✅ Kukopa Kitabu cha Kidijitali (Softcopy - Borrow)

```
1. Mwanachama → /books/<id>/ → bonyeza "Request Softcopy"
2. [BorrowRequest inaundwa]
3. Mtunzaji → idhinisha → /circulation/borrow/approve/<request_id>/
   [BorrowingTransaction inaundwa]
   [Kiungo cha PDF kinatumwa kwa SMS na barua pepe]
4. Mwanachama → /circulation/my-borrowings/msict/ → bonyeza "Read Online"
   → /catalog/copies/<copy_id>/read/ → PDF inafunguka
5. Baada ya siku X (mipangilio), kiungo kinaisha
```

### ✅ Kutuma Uhifadhi (Reservation)

```
1. Kitabu cha hardcopy kimekopwa (hali = 'borrowed')
2. Mwanachama → /books/<id>/ → "Reserve Hardcopy" (inaonekana tu kama imekopwa)
3. → /circulation/reserve/<book_id>/
   [Reservation inaundwa, nafasi = 1 au 2 au...]
   [Arifa inatumwa: "Umehifadhi nafasi #X"]
4. Kitabu kinarudishwa → mfumo unaona kuna uhifadhi
5. Mwanachama #1 anapata arifa: "Kitabu kinasubiri wewe — una siku 7"
6. [Reservation hali → 'fulfilled']
```

### ✅ Kubadilisha Nywila (OTP Flow)

```
1. /forgot-password/ → weka jina la kuingia
2. OTP inatumwa kwa barua pepe [OTPRecord inaundwa]
3. /verify-otp/ → weka OTP
4. /reset-password/ → weka nywila mpya
5. [Nywila inabadilishwa, OTPRecord inaashiria 'used=True']
```

---

## 🗄️ 10. JEDWALI ZOTE ZA DATABASE

| Jedwali | Model | App |
|---------|-------|-----|
| `users` | OLMSUser | accounts |
| `login_attempts` | LoginAttempt | accounts |
| `otp_records` | OTPRecord | accounts |
| `user_sessions` | UserSession | accounts |
| `virtual_cards` | VirtualCard | accounts |
| `audit_logs` | AuditLog | accounts |
| `system_preferences` | SystemPreference | accounts |
| `blocked_ips` | BlockedIP | accounts |
| `categories` | Category | catalog |
| `courses` | Course | catalog |
| `books` | Book | catalog |
| `book_copies` | BookCopy | catalog |
| `book_courses` | BookCourse | catalog |
| `shelves` | Shelf | catalog |
| `inventory_logs` | InventoryLog | catalog |
| `external_libraries` | ExternalLibrary | catalog |
| `news` | News | catalog |
| `media_slides` | MediaSlide | catalog |
| `deleted_accession_numbers` | DeletedAccessionNumber | catalog |
| `borrow_requests` | BorrowRequest | circulation |
| `borrowing_transactions` | BorrowingTransaction | circulation |
| `reservations` | Reservation | circulation |
| `fines` | Fine | circulation |
| `notifications` | Notification | circulation |
| `vendors` | Vendor | acquisitions |
| `budgets` | Budget | acquisitions |
| `funds` | Fund | acquisitions |
| `purchase_orders` | PurchaseOrder | acquisitions |
| `purchase_order_items` | PurchaseOrderItem | acquisitions |
| `invoices` | Invoice | acquisitions |
| `ill_requests` | ILLRequest | acquisitions |

---

## 🛠️ 11. JINSI YA KUFANYA MABADILIKO

---

### ➕ A. Kuongeza Jedwali Jipya (New Table/Model)

**Mfano: Nataka kuongeza jedwali la `BookReview` (maoni ya vitabu)**

**Hatua 1:** Fungua `catalog/models.py`, ongeza model:

```python
class BookReview(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE)
    rating = models.IntegerField()        # Alama 1-5
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'book_reviews'   # Jina la jedwali kwenye Oracle
```

**Hatua 2:** Tengeneza migration:
```bash
python manage.py makemigrations catalog
```

**Hatua 3:** Tekeleza migration (unda jedwali kwenye database):
```bash
python manage.py migrate
```

**Hatua 4:** Kama unataka kuiona kwenye admin panel, ongeza katika `catalog/admin.py`:
```python
from .models import BookReview
admin.site.register(BookReview)
```

---

### ➕ B. Kuongeza Kolamu Mpya (New Column/Field)

**Mfano: Nataka kuongeza `edition` (toleo) kwenye kitabu**

**Hatua 1:** Fungua `catalog/models.py`, tafuta class `Book`, ongeza mstari:

```python
class Book(models.Model):
    isbn = models.CharField(...)
    title = models.CharField(...)
    # ... (fields zilizopo)
    edition = models.CharField(max_length=20, blank=True, default='')  # ← ONGEZA HAPA
```

> ⚠️ Kama ni kolamu lazima (blank=False), ongeza `default='1st'` ili migration isishindwe.

**Hatua 2:** Tengeneza migration:
```bash
python manage.py makemigrations catalog
```

**Hatua 3:** Tekeleza:
```bash
python manage.py migrate
```

**Hatua 4:** Kama unataka ionekane kwenye fomu, ongeza kwenye template husika:
```html
<input type="text" name="edition" value="{{ book.edition }}">
```

**Hatua 5:** Kama unataka ihifadhiwe, ongeza kwenye view:
```python
book.edition = request.POST.get('edition', '')
book.save()
```

---

### ➕ C. Kuongeza URL na Ukurasa Mpya

**Mfano: Nataka ukurasa mpya wa `/catalog/reviews/`**

**Hatua 1:** Ongeza view kwenye `catalog/views.py`:
```python
@login_required
def review_list_view(request):
    reviews = BookReview.objects.all()
    return render(request, 'catalog/review_list.html', {'reviews': reviews})
```

**Hatua 2:** Ongeza URL kwenye `catalog/urls.py`:
```python
path('reviews/', views.review_list_view, name='review_list'),
```

**Hatua 3:** Unda template `templates/catalog/review_list.html`:
```html
{% extends 'base.html' %}
{% block content %}
  {% for review in reviews %}
    <p>{{ review.book.title }} — {{ review.rating }}/5</p>
  {% endfor %}
{% endblock %}
```

**Hatua 4:** Ongeza kiungo kwenye sidebar (`templates/partials/sidebar_nav.html`).

---

### ✏️ D. Kubadilisha Jina la Kolamu

1. Badilisha jina kwenye `models.py`
2. Endesha `makemigrations` na `migrate`
3. Sasisha kila mahali palipotumia jina la zamani kwenye `views.py` na `templates/`

---

### 🗑️ E. Kufuta Jedwali (Model)

1. Futa au toa tofauti model kwenye `models.py`
2. Endesha `makemigrations` na `migrate`
3. Futa kila import na matumizi yake kwenye views na templates

---

### ⚙️ F. Kubadilisha Mipangilio ya Mfumo

Mipangilio ya mfumo (siku za mkopo, faini/siku, n.k.) inabadilishwa kupitia:
- **Ukurasa wa Mipangilio:** `/admin/preferences/` (kwa msimamizi)
- **Faili ya mipangilio:** `OLMS/settings.py` (kwa wasanidi programu)
- **Faili ya siri:** `.env` (kwa nywila, hosts, n.k.)

---

## 🎨 12. TEMPLETI MAMA (base.html)

Faili `templates/base.html` ni mama ya templeti zote. Ina:
- **Sidebar** ya kushoto — menyu ya uabiri kulingana na jukumu
- **Topbar** juu — jina la mtumiaji, avatar, kitufe cha dark mode
- **Flash messages** — ujumbe wa mafanikio/makosa
- **Global spinner** — mzunguko wa upakiaji kwa seva polepole
- **Dark mode CSS** — hubadilika otomatiki kulingana na `user.theme`
- **System appearance overrides** — rangi/fonti zinazoweza kubadilishwa na mtunzaji

**Blocks (maeneo ya kubadilishwa na templeti watoto):**
```
{% block title %}      ← Kichwa cha ukurasa
{% block page_title %} ← Kichwa kinachoonekana ukurasa
{% block extra_css %}  ← CSS ya ziada ya ukurasa huu tu
{% block content %}    ← Maudhui makuu ya ukurasa
{% block extra_js %}   ← JavaScript ya ziada ya ukurasa huu tu
```

---

## 🔐 13. MAJUKUMU NA RUHUSA (Roles & Permissions)

| Jukumu | Wanachofanya |
|--------|-------------|
| **member** | Kutafuta vitabu, omba kukopa, angalia mikopo yao, hifadhi nafasi |
| **librarian** | Yote ya member + dhibiti vitabu, idhinisha/kataa maombi, rudisha vitabu, dhibiti faini |
| **admin** | Yote ya librarian + dhibiti watumiaji, angalia audit logs, badilisha mipangilio yote |

**Decorators za ulinzi kwenye views:**
```python
@login_required           # Lazima mtumiaji aingie kwanza
@librarian_required       # Lazima librarian au admin
@admin_required           # Lazima admin peke yake
```

---

## 📧 14. MFUMO WA ARIFA (Notifications)

Arifa zinatumwa kupitia:
- **SMS** → Beem Africa API (`BEEM_API_KEY` kwenye `.env`)
- **Barua pepe** → Gmail SMTP (`EMAIL_HOST_USER` kwenye `.env`)
- **Dashboard** → Notification model (inaonekana kwenye dashboard ya mwanachama)

**Kazi za kutuma arifa (accounts/utils.py):**
```python
create_notification(user, message, channel)  # Hifadhi kwenye DB
send_sms(phone, message)                     # Tuma SMS
send_email_notification(email, subject, msg) # Tuma barua pepe
```

---

## 🗂️ 15. FAILI ZA MIPANGILIO MUHIMU

| Faili | Mabadiliko gani |
|-------|----------------|
| `.env` | Nywila za DB, SMS, email; ALLOWED_HOSTS; DEBUG |
| `OLMS/settings.py` | Mipangilio ya Django; DB; middleware; apps |
| `templates/base.html` | Muundo wa ukurasa wote (sidebar, topbar, footer) |
| `templates/partials/sidebar_nav.html` | Viungo vya menyu ya uabiri |
| `static/` | CSS, JS, na picha za kudumu |

---

## 🧰 16. AMRI ZA KAWAIDA ZA MWENENDO (Common Commands)

```bash
# Endesha seva ya maendeleo
python manage.py runserver

# Tengeneza migration baada ya kubadilisha model
python manage.py makemigrations

# Tekeleza migration (badilisha DB)
python manage.py migrate

# Angalia matatizo ya mfumo
python manage.py check

# Angalia migrations zilizotekelezwa
python manage.py showmigrations

# Ingia kwenye shell ya Django kwa majaribio
python manage.py shell

# Unda msimamizi mkuu
python manage.py create_admin

# Angalia vitabu vilivyochelewa
python manage.py mark_overdue
```

---

*Imeandikwa kwa MSICT OLMS — Toleo la 2026 | Kiswahili*
