"""
config.py

This file is the single "settings sheet" for the whole project.
Every other file (ingest_reports.py, tools.py, chat.py, qualitative_search.py)
imports values FROM here instead of hardcoding passwords/paths directly.

It reads real secret values from a ".env" file (which you create by copying
.env.example) using the python-dotenv library. This keeps secrets out of
your actual code files.
"""

import os
from dotenv import load_dotenv

# Reads the .env file in this folder and loads its values into the
# environment, so os.getenv() below can find them.
load_dotenv()

# --------------------------------------------------
# MySQL connection settings
# --------------------------------------------------
# This dictionary gets passed directly into mysql.connector.connect(**MYSQL_CONFIG)
# in db.py, so the keys must match what that library expects.
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DATABASE"),
}

# --------------------------------------------------
# ChromaDB (vector database) settings
# --------------------------------------------------
# This is just a folder path on disk where Chroma stores its data.
# It gets created automatically the first time you run ingestion.
CHROMA_PATH = os.getenv("CHROMA_PATH", "chroma_db")

# Name of the Chroma "collection" (like a table, but for vectors)
# that stores embeddings of company insight text (pros/cons/recommendations).
INSIGHTS_COLLECTION_NAME = "company_insights"

# --------------------------------------------------
# Ollama (local LLM) settings
# --------------------------------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# --------------------------------------------------
# Slim backend settings (where the raw company report JSON comes from)
# --------------------------------------------------
SLIM_API_BASE = os.getenv("SLIM_API_BASE")
SLIM_API_TOKEN = os.getenv("SLIM_API_TOKEN")

# --------------------------------------------------
# Embedding model
# --------------------------------------------------
# This is the model that turns text into vectors (lists of numbers)
# so Chroma can do similarity search.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# --------------------------------------------------
# Retrieval tuning
# --------------------------------------------------
# How many similar chunks to retrieve from Chroma per question.
TOP_K_RESULTS = 5

# Distance threshold for Chroma results — lower distance = more similar.
# If the best match's distance is ABOVE this number, we treat it as
# "no good match found" rather than making something up.
# Start with this value and adjust based on testing with real questions.
SIMILARITY_THRESHOLD = 1.0