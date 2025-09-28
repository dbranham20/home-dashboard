# Dash Calendar + Postgres — Project Doc

_Last updated: 2025‑09‑27_

## Overview
A custom month‑view calendar component for a Dash app with:
- Full calendar grid (6×7) built from `html.Div` + CSS classes (theme‑aware via Mantine `data-mantine-color-scheme`).
- Click a date → modal to add events (title, time, author, recurrence).
- Events stored in Railway Postgres.
- Three‑month caching window (prev/current/next) to minimize DB trips.
- Mantine Skeleton "grid" loader while fetching.

## File Structure (suggested)
```
dashboard/
  app.py
  assets/
    calendar.css
  src/dashboard/
    db/pg.py             # PG wrapper (auto-reconnect + bulk insert)
    models/calendar.py   # MonthCtx (and future models)
    components/calendar.py  # UI + callbacks
    pages/home.py
```

## Environment & Secrets
Create `.env` (do **not** commit):
```
PGHOST=maglev.proxy.rlwy.net
PGPORT=31791
PGDATABASE=railway
PGUSER=postgres
PGPASSWORD=***
```
Load with `python-dotenv` or set via Railway project variables.

`.gitignore` (minimum):
```
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.env
```

## Database Schema
One table + helpful indexes + optional unique constraint for dedupe.
```sql
CREATE TABLE IF NOT EXISTS calendar_events (
  id            BIGSERIAL PRIMARY KEY,
  event_date    date        NOT NULL,
  event_time    time        NULL,
  title         text        NOT NULL,
  author        text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_event_date ON calendar_events (event_date);
CREATE INDEX IF NOT EXISTS idx_calendar_events_event_date_time ON calendar_events (event_date, event_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_author ON calendar_events (author);

-- Keep updated_at fresh
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_calendar_events_updated_at ON calendar_events;
CREATE TRIGGER trg_calendar_events_updated_at BEFORE UPDATE ON calendar_events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Optional: prevent duplicates for timed events
ALTER TABLE calendar_events
  ADD CONSTRAINT uq_calendar_events_four UNIQUE (event_date, event_time, title, author);
```
> Note: rows with `event_time IS NULL` are not deduped by Postgres UNIQUE (NULLs are distinct). Make `event_time` NOT NULL if you need full dedupe.

## PG Wrapper (auto‑reconnect + bulk insert)
`src/dashboard/db/pg.py`
```python
import time, os
import psycopg2
from psycopg2 import OperationalError, InterfaceError
from psycopg2.extras import execute_values
from contextlib import contextmanager
from dotenv import load_dotenv
load_dotenv()

class PG:
    def __init__(self):
        self.connection = None

    def _connect(self):
        if self.connection and getattr(self.connection, 'closed', 0) == 0:
            return
        self.connection = psycopg2.connect(
            host=os.getenv('PGHOST'), port=os.getenv('PGPORT'),
            dbname=os.getenv('PGDATABASE'), user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            connect_timeout=10,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
            # sslmode='require',  # enable if needed
        )

    def _ensure(self):
        if self.connection is None or getattr(self.connection, 'closed', 1) != 0:
            self._connect()

    def _reconnect(self):
        self.close(); time.sleep(0.5); self._connect()

    @contextmanager
    def _cursor(self):
        self._ensure(); cur = self.connection.cursor();
        try: yield cur
        finally: cur.close()

    def execute_query(self, sql, params=None, fetch=False):
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._cursor() as cur:
                    cur.execute(sql, params or ())
                    if fetch:
                        return cur.fetchall()
                    self.connection.commit(); return None
            except (OperationalError, InterfaceError):
                if attempts >= 2: raise
                self._reconnect()

    def execute_many_values(self, base_sql: str, rows: list[tuple], page_size: int = 1000):
        if not rows: return None
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._cursor() as cur:
                    execute_values(cur, base_sql, rows, page_size=page_size)
                    self.connection.commit(); return None
            except (OperationalError, InterfaceError):
                if attempts >= 2: raise
                self._reconnect()

    def close(self):
        if self.connection:
            try: self.connection.close()
            finally: self.connection = None
```

## Calendar Grid Logic
Always produce a 42‑day (6×7) grid to avoid duplicates.
```python
from datetime import date, timedelta

def iter_month_days(year: int, month: int):
    first = date(year, month, 1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)  # Sunday on/before 1st
    days = [start + timedelta(days=i) for i in range(42)]
    return [days[i:i+7] for i in range(0, 42, 7)]
```

## Theme‑Aware CSS (extract)
Key idea: variables switch based on `:root[data-mantine-color-scheme="light|dark"]`.
```css
:root{--radius-lg:16px;--gap:12px;--gap-sm:6px}
:root[data-mantine-color-scheme="light"]{--bg:#f6f7fb;--card:#fff;--muted:#606780;--text:#111319;--accent:#1565d8;--accent-soft:#e6eefb;--today:#eef3ff;--border:rgba(17,19,25,.08)}
:root[data-mantine-color-scheme="dark"]{--bg:#0b1020;--card:#111735;--muted:#8a91b4;--text:#e7eaf6;--accent:#5b8cff;--accent-soft:#263a80;--today:#2a3a7a;--border:rgba(255,255,255,.08)}
/* classes: .cal-app, .cal-card, .cal-header, .cal-weekdays, .cal-week, .cal-day, .cal-badge, .side-row, etc. */
```

## Mantine Skeleton Grid Loader
- `events-loading` store drives visibility.
- When loading: render a skeleton header + a 6×7 grid of placeholder cells; hide the real grid.
```python
import dash_mantine_components as dmc
from dash import html

def skeleton_day():
    return dmc.Paper(withBorder=True, radius="sm", className="cal-day",
        children=dmc.Stack(spacing=6, children=[
            dmc.Skeleton(height=10, width=24),
            dmc.Skeleton(height=14, width="90%"),
            dmc.Skeleton(height=14, width="80%"),
            dmc.Skeleton(height=14, width="55%"),
        ]), style={"minHeight":96, "padding":8})

def build_calendar_skeleton():
    header = dmc.SimpleGrid(cols=7, spacing="xs",
        children=[dmc.Skeleton(height=12, width="60%") for _ in range(7)],
        className="cal-weekdays")
    weeks = [dmc.SimpleGrid(cols=7, spacing="xs",
              children=[skeleton_day() for __ in range(7)], className="cal-week")
             for _ in range(6)]
    return html.Div([header, *weeks], className="cal-grid")
```

## Three‑Month Cache Window
Helpers:
```python
def first_of_month(y,m):
    from datetime import date
    return date(y,m,1)

def add_month(y,m,delta):
    i = (y*12 + (m-1)) + delta
    return i//12, (i%12)+1

def window_for_month(y,m):
    py, pm = add_month(y,m,-1)
    ny, nm = add_month(y,m,+2)
    from datetime import date
    return date(py,pm,1), date(ny,nm,1)  # [start, end)
```
Range fetch:
```python
from src.dashboard.db.pg import PG

def fetch_events_range(start, end):
    rows = PG().execute_query(
        """
        SELECT event_date,event_time,title,author
        FROM calendar_events
        WHERE event_date >= %s AND event_date < %s
        ORDER BY event_date, event_time NULLS LAST, id
        """, (start,end), fetch=True)
    out = {}
    for d,t,title,author in rows:
        iso = d.isoformat(); tt = t.strftime("%H:%M") if t else None
        out.setdefault(iso, []).append({"title":title, "time":tt, "author":author})
    return out
```

## Recurrence (Daily/Weekly/Monthly) + End Date
Modal adds chips + conditional end date. Save expands to individual rows and bulk‑inserts.
```python
from dateutil.relativedelta import relativedelta
from datetime import datetime, date, timedelta

def insert_events_bulk(start_date: date, end_date: date|None, freq: str|None,
                       title: str, author: str, time_str: str|None):
    # time parsing
    t=None
    if time_str:
        ts=time_str.strip()
        try: t=datetime.strptime(ts, "%H:%M").time()
        except ValueError: t=datetime.strptime(ts, "%I:%M %p").time()
    # dates
    if not freq or not end_date or end_date <= start_date:
        dates=[start_date]
    else:
        step = (lambda d:d+timedelta(days=1)) if freq=='daily' else \
               (lambda d:d+timedelta(days=7)) if freq=='weekly' else \
               (lambda d:d+relativedelta(months=+1))
        dates=[]; cur=start_date; limit=2000
        while cur<=end_date and len(dates)<limit:
            dates.append(cur); cur=step(cur)
    # bulk insert
    rows=[(d,t,title,author) for d in dates]
    PG().execute_many_values(
        "INSERT INTO calendar_events (event_date,event_time,title,author) VALUES %s",
        rows
    )
```

## UI Notes
- Author picker: use `dmc.ChipGroup(type=radio)` or `dmc.SegmentedControl`.
- Author colors (Amanda → pink, Daniel → blue) via CSS classes `.author-amanda`, `.author-daniel`.
- Right panel formats times as 12h (`%I:%M %p`) and aligns `time — title — author` with `space-between`.

## Callbacks (high level)
- Navigate months → update `cal-month` store.
- Month change → use 3‑month cache; fetch when out of window.
- Render month grid from `events-store`.
- Select day via pattern‑matching IDs → update `selected-date`.
- Open modal → choose title, time, author, recurrence, end date.
- Save → `insert_events_bulk` → refresh events (respect 3‑month cache if used).
- Toggle skeleton containers based on `events-loading`.

## Open TODOs / Next Steps
- Edit/delete events; bulk operations for recurring series.
- Event overlap visualization; per‑author color badges inside day cells.
- Server‑side caching (Redis) for range queries.
- Tests for date math (edge cases around DST, month lengths).
- Optional: make `event_time` NOT NULL with default `'00:00'` to dedupe all‑day entries.

## Setup
```bash
# install
poetry install

# run
poetry run python src/dashboard/app.py
```

---
Use this doc as the canonical reference when we resume. Add repo‑specific notes to `DEV_NOTES.md` alongside the code.

