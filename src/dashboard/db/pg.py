import os
import time
import psycopg2
from psycopg2 import OperationalError, InterfaceError
from contextlib import contextmanager
from psycopg2.extras import execute_values

class PG:
    def __init__(self):
        self.connection = psycopg2.connect(
            host=os.getenv("PGHOST"),
            port=os.getenv("PGPORT"),
            dbname=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
        )

    # ---- internals ----
    def _connect(self):
        if self.connection and getattr(self.connection, "closed", 0) == 0:
            return
        # Enable TCP keepalives; helps prevent idle timeouts on proxies
        self.connection = psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            connect_timeout=self.connect_timeout,
            keepalives=1,
            keepalives_idle=30,      
            keepalives_interval=10, 
            keepalives_count=3
            # If your Railway instance requires SSL, add: sslmode="require"
        )
        # Optional: self.connection.autocommit = True

    def _ensure_conn(self):
        if self.connection is None or getattr(self.connection, "closed", 1) != 0:
            self._connect()

    def _reconnect(self):
        self.close()
        time.sleep(self.reconnect_backoff_sec)
        self._connect()

    @contextmanager
    def _cursor(self):
        """Context manager that ensures a live connection and yields a cursor."""
        self._ensure_conn()
        cur = self.connection.cursor()
        try:
            yield cur
        finally:
            cur.close()

    # ---- public API ----
    def execute_query(self, query, params=None, fetch=False):
        """
        Execute a SQL statement.
        - If fetch=True, returns list of rows (tuples).
        - If fetch=False, commits and returns None.
        Retries once on broken connection.
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._cursor() as cur:
                    cur.execute(query, params or ())
                    if fetch:
                        rows = cur.fetchall()
                        return rows
                    self.connection.commit()
                    return None
            except (OperationalError, InterfaceError):
                # Connection-related issue → reconnect & retry once
                if attempts >= 2:
                    # second failure: bubble up
                    raise
                self._reconnect()
            except Exception:
                # Any other error → do not retry; re-raise
                raise

    def ping(self):
        """Return True if the connection is healthy (reconnects if needed)."""
        try:
            self._ensure_conn()
            with self._cursor() as cur:
                cur.execute("SELECT 1")
                _ = cur.fetchone()
            return True
        except Exception:
            # Try one reconnect then one more ping
            try:
                self._reconnect()
                with self._cursor() as cur:
                    cur.execute("SELECT 1")
                    _ = cur.fetchone()
                return True
            except Exception:
                return False

    def close(self):
        """Close the database connection."""
        if self.connection:
            try:
                self.connection.close()
            finally:
                self.connection = None


    def execute_many_values(self, base_sql: str, rows: list[tuple], page_size: int = 1000):
        """
        Bulk INSERT using psycopg2.extras.execute_values.

        base_sql must contain a single '%s' placeholder for VALUES, e.g.:
          "INSERT INTO calendar_events (event_date, event_time, title, author) VALUES %s"

        rows is a list of tuples matching the INSERT columns.
        """
        if not rows:
            return None
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._cursor() as cur:
                    execute_values(cur, base_sql, rows, page_size=page_size)
                    self.connection.commit()
                return None
            except (OperationalError, InterfaceError):
                if attempts >= 2:
                    raise
                self._reconnect()
            except Exception:
                raise
