"""
ingest_reports.py

This script pulls each company's report data from your Slim backend
and writes it into two places:
1. MySQL  -> structured, exact numbers (scores, modules, etc.)
2. Chroma -> vector embeddings of the qualitative text (pros/cons/
             recommendations/summary), used later for semantic search
             in qualitative_search.py

Run this:
    python ingest_reports.py

Beginner note: this uses "upsert" logic (INSERT ... ON DUPLICATE KEY
UPDATE) so it's safe to re-run. If a company or month already exists,
it updates it instead of creating a duplicate row.
"""

import json
import requests
import chromadb
from datetime import datetime
from sentence_transformers import SentenceTransformer

from config import (
    SLIM_API_BASE,
    SLIM_API_TOKEN,
    CHROMA_PATH,
    INSIGHTS_COLLECTION_NAME,
    EMBEDDING_MODEL,
)
from db import get_conn

# --------------------------------------------------
# Loaded once, reused for every company processed
# --------------------------------------------------
embedding_model = SentenceTransformer(EMBEDDING_MODEL)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
insights_collection = chroma_client.get_or_create_collection(INSIGHTS_COLLECTION_NAME)


# --------------------------------------------------
# Helper: normalize "May-2026" -> "2026-05"
#
# The schema stores month_year as ISO "YYYY-MM" so it sorts and
# compares correctly in SQL (needed for get_trend's BETWEEN queries
# in tools.py). The API gives us "Mon-YYYY" style strings instead.
# --------------------------------------------------
def normalize_month_year(raw: str) -> str:
    parsed = datetime.strptime(raw, "%b-%Y")
    return parsed.strftime("%Y-%m")


# --------------------------------------------------
# Helper: parse API timestamps like "2026-05-30T18:30:00.000000Z"
# into a real Python datetime object.
#
# MySQL's DATETIME column rejects the raw ISO 8601 string (the "T",
# "Z", and microseconds aren't valid MySQL datetime syntax). Passing
# an actual datetime object instead lets the MySQL connector format
# it correctly, and avoids doing fragile string surgery ourselves.
# --------------------------------------------------
def parse_api_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # Handles trailing "Z" (UTC) by converting it to "+00:00" first,
    # since Python's fromisoformat wants an explicit offset, not "Z".
    cleaned = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


# --------------------------------------------------
# STEP 0: Fetch the full list of company public_ids across all
# pages, instead of hand-maintaining a text file of 300+ IDs.
# --------------------------------------------------
def fetch_all_company_ids() -> list[str]:
    """
    Loops through every page of the companies list endpoint and
    collects each company's public_id.

    NOTE: update COMPANIES_LIST_ENDPOINT below to match your real
    Slim endpoint path once confirmed.
    """
    COMPANIES_LIST_ENDPOINT = f"{SLIM_API_BASE}/companies"  # <-- confirm/adjust this path

    all_ids = []
    page = 1

    while True:
        resp = requests.get(
            COMPANIES_LIST_ENDPOINT,
            headers={"Authorization": f"Bearer {SLIM_API_TOKEN}"},
            params={"page": page},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()

        data = body["data"]
        companies = data["data"]
        pagination = data["pagination"]

        for company in companies:
            all_ids.append(company["public_id"])

        print(f"  Fetched page {pagination['current_page']} of {pagination['last_page']} "
              f"({len(all_ids)} companies so far)")

        if pagination["current_page"] >= pagination["last_page"]:
            break

        page += 1

    return all_ids


# --------------------------------------------------
# STEP 1: Fetch one company's report data from Slim
# --------------------------------------------------
def fetch_company_report(public_id: str) -> dict:
    url = f"{SLIM_API_BASE}/reports/company/{public_id}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {SLIM_API_TOKEN}"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()

    # Real API shape: {"status": 200, "success": true, "data": {...}}
    # Everything we actually need lives inside "data".
    if "data" not in body:
        raise ValueError(
            f"Unexpected response shape from {url}.\n"
            f"Expected a 'data' key but got keys: {list(body.keys())}"
        )

    data = body["data"]

    if "company" not in data or "monthly_reports" not in data:
        raise ValueError(
            f"Unexpected 'data' shape from {url}.\n"
            f"Expected 'company' and 'monthly_reports' keys but got: {list(data.keys())}"
        )

    return data


# --------------------------------------------------
# STEP 2: Save/update the company row
# --------------------------------------------------
def upsert_company(cursor, company: dict, created_at: str | None, updated_at: str | None) -> int:
    cursor.execute(
        """
        INSERT INTO companies (public_id, name, domain, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = %s, domain = %s, updated_at = COALESCE(%s, updated_at)
        """,
        (
            company["public_id"], company["name"], company["domain"], created_at, updated_at,
            company["name"], company["domain"], updated_at,
        ),
    )
    cursor.execute("SELECT id FROM companies WHERE public_id = %s", (company["public_id"],))
    return cursor.fetchone()[0]


# --------------------------------------------------
# STEP 3: Save/update one month's report row
# --------------------------------------------------
def upsert_monthly_report(cursor, company_id: int, monthly: dict) -> int:
    latest = monthly["latest_execution"]
    month_year = normalize_month_year(monthly["month_year"])
    created_at = parse_api_datetime(latest["created_at"])

    cursor.execute(
        """
        INSERT INTO monthly_reports
            (company_id, execution_id, public_id, month_year, status,
             total_score, overall_score_percentage, total_modules,
             total_data_sources, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            total_score = %s,
            overall_score_percentage = %s,
            status = %s
        """,
        (
            company_id, latest["execution_id"], latest["public_id"],
            month_year, latest["status"], latest["total_score"],
            monthly["summary"]["overall_score_percentage"],
            monthly["summary"]["total_modules"],
            monthly["summary"]["total_data_sources"],
            created_at,
            latest["total_score"],
            monthly["summary"]["overall_score_percentage"],
            latest["status"],
        ),
    )

    cursor.execute(
        "SELECT id FROM monthly_reports WHERE company_id = %s AND month_year = %s",
        (company_id, month_year),
    )
    return cursor.fetchone()[0]


# --------------------------------------------------
# STEP 4: Save each module's score + insights, and embed
#         the qualitative text into Chroma
# --------------------------------------------------
def upsert_modules_and_insights(
    cursor,
    report_id: int,
    company_public_id: str,
    company_name: str,
    month_year: str,
    modules: list,
):
    for m in modules:
        cursor.execute(
            """
            INSERT INTO modules
                (monthly_report_id, module_name, display_name, description,
                 final_score, max_possible_score, score_percentage, public_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                report_id, m["module_name"], m["display_name"], m["description"],
                m["final_score"], m["max_possible_score"], m["score_percentage"],
                m["public_id"],
            ),
        )
        module_id = cursor.lastrowid

        # Some modules may have "insights": null (not just missing the
        # key) if insights haven't been generated for that module yet.
        # `.get("insights", {})` alone wouldn't catch that — an explicit
        # `or {}` handles both "missing" and "present but null".
        insight = m.get("insights") or {}
        cursor.execute(
            """
            INSERT INTO module_insights (module_id, tagline, pros, cons, recommendations)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                module_id,
                insight.get("tagline"),
                json.dumps(insight.get("pros", [])),
                json.dumps(insight.get("cons", [])),
                json.dumps(insight.get("recommendations", [])),
            ),
        )

        # --- Embed the qualitative text into Chroma ---
        text_blob = " ".join(
            [
                insight.get("tagline", "") or "",
                *insight.get("pros", []),
                *insight.get("cons", []),
                *insight.get("recommendations", []),
            ]
        ).strip()

        if text_blob:
            embedding = embedding_model.encode(text_blob)
            # id must be unique per (company, month, module) so re-running
            # ingestion updates the same vector instead of duplicating it
            vector_id = f"{company_public_id}_{month_year}_{m['module_name']}"

            insights_collection.upsert(
                ids=[vector_id],
                documents=[text_blob],
                embeddings=[embedding.tolist()],
                metadatas=[
                    {
                        # NOTE: key name must match qualitative_search.py's
                        # where_filter key ("company_public_id")
                        "company_public_id": company_public_id,
                        "company_name": company_name,
                        "month_year": month_year,
                        "module_name": m["module_name"],
                        "score_percentage": m["score_percentage"],
                    }
                ],
            )


# --------------------------------------------------
# STEP 5: Save the overall report summary
# --------------------------------------------------
def upsert_report_summary(cursor, report_id: int, monthly: dict):
    insights = monthly.get("insights") or {}
    if not insights.get("has_insights"):
        return

    cursor.execute(
        """
        INSERT INTO report_summaries (monthly_report_id, overall_summary, total_modules_analyzed)
        VALUES (%s, %s, %s)
        """,
        (report_id, insights.get("overall_summary"), insights.get("total_modules_analyzed")),
    )


# --------------------------------------------------
# Main entry point: runs ingestion for a list of company public_ids
# --------------------------------------------------
def run_ingestion(company_public_ids: list[str]):
    conn = get_conn()
    cursor = conn.cursor()

    for public_id in company_public_ids:
        print(f"Ingesting company: {public_id}")

        try:
            data = fetch_company_report(public_id)
        except (requests.RequestException, ValueError) as e:
            print(f"  FAILED to fetch {public_id}: {e}")
            continue

        company = data["company"]

        company_id = upsert_company(
            cursor,
            company,
            created_at=None,  # this endpoint doesn't return company created_at/updated_at
            updated_at=None,
        )

        for monthly in data["monthly_reports"]:
            report_id = upsert_monthly_report(cursor, company_id, monthly)
            month_year = normalize_month_year(monthly["month_year"])

            upsert_modules_and_insights(
                cursor,
                report_id,
                company_public_id=company["public_id"],
                company_name=company["name"],
                month_year=month_year,
                modules=monthly["modules"],
            )

            upsert_report_summary(cursor, report_id, monthly)

        # Commit after each company so partial progress isn't lost
        # if a later company fails.
        conn.commit()
        print(f"  Done: {company['name']}")

    cursor.close()
    conn.close()
    print("\nIngestion complete.")


if __name__ == "__main__":
    # --------------------------------------------------
    # Fetches every company's public_id automatically by walking
    # through all pages of the companies list endpoint, then runs
    # ingestion for all of them.
    #
    # To go back to testing a single company, comment out the two
    # lines below and uncomment the hardcoded single-ID list instead.
    # --------------------------------------------------
    print("Fetching full company list...")
    company_public_ids = fetch_all_company_ids()
    print(f"Found {len(company_public_ids)} companies total.\n")

    # company_public_ids = [
    #     "6df40870bbf75ec7a886fd035dec04fc",  # Cloud Dentistry, for single-company testing
    # ]

    run_ingestion(company_public_ids)