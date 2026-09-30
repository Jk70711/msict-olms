import os
import sys
import django

# Setup django
sys.path.append('/home/jonas/PROJECT/OLMS')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OLMS.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')

from django.test import Client
from accounts.models import OLMSUser
from catalog.models import Book, BookCopy, Category
from circulation.models import SoftcopyAccessLog

client = Client(SERVER_NAME='localhost')

# 1. Create or get test member
user, _ = OLMSUser.objects.get_or_create(username='testmember', defaults={'role': 'member', 'is_active': True, 'email': 'test@example.com'})
user.set_password('testpass123')
user.save()

login_resp = client.post('/login/', {'username': 'testmember', 'password': 'testpass123'})
print("Login status:", login_resp.status_code)
if login_resp.status_code == 302:
    print("Login redirect:", login_resp.url)

# 2. Create category and book
cat, _ = Category.objects.get_or_create(name='Test Category', defaults={'shelf_prefix': 'TC'})
book, _ = Book.objects.get_or_create(title='Test Book', defaults={'author': 'Test Author', 'category': cat})
copy, _ = BookCopy.objects.get_or_create(book=book, copy_type='softcopy', defaults={'status': 'available'})

# 3. Simulate request to borrow softcopy
print("Testing request_borrow_softcopy_view...")
response = client.get(f'/circulation/borrow/request-softcopy/{book.id}/')
print(f"Status Code: {response.status_code}")
if response.status_code == 302:
    print(f"Redirect URL: {response.url}")

# Verify softcopy access log was created
access_log = SoftcopyAccessLog.objects.filter(user=user, copy=copy).first()
if access_log:
    print(f"Success! SoftcopyAccessLog created with URL: {access_log.access_url}")
else:
    print("Failed! No SoftcopyAccessLog was created.")

# 4. Simulate direct download free book view (should also work)
print("\nTesting download_free_book_view...")
response = client.get(f'/circulation/borrow/download-free/{book.id}/')
print(f"Status Code: {response.status_code}")
if response.status_code == 302:
    print(f"Redirect URL: {response.url}")
