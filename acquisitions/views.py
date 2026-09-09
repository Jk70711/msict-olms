from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
import re
from accounts.views import librarian_required
from accounts.utils import log_audit, notify_user, create_notification, mark_badge_viewed
from accounts.models import OLMSUser
from .models import Vendor, Budget, Fund, PurchaseOrder, PurchaseOrderItem, Invoice, ILLRequest


@login_required
@librarian_required
def vendor_list_view(request):
    vendors = Vendor.objects.all()
    return render(request, 'acquisitions/vendor_list.html', {'vendors': vendors})


@login_required
@librarian_required
def vendor_create_view(request):
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        if phone and not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'acquisitions/vendor_form.html')
        Vendor.objects.create(
            name=request.POST.get('name', ''),
            contact_person=request.POST.get('contact_person', ''),
            email=request.POST.get('email', ''),
            phone=phone,
            address=request.POST.get('address', ''),
        )
        messages.success(request, 'Vendor added.')
        return redirect('vendor_list')
    return render(request, 'acquisitions/vendor_form.html')


@login_required
@librarian_required
def vendor_edit_view(request, vendor_id):
    vendor = get_object_or_404(Vendor, pk=vendor_id)
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        if phone and not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'acquisitions/vendor_form.html', {'vendor': vendor})
        
        vendor.name = request.POST.get('name', '')
        vendor.contact_person = request.POST.get('contact_person', '')
        vendor.email = request.POST.get('email', '')
        vendor.phone = phone
        vendor.address = request.POST.get('address', '')
        vendor.save()
        messages.success(request, 'Vendor updated successfully.')
        return redirect('vendor_list')
    return render(request, 'acquisitions/vendor_form.html', {'vendor': vendor})


@login_required
@librarian_required
@require_POST
def vendor_delete_view(request, vendor_id):
    vendor = get_object_or_404(Vendor, pk=vendor_id)
    # Could check for related purchase orders here, but let's assume on_delete=CASCADE or PROTECT
    vendor.delete()
    messages.success(request, 'Vendor deleted successfully.')
    return redirect('vendor_list')


@login_required
@librarian_required
def budget_list_view(request):
    budgets = Budget.objects.prefetch_related('funds').order_by('-fiscal_year')
    return render(request, 'acquisitions/budget_list.html', {'budgets': budgets})


@login_required
@librarian_required
def budget_create_view(request):
    if request.method == 'POST':
        Budget.objects.create(
            name=request.POST.get('name', ''),
            fiscal_year=request.POST.get('fiscal_year', 2025),
            total_amount=request.POST.get('total_amount', 0),
        )
        messages.success(request, 'Budget created.')
        return redirect('budget_list')
    return render(request, 'acquisitions/budget_form.html')


@login_required
@librarian_required
def purchase_order_list_view(request):
    orders = PurchaseOrder.objects.select_related('vendor').prefetch_related('items').order_by('-order_date')
    return render(request, 'acquisitions/po_list.html', {'orders': orders})


@login_required
@librarian_required
def purchase_order_create_view(request):
    vendors = Vendor.objects.all()
    if request.method == 'POST':
        order = PurchaseOrder.objects.create(
            vendor_id=request.POST.get('vendor'),
            status='draft',
            created_by=request.user,
        )
        log_audit(request.user, f"Created purchase order PO-{order.pk}", request)
        messages.success(request, f'Purchase order PO-{order.pk} created.')
        return redirect('purchase_order_list')
    return render(request, 'acquisitions/po_form.html', {'vendors': vendors})


@login_required
@librarian_required
def purchase_order_detail_view(request, po_id):
    order = get_object_or_404(PurchaseOrder, pk=po_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_item':
            PurchaseOrderItem.objects.create(
                order=order,
                title=request.POST.get('title', ''),
                isbn=request.POST.get('isbn', ''),
                quantity=int(request.POST.get('quantity', 1)),
                unit_price=request.POST.get('unit_price', 0),
            )
            messages.success(request, 'Item added.')
        elif action == 'edit_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(PurchaseOrderItem, pk=item_id, order=order)
            item.title = request.POST.get('title', '')
            item.isbn = request.POST.get('isbn', '')
            item.quantity = int(request.POST.get('quantity', 1))
            item.unit_price = request.POST.get('unit_price', 0)
            item.save()
            messages.success(request, 'Item updated.')
        elif action == 'update_status':
            order.status = request.POST.get('status', order.status)
            order.save(update_fields=['status'])
            messages.success(request, f'Status updated to {order.status}.')
        return redirect('purchase_order_detail', po_id=po_id)
    return render(request, 'acquisitions/po_detail.html', {'order': order})


@login_required
@librarian_required
@require_POST
def purchase_order_delete_view(request, po_id):
    order = get_object_or_404(PurchaseOrder, pk=po_id)
    log_audit(request.user, f"Deleted purchase order PO-{po_id}", request)
    order.delete()
    messages.success(request, 'Purchase order deleted successfully.')
    return redirect('purchase_order_list')


@login_required
@librarian_required
@require_POST
def purchase_order_delete_item_view(request, item_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    item = get_object_or_404(PurchaseOrderItem, pk=item_id)
    po_id = item.order.pk
    log_audit(request.user, f"Deleted purchase order item {item_id} from PO-{po_id}", request)
    item.delete()
    messages.success(request, 'Item deleted.')
    return redirect('purchase_order_detail', po_id=po_id)


@login_required
@librarian_required
def ill_request_list_view(request):
    requests_qs = ILLRequest.objects.select_related('user').order_by('-request_date')
    mark_badge_viewed(request.user, 'pending_ill_requests')
    return render(request, 'acquisitions/ill_list.html', {'ill_requests': requests_qs})


@login_required
def ill_request_create_view(request):
    if request.method == 'POST':
        ill = ILLRequest.objects.create(
            user=request.user,
            title=request.POST.get('title', ''),
            author=request.POST.get('author', ''),
            isbn=request.POST.get('isbn', ''),
            source_library=request.POST.get('source_library', ''),
            notes=request.POST.get('notes', ''),
            status='pending'
        )
        # Notify all librarians about new ILL request
        librarians = OLMSUser.objects.filter(role='librarian', is_active=True)
        for lib in librarians:
            msg = f"New ILL request from {request.user.get_full_name()}: '{ill.title}'"
            notify_user(lib, msg, 'email', subject='New ILL Request')
        # Notify member that request was received
        member_msg = f"MSICT OLMS: Your ILL request for '{ill.title}' has been submitted and is pending review."
        notify_user(request.user, member_msg, 'sms')
        log_audit(request.user, f"Created ILL request for '{request.POST.get('title')}'", request)
        messages.success(request, 'ILL Request submitted. Librarians have been notified.')
        return redirect('ill_request_list')
    return render(request, 'acquisitions/ill_form.html')


@login_required
@librarian_required
@require_POST
def ill_request_update_status_view(request, ill_id):
    """POST-only — protected by CSRF + librarian role decorator. Update ILL request status and notify member."""
    ill = get_object_or_404(ILLRequest, pk=ill_id)
    new_status = request.POST.get('status')
    old_status = ill.status
    if new_status and new_status != old_status:
        ill.status = new_status
        ill.save(update_fields=['status'])
        # Notify member of status change
        status_messages = {
            'sent': f"MSICT OLMS: Your ILL request for '{ill.title}' has been sent to the source library.",
            'fulfilled': f"MSICT OLMS: Your ILL request for '{ill.title}' has been fulfilled and is being processed.",
            'received': f"MSICT OLMS: Your ILL book '{ill.title}' has been received and is ready for pickup.",
            'cancelled': f"MSICT OLMS: Your ILL request for '{ill.title}' has been cancelled. Contact library for details.",
        }
        msg = status_messages.get(new_status, f"MSICT OLMS: Your ILL request for '{ill.title}' status changed to: {new_status}")
        notify_user(ill.user, msg, 'sms')
        notify_user(ill.user, msg, 'email', subject=f"ILL Request {new_status.title()}")
        log_audit(request.user, f"Updated ILL request '{ill.title}' status from {old_status} to {new_status}", request)
        messages.success(request, f'ILL request status updated to {new_status}. Member notified.')
    return redirect('ill_request_list')


@login_required
@librarian_required
@require_POST
def ill_request_delete_view(request, ill_id):
    """POST-only — protected by CSRF + librarian role decorator. Delete ILL request."""
    ill = get_object_or_404(ILLRequest, pk=ill_id)
    log_audit(request.user, f"Deleted ILL request '{ill.title}'", request)
    ill.delete()
    messages.success(request, 'ILL request deleted successfully.')
    return redirect('ill_request_list')
