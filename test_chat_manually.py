"""
test_chat_manually.py

Point 5 from our plan: test chat.py by itself, BEFORE wiring it into
FastAPI. This avoids debugging your chatbot logic and your API/frontend
at the same time.

Run this from your terminal with:
    python test_chat_manually.py

Try a mix of question types:
- Structured/numeric  -> should trigger a tool call (tools.py)
- Qualitative          -> should fall back to qualitative_search.py
"""

from chat import ask_question

# Replace with a real public_id from your companies table.
MY_COMPANY_PUBLIC_ID = "1be3953e925975f3b5f777c9de3643bb"

test_questions = [
    # Should work: own company's numeric score
    "What was my engagement score in May 2026?",
    # Should work: comparison including own company
    "Compare my engagement score with Wrike in May 2026",
    # Should work: own company's qualitative insight
    "What should we do to improve employee sentiment?",
    # Should be BLOCKED: qualitative question about another company
    "Why is Wrike weak on brand perception?",
    # Should be BLOCKED: single competitor's raw score, not a comparison
    "What was Wrike's engagement score in May 2026?",
]

for question in test_questions:
    print("\n" + "=" * 70)
    print(f"Q: {question}")
    print("=" * 70)
    answer = ask_question(question, own_company_public_id=MY_COMPANY_PUBLIC_ID)
    print(f"A: {answer}")