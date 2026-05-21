"""
Whitelist of reportable tables for the custom report builder (admin + librarian).

Each entry maps a stable key → Django model, allowed columns, and the field used
for time-range filtering. No raw SQL; queries are built via the ORM only.
"""

from accounts.models import OLMSUser, LoginAttempt, AuditLog
from catalog.models import Book, BookCopy, Category, News, InventoryLog
from circulation.models import (
    BorrowRequest,
    BorrowingTransaction,
    Reservation,
    Fine,
    Notification,
    LossReport,
)
from acquisitions.models import Vendor, PurchaseOrder, ILLRequest

# date_field: ORM lookup used as `{date_field}__gte` (None = no date filter)
REPORT_TABLES = {
    'users': {
        'label': 'Users / Members',
        'model': OLMSUser,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'columns': {
            'username': 'Username',
            'army_no': 'Army No',
            'first_name': 'First Name',
            'surname': 'Surname',
            'email': 'Email',
            'phone': 'Phone',
            'role': 'Role',
            'member_type': 'Member Type',
            'is_active': 'Active',
            'created_at': 'Created',
            'last_login': 'Last Login',
        },
        'default_columns': ['username', 'army_no', 'first_name', 'surname', 'role', 'email', 'is_active', 'created_at'],
        'filter_fields': {
            'role':        {'label': 'Role',        'type': 'choice', 'choices': [('member','Member'),('librarian','Librarian'),('admin','Admin')]},
            'is_active':   {'label': 'Active',      'type': 'bool'},
            'member_type': {'label': 'Member Type', 'type': 'choice', 'choices': [('officer','Officer'),('soldier','Soldier'),('civilian','Civilian'),('staff','Staff')]},
        },
    },
    'login_attempts': {
        'label': 'Login Attempts',
        'model': LoginAttempt,
        'date_field': 'timestamp',
        'order_by': '-timestamp',
        'admin_only': True,
        'columns': {
            'username': 'Username',
            'ip_address': 'IP Address',
            'status': 'Status',
            'attempt_count': 'Attempt Count',
            'timestamp': 'Timestamp',
        },
        'default_columns': ['username', 'ip_address', 'status', 'timestamp'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('success','Success'),('failed','Failed')]},
        },
    },
    'audit_logs': {
        'label': 'Audit Logs',
        'model': AuditLog,
        'date_field': 'timestamp',
        'order_by': '-timestamp',
        'admin_only': True,
        'select_related': ['user'],
        'columns': {
            'user_display': 'User',
            'action': 'Action',
            'ip_address': 'IP Address',
            'timestamp': 'Timestamp',
        },
        'default_columns': ['user_display', 'action', 'ip_address', 'timestamp'],
        'filter_fields': {},
    },
    'books': {
        'label': 'Books',
        'model': Book,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'select_related': ['category'],
        'columns': {
            'title': 'Title',
            'author': 'Author',
            'isbn': 'ISBN',
            'publisher': 'Publisher',
            'year': 'Year',
            'category_name': 'Category',
            'created_at': 'Created',
        },
        'default_columns': ['title', 'author', 'isbn', 'category_name', 'year', 'created_at'],
        'filter_fields': {},
    },
    'book_copies': {
        'label': 'Book Copies',
        'model': BookCopy,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'select_related': ['book'],
        'columns': {
            'book_title': 'Book Title',
            'accession_no': 'Accession No',
            'copy_type': 'Copy Type',
            'access_type': 'Access Type',
            'status': 'Status',
            'shelf_location': 'Shelf',
            'created_at': 'Created',
        },
        'default_columns': ['book_title', 'accession_no', 'copy_type', 'status', 'created_at'],
        'filter_fields': {
            'copy_type': {'label': 'Copy Type', 'type': 'choice', 'choices': [('hardcopy','Hardcopy'),('softcopy','Softcopy')]},
            'status':    {'label': 'Status',    'type': 'choice', 'choices': [('available','Available'),('borrowed','Borrowed'),('reserved','Reserved'),('lost','Lost')]},
        },
    },
    'categories': {
        'label': 'Categories',
        'model': Category,
        'date_field': None,
        'order_by': 'name',
        'admin_only': False,
        'columns': {
            'name': 'Name',
            'shelf_prefix': 'Shelf Prefix',
            'parent_name': 'Parent Category',
        },
        'default_columns': ['name', 'shelf_prefix', 'parent_name'],
        'filter_fields': {},
    },
    'borrow_requests': {
        'label': 'Borrow Requests',
        'model': BorrowRequest,
        'date_field': 'request_date',
        'order_by': '-request_date',
        'admin_only': False,
        'select_related': ['user', 'copy__book'],
        'columns': {
            'user_display': 'Member',
            'book_title': 'Book',
            'status': 'Status',
            'request_date': 'Request Date',
        },
        'default_columns': ['user_display', 'book_title', 'status', 'request_date'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled')]},
        },
    },
    'borrowing_transactions': {
        'label': 'Borrowing Transactions',
        'model': BorrowingTransaction,
        'date_field': 'borrow_date',
        'order_by': '-borrow_date',
        'admin_only': False,
        'select_related': ['user', 'copy__book'],
        'columns': {
            'user_display': 'Member',
            'book_title': 'Book',
            'borrow_type': 'Borrow Type',
            'borrow_date': 'Borrow Date',
            'due_date': 'Due Date',
            'return_date': 'Return Date',
            'status': 'Status',
        },
        'default_columns': ['user_display', 'book_title', 'borrow_type', 'borrow_date', 'due_date', 'status'],
        'filter_fields': {
            'status':      {'label': 'Status',    'type': 'choice', 'choices': [('borrowed','Borrowed'),('overdue','Overdue'),('returned','Returned')]},
            'borrow_type': {'label': 'Borrow Type','type': 'choice', 'choices': [('hardcopy','Hardcopy'),('softcopy','Softcopy')]},
        },
    },
    'reservations': {
        'label': 'Reservations',
        'model': Reservation,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'select_related': ['user', 'book'],
        'columns': {
            'user_display': 'Member',
            'book_title': 'Book',
            'position': 'Queue Position',
            'status': 'Status',
            'created_at': 'Created',
            'expires_at': 'Expires',
        },
        'default_columns': ['user_display', 'book_title', 'position', 'status', 'created_at'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('pending','Pending'),('notified','Notified'),('fulfilled','Fulfilled'),('cancelled','Cancelled'),('expired','Expired')]},
        },
    },
    'fines': {
        'label': 'Fines',
        'model': Fine,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'select_related': ['user'],
        'columns': {
            'user_display': 'Member',
            'amount': 'Amount',
            'amount_paid': 'Paid',
            'reason': 'Reason',
            'paid': 'Fully Paid',
            'created_at': 'Created',
            'paid_at': 'Paid At',
        },
        'default_columns': ['user_display', 'amount', 'amount_paid', 'reason', 'paid', 'created_at'],
        'filter_fields': {
            'paid': {'label': 'Fully Paid', 'type': 'bool'},
        },
    },
    'notifications': {
        'label': 'Notifications',
        'model': Notification,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'select_related': ['user'],
        'columns': {
            'user_display': 'Member',
            'message': 'Message',
            'channel': 'Channel',
            'status': 'Status',
            'priority': 'Priority',
            'created_at': 'Created',
        },
        'default_columns': ['user_display', 'message', 'channel', 'status', 'created_at'],
        'filter_fields': {
            'channel':  {'label': 'Channel',  'type': 'choice', 'choices': [('sms','SMS'),('email','Email')]},
            'status':   {'label': 'Status',   'type': 'choice', 'choices': [('pending','Pending'),('sent','Sent'),('failed','Failed')]},
            'priority': {'label': 'Priority', 'type': 'choice', 'choices': [('low','Low'),('normal','Normal'),('high','High')]},
        },
    },
    'vendors': {
        'label': 'Vendors',
        'model': Vendor,
        'date_field': None,
        'order_by': 'name',
        'admin_only': False,
        'columns': {
            'name': 'Name',
            'contact_person': 'Contact',
            'email': 'Email',
            'phone': 'Phone',
        },
        'default_columns': ['name', 'contact_person', 'email', 'phone'],
        'filter_fields': {},
    },
    'purchase_orders': {
        'label': 'Purchase Orders',
        'model': PurchaseOrder,
        'date_field': 'order_date',
        'order_by': '-order_date',
        'admin_only': False,
        'select_related': ['vendor'],
        'columns': {
            'id': 'PO ID',
            'vendor_name': 'Vendor',
            'status': 'Status',
            'total_amount': 'Total',
            'order_date': 'Order Date',
        },
        'default_columns': ['id', 'vendor_name', 'status', 'total_amount', 'order_date'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('pending','Pending'),('approved','Approved'),('received','Received'),('cancelled','Cancelled')]},
        },
    },
    'ill_requests': {
        'label': 'ILL Requests',
        'model': ILLRequest,
        'date_field': 'request_date',
        'order_by': '-request_date',
        'admin_only': False,
        'select_related': ['user'],
        'columns': {
            'user_display': 'Member',
            'title': 'Title',
            'author': 'Author',
            'status': 'Status',
            'request_date': 'Request Date',
        },
        'default_columns': ['user_display', 'title', 'author', 'status', 'request_date'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('pending','Pending'),('sent','Sent'),('fulfilled','Fulfilled'),('received','Received'),('cancelled','Cancelled')]},
        },
    },
    'news': {
        'label': 'News & Announcements',
        'model': News,
        'date_field': 'created_at',
        'order_by': '-created_at',
        'admin_only': False,
        'columns': {
            'title': 'Title',
            'news_type': 'Type',
            'is_active': 'Active',
            'is_featured': 'Featured',
            'created_at': 'Created',
        },
        'default_columns': ['title', 'news_type', 'is_active', 'created_at'],
        'filter_fields': {
            'is_active':   {'label': 'Active',   'type': 'bool'},
            'is_featured': {'label': 'Featured', 'type': 'bool'},
        },
    },
    'inventory_logs': {
        'label': 'Inventory Logs',
        'model': InventoryLog,
        'date_field': 'timestamp',
        'order_by': '-timestamp',
        'admin_only': True,
        'select_related': ['copy__book', 'performed_by'],
        'columns': {
            'copy_accession': 'Accession No',
            'action': 'Action',
            'performed_by_display': 'Performed By',
            'timestamp': 'Timestamp',
            'notes': 'Notes',
        },
        'default_columns': ['copy_accession', 'action', 'performed_by_display', 'timestamp'],
        'filter_fields': {},
    },
    'loss_reports': {
        'label': 'Loss Reports',
        'model': LossReport,
        'date_field': 'reported_at',
        'order_by': '-reported_at',
        'admin_only': False,
        'select_related': ['user', 'transaction__copy__book', 'reviewed_by', 'loss_fine'],
        'columns': {
            'user_display': 'Member',
            'book_title': 'Book',
            'copy_accession': 'Accession No',
            'circumstances': 'Circumstances',
            'status': 'Status',
            'reported_at': 'Reported At',
            'reviewed_by_display': 'Reviewed By',
        },
        'default_columns': ['user_display', 'book_title', 'status', 'reported_at'],
        'filter_fields': {
            'status': {'label': 'Status', 'type': 'choice', 'choices': [('pending','Pending'),('confirmed','Confirmed'),('resolved','Resolved'),('dismissed','Dismissed')]},
        },
    },
}


def get_tables_for_role(role):
    """Return {key: cfg} filtered by role. Admin sees all; librarian sees non-admin_only."""
    if role == 'admin':
        return REPORT_TABLES
    return {k: v for k, v in REPORT_TABLES.items() if not v.get('admin_only', False)}

TIME_PRESETS = [
    ('1d', 'Last 1 day'),
    ('7d', 'Last 7 days'),
    ('14d', 'Last 14 days'),
    ('1mo', 'Last 1 month'),
    ('3mo', 'Last 3 months'),
    ('6mo', 'Last 6 months'),
    ('1y', 'Last 1 year'),
    ('3y', 'Last 3 years'),
    ('5y', 'Last 5 years'),
    ('custom', 'Custom duration'),
    ('all', 'All time (no date filter)'),
]

MAX_EXPORT_ROWS = 5000
PREVIEW_PAGE_SIZE = 50
