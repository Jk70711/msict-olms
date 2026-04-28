# OLMS – TODO / Roadmap

## ✅ Completed

- [x] Custom User Model (`OLMSUser`) with army_no, role, member_type, OTP, virtual card
- [x] All 6 Django apps: accounts, catalog, circulation, acquisitions, reports, public
- [x] Oracle 23ai database configuration via python-oracledb
- [x] Admin registrations for all models
- [x] Utility services: SMS (BEEM), email notifications, QR code, virtual card PDF
- [x] Full views and URL routing for all apps (no DRF)
- [x] All HTML templates with Bootstrap 5 (responsive)
- [x] Public OPAC: homepage carousel, catalog search, federated search, book detail
- [x] Circulation: borrow request → approve → issue → return → fine → POS payment
- [x] Member dashboard: active borrows, overdue alerts, reservations, notifications
- [x] Librarian dashboard: pending requests, overdue list, quick actions
- [x] Admin dashboard: suspicious IPs, locked accounts, audit log
- [x] Reports: members, books, circulation, fines, CSV export, SQL console
- [x] Acquisitions: vendors, budgets, purchase orders, subscriptions, ILL, ERM
- [x] Management commands: `overdue_check`, `send_notifications`, `seed_data`, `create_admin`
- [x] Oracle DDL reference schema (`schema.sql`)
- [x] README.md with full setup, cron, and environment docs

## 🔲 Pending / Nice-to-Have

### High Priority
- [ ] Write unit tests for: login/OTP flow, borrow/return cycle, fine calculation
- [ ] Write integration test for: overdue_check management command
- [ ] Add `.env.example` file for easy setup
- [ ] Add pagination to book_list, user_list, all_requests, fine_list views

### Medium Priority
- [ ] Add barcode/QR scanner library (e.g. html5-qrcode) to return_desk for real scanning
- [ ] Export reports as Excel (openpyxl is already in requirements.txt)
- [ ] Bulk import books via CSV/Excel upload (librarian tool)
- [ ] Add MARC XML import for catalog records
- [ ] Member photo capture via webcam on profile page
- [ ] Print receipt for fine payment (ReportLab PDF)
- [ ] Admin IP blocking UI (currently only view, no block action)

### Low Priority
- [ ] Add Z39.50 protocol support for real federated catalog search
- [ ] Dark mode toggle in base template
- [ ] Email templates as HTML (currently plain text)
- [ ] Add book rating/review system for members
- [ ] REST API endpoints for mobile app (future phase)
- [ ] Docker/docker-compose setup for easier deployment
- [ ] CI/CD pipeline configuration

## 🐛 Known Limitations

- Federated search currently generates redirect URLs to external OPACs; no inline results
- Virtual card PDF download requires member to have a photo (falls back gracefully)
- SMS delivery depends on BEEM Africa API availability and account balance
- Oracle Instant Client not required (python-oracledb thin mode is the default)
