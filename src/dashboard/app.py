import os
import dash
import pandas as pd
import dash_mantine_components as dmc
import plotly.io as pio

from dash import Dash, Input, Output, State, callback, clientside_callback, html, dcc
from dash_iconify import DashIconify

external_stylesheets = list(dmc.styles.ALL)

app = Dash(__name__, use_pages=True, external_stylesheets=external_stylesheets)
dash._dash_renderer._set_react_version('18.2.0')
server = app.server


custom_template = pio.templates["plotly_dark"]
custom_template.layout.paper_bgcolor = "#2e2e2e"
custom_template.layout.plot_bgcolor = "#2e2e2e"
pio.templates["dark_custom"] = custom_template


# App layout
app.layout = dmc.MantineProvider(
    dmc.AppShell([
        dmc.AppShellHeader([
            dmc.Group(
                [
                    dmc.Burger(id="burger", size="sm", hiddenFrom="sm", opened=False),
                    # dmc.Image(src=logo, h=40),
                    dmc.Title("Dashboard", c="#4ea35a"),
                ],
                h="100%",
                px="md",
            ),
            dmc.Switch(
                offLabel=DashIconify(icon="radix-icons:sun", width=15, color=dmc.DEFAULT_THEME["colors"]["yellow"][8]),
                onLabel=DashIconify(icon="radix-icons:moon", width=15, color=dmc.DEFAULT_THEME["colors"]["yellow"][6]),
                id="color-scheme-switch",
                persistence=True,
                color="grey",
            )
        ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),
        dmc.AppShellNavbar(
            id="navbar",
            children=[
				dmc.NavLink(
                    label="Home",
                    leftSection=DashIconify(icon="bi:house-door-fill", width=16, height=16, color='#4ea35a'),
                    href="/", 
                    active="exact"
                ),
                dmc.NavLink(
                    label="Tesla",
                    leftSection=DashIconify(icon="simple-icons:tesla", width=16, height=16, color='red'),
                    href="/mileage-log", 
                    active="exact"
                ),
            ],
            p="md",
        ),
        dmc.AppShellMain(dash.page_container),
    ],
    header={"height": 60},
    padding="md",
    navbar={
        'width': {"sm": 100, "lg": 200 }, 
        "breakpoint": 'sm',
        "collapsed": {"mobile": True},
    },
    id="appshell")
)

clientside_callback(
    """
    (switchOn) => {
       document.documentElement.setAttribute('data-mantine-color-scheme', switchOn ? 'dark' : 'light');
       return window.dash_clientside.no_update
    }
    """,
    Output("color-scheme-switch", "id"),
    Input("color-scheme-switch", "checked"),
)


@callback(
    Output("appshell", "navbar"),
    Input("burger", "opened"),
    State("appshell", "navbar"),
)
def navbar_is_open(opened, navbar):
    navbar["collapsed"] = {"mobile": not opened}
    return navbar


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", 8050)), debug=False)
    # app.run(debug=True)