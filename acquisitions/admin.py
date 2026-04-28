from django.contrib import admin
from .models import Vendor, Budget, Fund, PurchaseOrder, PurchaseOrderItem, Invoice, ILLRequest


class FundInline(admin.TabularInline):
    model = Fund
    extra = 1


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'email', 'phone')
    search_fields = ('name', 'email')


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('name', 'fiscal_year', 'total_amount', 'spent_amount')
    inlines = [FundInline]


@admin.register(Fund)
class FundAdmin(admin.ModelAdmin):
    list_display = ('name', 'budget', 'allocated', 'encumbered')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('pk', 'vendor', 'order_date', 'status', 'total_amount')
    list_filter = ('status',)
    inlines = [PurchaseOrderItemInline]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_no', 'order', 'amount', 'status', 'issued_date')
    list_filter = ('status',)


@admin.register(ILLRequest)
class ILLRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'status', 'request_date')
    list_filter = ('status',)
    search_fields = ('title', 'user__username')
