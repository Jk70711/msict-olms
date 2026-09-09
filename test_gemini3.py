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

response = client.models.generate_content(
    model="gemini-2.5-flash-lite", 
    contents="What are the library policies?",
    config=types.GenerateContentConfig(tools=[active_tools]),
)
candidate = response.candidates[0]
for part in candidate.content.parts:
    print(part.model_dump(exclude_none=True))
