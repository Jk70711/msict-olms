import os
import django
import json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

from django.test import Client

c = Client()
try:
    response = c.post('/chat/send/', data=json.dumps({"message": "Hello"}), content_type="application/json")
    print("Response status:", response.status_code)
    print("Response content:", response.content.decode('utf-8'))
except Exception as e:
    import traceback
    traceback.print_exc()
