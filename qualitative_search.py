"""
qualitative_search.py

This is the piece chat.py falls back to when a question is NOT a
structured/numeric one (like "what's the score") but a qualitative one
(like "why is Company X weak on brand perception" or "what should
Company Y improve").

Beginner explanation of what happens here, step by step:
1. Turn the user's question into a vector (a list of numbers) using
   the same embedding model that was used during ingestion.
2. Ask ChromaDB: "which stored pieces of text have vectors most
   similar to this question's vector?" This is called a
   "similarity search" or "vector search".
3. Take the top matching pieces of text (the "context").
4. Hand that context + the original question to the LLM (Ollama) and
   ask it to answer USING that context, instead of making something up.

This is the same RAG pattern from your original React docs chatbot —
just applied to company insight text instead of documentation text.
"""

import chromadb
from sentence_transformers import SentenceTransformer
import ollama

from config import (
    CHROMA_PATH,
    INSIGHTS_COLLECTION_NAME,
    OLLAMA_MODEL,
    EMBEDDING_MODEL,
    TOP_K_RESULTS,
    SIMILARITY_THRESHOLD,
)

# Loaded once when this file is first imported, reused for every question.
embedding_model = SentenceTransformer(EMBEDDING_MODEL)

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
insights_collection = chroma_client.get_or_create_collection(INSIGHTS_COLLECTION_NAME)


def search_insights(question: str, company_public_id: str | None = None) -> str:
    """
    Searches the company_insights Chroma collection for text relevant
    to the question, then asks the LLM to answer using that text.

    company_public_id: optional. If your chatbot lives on a single
    company's dashboard page, pass that company's public_id here so
    results are restricted to that company only, instead of possibly
    mixing in other companies' data.
    """

    question_embedding = embedding_model.encode(question)

    # "where" lets us filter results to a specific company if given.
    # This matches against the metadata we stored during ingestion
    # (see the "metadatas" field in ingest_reports.py).
    where_filter = {"company_public_id": company_public_id} if company_public_id else None

    results = insights_collection.query(
        query_embeddings=[question_embedding.tolist()],
        n_results=TOP_K_RESULTS,
        where=where_filter,
    )

    documents = results["documents"][0]
    distances = results["distances"][0]

    # If nothing came back, or the closest match is too far away
    # (too dissimilar), don't guess — say so honestly.
    if not documents or distances[0] > SIMILARITY_THRESHOLD:
        return "Sorry, I couldn't find relevant information to answer that question."

    context = "\n\n".join(documents)

    prompt = f"""
You are a brand reputation analyst assistant for the ReputTracker platform.

Reference information about the company:
{context}

Rules:
- Answer naturally using only the reference information above.
- Never mention "documents", "context", or "reference material" explicitly.
- If the reference information is insufficient to answer, say so honestly.

Question:
{question}

Answer:
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )

    return response["message"]["content"]
