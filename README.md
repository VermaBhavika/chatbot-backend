# ReputTracker Chatbot — Setup Guide (Beginner Walkthrough)

This project answers questions about company reputation scores stored
across 300 companies. It combines:
- **MySQL** — stores exact scores/numbers (fast, precise lookups)
- **ChromaDB** — stores "vectors" (number representations of text) for
  fuzzy/semantic search over qualitative insights (pros/cons/recommendations)
- **Ollama (llama3.2)** — the local LLM that reads results and writes
  natural-language answers

Follow these steps **in order**. Don't skip ahead — each step depends
on the previous one working.

---

## Step 0: Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Also make sure Ollama is installed and the model is pulled:
```bash
ollama pull llama3.2:latest
```

---

## Step 1: Set up your secrets

```bash
cp .env.example .env
```

Open `.env` and fill in your real MySQL password, database name, and
your Slim backend's API base URL + token. Never commit this file.

---

## Step 2: Create the database and tables

First create an empty database in MySQL (skip if it already exists):
```sql
CREATE DATABASE reputracker;
```

Then run the schema file against it:
```bash
mysql -u root -p reputracker < schema.sql
```

Check it worked:
```sql
USE reputracker;
SHOW TABLES;
```
You should see: companies, monthly_reports, modules, module_insights, report_summaries

---

## Step 3: Test ingestion on ONE company first

Before running `ingest_reports.py` against all 300 companies, edit the
bottom of that file so `company_ids` only contains ONE public_id you
know is valid. Run it:

```bash
python ingest_reports.py
```

Then check both places got data:

**MySQL:**
```sql
SELECT * FROM companies;
SELECT * FROM monthly_reports;
SELECT * FROM modules;
```

**ChromaDB** — quick way to check, run this in a Python shell:
```python
import chromadb
client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_collection("company_insights")
print(collection.count())   # should be > 0
print(collection.peek())    # shows a few stored entries
```

Only once this looks correct should you add the remaining 299 company
IDs and re-run ingestion for the full set.

---

## Step 4: Test the chatbot logic directly (no API yet)

```bash
python test_chat_manually.py
```

This asks a mix of numeric and qualitative questions directly through
`ask_question()` — no FastAPI, no frontend, no browser involved. This
is the fastest way to catch bugs in the chatbot logic itself.

If answers look wrong:
- Numeric answer wrong/missing → check `tools.py` SQL and check the
  company name spelling matches exactly what's in MySQL
- Qualitative answer says "couldn't find information" → check
  `SIMILARITY_THRESHOLD` in `config.py`; it may be too strict

---

## Step 5: Run the FastAPI server

```bash
uvicorn app:app --reload --port 8000
```

Test it directly with curl (no frontend needed yet):
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What was HG Insights engagement score in May 2026?"}'
```

---

## Step 6: Connect the Next.js frontend

Once the API responds correctly via curl, point your Next.js chat
component at `http://localhost:8000/chat` (or wherever you deploy it),
sending `{ message: "..." }` and rendering the `answer` field back.

---

## File overview

| File | Purpose |
|---|---|
| `config.py` | Central settings, reads from `.env` |
| `.env` / `.env.example` | Actual secrets / template |
| `schema.sql` | MySQL table definitions |
| `db.py` | Shared MySQL connection pool |
| `tools.py` | SQL functions for structured/numeric questions |
| `qualitative_search.py` | Chroma vector search for qualitative questions |
| `ingest_reports.py` | Pulls data from Slim, writes to MySQL + Chroma |
| `chat.py` | Routes each question to the right tool or search |
| `app.py` | FastAPI HTTP endpoint for the Next.js frontend |
| `test_chat_manually.py` | Manual test script, run before wiring up FastAPI |
