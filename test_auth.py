import os
import sys
import django

sys.path.append('/home/jonas/PROJECT/OLMS')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OLMS.settings')
django.setup()

from django.test import Client
from accounts.models import OLMSUser
from django.urls import path
from django.http import HttpResponse

client = Client()
user = OLMSUser.objects.get(username='testmember')
print(f"User: {user}, Active: {user.is_active}, Role: {user.role}, is_guest: {user.is_guest}")
client.force_login(user)

response = client.get('/dashboard/')
print(f"Dashboard status: {response.status_code}")
if response.status_code == 302:
    print(f"Redirect: {response.url}")

