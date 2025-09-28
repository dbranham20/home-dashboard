import os
import dash
import pandas as pd
import plotly.graph_objects as go
import dash_mantine_components as dmc
import dash_ag_grid as dag
import teslapy
from dash import Input, Output, State, callback, html, dcc

from dashboard.db.pg import PG

dash.register_page(__name__, path="/mileage-log")

def fetch_live_tesla_data():
    with teslapy.Tesla(
        os.getenv("TESLA_EMAIL"),
        refresh_token=os.getenv("TESLA_REFRESH_TOKEN")
    ) as tesla:
        vehicles = tesla.vehicle_list()
        my_car = vehicles[0]
        return my_car.get_vehicle_data()


def fetch_mileage_data():
	pg = PG()
	try:
		query = 'SELECT date, miles FROM public."tesla-miles-log" ORDER BY date;'
		df = pd.read_sql(query, pg.connection)
		pg.close()

		df['Mileage_Diff'] = df['miles'].diff()
		df['Date'] = pd.to_datetime(df['date'])
		df["Mileage_Increment"] = df["miles"].diff()
		df["Days_Diff"] = df["Date"].diff().dt.days
		df["Avg_Mileage_Per_Day"] = df["Mileage_Increment"] / df["Days_Diff"]

		return df

	except Exception as e:
		print(f'Error connecting to database: {e}')
		return pd.DataFrame()


def make_charts(mileage_df, battery_perc):
	bar_colors = [
		"red" if avg > 40 else "#4ea35a"
		for avg in mileage_df["Avg_Mileage_Per_Day"].fillna(0)
	]

	line_fig = go.Figure()
	line_fig.add_trace(go.Scatter(
		x=mileage_df["Date"],
		y=mileage_df["miles"],
		mode="lines+markers",
		name="Mileage",
		line=dict(color="blue"),
		marker=dict(size=8),
		hovertemplate="Date: %{x|%Y-%m-%d}<br>Mileage: %{y}<extra></extra>"
	))
	line_fig.update_layout(
		margin=dict(l=20, r=20, t=5, b=30),
		xaxis_title="Date",
		yaxis_title="Mileage",
		template="plotly_white"
	)

	# Bar chart: Average mileage per day (highlight >40 in red)
	bar_fig = go.Figure()
	bar_fig.add_trace(go.Bar(
		x=mileage_df["Date"],
		y=mileage_df["Avg_Mileage_Per_Day"],
		marker_color=bar_colors,
		hovertemplate="Date: %{x|%Y-%m-%d}<br>Avg per day: %{y:.2f}<extra></extra>"
	))
	bar_fig.update_layout(
		margin=dict(l=20, r=20, t=5, b=30),
		xaxis_title="Date",
		yaxis_title="Average Mileage Per Day",
		template="plotly_white"
	)

	battery_level = max(0, min(100, battery_perc))

	if battery_level < 20:
		color = 'red'
	elif battery_level < 50:
		color = 'yellow'
	else:
		color = 'green'

	batt_fig = dmc.Progress(
			value=battery_level,
			color=color,  # Mantine color or hex
			size="lg",
			radius="sm"
	)
	battery_card = html.Div([
		html.H3("Battery Level", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
		batt_fig
	])

	# batt_fig.update_layout(
  #       xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False, zeroline=False),
  #       yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
  #       height=120,
  #       margin=dict(l=10, r=10, t=10, b=10),
  #       showlegend=False,
  #       title=None,
  #   )


	return line_fig, bar_fig, battery_card

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
					columnDefs=[{"field": 'date'}, {"field": 'mileage'}],
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
	Output('odometer-card', 'children'),
	Output('battery-card', 'children'),
	Output('mileage-log-grid', 'rowData'),
	Output('mileage-log-grid', 'className'),
	Output('tesla-title', 'children'),
	Input('mileage-init-load', 'data'),
	Input("color-scheme-switch", "checked"),
	State("color-scheme-switch", "checked"),
	State('line', 'figure'),
	State('bar', 'figure'),
	prevent_initial_call=True
)
def handle_mileage_load(_, _1, theme_state, line_fig, bar_fig):
	if dash.callback_context.triggered_id == 'color-scheme-switch':
		template = 'dark_custom' if theme_state else 'plotly'
		line_fig = go.Figure(line_fig).update_layout(template=template)
		bar_fig = go.Figure(bar_fig).update_layout(template=template)
		return line_fig, bar_fig, dash.no_update, dash.no_update, dash.no_update, "ag-theme-alpine-dark" if theme_state else "ag-theme-alpine", dash.no_update
	

	data = fetch_mileage_data()
	car_data = fetch_live_tesla_data()
	
	battery_level = car_data['charge_state']['battery_level']  
	odometer = car_data['vehicle_state']['odometer']
	tesla_name = car_data['display_name']

	odometer_card = [
			html.H3("Odometer", style={'paddingBottom': 0, 'marginBottom': '.5rem', 'marginTop': '.5rem'}),
			html.H2(f'{round(odometer):,} miles', style={'margin': 0})
		]
	line_fig, bar_fig, batt_fig = make_charts(data, int(battery_level))

	template = 'dark_custom' if theme_state else 'plotly'
	line_fig.update_layout(template=template)
	bar_fig.update_layout(template=template)
	grid_class = "ag-theme-alpine-dark" if theme_state else "ag-theme-alpine"

	return line_fig, bar_fig, odometer_card, batt_fig, data.to_dict('records'), grid_class, tesla_name
