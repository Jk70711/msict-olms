from django.db import models
from accounts.models import OLMSUser
from catalog.models import Book


class Vendor(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)

    class Meta:
        db_table = 'vendors'

    def __str__(self):
        return self.name


class Budget(models.Model):
    name = models.CharField(max_length=200)
    fiscal_year = models.IntegerField()
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    spent_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = 'budgets'

    def __str__(self):
        return f"{self.name} ({self.fiscal_year})"

    def remaining(self):
        return self.total_amount - self.spent_amount


class Fund(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='funds')
    name = models.CharField(max_length=200)
    allocated = models.DecimalField(max_digits=15, decimal_places=2)
    encumbered = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = 'funds'

    def __str__(self):
        return f"{self.name} (Budget: {self.budget.name})"

    def available(self):
        return self.allocated - self.encumbered


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('ordered', 'Ordered'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]
    vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, related_name='purchase_orders')
    order_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft')
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-order_date']

    def __str__(self):
        return f"PO-{self.pk} ({self.vendor}) [{self.status}]"


class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=500)
    isbn = models.CharField(max_length=13, blank=True)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    fund = models.ForeignKey(Fund, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'purchase_order_items'

    def __str__(self):
        return f"{self.title} x{self.quantity}"

    def total_price(self):
        return self.quantity * self.unit_price


class Invoice(models.Model):
    STATUS_CHOICES = [('unpaid', 'Unpaid'), ('paid', 'Paid'), ('partial', 'Partial')]
    order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, related_name='invoices')
    invoice_no = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unpaid')
    issued_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'invoices'

    def __str__(self):
        return f"Invoice {self.invoice_no}"


class ILLRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('fulfilled', 'Fulfilled'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='ill_requests')
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=200, blank=True)
    isbn = models.CharField(max_length=13, blank=True)
    source_library = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    request_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'ill_requests'
        verbose_name = 'ILL Request'
        ordering = ['-request_date']

    def __str__(self):
        return f"ILL: {self.title} ({self.status})"
