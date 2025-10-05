# pages/budget.py
from __future__ import annotations

from datetime import date, timedelta
import os
import requests

from dash import ClientsideFunction, html, dcc, callback, Input, Output, State
import dash
import dash_mantine_components as dmc
import dash_ag_grid as dag
from dash_iconify import DashIconify

dash.register_page(__name__, path="/budget")

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8050")
USER_ID = os.getenv("BUDGET_USER_ID", "default-user")

# ---------- Helpers ----------

def today_str() -> str:
    return date.today().isoformat()

def first_of_month_str() -> str:
    t = date.today()
    return t.replace(day=1).isoformat()

def start_of_week_sunday_str() -> str:
    # Monday=0 ... Sunday=6; we want last Sunday
    t = date.today()
    days_to_sunday = (t.weekday() + 1) % 7
    start = t - timedelta(days=days_to_sunday)
    return start.isoformat()

def kpi_card(title: str, value: str) -> dmc.Paper:
    return dmc.Paper(
        dmc.Stack(
            [
                dmc.Text(title, size="sm", c="dimmed"),
                dmc.Text(value, size="xl", fw=800),
            ],
            gap="xs",
        ),
        withBorder=True,
        shadow="sm",
        radius="md",
        p="md",
    )

def currency(n) -> str:
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return "$0.00"

# ---------- Layout ----------

controls = dmc.Group(
    [
        html.Div(
            [
              dmc.Title("Daily Budget", order=2, style={"marginRight": "1rem"}),
              html.Div(DashIconify(icon="mdi:refresh", width=25, height=25, color='green'), id="btn-refresh", className="mdi:refresh"),
            ], style={"display": "flex", "alignItems": "center"}
        ),
        html.Div(
            [
              dmc.Button("Link bank", id="btn-link", variant="light"),
              dmc.Badge("Status: idle", id="badge-status", variant="outline")
            ]
        )       
    ],
    justify="space-between",
    align="center",
)

kpis = dmc.SimpleGrid(
    id="kpi-cards",
    cols=3,
    spacing="md"
)

# Dash AG Grid – month view
grid = dag.AgGrid(
    id="grid-month",
    style={"height": "55vh", "width": "100%"},
    className="ag-theme-alpine-dark",
    columnDefs=[
        {
            "headerName": "Date",
            "field": "date",
            "sortable": True,
            "filter": "agTextColumnFilter",  # keep simple; data is 'YYYY-MM-DD'
            "minWidth": 120,
            "pinned": False,
        },
        {
            "headerName": "Description",
            "field": "name",
            "flex": 2,
            "sortable": True,
            "filter": True,
        },
        {
            "headerName": "Amount",
            "field": "amount",
            "type": "rightAligned",
            "minWidth": 130,
            # "valueFormatter": {
            #     # nice currency formatting in the browser
            #     "function": "return params.value!=null ? params.value.toLocaleString(undefined,{style:'currency',currency:'USD'}) : '';"
            # },
            "sortable": True,
            "filter": "agNumberColumnFilter",
        },
        {
            "headerName": "Category",
            "field": "category",
            "flex": 1,
            "sortable": True,
            "filter": True,
        },
        {
            "headerName": "Account",
            "field": "account_id",
            "flex": 1,
            "sortable": True,
            "filter": True,
        },
        {
            "headerName": "Pending",
            "field": "pending",
            "minWidth": 100,
            # "cellRenderer": {"function": "return params.value ? 'Yes' : ''"},
            "sortable": True,
            "filter": True,
        },
    ],
    defaultColDef={
        "resizable": True,
        "wrapHeaderText": True,
        "autoHeaderHeight": True,
    },
    rowData=[],  # filled by callback
)

content = dmc.Stack(
    [
        controls,
        dmc.Divider(my="sm"),
        kpis,
        dmc.Divider(my="sm"),
        grid,
    ],
    gap="md",
)

layout = dmc.Stack(
    [
        # The Box is positioned relative so the overlay can sit on top
        dmc.Box(
            children=[
                content,
                dmc.LoadingOverlay(
                    id="loading-overlay",
                    visible=False,
                    zIndex=1000,
                    overlayProps={"radius": "sm", "blur": 2},
                ),
            ],
            pos="relative",
        ),

        # State & initial load
        dcc.Store(id="st-month-transactions"),
        dcc.Store(id="api-base", data=API_BASE),
        dcc.Store(id="user-id", data=USER_ID),
        dcc.Store(id="linking", data=False),   
        dcc.Store(id="exchanged", data=0),
        dcc.Interval(id="ivl-initial", interval=200, n_intervals=0, max_intervals=1),
    ],
    p="md",
)


# ---------- Callbacks ----------
app = dash.get_app()
app.clientside_callback(
    ClientsideFunction(namespace="plaid", function_name="openLink"),
    Output("linking", "data"),
    Output("exchanged", "data"),
    Input("btn-link", "n_clicks"),
    State("api-base", "data"),
    State("user-id", "data"),
    State("exchanged", "data"),
)



# swap your _fetch_month_transactions to hit the combined endpoint
def _fetch_month_transactions(api_base: str, user_id: str):
    r = requests.get(f"{api_base}/budget/month",
                     params={"user_id": user_id, "include_pending": "true"},
                     timeout=60)
    if r.status_code == 409 and (r.json().get("relink_required")):
        return "Status: relink required", [], {"day": 0.0, "week": 0.0, "month": 0.0}

    r.raise_for_status()
    payload = r.json()

    totals = payload.get("totals", {"day": 0.0, "week": 0.0, "month": 0.0})
    return "Status: synced", payload.get("rows", []), totals


@callback(
    Output("loading-overlay", "visible"),
    Output("badge-status", "children"),
    Output("st-month-transactions", "data"),
    Input("ivl-initial", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
    Input("exchanged", "data"),   # <-- new: after /plaid/exchange
    Input("linking", "data"),     # <-- new: show interim status
    State("st-month-transactions", "data"),
    prevent_initial_call=True,
)
def load_or_refresh(_init, _click, _exchanged, linking, existing):
    if linking is True:
        return False, "Status: linking…", existing or []
    try:
        status, rows, totals = _fetch_month_transactions(API_BASE, USER_ID)
        return False, status, rows
    except Exception as e:
        print("Error fetching transactions:", e)
        return False, f"Status: error {e}", existing or []

@callback(
    Output("kpi-cards", "children"),
    Output("grid-month", "rowData"),
    Input("st-month-transactions", "data"),
    prevent_initial_call=True,
)
def update_kpis_and_grid(rows):
    if not rows:
        return (
            dmc.SimpleGrid(
                [kpi_card("Today", "$0.00"), kpi_card("This Week", "$0.00"), kpi_card("This Month", "$0.00")],
                cols=3,
                spacing="md",
                # breakpoints=[{"maxWidth": "md", "cols": 1}],
            ),
            [],
        )

    # Compute spend totals (amount > 0 considered spend)
    t_today = today_str()
    t_week_start = start_of_week_sunday_str()
    t_month_start = first_of_month_str()

    day_total = sum(r["amount"] for r in rows if r.get("amount") and r["amount"] > 0 and r["date"] == t_today)
    week_total = sum(r["amount"] for r in rows if r.get("amount") and r["amount"] > 0 and r["date"] >= t_week_start)
    month_total = sum(r["amount"] for r in rows if r.get("amount") and r["amount"] > 0 and r["date"] >= t_month_start)

    kpi_children = dmc.SimpleGrid(
        [
            kpi_card("Today", currency(day_total)),
            kpi_card("This Week", currency(week_total)),
            kpi_card("This Month", currency(month_total)),
        ],
        cols=3,
        spacing="md",
        # breakpoints=[{"maxWidth": "md", "cols": 1}],
    )

    return kpi_children, rows
