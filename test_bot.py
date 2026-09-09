import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

from chatbot.services.gemini import chat

history = []
print("Testing search_library_books...")
res1 = chat(history, "Can you find a book about python?", user_context={"is_authenticated": True, "role": "member", "user_id": 1})
print("Reply 1:", res1["reply"])
print("Tools used:", res1["tool_calls"])

print("\nTesting get_library_info...")
history.extend([
    {"role": "user", "text": "Can you find a book about python?"},
    {"role": "model", "text": res1["reply"]}
])
res2 = chat(history, "What is the fine for an overdue book?", user_context={"is_authenticated": True, "role": "member", "user_id": 1})
print("Reply 2:", res2["reply"])
print("Tools used:", res2["tool_calls"])

