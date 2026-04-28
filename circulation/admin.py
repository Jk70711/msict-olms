from django.contrib import admin
from .models import BorrowRequest, BorrowingTransaction, Reservation, Fine, Notification


@admin.register(BorrowRequest)
class BorrowRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'copy', 'request_date', 'status', 'approved_by')
    list_filter = ('status',)
    search_fields = ('user__username', 'copy__book__title', 'user__army_no')
    readonly_fields = ('request_date',)
    list_per_page = 25
    date_hierarchy = 'request_date'
    ordering = ('-request_date',)
    actions = ['approve_requests', 'reject_requests']

    def approve_requests(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='approved')
        self.message_user(request, f"{updated} request(s) marked approved.")
    approve_requests.short_description = "Mark selected requests as Approved"

    def reject_requests(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='rejected')
        self.message_user(request, f"{updated} request(s) marked rejected.")
    reject_requests.short_description = "Mark selected requests as Rejected"


@admin.register(BorrowingTransaction)
class BorrowingTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'copy', 'borrow_type', 'borrow_date', 'due_date', 'status', 'renewed_count')
    list_filter = ('status', 'borrow_type')
    search_fields = ('user__username', 'copy__book__title', 'user__army_no')
    readonly_fields = ('borrow_date',)
    list_per_page = 25
    date_hierarchy = 'borrow_date'
    ordering = ('-borrow_date',)
    actions = ['mark_returned', 'mark_overdue']

    def mark_returned(self, request, queryset):
        from django.utils import timezone
        updated = queryset.exclude(status='returned').update(status='returned', return_date=timezone.now())
        self.message_user(request, f"{updated} transaction(s) marked as returned.")
    mark_returned.short_description = "Mark selected transactions as Returned"

    def mark_overdue(self, request, queryset):
        updated = queryset.filter(status='borrowed').update(status='overdue')
        self.message_user(request, f"{updated} transaction(s) marked as overdue.")
    mark_overdue.short_description = "Mark selected transactions as Overdue"


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'position', 'status', 'created_at', 'expires_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'book__title', 'user__army_no')
    list_per_page = 25
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    actions = ['cancel_reservations']

    def cancel_reservations(self, request, queryset):
        updated = queryset.exclude(status='cancelled').update(status='cancelled')
        self.message_user(request, f"{updated} reservation(s) cancelled.")
    cancel_reservations.short_description = "Cancel selected reservations"


@admin.register(Fine)
class FineAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'reason', 'paid', 'payment_method', 'created_at', 'paid_at')
    list_filter = ('paid', 'payment_method')
    search_fields = ('user__username', 'user__army_no', 'reason')
    list_per_page = 25
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    actions = ['mark_paid', 'mark_unpaid']

    def mark_paid(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(paid=False).update(paid=True, paid_at=timezone.now())
        self.message_user(request, f"{updated} fine(s) marked as paid.")
    mark_paid.short_description = "Mark selected fines as Paid"

    def mark_unpaid(self, request, queryset):
        updated = queryset.filter(paid=True).update(paid=False, paid_at=None)
        self.message_user(request, f"{updated} fine(s) marked as unpaid.")
    mark_unpaid.short_description = "Mark selected fines as Unpaid"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'channel', 'priority', 'status', 'created_at', 'sent_at')
    list_filter = ('channel', 'status', 'priority')
    search_fields = ('user__username', 'message')
    list_per_page = 50
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    actions = ['delete_selected']

    def has_add_permission(self, request):
        return False
