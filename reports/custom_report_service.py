"""
Safe ORM query builder and time-range parsing for custom reports.
"""

import re
from datetime import timedelta

from django.core.paginator import Paginator
from django.utils import timezone

from .custom_report_config import REPORT_TABLES, MAX_EXPORT_ROWS, PREVIEW_PAGE_SIZE

# Approximate calendar units for custom duration strings (no dateutil dependency).
_UNIT_DAYS = {
    'd': 1, 'day': 1, 'days': 1,
    'w': 7, 'week': 7, 'weeks': 7,
    'mo': 30, 'month': 30, 'months': 30,
    'y': 365, 'year': 365, 'years': 365,
}

_PRESET_DELTAS = {
    '1d': timedelta(days=1),
    '7d': timedelta(days=7),
    '14d': timedelta(days=14),
    '1mo': timedelta(days=30),
    '3mo': timedelta(days=90),
    '6mo': timedelta(days=180),
    '1y': timedelta(days=365),
    '3y': timedelta(days=365 * 3),
    '5y': timedelta(days=365 * 5),
}


def get_table_config(table_key):
    if table_key not in REPORT_TABLES:
        return None
    return REPORT_TABLES[table_key]


def validate_columns(table_key, column_keys):
    cfg = get_table_config(table_key)
    if not cfg:
        return []
    allowed = set(cfg['columns'].keys())
    return [c for c in column_keys if c in allowed]


def parse_custom_duration(text):
    """
    Parse flexible durations: "2 days", "8 months", "1 year", "3w", etc.
    Returns timedelta or raises ValueError.
    """
    if not text or not str(text).strip():
        raise ValueError('Enter a duration, e.g. "2 days" or "8 months".')
    normalized = str(text).strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    m = re.match(
        r'^(\d+)\s*([a-z]+)$',
        normalized,
    )
    if not m:
        raise ValueError(
            'Invalid duration. Use a number and unit, e.g. "2 days", "8 months", "1 year".'
        )
    amount = int(m.group(1))
    if amount <= 0:
        raise ValueError('Duration must be greater than zero.')
    unit = m.group(2)
    if unit not in _UNIT_DAYS:
        raise ValueError(
            f'Unknown unit "{unit}". Use day(s), week(s), month(s), or year(s).'
        )
    return timedelta(days=amount * _UNIT_DAYS[unit])


def resolve_time_range(preset, custom_text=None):
    """
    Return (since_datetime or None, label_string, error_message or None).
    since=None means no lower bound on date (all time or static tables).
    """
    if preset == 'all':
        return None, 'All time', None
    if preset == 'custom':
        try:
            delta = parse_custom_duration(custom_text)
        except ValueError as exc:
            return None, '', str(exc)
        since = timezone.now() - delta
        return since, f'Last {custom_text.strip()}', None
    if preset in _PRESET_DELTAS:
        delta = _PRESET_DELTAS[preset]
        since = timezone.now() - delta
        label = dict(
            (k, lbl) for k, lbl in [
                ('1d', 'Last 1 day'), ('7d', 'Last 7 days'), ('14d', 'Last 14 days'),
                ('1mo', 'Last 1 month'), ('3mo', 'Last 3 months'), ('6mo', 'Last 6 months'),
                ('1y', 'Last 1 year'), ('3y', 'Last 3 years'), ('5y', 'Last 5 years'),
            ]
        ).get(preset, f'Last {preset}')
        return since, label, None
    return None, '', 'Please select a valid time range.'


def _format_datetime(val):
    if val is None:
        return '—'
    if hasattr(val, 'strftime'):
        if hasattr(val, 'hour'):
            return val.strftime('%d %b %Y %H:%M')
        return val.strftime('%d %b %Y')
    return str(val)


def _cell_value(obj, col_key):
    """Resolve display value for a whitelisted column key."""
    if col_key == 'user_display':
        u = getattr(obj, 'user', None)
        return u.get_full_name() if u else '—'
    if col_key == 'book_title':
        if hasattr(obj, 'book') and obj.book:
            return obj.book.title
        if hasattr(obj, 'copy') and obj.copy and obj.copy.book:
            return obj.copy.book.title
        return '—'
    if col_key == 'category_name':
        return obj.category.name if getattr(obj, 'category', None) else '—'
    if col_key == 'parent_name':
        return obj.parent.name if getattr(obj, 'parent', None) else '—'
    if col_key == 'vendor_name':
        return obj.vendor.name if getattr(obj, 'vendor', None) else '—'
    if col_key == 'performed_by_display':
        u = getattr(obj, 'performed_by', None)
        return u.get_full_name() if u else '—'
    if col_key == 'reviewed_by_display':
        u = getattr(obj, 'reviewed_by', None)
        return u.get_full_name() if u else '—'
    if col_key == 'copy_accession':
        c = getattr(obj, 'copy', None)
        return c.accession_no if c else '—'

    val = getattr(obj, col_key, None)
    if col_key in ('is_active', 'paid', 'is_featured', 'is_active') and isinstance(val, bool):
        return 'Yes' if val else 'No'
    if col_key == 'member_type' and val:
        return obj.get_member_type_display() if hasattr(obj, 'get_member_type_display') else str(val)
    if col_key in ('role', 'status', 'borrow_type', 'copy_type', 'access_type', 'channel', 'priority', 'news_type'):
        display = getattr(obj, f'get_{col_key}_display', None)
        if callable(display):
            return display()
    if col_key in ('created_at', 'timestamp', 'request_date', 'borrow_date', 'due_date',
                   'return_date', 'order_date', 'paid_at', 'expires_at', 'last_login'):
        return _format_datetime(val)
    if col_key in ('amount', 'amount_paid', 'total_amount'):
        try:
            return f'{float(val):,.2f}'
        except (TypeError, ValueError):
            return str(val) if val is not None else '—'
    if val is None or val == '':
        return '—'
    return str(val)


def parse_filters(table_key, request_data):
    """Extract up to 3 validated filter conditions from request data.
    Returns list of (field_key, raw_value) pairs.
    """
    cfg = get_table_config(table_key)
    if not cfg:
        return []
    allowed = cfg.get('filter_fields', {})
    filters = []
    for i in range(1, 4):
        k = (request_data.get(f'filter_key_{i}') or '').strip()
        v = (request_data.get(f'filter_val_{i}') or '').strip()
        if k and v and k in allowed:
            filters.append((k, v))
    return filters


def apply_filters(qs, table_key, filters):
    """Apply validated filter conditions to a queryset safely (no raw SQL)."""
    cfg = get_table_config(table_key)
    if not cfg or not filters:
        return qs
    allowed = cfg.get('filter_fields', {})
    for field, value in filters:
        if field not in allowed:
            continue
        ftype = allowed[field].get('type', 'choice')
        if ftype == 'bool':
            qs = qs.filter(**{field: value.lower() in ('true', '1', 'yes')})
        else:
            qs = qs.filter(**{field: value})
    return qs


def build_queryset(table_key, column_keys, since, filters=None):
    cfg = get_table_config(table_key)
    if not cfg:
        raise ValueError('Invalid table selected.')

    cols = validate_columns(table_key, column_keys)
    if not cols:
        cols = list(cfg['default_columns'])

    model = cfg['model']
    qs = model.objects.all()
    sr = cfg.get('select_related') or []
    if sr:
        qs = qs.select_related(*sr)

    date_field = cfg.get('date_field')
    if since and date_field:
        qs = qs.filter(**{f'{date_field}__gte': since})
    elif since and not date_field:
        # Static reference data — time filter does not apply
        pass

    if filters:
        qs = apply_filters(qs, table_key, filters)

    order = cfg.get('order_by')
    if order:
        if isinstance(order, (list, tuple)):
            qs = qs.order_by(*order)
        else:
            qs = qs.order_by(order)

    return qs, cols, cfg


def rows_from_queryset(qs, column_keys, limit=None):
    rows = []
    iterator = qs[:limit] if limit else qs.iterator(chunk_size=500)
    for obj in iterator:
        rows.append([_cell_value(obj, c) for c in column_keys])
    return rows


def run_report(table_key, column_keys, preset, custom_text=None, page=1, for_export=False, filters=None):
    """
    Execute report. Returns dict with headers, rows, pagination info, or error.
    """
    since, range_label, err = resolve_time_range(preset, custom_text)
    if err:
        return {'error': err}

    try:
        qs, cols, cfg = build_queryset(table_key, column_keys, since, filters=filters)
    except ValueError as exc:
        return {'error': str(exc)}

    headers = [cfg['columns'][c] for c in cols]
    total = qs.count()

    if for_export:
        cap = min(total, MAX_EXPORT_ROWS)
        rows = rows_from_queryset(qs, cols, limit=cap)
        truncated = total > MAX_EXPORT_ROWS
        return {
            'headers': headers,
            'rows': rows,
            'total': total,
            'truncated': truncated,
            'range_label': range_label,
            'table_label': cfg['label'],
            'column_keys': cols,
        }

    paginator = Paginator(qs, PREVIEW_PAGE_SIZE)
    page_obj = paginator.get_page(page)
    rows = rows_from_queryset(page_obj.object_list, cols)

    return {
        'headers': headers,
        'rows': rows,
        'total': total,
        'page_obj': page_obj,
        'range_label': range_label,
        'table_label': cfg['label'],
        'column_keys': cols,
        'date_field': cfg.get('date_field'),
    }


def report_params_from_request(request):
    """Extract and normalize report parameters from GET or POST."""
    data = request.POST if request.method == 'POST' else request.GET
    table_key = (data.get('table') or '').strip()
    preset = (data.get('preset') or '7d').strip()
    if preset not in dict(
        (k, 1) for k, _ in [
            ('1d', 1), ('7d', 1), ('14d', 1), ('1mo', 1), ('3mo', 1), ('6mo', 1),
            ('1y', 1), ('3y', 1), ('5y', 1), ('custom', 1), ('all', 1),
        ]
    ):
        preset = '7d'
    custom_text = (data.get('custom_duration') or '').strip()
    columns = data.getlist('columns') if hasattr(data, 'getlist') else []
    if not columns and data.get('columns'):
        columns = [data.get('columns')]
    page = data.get('page', 1)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    filters = parse_filters(table_key, data)
    return table_key, preset, custom_text, columns, page, filters
