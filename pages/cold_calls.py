"""
Cold Calls – tracker d'appels en live + analytics
Données persistées par utilisateur (cold_calls_benjamin.json, cold_calls_lucas.json)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State, callback_context, no_update, ALL
import dash_bootstrap_components as dbc

DATA_DIR = os.path.dirname(os.path.dirname(__file__))
USERS = ["Benjamin", "Lucas"]

def get_data_file(user: str) -> str:
    """Retourne le chemin du fichier de données pour un utilisateur."""
    return os.path.join(DATA_DIR, f"cold_calls_{user.lower()}.json")

OBJECTION_OPTIONS = [
    "Redirigé vers email",
    "Pas d'intérêt",
    "Pas de budget",
    "Pas le temps",
    "Pas le bon moment",
    "Déjà équipé",
    "Pas le décideur",
]

RESULT_LABELS = {
    "pitch_fail": "Recalé au pitch",
    "objection": "Objection",
    "success": "Succès",
}

RESULT_COLORS = {
    "pitch_fail": "#dc3545",
    "objection": "#fd7e14",
    "success": "#28a745",
}

# ── Data helpers ─────────────────────────────────────────────────────

def load_calls(user: str) -> list[dict]:
    """Load calls for a specific user."""
    data_file = get_data_file(user)
    if not os.path.exists(data_file):
        return []
    with open(data_file, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_calls(user: str, calls: list[dict]) -> None:
    """Save calls for a specific user."""
    data_file = get_data_file(user)
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)


def add_call(user: str, result: str, detail: str = "") -> None:
    """Add a call for a specific user."""
    calls = load_calls(user)
    calls.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "result": result,
        "detail": detail,
    })
    save_calls(user, calls)


def undo_last_call(user: str) -> bool:
    """Remove the last call for a user. Returns True if something was removed."""
    calls = load_calls(user)
    if not calls:
        return False
    calls.pop()
    save_calls(user, calls)
    return True


def filter_by_period(calls: list[dict], period: str) -> list[dict]:
    if period == "all":
        return calls
    days = {"1j": 1, "3j": 3, "7j": 7, "1m": 30}[period]
    cutoff = datetime.now() - timedelta(days=days)
    return [c for c in calls if datetime.fromisoformat(c["timestamp"]) >= cutoff]


def calls_to_df(calls: list[dict]) -> pd.DataFrame:
    if not calls:
        return pd.DataFrame(columns=["timestamp", "result", "detail"])
    df = pd.DataFrame(calls)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def compute_kpis(df: pd.DataFrame) -> dict:
    total = len(df)
    success = int((df["result"] == "success").sum()) if total else 0
    pitch_fail = int((df["result"] == "pitch_fail").sum()) if total else 0
    objections = int((df["result"] == "objection").sum()) if total else 0
    conversion = round(success / total * 100, 1) if total else 0.0
    return {
        "total": total,
        "success": success,
        "pitch_fail": pitch_fail,
        "objections": objections,
        "conversion": conversion,
    }


def compute_today_stats(all_calls: list[dict]) -> dict:
    today = datetime.now().date()
    today_calls = [c for c in all_calls if datetime.fromisoformat(c["timestamp"]).date() == today]
    total_today = len(today_calls)
    success_today = sum(1 for c in today_calls if c["result"] == "success")
    conversion_today = round(success_today / total_today * 100, 1) if total_today else 0.0

    obj_today = [c["detail"] for c in today_calls if c["result"] == "objection" and c.get("detail")]
    top_obj = max(set(obj_today), key=obj_today.count) if obj_today else None
    top_obj_count = obj_today.count(top_obj) if top_obj else 0

    last_call = all_calls[-1] if all_calls else None
    last_label = ""
    if last_call:
        r = last_call["result"]
        d = last_call.get("detail", "")
        label = RESULT_LABELS.get(r, r)
        last_label = f"{label} — {d}" if d else label
        ts = datetime.fromisoformat(last_call["timestamp"]).strftime("%H:%M")
        last_label = f"{last_label} ({ts})"

    return {
        "total_today": total_today,
        "conversion_today": conversion_today,
        "last_call": last_label,
        "top_objection": f"{top_obj} ({top_obj_count}×)" if top_obj else "—",
    }


# ── Layout ───────────────────────────────────────────────────────────

def layout():
    return dbc.Container([

        # ── Section 1 : KPI & Analytics ─────────────────────────────
        html.H5("KPI & Analytics", className="mt-3 mb-4 text-light"),

        # ── Sélecteur d'utilisateur (design system: glassmorphism dark) ───
        dbc.Row([
            dbc.Col(
                html.Div([
                    dbc.RadioItems(
                        id="cc-user-selector",
                        options=[
                            {"label": "🐼  Benjamin", "value": "Benjamin"},
                            {"label": "😺  Lucas", "value": "Lucas"}
                        ],
                        value="Benjamin",
                        inline=True,
                        className="cc-user-radio",
                        inputClassName="cc-user-radio-input",
                        labelClassName="cc-user-radio-label",
                    ),
                ], className="d-flex justify-content-center"),
                width=12,
            ),
        ], className="mb-4"),

        # Filtre de période
        dbc.Row([
            dbc.Col(
                dbc.RadioItems(
                    id="cc-period",
                    options=[
                        {"label": "1J", "value": "1j"},
                        {"label": "3J", "value": "3j"},
                        {"label": "7J", "value": "7j"},
                        {"label": "1M", "value": "1m"},
                        {"label": "All", "value": "all"},
                    ],
                    value="all",
                    inline=True,
                    className="mb-3",
                    inputClassName="me-1",
                ),
                className="text-end"
            ),
        ]),

        # Bloc KPI
        dbc.Row(id="cc-kpi-cards", className="mb-4 g-3"),

        # Graphiques
        dbc.Row([
            dbc.Col(dcc.Graph(id="cc-graph-line", config={"displayModeBar": False}), md=7),
            dbc.Col(dcc.Graph(id="cc-graph-pie", config={"displayModeBar": False}), md=5),
        ], className="mb-4"),

        html.Hr(style={"borderColor": "#444"}),

        # ── Section 2 : Call Tracker ─────────────────────────────────
        html.H5("Call Tracker", className="mb-3 text-light"),

        # Boutons principaux
        dbc.Row([
            dbc.Col(dbc.Button(
                "✗  Recalé au pitch",
                id="cc-btn-pitch-fail",
                color="danger",
                size="lg",
                className="w-100 py-3 fw-bold",
            ), md=4),
            dbc.Col(dbc.Button(
                "⚡  Objection",
                id="cc-btn-objection",
                color="warning",
                size="lg",
                className="w-100 py-3 fw-bold",
            ), md=4),
            dbc.Col(dbc.Button(
                "✓  Succès — RDV booké",
                id="cc-btn-success",
                color="success",
                size="lg",
                className="w-100 py-3 fw-bold",
            ), md=4),
        ], className="mb-3"),

        # Sous-menu objections (caché par défaut)
        dbc.Collapse(
            dbc.Card(
                dbc.CardBody([
                    html.P("Choisir le type d'objection :", className="text-muted mb-2"),
                    dbc.Row([
                        dbc.Col(dbc.Button(
                            label,
                            id={"type": "cc-obj-btn", "index": label},
                            color="warning",
                            outline=True,
                            size="sm",
                            className="w-100 mb-2",
                        ), md=6)
                        for label in OBJECTION_OPTIONS
                    ]),
                ]),
                style={"backgroundColor": "#2a2a2a", "border": "1px solid #fd7e14"},
            ),
            id="cc-collapse-objection",
            is_open=False,
        ),

        # Bouton annuler
        dbc.Row([
            dbc.Col(dbc.Button(
                "↩  Annuler le dernier appel",
                id="cc-btn-undo",
                color="secondary",
                outline=True,
                size="sm",
            ), className="text-center mt-2 mb-4"),
        ]),

        # Feedback action (notification temporaire)
        dbc.Alert(id="cc-action-feedback", is_open=False, duration=2000, className="text-center"),

        # Mini-stats session
        dbc.Card(
            dbc.CardBody([
                html.H6("Aujourd'hui", className="text-muted mb-3"),
                dbc.Row([
                    dbc.Col(html.Div([
                        html.Div(id="cc-today-total", className="fs-4 fw-bold text-light"),
                        html.Small("Appels", className="text-muted"),
                    ]), md=3, className="text-center"),
                    dbc.Col(html.Div([
                        html.Div(id="cc-today-conversion", className="fs-4 fw-bold text-success"),
                        html.Small("Taux de succès", className="text-muted"),
                    ]), md=3, className="text-center"),
                    dbc.Col(html.Div([
                        html.Div(id="cc-today-last", className="fs-6 text-light"),
                        html.Small("Dernier résultat", className="text-muted"),
                    ]), md=3, className="text-center"),
                    dbc.Col(html.Div([
                        html.Div(id="cc-today-top-obj", className="fs-6 text-warning"),
                        html.Small("Objection principale", className="text-muted"),
                    ]), md=3, className="text-center"),
                ]),
            ]),
            style={"backgroundColor": "#1e1e1e", "border": "1px solid #444"},
            className="mb-4",
        ),

        # Store pour trigger refresh après action (les stats se mettent à jour
        # à chaque appel enregistré — plus besoin de rafraîchir toutes les 5 s).
        dcc.Store(id="cc-trigger", data=0),

    ], fluid=True)


# ── Callbacks ────────────────────────────────────────────────────────

def register_callbacks(app):

    # Toggle sous-menu objections
    @app.callback(
        Output("cc-collapse-objection", "is_open"),
        Input("cc-btn-objection", "n_clicks"),
        State("cc-collapse-objection", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_objection_menu(n, is_open):
        return not is_open

    # Enregistrer un appel (pitch_fail, success, objection ou annuler)
    @app.callback(
        Output("cc-trigger", "data"),
        Output("cc-action-feedback", "children"),
        Output("cc-action-feedback", "color"),
        Output("cc-action-feedback", "is_open"),
        Output("cc-collapse-objection", "is_open", allow_duplicate=True),
        Input("cc-btn-pitch-fail", "n_clicks"),
        Input("cc-btn-success", "n_clicks"),
        Input("cc-btn-undo", "n_clicks"),
        Input({"type": "cc-obj-btn", "index": ALL}, "n_clicks"),
        State("cc-trigger", "data"),
        State("cc-user-selector", "value"),
        prevent_initial_call=True,
    )
    def handle_action(n_pitch, n_success, n_undo, n_obj_list, trigger_val, user):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update, no_update, no_update

        triggered_id = ctx.triggered[0]["prop_id"]

        if "cc-btn-pitch-fail" in triggered_id:
            add_call(user, "pitch_fail")
            return trigger_val + 1, "Recalé au pitch enregistré", "danger", True, False

        elif "cc-btn-success" in triggered_id:
            add_call(user, "success")
            return trigger_val + 1, "Succès — RDV booké enregistré !", "success", True, False

        elif "cc-btn-undo" in triggered_id:
            removed = undo_last_call(user)
            msg = "Dernier appel annulé" if removed else "Aucun appel à annuler"
            return trigger_val + 1, msg, "secondary", True, False

        elif "cc-obj-btn" in triggered_id:
            # Extraire le label depuis le dict id JSON
            btn_id_str = triggered_id.replace(".n_clicks", "")
            try:
                id_dict = json.loads(btn_id_str)
                detail = id_dict.get("index", "")
            except (json.JSONDecodeError, AttributeError):
                detail = ""
            add_call(user, "objection", detail)
            return trigger_val + 1, f"Objection : {detail}", "warning", True, False

        return no_update, no_update, no_update, no_update, no_update

    # Mettre à jour KPIs, graphiques et mini-stats
    @app.callback(
        Output("cc-kpi-cards", "children"),
        Output("cc-graph-line", "figure"),
        Output("cc-graph-pie", "figure"),
        Output("cc-today-total", "children"),
        Output("cc-today-conversion", "children"),
        Output("cc-today-last", "children"),
        Output("cc-today-top-obj", "children"),
        Input("cc-period", "value"),
        Input("cc-trigger", "data"),
        Input("cc-user-selector", "value"),
    )
    def update_analytics(period, _trigger, user):
        all_calls = load_calls(user)
        filtered = filter_by_period(all_calls, period)
        df = calls_to_df(filtered)
        kpis = compute_kpis(df)
        today_stats = compute_today_stats(all_calls)

        # KPI cards
        kpi_cards = [
            dbc.Col(_kpi_card("Total", kpis["total"], "#ffffff"), md=True),
            dbc.Col(_kpi_card("Succès", kpis["success"], "#28a745"), md=True),
            dbc.Col(_kpi_card("Recalés", kpis["pitch_fail"], "#dc3545"), md=True),
            dbc.Col(_kpi_card("Objections", kpis["objections"], "#fd7e14"), md=True),
            dbc.Col(_kpi_card("Conversion", f"{kpis['conversion']}%", "#17a2b8"), md=True),
        ]

        # Courbe appels par jour
        if not df.empty:
            df_day = df.copy()
            df_day["date"] = df_day["timestamp"].dt.date
            by_day = df_day.groupby("date").size().reset_index(name="appels")
            fig_line = px.line(
                by_day, x="date", y="appels",
                markers=True,
                labels={"date": "", "appels": "Appels"},
                template="plotly_dark",
            )
            fig_line.update_traces(line_color="#4dabf7", marker_color="#4dabf7")
        else:
            fig_line = go.Figure()
            fig_line.update_layout(
                template="plotly_dark",
                annotations=[{"text": "Aucune donnée", "showarrow": False, "font": {"color": "#888"}}],
            )
        fig_line.update_layout(
            plot_bgcolor="#1e1e1e", paper_bgcolor="#1e1e1e",
            margin=dict(l=20, r=20, t=30, b=20),
            title={"text": "Appels par jour", "font": {"color": "#ccc", "size": 13}},
        )

        # Camembert répartition
        if not df.empty:
            pie_data = df["result"].map(RESULT_LABELS).value_counts().reset_index()
            pie_data.columns = ["Résultat", "count"]
            color_map = {v: RESULT_COLORS[k] for k, v in RESULT_LABELS.items()}
            fig_pie = px.pie(
                pie_data, names="Résultat", values="count",
                color="Résultat", color_discrete_map=color_map,
                template="plotly_dark",
                hole=0.4,
            )
            fig_pie.update_traces(textfont_color="#fff")
        else:
            fig_pie = go.Figure()
            fig_pie.update_layout(
                template="plotly_dark",
                annotations=[{"text": "Aucune donnée", "showarrow": False, "font": {"color": "#888"}}],
            )
        fig_pie.update_layout(
            plot_bgcolor="#1e1e1e", paper_bgcolor="#1e1e1e",
            margin=dict(l=10, r=10, t=30, b=10),
            title={"text": "Répartition", "font": {"color": "#ccc", "size": 13}},
            legend={"font": {"color": "#ccc"}},
        )

        return (
            kpi_cards,
            fig_line,
            fig_pie,
            str(today_stats["total_today"]),
            f"{today_stats['conversion_today']}%",
            today_stats["last_call"] or "—",
            today_stats["top_objection"],
        )


def _kpi_card(label: str, value, color: str) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody([
            html.Div(str(value), style={"fontSize": "2rem", "fontWeight": "bold", "color": color}),
            html.Small(label, className="text-muted"),
        ], className="text-center p-2"),
        style={"backgroundColor": "#1e1e1e", "border": "1px solid #444"},
    )
