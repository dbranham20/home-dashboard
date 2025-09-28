import dash
import calendar
from dash import callback, html, dcc, Input, Output, State, ALL
from datetime import date, datetime, timedelta
import dash_mantine_components as dmc
from typing import Dict, List

from dashboard.db.pg import PG
from dashboard.models.calendar import MonthCtx
from dateutil.relativedelta import relativedelta


dash.register_page(__name__, path="/")


users = ['Amanda', 'Daniel']


def _skeleton_day_cell():
    return dmc.Paper(
        withBorder=True,
        radius="sm",
        className="cal-day",  # reuses your borders/padding
        children=dmc.Stack(
            children=[
                dmc.Skeleton(height=10, width=24),             # day number
                dmc.Skeleton(height=14, width="90%"),          # event line 1
                dmc.Skeleton(height=14, width="80%"),          # event line 2
            ],
        ),
        style={"minHeight": 96, "padding": 8}
    )

def build_calendar_skeleton():
    header = dmc.SimpleGrid(
        cols=7,
        spacing="xs",
        children=[dmc.Skeleton(height=12, width="60%") for _ in range(7)],
        className="cal-weekdays"
    )

    # 6 rows x 7 columns of day skeletons
    weeks = []
    for _ in range(6):
        weeks.append(
            dmc.SimpleGrid(
                cols=7,
                spacing="xs",
                children=[_skeleton_day_cell() for __ in range(7)],
                className="cal-week"
            )
        )

    # Wrap in a container that mirrors your real grid spacing
    return html.Div(
        [header, *weeks],
        className="cal-grid",
        style={"gap": "12px"}  # match your CSS var if needed
    )


def fetch_events_for_month(year: int, month: int):
    pg = PG()
    first = date(year, month-1, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1)
    sql = """
        SELECT event_date, event_time, title, author
        FROM calendar_events
        WHERE event_date >= %s AND event_date < %s
        ORDER BY event_date, event_time NULLS LAST, id
    """
    rows = pg.execute_query(sql, (first, last), fetch=True)
    events: Dict[str, List[dict]] = {}

    for event_date, event_time, title, author in rows:
        iso = event_date.isoformat()
        time_txt = event_time.strftime("%H:%M") if event_time else None
        events.setdefault(iso, []).append({
            "title": title,
            "time": time_txt,
            "author": author
        })
    return events

from datetime import date

def first_of_month(y: int, m: int) -> date:
    return date(y, m, 1)

def add_month(y: int, m: int, delta: int) -> tuple[int, int]:
    # returns (year, month) after delta months
    i = (y * 12 + (m - 1)) + delta
    return i // 12, (i % 12) + 1

def window_for_month(y: int, m: int) -> tuple[date, date]:
    """
    3-month window centered on (y, m):
      [ first_of(prev), first_of(next+1) )
    """
    py, pm = add_month(y, m, -1)   # previous month
    ny, nm = add_month(y, m, +2)   # month after next
    start = first_of_month(py, pm)
    end   = first_of_month(ny, nm)  # exclusive
    return start, end

def fetch_events_range(start: date, end: date) -> Dict[str, List[dict]]:
    pg = PG()

    sql = """
        SELECT event_date, event_time, title, author
        FROM calendar_events
        WHERE event_date >= %s AND event_date < %s
        ORDER BY event_date, event_time NULLS LAST, id
    """
    rows = pg.execute_query(sql, (start, end), fetch=True)
    events: Dict[str, List[dict]] = {}
    for event_date, event_time, title, author in rows:
        iso = event_date.isoformat()
        t = event_time.strftime("%H:%M") if event_time else None
        events.setdefault(iso, []).append({"title": title, "time": t, "author": author})
    return events


def insert_events_bulk(start_date: date, end_date: date | None,
                       freq: str | None, title: str, author: str,
                       time_str: str | None):
    # Parse time -> datetime.time | None
    t = None
    if time_str:
        ts = time_str.strip()
        try:
            t = datetime.strptime(ts, "%H:%M").time()        # 24h
        except ValueError:
            t = datetime.strptime(ts, "%I:%M %p").time()     # 12h

    # Build date list
    if not freq or not end_date or end_date <= start_date:
        dates = [start_date]
    else:
        step = (
            (lambda d: d + timedelta(days=1)) if freq == "daily"
            else (lambda d: d + timedelta(days=7)) if freq == "weekly"
            else (lambda d: d + relativedelta(months=+1))
        )
        dates, cur = [], start_date
        limit = 2000  # safety
        while cur <= end_date and len(dates) < limit:
            dates.append(cur)
            cur = step(cur)

    # Prepare rows and bulk insert
    rows = [(d, t, title, author) for d in dates]
    sql = """
        INSERT INTO calendar_events (event_date, event_time, title, author)
        VALUES %s
        ON CONFLICT (event_date, event_time, title, author) DO NOTHING
    """
    PG().execute_many_values(sql, rows, page_size=1000)



def insert_event(event_iso: str, title: str, time_str: str | None, author: str):
    pg = PG()
    d = datetime.strptime(event_iso, "%Y-%m-%d").date()
    t = datetime.strptime(time_str, "%H:%M").time()

    sql = """
        INSERT INTO calendar_events (event_date, event_time, title, author)
        VALUES (%s, %s, %s, %s)
    """
    pg.execute_query(sql, (d, t, title, author))


def format_time_12h(t: str | None) -> str:
    """Convert 'HH:MM' or None into 12h with AM/PM, e.g., '5:04 PM'."""
    if not t:
        return ""
    try:
        # parse as 24h and format as 12h
        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except Exception:
        return t  # fallback: show raw string if parsing fails


def month_label(y: int, m: int) -> str:
    return f"{calendar.month_name[m]} {y}"

def shift_month(y: int, m: int, delta: int) -> MonthCtx:
    nm = (m - 1 + delta) % 12 + 1
    ny = y + (m - 1 + delta) // 12
    if nm == 12 and delta < 0 and (m - 1 + delta) % 12 == 11:
        ny -= 1
    return MonthCtx(ny, nm)

def iter_month_days(year: int, month: int):
    first = date(year, month, 1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    days = [start + timedelta(days=i) for i in range(42)]  # 6 weeks * 7 days
    return [days[i:i+7] for i in range(0, 42, 7)]


def day_cell(day: date, ctx: MonthCtx, events_map: Dict[str, List[dict]], selected_iso: str):
    iso = day.isoformat()
    in_month = (day.month == ctx.month)
    is_today = (day == date.today())
    is_selected = (iso == selected_iso)

    classes = ["cal-day"]
    if not in_month:
        classes.append("cal-day--out")
    if is_today:
        classes.append("cal-day--today")
    if is_selected:
        classes.append("cal-day--selected")

    badges = []
    for ev in events_map.get(iso, [])[:3]:
        label = format_time_12h(ev.get("time"))
        author = ev.get("author", "")
        title = ev.get("title", "")
        text = f"{label} · {title}" if label else title
        bg_color = '#d63384' if author.lower() == 'amanda' else '#1e6ffb' if author.lower() == 'daniel' else 'var(--muted)'
        badges.append(html.Div(text, className="cal-badge", style={'backgroundColor': bg_color}))

    more_count = max(0, len(events_map.get(iso, [])) - 3)
    if more_count:
        badges.append(html.Div(f"+{more_count} more", className="cal-badge cal-badge--more"))

    title_attr = {"title": "\n".join([ev["title"] for ev in events_map.get(iso, [])])} if iso in events_map else {}

    return html.Div(
        [
            html.Div(str(day.day), className="cal-day__num"),
            html.Div(badges, className="cal-badges"),
        ],
        id={"type": "day-cell", "date": iso},
        role="button",
        n_clicks=0,
        className=" ".join(classes),
        **title_attr,
    )

def month_grid(ctx: MonthCtx, events_map: Dict[str, List[dict]], selected_iso: str):
    weeks = iter_month_days(ctx.year, ctx.month)
    header = html.Div(
        [html.Span(x) for x in ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]],
        className="cal-weekdays",
    )
    rows = [html.Div([day_cell(d, ctx, events_map, selected_iso) for d in w], className="cal-week") for w in weeks]
    return html.Div([header, *rows], className="cal-grid")


def layout():
    return html.Div(
        [
            dcc.Store(id="cal-month", data={"year": date.today().year, "month": date.today().month}),
            dcc.Store(id="selected-date", data=date.today().isoformat()),
            dcc.Store(id="events-store", data={}),  # start empty; we’ll load from DB
            dcc.Store(id="db-flash", data=""),
            dcc.Store(id="events-loading", data=True),
            dcc.Store(id="events-cache-range", data=None),
            html.Div(
                [
                    html.Div(
                        [
                            html.Button("‹ Prev", id="prev-month", className="cal-btn"),
                            html.Div(id="month-label", className="cal-month-label"),
                            html.Button("Next ›", id="next-month", className="cal-btn"),
                        ],
                        className="cal-header",
                    ),
                    html.Div(id="calendar-grid", children=build_calendar_skeleton()),
                ],
                className="cal-card",
            ),
            html.Div(
                [
                    html.H3("Selected Day", className="side-title"),
                    html.Div(id="selected-date-label", className="side-subtitle"),
                    html.Div(id="selected-events"),
                    html.Div(
                        dmc.Button("Add Event", id="open-add-event", variant="filled", n_clicks=0),
                        style={"marginTop": "12px"}
                    ),
                    html.Div(id="db-flash-msg", className="side-subtitle", style={"marginTop": "8px"}),
                ],
                className="side-card",
            ),

            # Modal for creating a new event
            dmc.Modal(
                id="add-event-modal",
                title=html.Div("Add Event", id='modal-title'),
                opened=False,
                children=[
                    dmc.ChipGroup(
                        id="event-author",
                        multiple=False,
                        children=html.Div([
                            dmc.Chip(k, value=k, className='author-chips') for k in users
                        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '8px', 'marginBottom': '1rem'})
                    ),
                    dmc.TextInput(id="event-title", label="Title", placeholder="Team Sync", required=True, style={'marginBottom': '1rem'}),
                    dmc.TimePicker(
                        id="event-time",
                        label="Time",
                        withDropdown=True,
                        format="12h",
                        style={'zIndex': 10001, 'marginBottom': '1rem'}
                    ),
                    html.H4("Recurring", style={'marginBottom': '1rem'} ),
                    dmc.ChipGroup(
                        id="event-recur",
                        multiple=False,
                        value="none",
                        children=html.Div([
                            dmc.Chip("None", value="none"),
                            dmc.Chip("Daily", value="daily"),
                            dmc.Chip("Weekly", value="weekly"),
                            dmc.Chip("Monthly", value="monthly"),
                        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '8px'}),
                    ),
                    dmc.Collapse(
                        id="recur-end-wrap",
                        opened=False,
                        children=[
                            dmc.DatePicker(
                                id="event-recur-end",
                                mt=8,
                            )
                        ],
                    ),
                    dmc.Group(
                        [
                            dmc.Button("Save", id="save-event", n_clicks=0),
                            dmc.Button("Cancel", id="cancel-event", color="gray", variant="light", n_clicks=0),
                        ],
                        style={'marginTop': '1.5rem'},
                        p="right",
                        mt=16,
                    ),
                ],
                size="lg",
                centered=True,
                zIndex=10000,
            ),
        ],
        className="cal-app",
    )


@callback(
    Output("cal-month", "data"),
    Input("prev-month", "n_clicks"),
    Input("next-month", "n_clicks"),
    State("cal-month", "data"),
    prevent_initial_call=True,
)
def navigate(prev_clicks, next_clicks, cur):
    triggered = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
    ctx = MonthCtx(cur["year"], cur["month"])
    delta = -1 if triggered == "prev-month" else 1
    nm = shift_month(ctx.year, ctx.month, delta)
    return {"year": nm.year, "month": nm.month}


@callback(
    Output("month-label", "children"), 
    Input("cal-month", "data")
)
def label(ctx_data):
    return month_label(ctx_data["year"], ctx_data["month"])


@callback(
    Output("calendar-grid", "children"),
    Input("cal-month", "data"),
    Input("events-store", "data"),
    Input("selected-date", "data"),
)
def render_grid(ctx_data, events_map, selected_iso):
    ctx = MonthCtx(ctx_data["year"], ctx_data["month"])
    return month_grid(ctx, events_map or {}, selected_iso)


@callback(
    Output("selected-date", "data"),
    Input({"type": "day-cell", "date": ALL}, "n_clicks"),
    State({"type": "day-cell", "date": ALL}, "date"),
    prevent_initial_call=True,
)
def select_day(n_clicks, _1):
    if not any(n_clicks):
        return dash.no_update
    return dash.callback_context.triggered_id['date']

@callback(
    Output("selected-date-label", "children"),
    Output("selected-events", "children"),
    Input("selected-date", "data"),
    Input("events-store", "data"),
    State("events-store", "data"),
)
def show_selected(iso, _, events_map):
    dt = datetime.strptime(iso, "%Y-%m-%d")
    pretty = dt.strftime("%A, %B %#d, %Y")
    items = events_map.get(iso, [])
    if not items:
        return pretty, html.Div("No events", className="side-subtitle")
    
    rows = []
    for ev in items:
        time_str = format_time_12h(ev.get("time"))
        author = ev.get("author", "")

        # CSS class depending on author
        author_class = "side-row__author"
        if author.lower() == "amanda":
            author_class += " author-amanda"
        elif author.lower() == "daniel":
            author_class += " author-daniel"

        row = html.Div(
            [
                html.Div(time_str, className="side-row__time"),
                html.Div(ev.get("title", ""), className="side-row__title"),
                html.Div(author, className=author_class),
            ],
            className="side-row",
            style={"justifyContent": "space-between"},
        )
        rows.append(row)

    return pretty, html.Div(rows)


@callback(
    Output("add-event-modal", "opened", allow_duplicate=True),
    Output("events-store", "data", allow_duplicate=True),
    Output("db-flash", "data"),
    Input("save-event", "n_clicks"),
    State("selected-date", "data"),
    State("event-title", "value"),
    State("event-time", "value"),
    State("event-author", "value"),
    State("event-recur", "value"),
    State("event-recur-end", "value"),
    State("cal-month", "data"),
    running=[
        (Output("save-event", "disabled"), True, False),
        (Output("save-event", "children"), dmc.Loader(size="xs"), "Save"),
    ],
    prevent_initial_call=True,
)
def save_event(n, selected_iso, title, time_str, author, recur, recur_end_iso, ctx_data):
    if not n:
        raise dash.exceptions.PreventUpdate

    title = (title or "").strip()
    author = (author or "").strip()
    if not title:
        return dash.no_update, dash.no_update, "Title required."

    start_d = datetime.strptime(selected_iso, "%Y-%m-%d").date()
    end_d = None
    freq = None if recur in (None, "none") else recur

    if freq:
        if not recur_end_iso:
            return dash.no_update, dash.no_update, "Please choose an end date for the recurrence."
        end_d = datetime.fromisoformat(recur_end_iso).date()
        if end_d < start_d:
            return dash.no_update, dash.no_update, "End date must be on or after the start date."

    try:
        insert_events_bulk(start_d, end_d, freq, title, author, time_str or None)
        from_date = date(ctx_data["year"], ctx_data["month"], 1)
        win_start, win_end = window_for_month(from_date.year, from_date.month)  # just to illustrate usage
        data = fetch_events_range(win_start, win_end)

        msg = "Event saved." if not freq else f"Recurring events saved ({freq})."
        return False, data, msg
    except Exception as e:
        return dash.no_update, dash.no_update, f"DB error: {e}"
    

@callback(
    Output("db-flash-msg", "children"),
    Input("db-flash", "data"),
)
def show_flash(msg):
    return msg or ""


@callback(
    Output("add-event-modal", "opened"),
    Output("modal-title", "children"),
    Input("open-add-event", "n_clicks"),
    Input("cancel-event", "n_clicks"),
    State("selected-date", "data"),
    State("add-event-modal", "opened"),
    prevent_initial_call=True,
)
def toggle_modal(open_clicks, cancel_clicks, selected_iso, opened):
    trig = dash.callback_context.triggered_id
    if trig == "open-add-event":
        dt = datetime.strptime(selected_iso, "%Y-%m-%d")
        title = f"{dt.strftime('%A, %B')} {dt.day}, {dt.year}"
        return True, title

    return False, dash.no_update


@callback(
    Output("events-store", "data"),
    Output("events-cache-range", "data"),
    Output("events-loading", "data"),   # set False when done
    Input("cal-month", "data"),
    State("events-store", "data"),
    State("events-cache-range", "data"),
    prevent_initial_call=False,
)
def load_or_use_cache(ctx_data, current_events, cache_range):
    y, m = ctx_data["year"], ctx_data["month"]
    month_start = first_of_month(y, m)

    # If we already have a cache range and the requested month is inside it, reuse
    if cache_range:
        start = date.fromisoformat(cache_range["start"])
        end   = date.fromisoformat(cache_range["end"])  # exclusive
        if start <= month_start < end:
            # within cached 3-month window → no DB trip
            return current_events or {}, cache_range, False

    # Not cached (or first load) → fetch new 3-month window
    win_start, win_end = window_for_month(y, m)
    data = fetch_events_range(win_start, win_end)
    new_range = {"start": win_start.isoformat(), "end": win_end.isoformat()}
    return data, new_range, False



@callback(
    Output("recur-end-wrap", "opened"),
    Input("event-recur", "value"),
)
def toggle_recur_end(v):
    return v in {"daily", "weekly", "monthly"}