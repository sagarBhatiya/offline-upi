import os
import shutil
import sqlite3
from urllib.parse import urlparse
from src.config import Config

# Drivers for PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import pg8000.native
    HAS_PG8000 = True
except ImportError:
    HAS_PG8000 = False


class PostgresDictCursorWrapper:
    """Wrapper around PostgreSQL cursor providing dict-like row access and param normalization."""
    def __init__(self, raw_cursor, is_pg8000=False):
        self._cursor = raw_cursor
        self._is_pg8000 = is_pg8000
        self.lastrowid = None

    def execute(self, sql, params=None):
        # Convert SQLite style '?' placeholders to PostgreSQL '%s'
        pg_sql = sql.replace('?', '%s')
        
        # In PostgreSQL, lastrowid for INSERT is retrieved via RETURNING id
        is_insert = pg_sql.strip().upper().startswith('INSERT') and 'RETURNING' not in pg_sql.upper()
        if is_insert and ('INTO transactions' in pg_sql or 'INTO vouchers' in pg_sql or 'INTO fraud_audit_log' in pg_sql):
            pg_sql = pg_sql.rstrip(';') + ' RETURNING id;'

        if params is None:
            self._cursor.execute(pg_sql)
        else:
            self._cursor.execute(pg_sql, tuple(params))

        if is_insert and 'RETURNING id' in pg_sql:
            try:
                row = self._cursor.fetchone()
                if row:
                    self.lastrowid = row['id'] if isinstance(row, dict) else row[0]
            except Exception:
                pass
        return self

    def executemany(self, sql, params_list):
        pg_sql = sql.replace('?', '%s')
        for params in params_list:
            self.execute(pg_sql, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        # Wrap sequence to allow column or index access
        return row

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    def close(self):
        self._cursor.close()


class PostgresConnectionWrapper:
    """Wrapper around raw PostgreSQL connection."""
    def __init__(self, conn, is_pg8000=False):
        self._conn = conn
        self._is_pg8000 = is_pg8000

    def cursor(self):
        if HAS_PSYCOPG2 and not self._is_pg8000:
            raw_cur = self._conn.cursor(cursor_factory=RealDictCursor)
        else:
            raw_cur = self._conn.cursor()
        return PostgresDictCursorWrapper(raw_cur, is_pg8000=self._is_pg8000)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_sqlite_path():
    """Detects serverless environment for SQLite fallback."""
    is_serverless = bool(
        os.environ.get("VERCEL") or 
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or 
        not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK)
    )
    if is_serverless:
        tmp_dir = os.environ.get("TMPDIR", "/tmp")
        tmp_db = os.path.join(tmp_dir, "upi.db")
        return tmp_db
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_dir, "upi.db")


def is_postgres_configured():
    """Returns True if PostgreSQL connection URL is defined."""
    return bool(Config.DATABASE_URL and len(Config.DATABASE_URL.strip()) > 0)


def get_connection():
    """
    Returns an active database connection.
    Connects to PostgreSQL if DATABASE_URL is set, otherwise transparently falls back to SQLite.
    """
    db_url = Config.DATABASE_URL
    if db_url:
        try:
            if HAS_PSYCOPG2:
                conn = psycopg2.connect(db_url)
                return PostgresConnectionWrapper(conn, is_pg8000=False)
            elif HAS_PG8000:
                p = urlparse(db_url)
                conn = pg8000.dbapi.connect(
                    user=p.username,
                    password=p.password,
                    host=p.hostname,
                    port=p.port or 5432,
                    database=p.path.lstrip('/')
                )
                return PostgresConnectionWrapper(conn, is_pg8000=True)
        except Exception as e:
            print(f"[Database] PostgreSQL connection failed: {e}. Falling back to SQLite.")

    # SQLite fallback
    db_path = get_sqlite_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_db_type():
    """Returns 'postgres' if active connection uses PostgreSQL, else 'sqlite'."""
    return "postgres" if is_postgres_configured() else "sqlite"
