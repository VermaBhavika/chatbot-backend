"""
tools.py

These are plain Python functions that run SQL queries against MySQL.
chat.py exposes these to the LLM as "tools" it can call — the LLM
decides WHICH function fits the user's question, and Python actually
runs the real query (the LLM never writes SQL itself here, which
avoids it hallucinating wrong column/table names).

Beginner note on the pattern in every function below:
1. Open a connection (borrowed from the pool in db.py)
2. Run a query with cursor.execute(sql, params)
   - The %s placeholders get safely filled in with `params` —
     never build SQL strings with f-strings/concatenation directly
     with user input, that's how SQL injection happens.
3. Fetch the results
4. Close the cursor and connection
5. Return the results as plain Python data (list of dicts)
"""

from db import get_conn


def get_company_by_public_id(public_id: str):
    """
    Looks up a company's name from its public_id. Used to resolve
    'who is the requesting user's own company' for access control.
    """
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, public_id FROM companies WHERE public_id = %s",
        (public_id,),
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


def get_all_company_names():
    """
    Returns every company name in the system. Used to detect when a
    question mentions a competitor by name, so we can block
    qualitative/insight questions about companies other than the
    requesting user's own.
    """
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name, public_id FROM companies")
    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def get_latest_month_year():
    """
    Returns the most recent month_year present in the database.
    Used as a default whenever a question doesn't mention a specific
    month — e.g. "what's my score" or "compare me with Wrike" — so the
    LLM isn't forced to guess a date just to make the tool call work.
    """
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(month_year) FROM monthly_reports")
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None


def get_company_score(company_name: str, month_year: str | None = None, module_name: str | None = None):
    """
    Get a company's score for a given month.
    If month_year is omitted, defaults to the most recent month available.
    If module_name is given (e.g. "engagement"), returns just that module's score.
    Otherwise returns the overall report score for that month.
    """
    if not month_year:
        month_year = get_latest_month_year()

    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    if module_name:
        cursor.execute(
            """
            SELECT c.name, mr.month_year, m.display_name,
                   m.final_score, m.max_possible_score, m.score_percentage
            FROM companies c
            JOIN monthly_reports mr ON mr.company_id = c.id
            JOIN modules m ON m.monthly_report_id = mr.id
            WHERE c.name = %s AND mr.month_year = %s AND m.module_name = %s
            """,
            (company_name, month_year, module_name),
        )
    else:
        cursor.execute(
            """
            SELECT c.name, mr.month_year, mr.overall_score_percentage, mr.total_score
            FROM companies c
            JOIN monthly_reports mr ON mr.company_id = c.id
            WHERE c.name = %s AND mr.month_year = %s
            """,
            (company_name, month_year),
        )

    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def compare_companies(company_names: list[str], module_name: str, month_year: str | None = None):
    """
    Compare multiple companies' score for one module in one month.
    If month_year is omitted, defaults to the most recent month available.
    """
    if not month_year:
        month_year = get_latest_month_year()

    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    placeholders = ",".join(["%s"] * len(company_names))
    cursor.execute(
        f"""
        SELECT c.name, m.score_percentage, m.final_score
        FROM companies c
        JOIN monthly_reports mr ON mr.company_id = c.id
        JOIN modules m ON m.monthly_report_id = mr.id
        WHERE c.name IN ({placeholders}) AND mr.month_year = %s AND m.module_name = %s
        """,
        (*company_names, month_year, module_name),
    )

    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def list_companies_below_threshold(module_name: str, threshold: int, month_year: str | None = None):
    """
    List companies scoring below a threshold percentage on a given module,
    for a given month. Sorted lowest-first.
    If month_year is omitted, defaults to the most recent month available.
    """
    if not month_year:
        month_year = get_latest_month_year()

    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT c.name, m.score_percentage
        FROM companies c
        JOIN monthly_reports mr ON mr.company_id = c.id
        JOIN modules m ON m.monthly_report_id = mr.id
        WHERE m.module_name = %s AND mr.month_year = %s AND m.score_percentage < %s
        ORDER BY m.score_percentage ASC
        """,
        (module_name, month_year, threshold),
    )

    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result


def get_trend(company_name: str, module_name: str, start_month: str, end_month: str):
    """
    Get a company's score for one module across a range of months,
    useful for "how has this changed over time" questions.
    """
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT mr.month_year, m.score_percentage
        FROM companies c
        JOIN monthly_reports mr ON mr.company_id = c.id
        JOIN modules m ON m.monthly_report_id = mr.id
        WHERE c.name = %s AND m.module_name = %s
          AND mr.month_year BETWEEN %s AND %s
        ORDER BY mr.month_year ASC
        """,
        (company_name, module_name, start_month, end_month),
    )

    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return result