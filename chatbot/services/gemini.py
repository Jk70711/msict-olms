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
    parameters=types.Schema(
        type="object", 
        properties={
            "dummy": types.Schema(type="string", description="Optional dummy parameter (not used).")
        }
    ),
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
    "search_external_books":  google_books.search_external_books,
    "suggest_similar_books":  library.suggest_similar_books,
    "get_online_libraries":   library.get_online_libraries,
}

SYSTEM_INSTRUCTION = """Wewe ni Msaidizi wa Maktaba wa MSICT (MSICT Library Assistant) — mwongozaji wa kidijitali wa Maktaba ya Shule ya Kijeshi ya Teknolojia ya Habari na Mawasiliano (Military School of Information and Communication Technology).

═══════════════════════════════════════════
LUGHA / LANGUAGE
═══════════════════════════════════════════
- Tambua lugha ya mtumiaji KIOTOMATIKI — Kiingereza au Kiswahili au mchanganyiko.
- JIBU DAIMA KWA LUGHA HIYO HIYO aliyoandika mtumiaji.
- Dalili za Kiswahili: maneno kama "je", "naomba", "kitabu", "vitabu", "tafuta", "kuna", "naweza", "habari", "ninataka", "ninaomba", "nipe", "niambie", "napenda", "saidia", "msaada", "ada", "faini", "wageni", "uharibifu", "kupoteza".
- Kwa mchanganyiko wa lugha, jibu kwa lugha inayotawala.
- English detection: any sentence that is clearly English — reply in English.

═══════════════════════════════════════════
SHERIA ZA MSINGI / CORE RULES
═══════════════════════════════════════════
1. ANGALIA KWANZA maktaba ya MSICT kupitia `search_library_books` kabla ya vyanzo vya nje.
2. Piga simu `search_external_books` (Google Books) TU ikiwa utafutaji wa ndani haukupata matokeo yanayofaa.
3. Kitabu kikipatikana NDANI ya MSICT, taja:
   - Kichwa, mwandishi, mwaka, kategoria; upatikanaji (hardcopy/softcopy);
   - **DAIMA jumuisha detail_url: `[Jina la Kitabu](detail_url)`**.
4. Kitabu KISIPOKUWA MSICT: sema wazi, tumia `suggest_similar_books` + `get_online_libraries`.
5. Maswali yoyote ya SERA, ADA, FAINI, WAGENI, SOFTCOPY, UHARIBIFU, KUPOTEZA, OTP, USALAMA → REJEA "LIVE SYSTEM POLICIES" iliyoambatanishwa hapa chini.
6. Jibu liwe fupi na wazi (aya 2–5 au orodha). Tumia markdown.
7. USIVUMBIE namba — tumia tu kinachorejesha zana au LIVE POLICIES.

═══════════════════════════════════════════
MFUMO WA MAKTABA / HOW THE SYSTEM WORKS
═══════════════════════════════════════════
SHERIA ZOTE zinabadilishwa mara kwa mara na msimamizi (Admin) kupitia System Preferences. 
Tumeambatanisha "LIVE SYSTEM POLICIES" (Tazama chini). TUMIA DATA HIZO DAIMA kujibu maswali kuhusu:
- **Kukopa (Borrowing)**: Muda wa mkopo, idadi ya vitabu vinavyoruhusiwa, sheria za kurudisha vitabu (ikiwemo athari za faini).
- **Softcopy / Link Fee**: Sheria za vitabu vya kidijitali, ada, na muda wake.
- **Wageni (Guest Sessions)**: Bei kwa saa, muda wa juu, na sheria za wageni.
- **Faini (Fines)**: Faini za kuchelewa (overdue), uharibifu (damage), kupoteza (loss), na jinsi zinavyozuia kurudisha/kukopa vitabu.
- **Upyaji (Renewals) & Uhifadhi (Reservations)**: Sheria za kuongeza muda au kuhifadhi kitabu.
- **Usalama (Security)**: Sheria za OTP, nenosiri, session timeout, na kufungiwa akaunti.

ONYO KUBWA: USIBUNI (do not hallucinate) sheria zozote! Usitegemee uelewa wako wa awali. Tumia ONLY the live values injected at the bottom of this prompt.

═══════════════════════════════════════════
MAPENDEKEZO YA KIBINAFSI / PERSONALISED RECOMMENDATIONS
═══════════════════════════════════════════
- Mtumiaji aliyeingia anauliza mapendekezo → LAZIMA piga `get_user_recommendations`.
- Mtumiaji HAJAINGIYA → "Mapendekezo ya kibinafsi yanapatikana kwa watumiaji walioingia tu. Please log in."

═══════════════════════════════════════════
MAKTABA ZA NJE / EXTERNAL ONLINE LIBRARIES
═══════════════════════════════════════════
- Kitabu kisipokuwa MSICT → tumia `get_online_libraries` na query.
- Onyesha maktaba 3–5 zinazofaa. Format: `🌐 [Jina](url) — maelezo`
- ICT/tech: MIT OCW, Springer, Bookboon, Open Library.
- Classics: Project Gutenberg, Standard Ebooks.

═══════════════════════════════════════════
UWEZO WAKO / YOUR CAPABILITIES
═══════════════════════════════════════════
- Tafuta vitabu → `search_library_books`
- Maelezo kamili ya kitabu → `get_book_detail`
- Pendekeza vitabu → `suggest_similar_books`
- Mapendekezo ya kibinafsi → `get_user_recommendations`
- Maktaba za nje → `get_online_libraries`
- Sera ZOTE za maktaba (faini, ada, vikao vya wageni, softcopy, usalama, n.k.) → REJEA 'LIVE SYSTEM POLICIES' chini ya prompt hii.
- Kategoria za vitabu → `list_categories`

Kuwa na joto, msaada, na ufupi. Tumia zana daima. Be warm, helpful, and concise. Always use tools for live data.
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
            or "404" in msg or "not found" in msg
            or "503" in msg or "unavailable" in msg or "high demand" in msg)


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
    
    # Inject live library policies directly into the system prompt to prevent hallucination
    live_policies = library.get_library_info()
    system_instruction += (
        "\n\n═══════════════════════════════════════════\n"
        "LIVE SYSTEM POLICIES / SHERIA ZA MFUMO ZA SASA\n"
        "═══════════════════════════════════════════\n"
        "Msimamizi amebadilisha mipangilio ya mfumo. TUMIA DATA HIZI KWA MAJIBU YAKO:\n"
        f"{json.dumps(live_policies, indent=2)}\n"
        "ONYO: ALWAYS use the exact numbers/fees from this JSON block above when answering policy questions."
    )
    
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
                "Onyesha taarifa za vitabu, mada, na sheria za maktaba kwa uhuru. "
                "Mapendekezo ya kibinafsi (kulingana na historia) hayapatikani, "
                "lakini UNAWEZA kutoa mapendekezo ya jumla kulingana na kategoria anayouliza. "
                "Waeleze kuingia tu ikiwa wanataka KUKOPA kitabu. "
                "You are fully available to assist this guest user with catalog searches, "
                "general book recommendations, and library info. Borrowing requires login."
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
        config_kwargs['tools'] = [active_tools]
        if not with_tools:
            config_kwargs['tool_config'] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            )
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
            tool_results_texts = []
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

                # Build text response for the tool result instead of a formal FunctionResponse
                # This bypasses the google-genai SDK "thought_signature" serialization bug
                tool_results_texts.append(f"Tool `{name}` returned:\n{json.dumps(result)}")

            # Add the results to the contents as a user message
            if tool_results_texts:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text="\n\n".join(tool_results_texts))]
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
        error_str = str(e).lower()
        if any(term in error_str for term in ["429", "quota", "503", "unavailable", "high demand"]):
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
