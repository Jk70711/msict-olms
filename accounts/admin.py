from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import redirect
from .models import OLMSUser, LoginAttempt, OTPRecord, VirtualCard, AuditLog, SystemPreference, BlockedIP, UserSession, GuestSession, BulkMessage, BulkMessageRecipient, UserManualSection, TermsSection


# ── Customise Django admin site ────────────────────────────────────────────
admin.site.site_header = 'MSICT OLMS – Django Administration'
admin.site.site_title  = 'MSICT OLMS Admin'
admin.site.index_title = 'System Management'


# ── Inject OLMS dashboard shortcuts into Django admin index ────────────────
original_each_context = admin.site.each_context

def each_context_with_olms(request):
    ctx = original_each_context(request)
    ctx['olms_dashboards'] = [
        {'label': 'Admin Dashboard',    'url': '/admin-dashboard/'},
        {'label': 'Librarian Dashboard','url': '/superuser/dashboard/?view=librarian'},
        {'label': 'Member Dashboard',   'url': '/superuser/dashboard/?view=member'},
        {'label': 'Catalog Search',     'url': '/catalog/'},
        {'label': 'User List',          'url': '/users/'},
        {'label': 'Audit Logs',         'url': '/admin/audit-logs/'},
        {'label': 'Suspicious IPs',     'url': '/admin/suspicious-activity/'},
    ]
    return ctx

admin.site.each_context = each_context_with_olms


@admin.register(OLMSUser)
class OLMSUserAdmin(UserAdmin):
    list_display = ('username', 'get_full_name', 'army_no', 'rank', 'role', 'member_type', 'is_active', 'failed_attempts', 'created_at')
    list_filter = ('role', 'member_type', 'is_active', 'rank')
    search_fields = ('username', 'army_no', 'first_name', 'surname', 'email', 'phone', 'rank__rank_name')
    ordering = ('-created_at',)
    list_per_page = 25
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'last_login', 'failed_attempts')
    actions = ['lock_accounts', 'unlock_accounts', 'reset_failed_attempts']

    fieldsets = (
        ('Login Info', {'fields': ('username', 'password')}),
        ('Personal', {'fields': ('first_name', 'middle_name', 'surname', 'army_no', 'rank', 'registration_no', 'photo')}),
        ('Contact', {'fields': ('email', 'phone')}),
        ('Role', {'fields': ('role', 'member_type')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Security', {'fields': ('failed_attempts', 'last_login', 'last_password_change', 'created_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'army_no', 'rank', 'first_name', 'surname', 'email', 'phone', 'role', 'password1', 'password2'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # If creating a new user via admin
            obj.is_active = True
            obj.registration_status = 'approved'
            obj.approved_by = request.user
            from django.utils import timezone
            obj.approved_at = timezone.now()
        super().save_model(request, obj, form, change)

    def lock_accounts(self, request, queryset):
        updated = queryset.update(is_active=False)
        from accounts.utils import notify_user
        for user in queryset:
            notify_user(
                user,
                f"Your MSICT OLMS account has been locked by the administrator. Contact the library for assistance.",
                'sms',
                subject='Account Locked - MSICT OLMS',
                priority='high',
                is_security_alert=True
            )
        self.message_user(request, f"Locked {updated} account(s).")
    lock_accounts.short_description = "🔒 Lock selected accounts"

    def unlock_accounts(self, request, queryset):
        updated = queryset.update(is_active=True, failed_attempts=0)
        from accounts.utils import notify_user
        for user in queryset:
            notify_user(
                user,
                f"Your MSICT OLMS account has been unlocked. You can now log in.",
                'sms',
                subject='Account Unlocked - MSICT OLMS',
                priority='high',
                is_security_alert=True
            )
        self.message_user(request, f"Unlocked {updated} account(s).")
    unlock_accounts.short_description = "🔓 Unlock selected accounts"

    def reset_failed_attempts(self, request, queryset):
        updated = queryset.update(failed_attempts=0)
        self.message_user(request, f"Reset failed attempts for {updated} account(s).")
    reset_failed_attempts.short_description = "↺ Reset failed login attempts"


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ('username', 'ip_address', 'attempt_count', 'status', 'timestamp')
    list_filter = ('status',)
    search_fields = ('username', 'ip_address')
    readonly_fields = ('timestamp',)
    list_per_page = 50
    date_hierarchy = 'timestamp'
    actions = ['delete_selected']

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'truncated_action', 'ip_address')
    search_fields = ('action', 'ip_address', 'user__username')
    list_filter = ('user__role',)
    list_per_page = 50
    date_hierarchy = 'timestamp'
    ordering = ('-timestamp',)
    actions = ['delete_selected']

    def truncated_action(self, obj):
        return obj.action[:100] + '…' if len(obj.action) > 100 else obj.action
    truncated_action.short_description = 'Action'

    def has_delete_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request):
        return False


@admin.register(SystemPreference)
class SystemPreferenceAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'unit', 'updated_at', 'updated_by', 'description')
    search_fields = ('key',)


@admin.register(VirtualCard)
class VirtualCardAdmin(admin.ModelAdmin):
    list_display = ('user', 'card_no', 'barcode', 'generated_at')
    search_fields = ('user__username', 'card_no', 'barcode')
    readonly_fields = ('generated_at', 'qr_code')
    list_per_page = 25


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'blocked_by', 'reason', 'blocked_at')
    search_fields = ('ip_address', 'reason')
    list_per_page = 25
    actions = ['delete_selected']


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'session_id', 'ip_address', 'login_time', 'logout_time')
    search_fields = ('user__username', 'ip_address', 'session_id')
    readonly_fields = ('session_id', 'login_time')
    list_per_page = 50
    date_hierarchy = 'login_time'
    ordering = ('-login_time',)
    actions = ['delete_selected']


@admin.register(GuestSession)
class GuestSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'sign_in_time', 'sign_out_time', 'paid_hours', 'duration_hours', 'amount_paid', 'payment_status', 'status')
    list_filter = ('status', 'payment_status')
    search_fields = ('user__username', 'user__email', 'user__phone', 'ip_address')
    readonly_fields = ('sign_in_time', 'created_at')
    date_hierarchy = 'sign_in_time'
    ordering = ('-sign_in_time',)


@admin.register(BulkMessage)
class BulkMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'sent_by', 'sent_at', 'status', 'total_recipients', 'total_sent', 'total_failed', 'is_new_arrival')
    list_filter = ('status', 'is_new_arrival', 'send_via')
    search_fields = ('subject', 'body', 'sent_by__username')
    readonly_fields = ('sent_at', 'created_at', 'total_recipients', 'total_sent', 'total_failed')
    date_hierarchy = 'sent_at'
    ordering = ('-sent_at',)


@admin.register(BulkMessageRecipient)
class BulkMessageRecipientAdmin(admin.ModelAdmin):
    list_display = ('message', 'user', 'delivered_via', 'status', 'delivered_at')
    list_filter = ('status', 'delivered_via')
    search_fields = ('user__username', 'user__email', 'message__subject')
    ordering = ('-message',)


@admin.register(UserManualSection)
class UserManualSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'section_key', 'icon', 'order', 'is_active', 'updated_at', 'updated_by')
    list_filter = ('is_active', 'section_key')
    search_fields = ('title', 'section_key', 'content')
    list_editable = ('order', 'is_active')
    readonly_fields = ('updated_at', 'updated_by')
    ordering = ('order', 'section_key')
    
    fieldsets = (
        ('Section Info', {
            'fields': ('section_key', 'title', 'icon', 'order', 'is_active')
        }),
        ('Content', {
            'fields': ('content',)
        }),
        ('Metadata', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(TermsSection)
class TermsSectionAdmin(admin.ModelAdmin):
    list_display = ('order', 'title', 'section_key', 'icon', 'is_active', 'updated_at', 'updated_by')
    list_display_links = ('title',)
    list_filter = ('is_active', 'section_key')
    search_fields = ('title', 'section_key', 'content')
    list_editable = ('order', 'is_active')
    readonly_fields = ('updated_at', 'updated_by')
    ordering = ('order', 'section_key')

    fieldsets = (
        ('Section Info', {
            'fields': ('section_key', 'title', 'icon', 'order', 'is_active')
        }),
        ('Content', {
            'description': 'You may use HTML tags: &lt;ul&gt;, &lt;li&gt;, &lt;p&gt;, &lt;strong&gt;, &lt;em&gt;, &lt;a&gt;, &lt;h6&gt;',
            'fields': ('content',)
        }),
        ('Metadata', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
