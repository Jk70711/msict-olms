# ============================================================
# accounts/security_utils.py
#
# Reusable security primitives used across views:
#
#   - safe_redirect(request, value, fallback)
#       Validates an untrusted "next"-style URL/view name before
#       redirecting, defeating Open-Redirect attacks. Falls back to
#       the supplied named view if the value is missing or unsafe.
#
#   - safe_attachment_filename(name, default)
#       Returns a Content-Disposition-safe ASCII filename plus an
#       RFC-5987 UTF-8 variant, defeating HTTP-Response-Splitting
#       and quoting issues caused by user-supplied titles/usernames
#       in file download responses.
#
#   - validate_upload(file, *, allowed_extensions, allowed_mime,
#                     max_size, magic_signatures)
#       Defence-in-depth check for file uploads:
#         · extension whitelist
#         · MIME-type whitelist (best-effort, browser-supplied)
#         · maximum size
#         · file-magic signature check (e.g. PDF must start with
#           "%PDF-").
#       Raises django.core.exceptions.ValidationError on any
#       violation, so callers can surface a nice form error.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.shortcuts import redirect, resolve_url
from django.urls import NoReverseMatch
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _


class PasswordMaxLengthValidator:
    """Password validator enforcing an upper bound on password length.

    Configurable via the standard AUTH_PASSWORD_VALIDATORS entry:
        {'NAME': 'accounts.security_utils.PasswordMaxLengthValidator', 'OPTIONS': {'max_length': 12}}
    """
    def __init__(self, max_length=12):
        try:
            self.max_length = int(max_length)
        except (TypeError, ValueError):
            self.max_length = 12

    def validate(self, password, user=None):
        if password is None:
            return
        if len(password) > self.max_length:
            raise ValidationError(
                _('This password is too long. It must contain at most %(max)d characters.'),
                code='password_too_long',
                params={'max': self.max_length},
            )

    def get_help_text(self):
        return _('Your password must contain at most %(max)d characters.') % {'max': self.max_length}


# ---------------------------------------------------------------
# 1. Safe redirect helper (anti Open-Redirect)
# ---------------------------------------------------------------
def safe_redirect(request, value, fallback):
    """
    Redirect to *value* only if it is safe; otherwise redirect to *fallback*.

    A value is considered safe when:
      * it resolves to a Django named-view (e.g. "admin_dashboard"); OR
      * it is a URL whose host+scheme matches the current request
        (Django's url_has_allowed_host_and_scheme).

    Fallback may be either a named-view or a URL — anything that
    django.shortcuts.redirect understands.

    Usage:
        return safe_redirect(request, request.POST.get('next'), 'admin_dashboard')
    """
    if value:
        # Try the value as a named view first (most common case in this app).
        try:
            return redirect(resolve_url(value))
        except NoReverseMatch:
            pass
        # Otherwise allow it only if it is a same-origin URL.
        if url_has_allowed_host_and_scheme(
            url=value,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(value)
    return redirect(fallback)


# ---------------------------------------------------------------
# 2. Safe Content-Disposition filename (anti header-injection)
# ---------------------------------------------------------------
_FILENAME_BAD_CHARS = re.compile(r'[\r\n"\\\x00-\x1f\x7f]')


def safe_attachment_filename(name: str, default: str = 'download') -> str:
    """
    Return an ASCII-safe filename for use inside a Content-Disposition
    header, stripped of CR/LF/control characters and quote characters
    that would break the header or allow HTTP-response-splitting.

    Non-ASCII characters are replaced with their closest ASCII
    equivalents (e.g. "Pörsche" -> "Porsche"). If everything is
    stripped away, *default* is returned.

    Callers that need full Unicode in the filename should also emit
    an RFC-5987 ``filename*=UTF-8''…`` parameter alongside the ASCII
    one — use :func:`build_content_disposition` for that.
    """
    if not name:
        return default
    # Strip diacritics where possible.
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Drop any header-breaking characters.
    name = _FILENAME_BAD_CHARS.sub('', name).strip()
    # Collapse whitespace and slashes.
    name = re.sub(r'[\s/]+', '_', name)
    # Trim to a sane length so the header stays small.
    name = name[:120]
    return name or default


def build_content_disposition(disposition: str, filename: str) -> str:
    """
    Build a fully-quoted, injection-safe Content-Disposition header
    value with both an ASCII filename and an RFC-5987 UTF-8 variant.

        disposition  : "inline" or "attachment"
        filename     : raw filename, may contain Unicode / arbitrary chars

    The resulting header is safe to assign directly to
    response['Content-Disposition'].
    """
    ascii_name = safe_attachment_filename(filename)
    utf8_name = quote(filename.replace('"', '').replace('\r', '').replace('\n', ''))
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'


# ---------------------------------------------------------------
# 3. Upload validator (defence-in-depth)
# ---------------------------------------------------------------
# Common executable / script extensions that must NEVER be accepted
# from any user, regardless of role. Even if the librarian uploads
# them, they could later be served and executed by a member's
# browser via MIME-sniffing on a misconfigured proxy.
DANGEROUS_EXTENSIONS = frozenset({
    '.exe', '.bat', '.cmd', '.com', '.msi', '.scr', '.ps1', '.vbs',
    '.js',  '.jse', '.wsf', '.wsh', '.jar', '.jnlp',
    '.sh',  '.bash', '.zsh', '.csh', '.ksh', '.fish',
    '.php', '.phtml', '.phar', '.py', '.pyc', '.pyo', '.rb', '.pl',
    '.cgi', '.asp', '.aspx', '.jsp', '.htaccess', '.htpasswd',
    '.swf', '.svg',  # SVG can carry XSS via inline <script>
    '.html', '.htm', '.xhtml', '.xml',  # may contain inline JS
})

# Magic-byte signatures for the formats the system actually serves.
# Each value is a list of accepted prefixes (bytes) so we can match
# any of them. Empty list = any signature accepted.
DEFAULT_MAGIC_SIGNATURES = {
    '.pdf':  [b'%PDF-'],
    '.png':  [b'\x89PNG\r\n\x1a\n'],
    '.jpg':  [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
    '.gif':  [b'GIF87a', b'GIF89a'],
    '.webp': [b'RIFF'],   # then "WEBP" at offset 8 — checked below
    '.bmp':  [b'BM'],
    '.docx': [b'PK\x03\x04'],
    '.xlsx': [b'PK\x03\x04'],
    '.pptx': [b'PK\x03\x04'],
    '.zip':  [b'PK\x03\x04'],
    '.epub': [b'PK\x03\x04'],  # EPUB is a ZIP archive
    '.doc':  [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],  # OLE2 Compound Document
}


def validate_upload(
    file,
    *,
    allowed_extensions: set[str] | tuple[str, ...] | list[str] | None = None,
    allowed_mime: set[str] | tuple[str, ...] | list[str] | None = None,
    max_size: int | None = None,
    check_magic: bool = True,
) -> None:
    """
    Validate a Django UploadedFile against a whitelist policy.

    Raises ``django.core.exceptions.ValidationError`` on any violation
    so callers can use ``form.add_error`` / ``messages.error`` cleanly.

    Pass ``allowed_extensions`` as a set of lowercase extensions
    *with* the leading dot, e.g. ``{'.pdf'}``.
    """
    if file is None:
        return

    name = (file.name or '').lower()
    ext = '.' + name.rsplit('.', 1)[-1] if '.' in name else ''

    # 1. Hard-block dangerous extensions regardless of role.
    if ext in DANGEROUS_EXTENSIONS:
        raise ValidationError(
            f"File type '{ext}' is not allowed for security reasons."
        )

    # 2. Whitelist extensions if the caller specified one.
    if allowed_extensions is not None:
        allowed = {e.lower() for e in allowed_extensions}
        if ext not in allowed:
            raise ValidationError(
                f"Only {', '.join(sorted(allowed))} files are accepted "
                f"(got '{ext or 'no extension'}')."
            )

    # 3. MIME whitelist (browser-supplied; not authoritative but useful).
    if allowed_mime is not None:
        ct = (getattr(file, 'content_type', '') or '').lower()
        allowed_ct = {m.lower() for m in allowed_mime}
        if ct and ct not in allowed_ct:
            raise ValidationError(
                f"Unsupported content type '{ct}'."
            )

    # 4. Size cap.
    if max_size is not None and file.size > max_size:
        mb = max_size / (1024 * 1024)
        raise ValidationError(
            f"File is too large ({file.size / (1024*1024):.1f} MB). "
            f"Maximum allowed is {mb:.0f} MB."
        )

    # 5. Magic-byte sniff so a renamed .exe → .pdf fails loudly.
    if check_magic and ext in DEFAULT_MAGIC_SIGNATURES:
        signatures = DEFAULT_MAGIC_SIGNATURES[ext]
        if signatures:
            try:
                pos = file.tell()
            except (AttributeError, OSError):
                pos = 0
            try:
                file.seek(0)
                head = file.read(16)
            finally:
                try:
                    file.seek(pos)
                except (AttributeError, OSError):
                    pass
            ok = any(head.startswith(sig) for sig in signatures)
            # Special-case: WebP requires "WEBP" at offset 8.
            if ok and ext == '.webp':
                ok = head[8:12] == b'WEBP'
            if not ok:
                raise ValidationError(
                    "File contents do not match its extension. "
                    "Refusing upload."
                )
