import os
import django
import json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

from django.test import Client

c = Client(raise_request_exception=True, SERVER_NAME="localhost")
try:
    response = c.post('/assistant/send/', data=json.dumps({"message": "What is python?"}), content_type="application/json")
    print("Status:", response.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()
