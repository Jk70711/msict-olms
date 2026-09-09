import sys
from google import genai
from google.genai import types
from django.conf import settings
import os
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "OLMS.settings")
django.setup()

client = genai.Client(api_key=settings.GEMINI_API_KEY)
get_library_info_fn = types.FunctionDeclaration(
    name="get_library_info",
    description="Return ALL current MSICT library policies.",
    parameters=types.Schema(type="object", properties={}),
)
active_tools = types.Tool(function_declarations=[get_library_info_fn])

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite", 
        contents="What are the library policies?",
        config=types.GenerateContentConfig(tools=[active_tools]),
    )
    candidate = response.candidates[0]
    print("Candidate Content Parts:")
    for i, part in enumerate(candidate.content.parts):
        print(f"Part {i}: function_call={bool(part.function_call)}, id={part.function_call.id if part.function_call else None}, thought={bool(part.thought)}, thought_signature={bool(part.thought_signature)}")
        
    contents = [
        types.Content(role="user", parts=[types.Part(text="What are the library policies?")]),
        candidate.content
    ]
    
    fr_kwargs = {"name": "get_library_info", "response": {"result": "policies"}}
    
    # Try with ID first
    if candidate.content.parts[0].function_call:
        fr_kwargs["id"] = candidate.content.parts[0].function_call.id
    elif len(candidate.content.parts) > 1 and candidate.content.parts[1].function_call:
        fr_kwargs["id"] = candidate.content.parts[1].function_call.id
        
    print(f"Using kwargs: {fr_kwargs}")
    
    contents.append(types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(**fr_kwargs))]
    ))
    
    response2 = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=contents,
        config=types.GenerateContentConfig(tools=[active_tools]),
    )
    print("Success with ID!")
except Exception as e:
    print(f"Error: {e}")
