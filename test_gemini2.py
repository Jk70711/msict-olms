import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

from google import genai
from google.genai import types
from django.conf import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)
get_library_info_fn = types.FunctionDeclaration(
    name="get_library_info",
    description="Return ALL current MSICT library policies.",
    parameters=types.Schema(type="object", properties={}),
)
active_tools = types.Tool(function_declarations=[get_library_info_fn])

print("Sending request 1...")
response = client.models.generate_content(
    model="gemini-2.5-flash-lite", 
    contents="What are the library policies?",
    config=types.GenerateContentConfig(tools=[active_tools]),
)
candidate = response.candidates[0]

print("Parts returned by model:")
for i, part in enumerate(candidate.content.parts):
    print(f"[{i}] function_call: {part.function_call}, thought_signature: {part.thought_signature}")

contents = [
    types.Content(role="user", parts=[types.Part(text="What are the library policies?")]),
    candidate.content
]

fr_kwargs = {"name": "get_library_info", "response": {"result": "policies"}}
fc_id = None
for part in candidate.content.parts:
    if part.function_call and part.function_call.id:
        fc_id = part.function_call.id
if fc_id:
    fr_kwargs["id"] = fc_id

contents.append(types.Content(
    role="user",
    parts=[types.Part(function_response=types.FunctionResponse(**fr_kwargs))]
))

try:
    print("Sending request 2 (function response)...")
    response2 = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=contents,
        config=types.GenerateContentConfig(tools=[active_tools]),
    )
    print("Success!")
except Exception as e:
    print(f"Error: {e}")

