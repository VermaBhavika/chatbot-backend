"""
chat.py

Same "brain" as before, PLUS an access-control layer:

RULE: a user should never receive qualitative insights (pros/cons/
recommendations/"why"/"what should X improve") about a company that
isn't their own. Numeric comparisons that INCLUDE their own company
are fine, since a score is just a number, not proprietary text.

IMPORTANT SECURITY NOTE:
own_company_public_id is currently trusted as given by the caller
(passed through from app.py's request body). This is NOT secure
against a tampered request yet — a real deployment should decode and
verify the user's JWT server-side in FastAPI and read company.public_id
from the verified token claims, not from client-supplied input. Wire
that in once your JWT verification approach (secret/algorithm) is
decided.
"""

import json

import ollama

from config import OLLAMA_MODEL
from tools import (
    get_company_score,
    compare_companies,
    list_companies_below_threshold,
    get_trend,
    get_company_by_public_id,
    get_all_company_names,
)
from qualitative_search import search_insights


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_company_score",
            "description": (
                "Get a company's score for a specific month. "
                "Use module_name for a specific module's score, "
                "or omit it for the overall report score."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "month_year": {
                        "type": "string",
                        "description": (
                            "Optional. Format YYYY-MM, e.g. 2026-05. "
                            "Omit this if the question doesn't mention a specific "
                            "month — it will default to the most recent month available."
                        ),
                    },
                    "module_name": {
                        "type": "string",
                        "description": (
                            "Optional. One of: pov, awareness, engagement, "
                            "perception, employee_sentiment"
                        ),
                    },
                },
                "required": ["company_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_companies",
            "description": "Compare multiple companies' score for one module in one month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "module_name": {"type": "string"},
                    "month_year": {
                        "type": "string",
                        "description": (
                            "Optional. Format YYYY-MM. Omit if no specific month "
                            "was mentioned — defaults to the most recent month available."
                        ),
                    },
                },
                "required": ["company_names", "module_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_companies_below_threshold",
            "description": (
                "List companies scoring below a given percentage on a "
                "module, for a given month."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module_name": {"type": "string"},
                    "threshold": {"type": "integer"},
                    "month_year": {
                        "type": "string",
                        "description": (
                            "Optional. Format YYYY-MM. Defaults to the most "
                            "recent month available if omitted."
                        ),
                    },
                },
                "required": ["module_name", "threshold"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend",
            "description": (
                "Get a company's score for one module across a range of "
                "months, for trend/change-over-time questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "module_name": {"type": "string"},
                    "start_month": {"type": "string", "description": "Format YYYY-MM"},
                    "end_month": {"type": "string", "description": "Format YYYY-MM"},
                },
                "required": ["company_name", "module_name", "start_month", "end_month"],
            },
        },
    },
]

FUNCTION_MAP = {
    "get_company_score": get_company_score,
    "compare_companies": compare_companies,
    "list_companies_below_threshold": list_companies_below_threshold,
    "get_trend": get_trend,
}

# --------------------------------------------------
# Access policy per tool:
#   "single_own_only"   -> the company_name argument MUST match the
#                          requesting user's own company
#   "must_include_own"   -> company_names list MUST include the
#                          requesting user's own company
#   "benchmark_allowed"  -> reveals a list of companies+scores but no
#                          qualitative text; allowed as-is (this mirrors
#                          the industry-benchmark feature already in
#                          the product). Change to a stricter policy
#                          here if you want it locked down further.
# --------------------------------------------------
ACCESS_POLICY = {
    "get_company_score": "single_own_only",
    "get_trend": "single_own_only",
    "compare_companies": "must_include_own",
    "list_companies_below_threshold": "benchmark_allowed",
}

BLOCKED_MESSAGE = (
    "Sorry, I can only share detailed insights and scores for your own "
    "company. I'm happy to help compare your company's performance "
    "against others, though — just ask!"
)

# Quick, reliable phrases for "what company am I" questions. These are
# handled directly in Python rather than via an LLM tool call, since
# none of the 4 defined tools are built to answer identity questions —
# forcing the LLM to pick one anyway was causing it to misfire (e.g.
# calling get_company_score with a guessed/missing month_year).
IDENTITY_PHRASES = [
    "name of my company",
    "which company am i",
    "what company am i",
    "who am i",
    "what is my company",
    "what's my company",
]


def _is_identity_question(question: str) -> bool:
    question_lower = question.lower()
    return any(phrase in question_lower for phrase in IDENTITY_PHRASES)


def _names_match(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _mentions_other_company(question: str, own_company_name: str) -> bool:
    """
    Heuristic check: does the question mention a company by name that
    is NOT the requesting user's own company? Used to block qualitative
    questions about competitors before we even attempt a Chroma search.
    """
    question_lower = question.lower()
    for company in get_all_company_names():
        name = company["name"]
        if _names_match(name, own_company_name):
            continue
        if name.lower() in question_lower:
            return True
    return False


def _tool_call_allowed(fn_name: str, fn_args: dict, own_company_name: str) -> bool:
    policy = ACCESS_POLICY.get(fn_name)

    if policy == "single_own_only":
        return _names_match(fn_args.get("company_name", ""), own_company_name)

    if policy == "must_include_own":
        company_names = fn_args.get("company_names", [])
        return any(_names_match(n, own_company_name) for n in company_names)

    if policy == "benchmark_allowed":
        return True

    # Unknown tool -> deny by default (safer than accidentally allowing)
    return False


def ask_question(question: str, own_company_public_id: str) -> str:
    """
    Main entry point.

    own_company_public_id: REQUIRED. Identifies which company the
    requesting user belongs to.

    IMPORTANT SECURITY NOTE (see top of file): this value currently
    comes from client-supplied input, not a server-verified source,
    because Slim doesn't yet expose a "verify this token, tell me who
    it belongs to" endpoint. A modified request could currently claim
    a different company_public_id. Once Slim adds such an endpoint,
    switch this back to resolving identity from the verified token
    instead (see the commented-out approach in auth.py).
    """

    own_company = get_company_by_public_id(own_company_public_id)
    if not own_company:
        return "Sorry, I couldn't identify your company. Please contact support."

    own_company_name = own_company["name"]

    # Fast-path: identity questions answered directly, no LLM/tool call
    # needed — this is both more reliable and avoids the LLM forcing
    # the question into an ill-fitting tool (see IDENTITY_PHRASES above).
    if _is_identity_question(question):
        return f"You're chatting as {own_company_name}."

    system_message = {
        "role": "system",
        "content": (
            f"The user asking questions belongs to the company '{own_company_name}'. "
            f"When they say 'my company', 'we', 'us', 'our', or similar, they mean "
            f"'{own_company_name}'. Use '{own_company_name}' as the exact company_name "
            f"value in any tool call when referring to their own company."
        ),
    }

    conversation = [system_message, {"role": "user", "content": question}]

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=conversation,
        tools=TOOLS,
    )

    message = response["message"]
    tool_calls = message.get("tool_calls")

    # --------------------------------------------------
    # CASE 1: The LLM picked a tool (structured/numeric question)
    # --------------------------------------------------
    if tool_calls:
        tool_call = tool_calls[0]
        fn_name = tool_call["function"]["name"]
        fn_args = tool_call["function"]["arguments"]

        if fn_name not in FUNCTION_MAP:
            return "Sorry, I couldn't process that request."

        if not _tool_call_allowed(fn_name, fn_args, own_company_name):
            return BLOCKED_MESSAGE

        try:
            result = FUNCTION_MAP[fn_name](**fn_args)
        except TypeError as e:
            # Usually means the LLM didn't supply a required argument
            # (e.g. company_name for get_company_score). month_year is
            # no longer required (it defaults to the latest month), so
            # this now mainly catches genuinely missing/malformed args.
            print(f"Tool '{fn_name}' called with bad arguments: {e}")
            return (
                "I need a bit more detail to answer that — could you mention "
                "the company or module you're asking about?"
            )
        except Exception as e:
            print(f"Tool '{fn_name}' failed: {e}")
            return "Sorry, something went wrong while looking that up."

        if not result:
            return "I couldn't find any data matching that request."

        follow_up = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                *conversation,
                message,
                {"role": "tool", "content": json.dumps(result, default=str)},
            ],
        )
        return follow_up["message"]["content"]

    # --------------------------------------------------
    # CASE 2: No tool matched -> qualitative/semantic question.
    # Block upfront if the question names another company, and
    # otherwise ALWAYS scope the Chroma search to the user's own
    # company (never trust anything else in the question text).
    # --------------------------------------------------
    if _mentions_other_company(question, own_company_name):
        return BLOCKED_MESSAGE

    return search_insights(question, company_public_id=own_company_public_id)