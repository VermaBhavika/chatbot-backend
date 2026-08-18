"""
db.py

Beginner note: without this file, every single file that needs MySQL
(ingest_reports.py, tools.py) would each write their own
mysql.connector.connect(...) code. That's repetitive AND means if you
ever need to change HOW you connect (e.g., add connection pooling,
change timeout settings), you'd have to change it in every file.

This file centralizes that: everyone else just calls get_conn()
and doesn't need to know the connection details.

We use a "connection pool" here instead of a single connection.
A pool is like a small set of pre-opened connections that get reused,
which is faster and safer than opening/closing a brand new connection
every single time (important once your FastAPI app is handling
multiple chat requests at once).
"""

from mysql.connector import pooling
from config import MYSQL_CONFIG

_pool = None


def get_pool():
    """
    Creates the connection pool the first time it's needed,
    then reuses the same pool every time after that.
    """
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="reputracker_pool",
            pool_size=5,
            **MYSQL_CONFIG
        )
    return _pool


def get_conn():
    """
    Returns a MySQL connection borrowed from the pool.

    IMPORTANT: always call conn.close() when you're done with it
    (see examples in tools.py). This does NOT actually disconnect —
    it just returns the connection back to the pool so it can be
    reused by the next request. Forgetting to close it will
    eventually exhaust the pool.
    """
    return get_pool().get_connection()
