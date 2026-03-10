import os
import time
import dash
import pandas as pd
import plotly.graph_objects as go
import dash_mantine_components as dmc
import dash_ag_grid as dag
import requests
import teslapy
from sqlalchemy import create_engine
from dash import Input, Output, State, callback, html, dcc

from dashboard.db.pg import PG

dash.register_page(__name__, path="/mileage-log")

def fetch_live_tesla_data(max_retries: int = 1, retry_delay: int = 10):
	with teslapy.Tesla(os.getenv("TESLA_EMAIL")) as tesla:
		if not tesla.authorized:
			tesla.refresh_token(refresh_token=os.getenv("TESLA_REFRESH_TOKEN"))

		vehicles = tesla.vehicle_list()
		my_car = vehicles[0]

		for attempt in range(max_retries + 1):
			try:
				return my_car.get_vehicle_data()

			except requests.exceptions.HTTPError as e:
				if e.response.status_code == 408:
					print("Vehicle unavailable — attempting to wake it up...")
					my_car.sync_wake_up()
					if attempt < max_retries:
						time.sleep(retry_delay)
						continue
					else:
						return {"error": "Vehicle unavailable after retries"}
				else:
					raise  # re-raise other HTTP errors

			except Exception as e:
				return {"error": str(e)}

	return {"error": "Unknown failure"}


def fetch_mileage_data():
	try:
		pg = PG()
		query = 'SELECT date, miles FROM public."tesla-miles-log" ORDER BY date;'
		df = pd.read_sql(query, pg.get_engine())

		df['Date'] = pd.to_datetime(df['date'])
		df["Mileage_Increment"] = df["miles"].diff()
		df["Days_Diff"] = df["Date"].diff().dt.days
		df["Avg_Mileage_Per_Day"] = df["Mileage_Increment"] / df["Days_Diff"]

		return df

	except Exception as e:
			print(f'Error connecting to database: {e}')
			return pd.DataFrame()

def build_monthly_data(df):
	rows = []
	for i in range(1, len(df)):
			start_date = df.loc[i-1, "Date"]
			end_date = df.loc[i, "Date"]
			miles = df.loc[i, "Mileage_Increment"]
			days = df.loc[i, "Days_Diff"]
			daily_rate = miles / days

			# Generate each day in the interval and assign daily miles
			date_range = pd.date_range(start=start_date, end=end_date - pd.Timedelta(days=1))
			for day in date_range:
					rows.append({"date": day, "miles": daily_rate})

	daily_df = pd.DataFrame(rows)
	daily_df["year"] = daily_df["date"].dt.year
	daily_df["month"] = daily_df["date"].dt.month

	monthly_df = daily_df.groupby(["year", "month"])["miles"].sum().reset_index()
	monthly_df["month_name"] = pd.to_datetime(monthly_df["month"], format="%m").dt.strftime("%b")
	return monthly_df


def calculate_rolling_average(mileage_df):
	mileage_df["date"] = pd.to_datetime(mileage_df["date"])

	mileage_df = mileage_df.sort_values("date").reset_index(drop=True)
	mileage_df["prev_date"] = mileage_df["date"].shift(1)
	mileage_df["prev_miles"] = mileage_df["miles"].shift(1)
	mileage_df["days_elapsed"] = (mileage_df["date"] - mileage_df["prev_date"]).dt.days
	mileage_df["miles_driven"] = mileage_df["miles"] - mileage_df["prev_miles"]
	mileage_df["daily_rate"] = mileage_df["miles_driven"] / mileage_df["days_elapsed"]

	# Rolling average (window=3 smooths without losing too much detail)
	mileage_df["rolling_avg"] = mileage_df["daily_rate"].rolling(window=3, min_periods=1).mean()

	return mileage_df


def make_db_charts(mileage_df):
	bar_colors = ["rgba(255, 80, 80, 0.3)" if x > 40 else "rgba(100, 149, 237, 0.3)" for x in mileage_df["Avg_Mileage_Per_Day"]]

	monthly_df = build_monthly_data(mileage_df.copy())

	mom_fig = go.Figure()
	for year in sorted(monthly_df["year"].unique()):
			year_data = monthly_df[monthly_df["year"] == year]
			mom_fig.add_trace(go.Scatter(
					x=year_data["month_name"],
					y=year_data["miles"],
					mode="lines+markers",
					name=str(year),
					hovertemplate="Month: %{x}<br>Miles: %{y:.0f}<extra></extra>"
			))

	mom_fig.update_layout(
			title="Month-over-Month Mileage",
			xaxis=dict(categoryorder="array", categoryarray=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]),
			yaxis_title="Miles Driven",
			template="plotly_dark",
			legend_title="Year"
	)


	bar_fig = go.Figure()
	mileage_df = calculate_rolling_average(mileage_df)
	# Raw daily rate as faint bars for context
	bar_fig.add_trace(go.Bar(
			x=mileage_df["date"],
			y=mileage_df["daily_rate"],
			marker_color=bar_colors,
			name="Miles/Day (interval)",
			hovertemplate="Date: %{x|%Y-%m-%d}<br>Interval avg: %{y:.1f} mi/day<extra></extra>"
	))

	# Rolling average as a bold line on top
	bar_fig.add_trace(go.Scatter(
			x=mileage_df["date"],
			y=mileage_df["rolling_avg"],
			mode="lines+markers",
			line=dict(color="royalblue", width=3),
			marker=dict(size=6),
			name="3-Entry Rolling Avg",
			hovertemplate="Date: %{x|%Y-%m-%d}<br>Rolling avg: %{y:.1f} mi/day<extra></extra>"
	))

	bar_fig.update_layout(
			margin=dict(l=20, r=20, t=5, b=30),
			xaxis_title="date",
			yaxis_title="Miles Per Day",
			template="plotly_white",
			legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
	)

	return mom_fig, bar_fig


def make_live_charts(battery_perc):
	battery_level = max(0, min(100, battery_perc))

	if battery_level < 20:
		color = 'red'
	elif battery_level < 50:
		color = 'yellow'
	else:
		color = 'green'


	batt_fig = dmc.ProgressRoot(
			[
					dmc.ProgressSection(dmc.ProgressLabel(f"{battery_level}%"), value=battery_level, color=color)
			],
			size="xl",
	)
	battery_card = html.Div([
		html.H3("Battery Level", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
		batt_fig
	])

	return battery_card

# Add to your Dash layout
def layout():
	return html.Div([
		html.H2(id='tesla-title', children=dmc.Skeleton(height=30, width='10%'), style={'marginLeft': '.5rem', 'marginTop': '.5rem'}),
		dcc.Store(id='mileage-init-load', data=None),
		dmc.SimpleGrid(
			cols=2,
			spacing="sm",
			children=[
				dmc.Card(
					id='battery-card',
					children=[
						html.H3("Battery Level", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
						dmc.Skeleton(height=30, width='100%')
					],
					shadow="sm",
					radius="md",
					withBorder=True
				),
				dmc.Card(
					id='odometer-card',
					children=[
						html.H3("Odometer", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
						dmc.Skeleton(height=30, width='100%')
					],
					shadow="sm",
					padding="md",
					radius="md",
					withBorder=True
				),
				dmc.Card(
					children=[
						html.H3("Mileage Over Time", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
						dcc.Graph(id='line', config={"displayModeBar": False})
					],
					shadow="sm",
					padding="md",
					radius="md",
					withBorder=True
				),
				dmc.Card(
					children=[
						html.H3("Average Mileage Per Day", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
						dcc.Graph(id='bar', config={"displayModeBar": False})
					],
					shadow="sm",
					padding="md",
					radius="md",
					withBorder=True
				)
		], style={'marginBottom': '.5rem'}),
		dmc.Card(
			children=[
				html.H3("All Mileage Data", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
				dag.AgGrid(
					id="mileage-log-grid",
					rowData=pd.DataFrame().to_dict("records"),
					columnDefs=[{"field": 'date', "headerName": "Date"}, {"field": 'miles', "headerName": "Miles"}],
					className="ag-theme-alpine-dark",
					style={"height": "400px"},
					columnSize="responsiveSizeToFit",
					defaultColDef={"filter": True, "resizable": True},
				),
			],
			shadow="sm",
			padding="md",
			radius="md",
			withBorder=True
		)
	], style={'margin': '.5rem'})

@callback(
	Output('line', 'figure', allow_duplicate=True),
	Output('bar', 'figure', allow_duplicate=True),
	Output('mileage-log-grid', 'rowData'),
	Output('mileage-log-grid', 'className'),
	Input('mileage-init-load', 'data'),
	Input("color-scheme-switch", "checked"),
	State("color-scheme-switch", "checked"),
	State('line', 'figure'),
	State('bar', 'figure'),
	prevent_initial_call=True
)
def init_db_charts(_, _1, theme_state, line_fig, bar_fig):
	if dash.callback_context.triggered_id == 'color-scheme-switch':
		template = 'dark_custom' if theme_state else 'plotly'
		line_fig = go.Figure(line_fig).update_layout(template=template)
		bar_fig = go.Figure(bar_fig).update_layout(template=template)
		return line_fig, bar_fig, dash.no_update, "ag-theme-alpine-dark" if theme_state else "ag-theme-alpine"

	data = fetch_mileage_data()
	line_fig, bar_fig = make_db_charts(data)

	template = 'dark_custom' if theme_state else 'plotly'
	line_fig.update_layout(template=template)
	bar_fig.update_layout(template=template)

	grid_class = "ag-theme-alpine-dark" if theme_state else "ag-theme-alpine"

	return line_fig, bar_fig, data.to_dict('records'), grid_class,


@callback(
	Output('odometer-card', 'children'),
	Output('battery-card', 'children'),
	Output('tesla-title', 'children'),
	Input('mileage-init-load', 'data'),	
	prevent_initial_call=True
)
def handle_mileage_load(_,):
	car_data = fetch_live_tesla_data()
	
	battery_level = car_data['charge_state']['battery_level']  
	odometer = car_data['vehicle_state']['odometer']
	tesla_name = car_data['display_name']

	odometer_card = [
			html.H3("Odometer", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
			html.H2(f'{round(odometer):,} miles', style={'margin': 0})
		]
	batt_fig = make_live_charts(int(battery_level))

	return odometer_card, batt_fig, tesla_name
