import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OLMS.settings')
django.setup()

from django.apps import apps
from django.db import connection

all_models = apps.get_models()

print("--- Models in System ---")
for model in all_models:
    app_label = model._meta.app_label
    if app_label in ['accounts', 'catalog', 'circulation', 'acquisitions', 'reports', 'public', 'chat', 'chatbot']:
        table_name = model._meta.db_table
        count = model.objects.count()
        print(f"App: {app_label} | Model: {model.__name__} | Table: {table_name} | Row Count: {count}")

print("\n--- Tables in Database ---")
with connection.cursor() as cursor:
    tables = connection.introspection.table_names()
    for table in tables:
        print(table)
