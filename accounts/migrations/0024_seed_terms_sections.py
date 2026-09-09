"""
Data migration: Seeds the original hardcoded Terms & Conditions
into the TermsSection table so the admin can edit them immediately.
"""
from django.db import migrations


SECTIONS = [
    {
        'section_key': 'acceptance',
        'title': '1. Acceptance of Terms',
        'icon': 'bi-check-circle',
        'order': 10,
        'content': (
            '<p>By registering and using the MSICT Library Management System (OLMS), '
            'you agree to comply with and be bound by these Terms and Conditions. '
            'If you do not agree to these terms, please do not use this system.</p>'
        ),
    },
    {
        'section_key': 'user_resp',
        'title': '2. User Responsibilities',
        'icon': 'bi-person-check',
        'order': 20,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Account Security:</strong> You are responsible for maintaining the confidentiality of your login credentials. Do not share your password with anyone.</li>'
            '<li class="list-group-item px-0"><strong>Accurate Information:</strong> You must provide accurate and complete information during registration. Any false information may result in account termination.</li>'
            '<li class="list-group-item px-0"><strong>Proper Use:</strong> Use the library system for its intended purpose. Misuse, abuse, or unauthorized access is prohibited.</li>'
            '<li class="list-group-item px-0"><strong>Respect for Others:</strong> Respect other users, library staff, and library property at all times.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'borrowing',
        'title': '3. Borrowing Rules',
        'icon': 'bi-book',
        'order': 30,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Loan Period:</strong> Books must be returned by the due date. The standard loan period is determined by the library administration.</li>'
            '<li class="list-group-item px-0"><strong>Renewals:</strong> You may renew borrowed items up to the maximum allowed limit, provided they are not reserved by others and are not overdue.</li>'
            '<li class="list-group-item px-0"><strong>Overdue Items:</strong> Late returns may incur fines as per library policy. Continued overdue items may result in borrowing privileges suspension.</li>'
            '<li class="list-group-item px-0"><strong>Lost or Damaged Items:</strong> You are responsible for any items borrowed under your account. Lost or damaged items must be reported immediately and may require payment of replacement costs.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'fines',
        'title': '4. Fines and Payments',
        'icon': 'bi-cash-coin',
        'order': 40,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Fine Calculation:</strong> Fines for overdue items are calculated based on the number of days overdue and the daily fine rate set by the library.</li>'
            '<li class="list-group-item px-0"><strong>Payment:</strong> All fines must be paid before borrowing additional items. Payment methods are available through the system.</li>'
            '<li class="list-group-item px-0"><strong>Receipts:</strong> Digital receipts are provided for all payments. Keep these for your records.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'digital',
        'title': '5. Digital Resources',
        'icon': 'bi-file-earmark-text',
        'order': 50,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Softcopy Access:</strong> Digital books and resources are provided for personal use only. You must be logged in to access softcopy links.</li>'
            '<li class="list-group-item px-0"><strong>No Sharing:</strong> Do not share softcopy access links with others. Each link is tied to your account.</li>'
            '<li class="list-group-item px-0"><strong>Copyright:</strong> All digital materials are protected by copyright. Unauthorized distribution or reproduction is prohibited.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'privacy',
        'title': '6. Privacy and Data',
        'icon': 'bi-shield-lock',
        'order': 60,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Data Collection:</strong> The library collects personal information necessary for providing library services.</li>'
            '<li class="list-group-item px-0"><strong>Data Protection:</strong> Your personal data is protected and used only for library-related purposes.</li>'
            '<li class="list-group-item px-0"><strong>Communication:</strong> You may receive notifications about due dates, reservations, and other library-related information via SMS or email.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'conduct',
        'title': '7. Conduct and Discipline',
        'icon': 'bi-exclamation-triangle',
        'order': 70,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>Behavior:</strong> Maintain appropriate behavior in the library and when using library services.</li>'
            '<li class="list-group-item px-0"><strong>Violations:</strong> Violations of these terms may result in warning, suspension of privileges, or account termination depending on severity.</li>'
            '<li class="list-group-item px-0"><strong>Appeals:</strong> If you believe your account has been unfairly suspended, you may appeal to the library administration.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'system_usage',
        'title': '8. System Usage',
        'icon': 'bi-laptop',
        'order': 80,
        'content': (
            '<ul class="list-group list-group-flush">'
            '<li class="list-group-item px-0"><strong>AI Assistant:</strong> The library provides an AI assistant to help with queries. Use it responsibly for library-related questions only.</li>'
            '<li class="list-group-item px-0"><strong>Chat System:</strong> Members can communicate with librarians through the in-system chat. This feature is for library-related assistance only.</li>'
            '<li class="list-group-item px-0"><strong>Technical Issues:</strong> Report any technical issues to library staff immediately.</li>'
            '</ul>'
        ),
    },
    {
        'section_key': 'changes',
        'title': '9. Changes to Terms',
        'icon': 'bi-arrow-repeat',
        'order': 90,
        'content': (
            '<p>The library reserves the right to modify these terms at any time. '
            'Changes will be posted on this page with an updated date. '
            'Continued use of the system after changes constitutes acceptance of the new terms.</p>'
        ),
    },
    {
        'section_key': 'contact',
        'title': '10. Contact Information',
        'icon': 'bi-envelope',
        'order': 100,
        'content': (
            '<p>For questions about these Terms and Conditions, please contact the library '
            'administration at the MSICT Library.</p>'
        ),
    },
]


def seed_terms_sections(apps, schema_editor):
    TermsSection = apps.get_model('accounts', 'TermsSection')
    for data in SECTIONS:
        TermsSection.objects.get_or_create(
            section_key=data['section_key'],
            defaults={
                'title': data['title'],
                'icon': data['icon'],
                'order': data['order'],
                'content': data['content'],
                'is_active': True,
            }
        )


def unseed_terms_sections(apps, schema_editor):
    """Reverse: remove only the seeded rows (by section_key, skip custom ones)."""
    TermsSection = apps.get_model('accounts', 'TermsSection')
    keys = [s['section_key'] for s in SECTIONS]
    TermsSection.objects.filter(section_key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0023_terms_sections'),
    ]

    operations = [
        migrations.RunPython(seed_terms_sections, reverse_code=unseed_terms_sections),
    ]
