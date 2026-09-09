import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

from chatbot.services.gemini import chat

history = [
    {"role": "user", "text": "What are the policies?"},
    {"role": "model", "text": "Policies are here."}
]
try:
    print("Calling chat...")
    res = chat(history, "Tell me more.", user_context={"is_authenticated": True, "role": "member", "user_id": 1})
    print("Chat returned successfully:", res.keys())
except Exception as e:
    import traceback
    traceback.print_exc()
