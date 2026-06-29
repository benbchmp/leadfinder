"""
LeadFinder – Entry point
Routing multi-pages : / → leadfinder, /cold-calls → cold calls analytics
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
from dash import Dash, html, dcc, Output, Input
import dash_bootstrap_components as dbc

import pages.leadfinder as leadfinder
import pages.cold_calls as cold_calls
import pages.prospects as prospects

load_dotenv()

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
app.title = "LeadFinder"
server = app.server  # pour gunicorn

leadfinder.register_callbacks(app)
cold_calls.register_callbacks(app)
prospects.register_callbacks(app)

# ── Navbar ───────────────────────────────────────────────────────────

def _nav_tab(label: str, href: str, icon: str, active: bool):
    # dcc.Link = navigation côté client (PAS de rechargement de page → pas de flash).
    return dcc.Link(
        [html.I(className=f"bi {icon} lf-nav-ico"), html.Span(label)],
        href=href,
        className="lf-nav-tab active" if active else "lf-nav-tab",
    )


def _navbar(active_path: str) -> dbc.Container:
    return dbc.Container(
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.Img(
                        src="/assets/eagle.png",
                        alt="",
                        style={
                            "height": "42px",
                            "filter": "invert(1)",
                            "mixBlendMode": "screen",
                            "display": "block",
                        },
                    ),
                    html.Span("LeadFinder", className="lf-brand ms-2"),
                ], className="d-flex align-items-center"),
                width="auto", className="d-flex align-items-center",
            ),
            dbc.Col(width=True),  # spacer
            dbc.Col(
                html.Nav([
                    _nav_tab("LeadFinder", "/", "bi-search", active_path == "/"),
                    _nav_tab("Prospects", "/prospects", "bi-bookmark-star", active_path == "/prospects"),
                    _nav_tab("Call Tracker", "/cold-calls", "bi-telephone", active_path == "/cold-calls"),
                ], className="lf-nav-group"),
                width="auto", className="d-flex align-items-center",
            ),
        ], align="center", className="py-2 px-3 lf-navbar"),
        fluid=True,
        style={"marginBottom": "16px"},
    )


# ── App layout ───────────────────────────────────────────────────────

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    # Navbar rendue dès le 1er affichage (évite un "trou" au chargement)
    html.Div(_navbar("/"), id="navbar-container"),
    # Styles initiaux : seul LeadFinder (page d'accueil) est visible au chargement.
    # Sans ça, les 3 pages s'affichent une fraction de seconde avant que le
    # callback `route` n'en cache deux (le fameux flash de l'onglet Call Tracker).
    html.Div(leadfinder.layout(), id="page-leadfinder", style={"display": "block"}),
    html.Div(cold_calls.layout(), id="page-coldcalls", style={"display": "none"}),
    html.Div(prospects.layout(), id="page-prospects", style={"display": "none"}),
])


@app.callback(
    Output("navbar-container", "children"),
    Output("page-leadfinder", "style"),
    Output("page-coldcalls", "style"),
    Output("page-prospects", "style"),
    Input("url", "pathname"),
)
def route(pathname):
    show = {"display": "block"}
    hide = {"display": "none"}
    if pathname == "/cold-calls":
        return _navbar("/cold-calls"), hide, show, hide
    if pathname == "/prospects":
        return _navbar("/prospects"), hide, hide, show
    return _navbar("/"), show, hide, hide


# ── Run ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8060))
    # debug=False : pas de reloader (démarrage plus rapide, un seul process).
    # threaded=True : indispensable pour que la barre de progression LeadFinder
    # puisse interroger l'avancement pendant qu'une recherche tourne en parallèle.
    # host="0.0.0.0" : écoute sur toutes les interfaces (nécessaire pour Railway/production).
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
