# ============================================================
# chatbot/services/gemini.py
# Gemini API client using google.genai SDK with function-calling.
#
# Uses Client with gemini-1.5-flash model.
# Docs: https://ai.google.dev/gemini-api/docs/function-calling
# ============================================================

import json
import logging
from django.conf import settings

from google import genai
from google.genai import types

from . import library, google_books

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Tool declarations for Gemini SDK
# ----------------------------------------------------------------------
search_library_books_fn = types.FunctionDeclaration(
    name="search_library_books",
    description=(
        "Search MSICT's internal library catalog for books by title, "
        "author, or category. ALWAYS try this BEFORE searching external "
        "sources. Returns book details, availability, and a detail-page URL."
    ),
    parameters=types.Schema(
        type="object",
        properties={
            "query": types.Schema(type="string", description="Free text — title keywords, ISBN, or topic."),
            "author": types.Schema(type="string", description="Filter by author name (optional)."),
            "category": types.Schema(type="string", description="Filter by category (e.g. 'networking', 'programming')."),
            "limit": types.Schema(type="integer", description="Max results to return (1-20). Default 8."),
        },
    ),
)

get_book_detail_fn = types.FunctionDeclaration(
    name="get_book_detail",
    description="Get full information for one book including copies, shelf, ISBN.",
    parameters=types.Schema(
        type="object",
        properties={
            "book_id": types.Schema(type="integer", description="Internal MSICT book id."),
        },
        required=["book_id"],
    ),
)

list_categories_fn = types.FunctionDeclaration(
    name="list_categories",
    description="List all top-level subject categories available in the MSICT library.",
    parameters=types.Schema(type="object", properties={}),
)

get_library_info_fn = types.FunctionDeclaration(
    name="get_library_info",
    description="Library policies — loan period, max copies, fine per day, hours.",
    parameters=types.Schema(type="object", properties={}),
)

suggest_similar_books_fn = types.FunctionDeclaration(
    name="suggest_similar_books",
    description="Suggest similar books when the requested book is unavailable or not found. Use this to recommend alternatives from MSICT library.",
    parameters=types.Schema(
        type="object",
        properties={
            "query": types.Schema(type="string", description="Book title or keywords to find similar books."),
            "author": types.Schema(type="string", description="Author name to match similar authors."),
            "category": types.Schema(type="string", description="Category/subject to find related books."),
            "limit": types.Schema(type="integer", description="Max suggestions (1-10). Default 5."),
        },
    ),
)

search_external_books_fn = types.FunctionDeclaration(
    name="search_external_books",
    description=(
        "Search Google Books (the wider web) for a title or topic. "
        "ONLY call this if the internal library returned no relevant results, "
        "or the user explicitly asked for external sources / where to find a book."
    ),
    parameters=types.Schema(
        type="object",
        properties={
            "query": types.Schema(type="string", description="Search query."),
            "limit": types.Schema(type="integer", description="Max results (1-10). Default 5."),
        },
        required=["query"],
    ),
)

TOOLS = types.Tool(
    function_declarations=[
        search_library_books_fn,
        get_book_detail_fn,
        list_categories_fn,
        get_library_info_fn,
        suggest_similar_books_fn,
        search_external_books_fn,
    ]
)

# Tool registry for execution
callable_tools = {
    "search_library_books": library.search_library_books,
    "get_book_detail": library.get_book_detail,
    "list_categories": library.list_categories,
    "get_library_info": library.get_library_info,
    "search_external_books": google_books.search_external_books,
    "suggest_similar_books": library.suggest_similar_books,
}

SYSTEM_INSTRUCTION = """You are MSICT Library Assistant — a friendly, professional digital librarian for the Military School of Information and Communication Technology online library.

LANGUAGE:
- Auto-detect whether the user wrote in English or Swahili (or a mix).
- ALWAYS reply in the SAME language the user used.
- Swahili indicators: words like "je", "naomba", "kitabu", "vitabu", "tafuta", "kuna", "naweza", "habari".
- For mixed input, reply in the language that dominates.

CORE RULES:
1. ALWAYS check the internal MSICT library first via `search_library_books` before going external.
2. Only call `search_external_books` (Google Books) if internal search returns nothing relevant, OR the user explicitly asks for external sources.
3. When a book IS found internally, mention:
   - title, author, year, category;
   - clear availability (hard-copy count, free softcopy, special softcopy);
   - the detail-page URL so the user can click to view/borrow.
4. When a book is NOT in MSICT but exists on Google Books, say so clearly, use `suggest_similar_books` to suggest alternatives in MSICT, and point them to the external source.
5. Keep answers concise (2–5 short paragraphs or a short list). Use markdown for clarity.
6. NEVER invent book ids, ISBNs, availability numbers — only use what the tools return.
7. Borrowing requires the user to be logged in. If they ask to borrow, tell them to click the book detail link and sign in.

CAPABILITIES YOU CAN OFFER:
- Search books by title, author, topic — use `search_library_books`.
- Suggest similar books when unavailable — use `suggest_similar_books`.
- Recommend books on a topic.
- Explain a topic at a beginner / intermediate level.
- Summarise a book.
- Answer library policy questions (loan period, fines, etc.) — use `get_library_info`.

Be warm, helpful, and short. Use the tools.
"""


def _run_tool(name, args):
    """Execute a tool by name with given arguments."""
    tool_func = callable_tools.get(name)
    if not tool_func:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = tool_func(**(args or {}))
        return result
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return {"error": f"Tool {name} crashed: {e}"}


def _summarise_result(name, result):
    """Summarize tool result for UI display."""
    if not isinstance(result, dict):
        return str(result)[:80]
    if "error" in result:
        return f"error: {result['error']}"
    if name == "search_library_books":
        return f"{result.get('count', 0)} internal book(s)"
    if name == "search_external_books":
        return f"{result.get('count', 0)} Google Books result(s)"
    if name == "get_book_detail":
        return result.get("title", "?")
    if name == "list_categories":
        return f"{len(result.get('categories', []))} categories"
    if name == "get_library_info":
        return "library policies"
    return "ok"


def _model_name():
    """Get the configured model name."""
    return settings.GEMINI_MODEL or "gemini-pro"


def _build_contents(history, user_message):
    """Build conversation contents for the new SDK."""
    contents = []
    for h in history:
        contents.append(types.Content(
            role=h["role"],
            parts=[types.Part(text=h["text"])]
        ))
    contents.append(types.Content(
        role="user",
        parts=[types.Part(text=user_message)]
    ))
    return contents


def chat(history, user_message, max_tool_rounds=4):
    """
    Run a chatbot turn using google.genai SDK with manual function calling.

    `history`: list of dicts [{'role': 'user'|'model', 'text': '...'}]
    `user_message`: latest user text (string)

    Returns: {
        'reply': str,
        'tool_calls': [ {name, args, result_summary}, ... ],
        'referenced_book_ids': [int, ...],
    }
    """
    if not settings.GEMINI_API_KEY:
        return {
            "reply": "AI backend not configured. Please ask the administrator to set GEMINI_API_KEY.",
            "tool_calls": [],
            "referenced_book_ids": [],
        }

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = _model_name()

    tool_calls_log = []
    referenced_books = set()
    contents = _build_contents(history, user_message)

    try:
        round_count = 0
        while round_count < max_tool_rounds:
            # Generate content
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[TOOLS],
                ),
            )

            # Check for function calls
            if not response.candidates:
                break

            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                break

            function_calls = []
            text_parts = []

            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

            # If no function calls, return the text response
            if not function_calls:
                reply_text = "".join(text_parts).strip()
                return {
                    "reply": reply_text or "I'm not sure how to answer that — could you rephrase?",
                    "tool_calls": tool_calls_log,
                    "referenced_book_ids": sorted(referenced_books),
                }

            # Execute function calls and build function response contents
            function_response_parts = []
            for fc in function_calls:
                name = fc.name
                args = dict(fc.args) if fc.args else {}

                # Execute the tool
                result = _run_tool(name, args)

                # Log the tool call
                tool_calls_log.append({
                    "name": name,
                    "args": args,
                    "result_summary": _summarise_result(name, result),
                })

                # Track referenced books
                if name == "search_library_books" and isinstance(result, dict):
                    for b in result.get("books", []):
                        if isinstance(b, dict) and "id" in b:
                            referenced_books.add(b["id"])

                # Build function response
                function_response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result},
                    )
                )

            # Add model's function call to contents
            contents.append(candidate.content)

            # Add function responses to contents
            contents.append(types.Content(
                role="user",
                parts=function_response_parts,
            ))

            round_count += 1

        # Max rounds reached - try final generation
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[TOOLS],
            ),
        )

        reply_text = ""
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            reply_text += part.text

        return {
            "reply": reply_text.strip() or "Sorry, I couldn't finish that — please ask again.",
            "tool_calls": tool_calls_log,
            "referenced_book_ids": sorted(referenced_books),
        }

    except Exception as e:
        logger.exception("Gemini SDK call failed")
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower():
            reply = (
                "⏳ *AI Service Busy*\n\n"
                "The AI assistant is experiencing high demand right now. "
                "Please wait about 30 seconds and try again, or use the search feature to find books directly."
            )
        else:
            reply = f"Sorry, the AI service is temporarily unavailable. ({e})"

        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "referenced_book_ids": sorted(referenced_books),
        }
