"""
app.py

The FastAPI HTTP server. This is the only file your Next.js frontend
talks to directly — it exposes a single POST /chat endpoint.

Run this with:
    uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chat import ask_question

app = FastAPI(title="ReputTracker Chatbot API")

# Allows your Next.js dev server (localhost:3000) to call this API
# from the browser. Add your production frontend URL here too once deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    # SECURITY NOTE: this is currently trusted as sent by the frontend.
    # Slim doesn't yet have an endpoint that verifies a token and
    # returns its owner's company, so we can't independently confirm
    # this value server-side yet. The frontend should populate this
    # from the company.public_id it already received at login.
    #
    # Once Slim adds a real "verify this token" endpoint, switch this
    # back to resolving identity from the verified bearer token
    # instead of trusting this field (see auth.py, currently unused).
    company_public_id: str


@app.post("/chat")
def chat(request: ChatRequest):
    answer = ask_question(
        question=request.message,
        own_company_public_id=request.company_public_id,
    )
    return {"answer": answer}


@app.get("/health")
def health():
    """Simple endpoint to confirm the server is running."""
    return {"status": "ok"}