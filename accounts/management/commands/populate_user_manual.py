from django.core.management.base import BaseCommand
from accounts.models import UserManualSection


class Command(BaseCommand):
    help = 'Populate User Manual sections with initial content'

    def handle(self, *args, **options):
        sections_data = [
            {
                'section_key': 'getting_started',
                'title': 'Getting Started',
                'icon': 'bi-play-circle',
                'order': 1,
                'content': '''<h6 class="fw-bold">Registration</h6>
<ul>
  <li>Visit the registration page and fill in your details (Army Number, Name, Email, Phone, Member Type)</li>
  <li>You must accept the Terms and Conditions to complete registration</li>
  <li>Your account will require approval from a librarian before you can borrow books</li>
  <li>You will receive an OTP via SMS/Email to verify your account</li>
</ul>
<h6 class="fw-bold mt-3">Login</h6>
<ul>
  <li>Use your Army Number or Email and password to log in</li>
  <li>If you forget your password, use the "Forgot Password" link to reset via OTP</li>
  <li>For security, passwords expire every {{ password_expiry_days }} days and must be changed</li>
</ul>'''
            },
            {
                'section_key': 'borrowing',
                'title': 'Borrowing Books',
                'icon': 'bi-book',
                'order': 2,
                'content': '''<h6 class="fw-bold">How to Borrow</h6>
<ol>
  <li>Search for books using the catalog search bar</li>
  <li>Click "Borrow Request" on the book you want</li>
  <li>Wait for librarian approval (you'll receive a notification)</li>
  <li>For softcopies, complete payment to receive access link</li>
  <li>For hardcopies, collect the physical book from the library desk</li>
</ol>
<h6 class="fw-bold mt-3">Borrowing Rules</h6>
<ul>
  <li>Standard loan period is <strong>{{ loan_period_days }} days</strong></li>
  <li>You can borrow up to <strong>{{ max_borrow_limit }} items</strong> at a time</li>
  <li>Books must be returned by the due date to avoid fines</li>
  <li>Some books may have special borrowing restrictions</li>
</ul>'''
            },
            {
                'section_key': 'returning',
                'title': 'Returning Books',
                'icon': 'bi-arrow-return-left',
                'order': 3,
                'content': '''<h6 class="fw-bold">Hardcopy Returns</h6>
<ul>
  <li>Bring the physical book to the library desk</li>
  <li>The librarian will process the return and update your record</li>
  <li>You will receive a confirmation of return</li>
</ul>
<h6 class="fw-bold mt-3">Softcopy Returns</h6>
<ul>
  <li>Softcopy access automatically expires after the loan period</li>
  <li>No physical return is required</li>
  <li>You can renew softcopy access before expiry</li>
</ul>'''
            },
            {
                'section_key': 'renewals',
                'title': 'Renewals',
                'icon': 'bi-arrow-clockwise',
                'order': 4,
                'content': '''<h6 class="fw-bold">Renewal Policy</h6>
<ul>
  <li>You can renew a book up to <strong>{{ max_renewals }} times</strong></li>
  <li>Renewals are only allowed within <strong>{{ renewal_window_days }} days</strong> before the due date</li>
  <li>Books with pending reservations cannot be renewed</li>
  <li>Overdue books cannot be renewed (must return and pay fines first)</li>
</ul>
<h6 class="fw-bold mt-3">How to Renew</h6>
<ol>
  <li>Go to "My MSICT Borrowings" in your dashboard</li>
  <li>Find the book you want to renew</li>
  <li>Click the "Renew" button (if eligible)</li>
  <li>For softcopies, complete the renewal payment</li>
</ol>
<div class="alert alert-warning mt-3">
  <i class="bi bi-exclamation-triangle"></i> Note: Renewal status will show as "Renewed 1" or "Renewed 2" to track your renewal count.
</div>'''
            },
            {
                'section_key': 'reservations',
                'title': 'Reservations',
                'icon': 'bi-bookmark-star',
                'order': 5,
                'content': '''<h6 class="fw-bold">How to Reserve</h6>
<ol>
  <li>Search for the book you want in the catalog</li>
  <li>If the book is currently borrowed, click "Reserve" on the book detail page</li>
  <li>You will be added to the reservation queue</li>
  <li>When the book becomes available, you'll receive a notification</li>
  <li>You have 24 hours to collect the book after notification</li>
</ol>
<h6 class="fw-bold mt-3">Reservation Rules</h6>
<ul>
  <li>Reservations expire after <strong>{{ reservation_expiry_days }} days</strong> if unclaimed</li>
  <li>You can only reserve books that are currently borrowed by others</li>
  <li>If you miss the 24-hour collection window, the reservation passes to the next person</li>
  <li>Books with pending reservations cannot be renewed by current borrowers</li>
  <li>You can cancel your reservation from your dashboard</li>
</ul>
<div class="alert alert-info mt-3">
  <i class="bi bi-info-circle"></i> Tip: Check your notifications regularly to avoid missing reserved books.
</div>'''
            },
            {
                'section_key': 'fines',
                'title': 'Fines & Payments',
                'icon': 'bi-cash-coin',
                'order': 6,
                'content': '''<h6 class="fw-bold">Fine Calculation</h6>
<ul>
  <li>Fines are charged at <strong>TZS {{ fine_per_day }} per day</strong> for overdue items</li>
  <li>Fines start accruing from the day after the due date</li>
  <li>Renewed books do not incur fines (renewal is before due date)</li>
  <li>Lost books have additional replacement costs</li>
</ul>
<h6 class="fw-bold mt-3">Payment Methods</h6>
<ul>
  <li>Pay fines through the "My Fines" section in your dashboard</li>
  <li>Digital receipts are provided for all payments</li>
  <li>Unpaid fines may block borrowing privileges</li>
</ul>'''
            },
            {
                'section_key': 'loss',
                'title': 'Lost Books',
                'icon': 'bi-exclamation-diamond',
                'order': 7,
                'content': '''<h6 class="fw-bold">Reporting Lost Books</h6>
<ul>
  <li>Report lost books immediately through your dashboard</li>
  <li>Go to "My MSICT Borrowings" and click "Report Loss"</li>
  <li>The librarian will review and confirm the loss report</li>
</ul>
<h6 class="fw-bold mt-3">Loss Fines</h6>
<ul>
  <li>Lost books incur a replacement fine based on book value</li>
  <li>Pay the loss fine to clear your record</li>
  <li>Receipts are provided for loss fine payments</li>
</ul>'''
            },
            {
                'section_key': 'softcopy',
                'title': 'Digital Resources (Softcopies)',
                'icon': 'bi-file-earmark-pdf',
                'order': 8,
                'content': '''<h6 class="fw-bold">Accessing Softcopies</h6>
<ul>
  <li>Request softcopy borrowing through the catalog</li>
  <li>Complete payment to receive access link</li>
  <li>You must be logged in to access softcopy links</li>
  <li>Links are personal and cannot be shared with others</li>
</ul>
<h6 class="fw-bold mt-3">Softcopy Rules</h6>
<ul>
  <li>Access link expires after the loan period</li>
  <li>You can renew access before expiry (up to {{ max_renewals }} times)</li>
  <li>Softcopies are for personal use only</li>
  <li>Copyright laws apply to all digital materials</li>
</ul>
<div class="alert alert-danger mt-3">
  <i class="bi bi-shield-lock"></i> Security: Softcopy links require login. Sharing links with others is prohibited and may result in account suspension.
</div>'''
            },
            {
                'section_key': 'notifications',
                'title': 'Notifications',
                'icon': 'bi-bell',
                'order': 9,
                'content': '''<h6 class="fw-bold">Types of Notifications</h6>
<ul>
  <li><strong>Due Date Reminders:</strong> Sent 2 days before due date</li>
  <li><strong>Overdue Alerts:</strong> Sent when books become overdue</li>
  <li><strong>Approval Notifications:</strong> When borrow requests are approved</li>
  <li><strong>Reservation Alerts:</strong> When reserved books become available</li>
  <li><strong>Fine Notifications:</strong> When fines are issued or updated</li>
</ul>
<h6 class="fw-bold mt-3">Notification Channels</h6>
<ul>
  <li>SMS to your registered phone number</li>
  <li>Email to your registered email address</li>
  <li>In-app notifications in your dashboard</li>
</ul>'''
            },
            {
                'section_key': 'chat',
                'title': 'Chat & Support',
                'icon': 'bi-chat-dots',
                'order': 10,
                'content': '''<h6 class="fw-bold">In-System Chat</h6>
<ul>
  <li>Members can chat with librarians for assistance</li>
  <li>Access chat through the chat icon in the sidebar or topbar</li>
  <li>Chat is for library-related assistance only</li>
  <li>Unread messages show a badge on the chat icon</li>
</ul>
<h6 class="fw-bold mt-3">Getting Help</h6>
<ul>
  <li>For quick questions, use the in-system chat</li>
  <li>For complex issues, visit the library desk</li>
  <li>Contact library administration for account issues</li>
</ul>'''
            },
            {
                'section_key': 'passwords',
                'title': 'Password Security',
                'icon': 'bi-shield-lock',
                'order': 11,
                'content': '''<h6 class="fw-bold">Password Requirements</h6>
<ul>
  <li>Passwords must be at least 8 characters long</li>
  <li>Must include uppercase, lowercase, numbers, and special characters</li>
  <li>Cannot reuse your last 5 passwords</li>
  <li>Passwords expire every {{ password_expiry_days }} days</li>
</ul>
<h6 class="fw-bold mt-3">Password Reset</h6>
<ul>
  <li>Use "Forgot Password" for self-reset via OTP</li>
  <li>Librarians can initiate password resets for your account</li>
  <li>Always keep your password confidential</li>
  <li>Never share your login credentials</li>
</ul>
<h6 class="fw-bold mt-3">Session Management</h6>
<ul>
  <li>Sessions automatically timeout after {{ session_timeout_minutes }} minutes of inactivity</li>
  <li>You will be logged out automatically for security</li>
  <li>Use "Remember Me" to extend session (if enabled)</li>
</ul>'''
            },
            {
                'section_key': 'login_attempts',
                'title': 'Login Attempts & Security',
                'icon': 'bi-shield-exclamation',
                'order': 12,
                'content': '''<h6 class="fw-bold">Failed Login Attempts</h6>
<ul>
  <li>After <strong>{{ max_login_attempts }} failed attempts</strong>, your account will be temporarily locked</li>
  <li>After <strong>{{ suspend_attempts }} failed attempts</strong>, your account will be suspended</li>
  <li>Suspension lasts for <strong>{{ suspend_duration_minutes }} minutes</strong></li>
  <li>Failed attempts are logged for security monitoring</li>
</ul>
<h6 class="fw-bold mt-3">Account Lockout</h6>
<ul>
  <li>Locked accounts require password reset via OTP</li>
  <li>Suspended accounts require librarian intervention</li>
  <li>Contact library administration if locked out</li>
</ul>
<h6 class="fw-bold mt-3">Security Best Practices</h6>
<ul>
  <li>Use strong, unique passwords</li>
  <li>Don't share your credentials with anyone</li>
  <li>Report suspicious activity immediately</li>
  <li>Log out when using shared computers</li>
</ul>
<div class="alert alert-warning mt-3">
  <i class="bi bi-exclamation-triangle"></i> Multiple failed login attempts may indicate unauthorized access attempts. Protect your account by using strong passwords.
</div>'''
            },
            {
                'section_key': 'guest',
                'title': 'Guest Access',
                'icon': 'bi-person-badge',
                'order': 13,
                'content': '''<h6 class="fw-bold">Guest Sessions</h6>
<ul>
  <li>Guests can access the library for limited time sessions</li>
  <li>Session duration is purchased in hours (max {{ guest_max_hours }} hours per session)</li>
  <li>Hourly rate is <strong>TZS {{ guest_hourly_rate }}/hour</strong></li>
  <li>Guests can browse the catalog but cannot borrow</li>
  <li>Guest sessions expire after the purchased time</li>
  <li>Daily limit: Maximum {{ guest_max_hours }} hours total per day</li>
</ul>
<h6 class="fw-bold mt-3">Session Renewal</h6>
<ul>
  <li>Guests can renew their session before expiry</li>
  <li>Renewal payment is based on remaining available hours</li>
  <li>Session expiry countdown is displayed in real-time</li>
  <li>5-minute warning popup before session expires</li>
</ul>
<h6 class="fw-bold mt-3">Guest to Member Upgrade</h6>
<ul>
  <li>Guests can upgrade to full member status</li>
  <li>Complete registration form with your details</li>
  <li>Requires librarian approval</li>
</ul>'''
            },
            {
                'section_key': 'ai',
                'title': 'AI Assistant',
                'icon': 'bi-robot',
                'order': 14,
                'content': '''<h6 class="fw-bold">AI Library Assistant</h6>
<ul>
  <li>The library provides an AI assistant to help with queries</li>
  <li>Access the AI assistant through the floating chat widget</li>
  <li>Ask questions about books, borrowing, fines, and library services</li>
  <li>The AI can help with book recommendations and catalog searches</li>
</ul>
<h6 class="fw-bold mt-3">AI Usage Guidelines</h6>
<ul>
  <li>Use the AI for library-related questions only</li>
  <li>The AI provides general guidance - librarians handle specific requests</li>
  <li>AI responses are based on current library data</li>
  <li>Report any AI errors or misinformation to library staff</li>
</ul>
<div class="alert alert-info mt-3">
  <i class="bi bi-info-circle"></i> The AI assistant is continuously learning. Your feedback helps improve its accuracy.
</div>'''
            },
        ]

        created = 0
        updated = 0

        for section_data in sections_data:
            section_key = section_data['section_key']
            obj, created_flag = UserManualSection.objects.update_or_create(
                section_key=section_key,
                defaults=section_data
            )
            if created_flag:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'Created section: {obj.title}'))
            else:
                updated += 1
                self.stdout.write(self.style.WARNING(f'Updated section: {obj.title}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone! Created {created} new sections, updated {updated} existing sections.'
            )
        )
