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

get_online_libraries_fn = types.FunctionDeclaration(
    name="get_online_libraries",
    description=(
        "Return a curated list of free/open-access external online libraries "
        "(Google Books, Open Library, MIT OCW, Project Gutenberg, Springer, etc.) "
        "with direct search URLs pre-filled for the given topic. "
        "Call this when: (a) the requested book is not in MSICT library, "
        "(b) user asks where to find books online, or "
        "(c) user asks for online/external resources."
    ),
    parameters=types.Schema(
        type="object",
        properties={
            "query": types.Schema(type="string", description="Book title or topic to pre-fill in the search URLs."),
        },
    ),
)

get_user_recommendations_fn = types.FunctionDeclaration(
    name="get_user_recommendations",
    description=(
        "Get personalised book recommendations for the currently logged-in user, "
        "based on their borrowing history and favourite categories/authors. "
        "Only available for authenticated users. Call this when the user asks "
        "for recommendations, 'what should I read next', 'vitabu vya kupendekeza', "
        "'napendekeza nini', or similar personal recommendation requests."
    ),
    parameters=types.Schema(
        type="object",
        properties={
            "limit": types.Schema(type="integer", description="Number of recommendations (1-10). Default 5."),
        },
    ),
)

# Base tools always available
TOOLS = types.Tool(
    function_declarations=[
        search_library_books_fn,
        get_book_detail_fn,
        list_categories_fn,
        get_library_info_fn,
        suggest_similar_books_fn,
        search_external_books_fn,
        get_online_libraries_fn,
    ]
)

# Auth-user tools (added dynamically in chat() when user is logged in)
AUTH_TOOLS_FNS = [get_user_recommendations_fn]

# Tool registry for execution (get_user_recommendations added per-request with user_id bound)
callable_tools = {
    "search_library_books":  library.search_library_books,
    "get_book_detail":        library.get_book_detail,
    "list_categories":        library.list_categories,
    "get_library_info":       library.get_library_info,
    "search_external_books":  google_books.search_external_books,
    "suggest_similar_books":  library.suggest_similar_books,
    "get_online_libraries":   library.get_online_libraries,
}

SYSTEM_INSTRUCTION = """Wewe ni Msaidizi wa Maktaba wa MSICT (MSICT Library Assistant) — daktari wa kidijitali wa Maktaba ya Shule ya Kijeshi ya Teknolojia ya Habari na Mawasiliano (Military School of Information and Communication Technology).

═══════════════════════════════════════════
LUGHA / LANGUAGE
═══════════════════════════════════════════
- Tambua lugha ya mtumiaji KIOTOMATIKI — Kiingereza au Kiswahili au mchanganyiko.
- JIBU DAIMA KWA LUGHA HIYO HIYO aliyoandika mtumiaji.
- Dalili za Kiswahili: maneno kama "je", "naomba", "kitabu", "vitabu", "tafuta", "kuna", "naweza", "habari", "ninataka", "ninaomba", "nipe", "niambie", "napenda", "saidia", "msaada".
- Kwa mchanganyiko wa lugha, jibu kwa lugha inayotawala.
- Unapojibu kwa Kiswahili, tumia Kiswahili safi na sahihi, usichanganye bila sababu.
- English detection: any sentence that is clearly English — reply in English.

═══════════════════════════════════════════
SHERIA ZA MSINGI / CORE RULES
═══════════════════════════════════════════
1. ANGALIA KWANZA maktaba ya MSICT kupitia `search_library_books` kabla ya vyanzo vya nje.
2. Piga simu `search_external_books` (Google Books) TU ikiwa utafutaji wa ndani haukupata matokeo yanayofaa, AU mtumiaji ameomba vyanzo vya nje.
3. Kitabu kikipatikana NDANI ya MSICT, taja:
   - Kichwa cha kitabu, mwandishi, mwaka, kategoria;
   - Upatikanaji wazi (nakala ngumu, softcopy huru, softcopy maalum);
   - **DAIMA jumuisha detail_url kama kiungo cha markdown: `[Jina la Kitabu](detail_url)`**.
4. Kitabu KISIPOKUWA katika MSICT:
   a. Sema wazi kwamba hakipo MSICT.
   b. Tumia `suggest_similar_books` kupendekeza mbadala katika MSICT.
   c. Tumia `get_online_libraries` kutoa viungo vya maktaba za nje zinazofaa.
   d. **DAIMA jumuisha viungo vya maktaba za nje kama markdown links zinazoweza kubonyezwa**.
5. Jibu liwe fupi na wazi (aya 2–5 au orodha fupi). Tumia markdown.
6. USIVUMBIE vitambulisho vya vitabu, ISBN, au namba za upatikanaji — tumia tu kinachorejesha zana.
7. Kukopa kitabu kunahitaji kuingia (login). Ikiwa wanauliza kukopa, waeleze kubonyeza kiungo cha kitabu na kuingia.

═══════════════════════════════════════════
MAPENDEKEZO YA KIBINAFSI / PERSONALISED RECOMMENDATIONS
(Authenticated users only)
═══════════════════════════════════════════
- Kama mtumiaji ameingia (logged in) na anauliza mapendekezo, vita vya kusoma, au "what should I read next" — LAZIMA piga simu `get_user_recommendations`.
- Zana hii hutumia historia ya kukopa ya mtumiaji kutengeneza mapendekezo ya kibinafsi.
- Ikiwa mtumiaji HAJAINGIYA (not logged in) na anauliza mapendekezo ya kibinafsi:
  Jibu: "Mapendekezo ya kibinafsi yanapatikana kwa watumiaji walioingia tu. / Personal recommendations are only available for logged-in users. Please log in to get personalised suggestions."

═══════════════════════════════════════════
MAKTABA ZA NJE / EXTERNAL ONLINE LIBRARIES
═══════════════════════════════════════════
- Kitabu kisipokuwa MSICT, LAZIMA tumia `get_online_libraries` na query ya kitabu hicho.
- Onyesha maktaba 3–5 zinazofaa zaidi kwa mada hiyo kama viungo vya kubonyezwa.
- Maktaba zinazofaa kwa ICT/tech: MIT OCW, Springer, Bookboon, Open Library.
- Maktaba zinazofaa kwa classics/fasihi: Project Gutenberg, Standard Ebooks.
- Maktaba ya jumla: Google Books, Open Library.
- Format ya jibu kwa maktaba za nje:
  `🌐 [Jina la Maktaba](url) — maelezo mafupi`

═══════════════════════════════════════════
UWEZO WAKO / YOUR CAPABILITIES
═══════════════════════════════════════════
- Tafuta vitabu kwa kichwa, mwandishi, mada — tumia `search_library_books`.
- Pendekeza vitabu vinavyofanana — tumia `suggest_similar_books`.
- Mapendekezo ya kibinafsi kwa mtumiaji aliyeingia — tumia `get_user_recommendations`.
- Toa viungo vya maktaba za nje — tumia `get_online_libraries`.
- Eleza mada kwa kiwango cha mwanzo/kati.
- Fupi muhtasari wa kitabu.
- Jibu maswali ya sera ya maktaba — tumia `get_library_info`.

Kuwa na joto, msaada, na ufupi. Tumia zana. Be warm, helpful, and concise. Use the tools.
"""


def _run_tool(name, args, tools_registry=None):
    """Execute a tool by name with given arguments."""
    registry = tools_registry if tools_registry is not None else callable_tools
    tool_func = registry.get(name)
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
    return settings.GEMINI_MODEL or "gemini-flash-latest"


# Fallback models tried in order if the primary model returns a 404
# (model not available) or 429 (quota exceeded). We keep them lite-tier
# because the assistant only needs short, factual replies.
_FALLBACK_MODELS = (
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
)


def _is_quota_or_404_error(exc):
    """Return True if the exception is worth retrying on a different model."""
    msg = str(exc).lower()
    return ("429" in msg or "quota" in msg or "resource_exhausted" in msg
            or "404" in msg or "not found" in msg)


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


def chat(history, user_message, max_tool_rounds=4, user_context=None):
    """
    Run a chatbot turn using google.genai SDK with manual function calling.

    `history`: list of dicts [{'role': 'user'|'model', 'text': '...'}]
    `user_message`: latest user text (string)
    `user_context`: dict with 'is_authenticated' and 'role' keys

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

    # Build context-aware system instruction and per-request tool set
    system_instruction = SYSTEM_INSTRUCTION
    local_callable = dict(callable_tools)
    active_tool_fns = list(TOOLS.function_declarations)

    if user_context:
        is_auth  = user_context.get('is_authenticated', False)
        role     = user_context.get('role', None)
        user_id  = user_context.get('user_id', None)

        if not is_auth:
            system_instruction += (
                "\n\n[MUKTADHA WA MTUMIAJI / USER CONTEXT]: "
                "Mtumiaji HAJAINGIYA (not logged in). "
                "Onyesha taarifa za vitabu tu bila kukopa. "
                "Mapendekezo ya kibinafsi HAYAPATIKANI — waeleze kuingia kwanza. "
                "Show books in VIEW-ONLY mode; borrowing and personal recommendations require login."
            )
        else:
            system_instruction += (
                f"\n\n[MUKTADHA WA MTUMIAJI / USER CONTEXT]: "
                f"Mtumiaji ameingia (logged in), role={role}. "
                f"Mapendekezo ya kibinafsi YANAPATIKANA — tumia get_user_recommendations. "
                f"Personal recommendations ARE available — call get_user_recommendations when asked."
            )
            if user_id:
                # Bind user_id via closure so the model never needs to pass it
                _uid = user_id
                local_callable['get_user_recommendations'] = (
                    lambda limit=5, _u=_uid: library.get_user_recommendations(user_id=_u, limit=limit)
                )
                active_tool_fns = active_tool_fns + AUTH_TOOLS_FNS

    active_tools = types.Tool(function_declarations=active_tool_fns)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    primary = _model_name()
    # Try the configured model first, then any fallbacks not equal to it.
    model_chain = (primary,) + tuple(m for m in _FALLBACK_MODELS if m != primary)

    def _generate(contents, with_tools=True):
        """Try each model in the chain until one succeeds (or all fail).

        When ``with_tools=False`` we omit the tool declarations so the
        model is forced to produce a final text answer (used after the
        max-tool-rounds budget is exhausted).
        """
        last_exc = None
        config_kwargs = {'system_instruction': system_instruction}
        if with_tools:
            config_kwargs['tools'] = [active_tools]
        for m in model_chain:
            try:
                return client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except Exception as exc:
                if _is_quota_or_404_error(exc) and m != model_chain[-1]:
                    logger.warning("Gemini model '%s' unavailable (%s); falling back.", m, exc)
                    last_exc = exc
                    continue
                raise
        if last_exc:
            raise last_exc

    tool_calls_log = []
    referenced_books = set()
    contents = _build_contents(history, user_message)

    try:
        round_count = 0
        while round_count < max_tool_rounds:
            response = _generate(contents)

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
                result = _run_tool(name, args, local_callable)

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

        # Max rounds reached. Drop tool declarations so the model is forced
        # to synthesise a text answer from the data we already gathered.
        response = _generate(contents, with_tools=False)

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
                "⏳ *Library Assistant Service Busy*\n"
                "The AI assistant is experiencing high demand right now. "
                "Please wait a moment and try again, or use the search feature to find books directly."
            )
        else:
            reply = f"Sorry, the AI service is temporarily unavailable. ({e})"

        return {
            "reply": reply,
            "tool_calls": tool_calls_log,
            "referenced_book_ids": sorted(referenced_books),
        }
