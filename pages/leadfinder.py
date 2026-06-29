"""
LeadFinder – page de recherche de leads Google Maps
"""
from __future__ import annotations

import io
import os
import re
import threading
import uuid

import requests
import pandas as pd
from dotenv import load_dotenv
from dash import html, dcc, Output, Input, State, no_update, ALL, callback_context
import dash_bootstrap_components as dbc

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

# ── Liste des activités ──────────────────────────────────────────────

def _cat(label):
    return {"label": f"── {label} ──", "value": f"__{label}", "disabled": True}

def _opt(label):
    return {"label": f"  {label}", "value": label}

ACTIVITY_OPTIONS = [
    _cat("Artisanat & BTP"),
    _opt("Plombier"), _opt("Électricien"), _opt("Menuisier"), _opt("Maçon"),
    _opt("Carreleur"), _opt("Peintre en bâtiment"), _opt("Serrurier"),
    _opt("Chauffagiste"), _opt("Couvreur"), _opt("Vitrier"),

    _cat("Beauté & Bien-être"),
    _opt("Coiffeur"), _opt("Barbier"), _opt("Esthéticienne"),
    _opt("Institut de beauté"), _opt("Massage"),

    _cat("Alimentation"),
    _opt("Boulangerie"), _opt("Boucherie"), _opt("Épicerie"),
    _opt("Traiteur"), _opt("Pizzeria"), _opt("Restaurant"),

    _cat("Auto & Moto"),
    _opt("Garagiste"), _opt("Carrossier"),
    _opt("Contrôle technique"), _opt("Pneumatiques"),

    _cat("Services"),
    _opt("Pressing"), _opt("Cordonnerie"), _opt("Photographe"),
    _opt("Agence immobilière"), _opt("Expert-comptable"), _opt("Avocat"),
    _opt("Vétérinaire"), _opt("Déménagement"), _opt("Nettoyage"),
]

# ── Google Places API (New) ──────────────────────────────────────────
# On utilise la « Places API (New) » de Google. Un SEUL appel renvoie déjà le
# nom, l'adresse, le site web, le téléphone et la note — plus besoin d'un appel
# « détails » par établissement (l'ancienne API textsearch/details est
# abandonnée par Google et n'est plus activable sur les projets récents).

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

_FIELD_MASK = ",".join([
    "nextPageToken",
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.businessStatus",
    "places.googleMapsUri",
])


def text_search(query: str, page_token: str | None = None) -> dict:
    """Recherche textuelle (Places API New). Renvoie le JSON brut de la page.
    Une page = jusqu'à 20 commerces, avec un `nextPageToken` pour la suivante.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY or "",
        "X-Goog-FieldMask": _FIELD_MASK,
    }
    body = {"textQuery": query, "languageCode": "fr", "regionCode": "FR"}
    if page_token:
        body["pageToken"] = page_token
    r = requests.post(PLACES_SEARCH_URL, headers=headers, json=body, timeout=30)
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            status = err.get("status", "")
            message = err.get("message", "")
        except Exception:
            status, message = str(r.status_code), r.text[:200]
        raise RuntimeError(f"Places API error: {status} – {message}")
    return r.json()


def _extract_city_postal(address: str) -> str:
    """Extract 'VILLE, 00000' from a French Google Maps address."""
    # Typical format: "12 Rue X, 75011 Paris, France"
    m = re.search(r"(\d{5})\s+([^,]+)", address)
    if m:
        return f"{m.group(2).strip().upper()}, {m.group(1)}"
    # Fallback: return last meaningful part before country
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        return parts[-2].upper()
    return address.upper()


def places_to_df(places: list[dict]) -> pd.DataFrame:
    rows = []
    for p in places:
        rows.append({
            "Nom": (p.get("displayName") or {}).get("text", ""),
            "Localisation": _extract_city_postal(p.get("formattedAddress", "")),
            "Téléphone": p.get("nationalPhoneNumber", ""),
            "Note": p.get("rating", ""),
            "Avis": p.get("userRatingCount", ""),
            "Site web": p.get("websiteUri", ""),
            "Statut": p.get("businessStatus", ""),
            "Google Maps": p.get("googleMapsUri", ""),
        })
    return pd.DataFrame(rows)


# ── Recherche en arrière-plan + suivi de progression ─────────────────
# La recherche tourne dans un thread pour ne pas figer l'interface. Elle écrit
# son avancement dans _SEARCH_STATE ; un dcc.Interval le lit toutes les ~400 ms
# pour alimenter la barre de progression. Zéro dépendance externe.

_search_lock = threading.Lock()
_SEARCH_STATE: dict[str, dict] = {}


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if "legacy api" in low or "not enabled" in low or "has not been used" in low or "serviceusage" in low:
        return ("L'API « Places API (New) » n'est pas activée sur ton projet Google Cloud. "
                "Active-la dans Google Cloud Console (APIs & Services → Library), puis réessaie.")
    if ("permission_denied" in low or "request_denied" in low or "api key" in low
            or "api_key" in low or "apikey" in low or "invalid" in low):
        return ("Erreur de clé API Google : la clé est invalide, restreinte, ou l'API "
                "« Places API (New) » n'est pas activée. Vérifie le fichier .env et Google Cloud.")
    if "over_query_limit" in low or "quota" in low or "resource_exhausted" in low:
        return "Quota Google dépassé. Réessaie plus tard ou vérifie la facturation Google Cloud."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Impossible de joindre Google. Vérifie ta connexion Internet, puis réessaie."
    if isinstance(exc, requests.exceptions.Timeout):
        return "Google met trop de temps à répondre. Réessaie dans un instant."
    return f"Une erreur est survenue pendant la recherche : {text[:200]}"


def _run_search_job(token: str, city: str, activity: str) -> None:
    def update(**kw):
        with _search_lock:
            st = _SEARCH_STATE.get(token)
            if st is not None:
                st.update(kw)

    try:
        if not API_KEY:
            raise RuntimeError("API key manquante (GOOGLE_API_KEY absent du .env).")

        query = f"{activity} à {city}"
        update(pct=12, message="Recherche des commerces sur Google Maps…")

        places: list[dict] = []
        page_token = None
        for page in range(3):  # jusqu'à 3 pages × 20 = 60 commerces
            data = text_search(query, page_token=page_token)
            places.extend(data.get("places", []))
            update(pct=min(90, 25 + page * 25),
                   message=f"Recherche des commerces… ({len(places)} trouvés)")
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        if not places:
            update(done=True, pct=100, message="Aucun commerce trouvé.", results=[])
            return

        update(pct=95, message="Mise en forme des résultats…")
        df = places_to_df(places)
        update(done=True, pct=100,
               message=f"Terminé — {len(df)} commerces récupérés.",
               results=df.to_dict("records"))
    except Exception as exc:  # noqa: BLE001 - on veut tout attraper pour l'afficher
        update(done=True, error=True, pct=100,
               message=_friendly_error(exc), results=[])


# ── Petits composants d'affichage ────────────────────────────────────

ALL_COLS = ["Nom", "Localisation", "Téléphone", "Note", "Avis", "Site web", "Google Maps"]


def _progress_view(pct: int, message: str) -> html.Div:
    return html.Div(
        [
            dbc.Progress(
                value=pct, color="info", striped=True, animated=True,
                style={"height": "8px"}, className="lf-progress mb-2",
            ),
            html.Div(message, className="lf-progress-status small"),
        ],
        className="lf-progress-wrap",
        role="status", **{"aria-live": "polite"},
    )


def _welcome_state() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-search lf-empty-icon"),
            html.P("Trouve des commerces sans site web à prospecter.",
                   className="mb-1 fw-medium"),
            html.Small("Saisis une ville et une activité, puis clique sur « Rechercher » "
                       "(ou appuie sur Entrée).", className="text-muted"),
        ],
        className="lf-empty-state text-center py-5",
    )


def _no_results_state() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-inbox lf-empty-icon"),
            html.P("Aucun commerce trouvé pour cette recherche.", className="mb-1 fw-medium"),
            html.Small("Essaie une autre ville ou une autre activité.", className="text-muted"),
        ],
        className="lf-empty-state text-center py-5",
    )


# ── Layout ───────────────────────────────────────────────────────────

def layout():
    return dbc.Container([
        html.H5("Recherche de leads", className="mt-3 mb-3 text-light"),

        # ── Barre de recherche (carte épurée, champs avec icône) ─────
        dbc.Card(dbc.CardBody(
            dbc.Row([
                dbc.Col(dbc.InputGroup([
                    dbc.InputGroupText(html.I(className="bi bi-geo-alt")),
                    dbc.Input(
                        id="lf-input-city", placeholder="Ville (ex : Lyon)",
                        type="text", autoFocus=True,
                    ),
                ]), md=5),
                dbc.Col(html.Div([
                    dbc.InputGroup([
                        dbc.InputGroupText(html.I(className="bi bi-shop")),
                        dbc.Input(
                            id="lf-input-activity",
                            placeholder="Activité (ex : Plombier, Coiffeur, Restaurant…)",
                            type="text", list="lf-activity-suggestions",
                        ),
                    ]),
                    html.Datalist(
                        id="lf-activity-suggestions",
                        children=[html.Option(value=o["value"]) for o in ACTIVITY_OPTIONS if not o.get("disabled")],
                    ),
                ]), md=5),
                dbc.Col(dbc.Button(
                    [html.I(className="bi bi-search me-2"), "Rechercher"],
                    id="lf-btn-search", color="primary", className="w-100",
                ), md=2),
            ], className="g-2", align="center"),
        ), className="lf-search-card mb-3"),

        # ── Barre de filtres / actions ──────────────────────────────
        dbc.Row([
            dbc.Col(dbc.Checklist(
                id="lf-filter-no-site",
                options=[{"label": " Sans site web uniquement", "value": "no_site"}],
                value=["no_site"],
                inline=True,
            ), md="auto"),
            dbc.Col(dbc.Button(
                [html.I(className="bi bi-funnel me-1"), "Filtres"],
                id="lf-btn-toggle-filters",
                color="secondary", outline=True, size="sm",
            ), md="auto"),
            dbc.Col(dbc.InputGroup([
                dbc.InputGroupText(html.I(className="bi bi-arrow-down-up")),
                dbc.Select(
                    id="lf-sort-by",
                    options=[{"label": c, "value": c} for c in ALL_COLS],
                    value="Nom",
                    style={"fontSize": "0.85rem"},
                ),
                dbc.Button(
                    html.I(className="bi bi-arrow-up"),
                    id="lf-sort-order", color="secondary", outline=True,
                    title="Inverser l'ordre", size="sm",
                    style={"padding": "5px 8px"},
                ),
            ], size="sm"), md="auto"),
            dbc.Col(dbc.DropdownMenu(
                label=html.Span([html.I(className="bi bi-layout-three-columns me-1"), "Colonnes"]),
                children=[
                    dbc.Checklist(
                        id="lf-col-visibility",
                        options=[{"label": c, "value": c} for c in ALL_COLS],
                        value=list(ALL_COLS),
                        style={"padding": "8px 12px"},
                    )
                ],
                color="secondary", size="sm",
                toggle_style={"fontSize": "0.85rem"},
            ), md="auto"),
            dbc.Col(html.Div(id="lf-result-count", className="text-muted small"),
                    md=True, className="d-flex align-items-center justify-content-end text-end"),
            dbc.Col(dbc.Button(
                [html.I(className="bi bi-file-earmark-excel me-1"), "Excel"],
                id="lf-btn-csv", color="success", outline=True, size="sm",
                title="Exporter les résultats affichés en Excel",
            ), md="auto"),
        ], className="mb-2 g-2", align="center"),

        # Collapse filtres par colonne
        dbc.Collapse(
            dbc.Card(dbc.CardBody(
                html.Div(id="lf-filter-inputs-container"),
                style={"padding": "8px"},
            ), className="lf-filter-card"),
            id="lf-collapse-filters",
            is_open=False,
            className="mb-2",
        ),

        # Message d'erreur visible (clé API, réseau…)
        dbc.Alert(
            id="lf-error-alert", color="danger", is_open=False, dismissable=True,
            className="d-flex align-items-center gap-2",
        ),

        # Barre de progression de la recherche
        html.Div(id="lf-progress-wrap", className="mb-2"),

        # Résultats
        html.Div(id="lf-table-results"),

        # Hidden stores / mécanique
        dcc.Store(id="lf-store-data"),
        dcc.Store(id="lf-col-filters", data={}),
        dcc.Store(id="lf-search-token"),
        dcc.Store(id="lf-sort-order-state", data=True),  # True = ascending, False = descending
        dcc.Interval(id="lf-progress-interval", interval=400, disabled=True),
        dcc.Download(id="lf-download-csv"),
        dcc.Store(id="lf-pending-prospect", data=None),

        # Feedback ajout prospect
        dbc.Alert(id="lf-prospect-feedback", is_open=False, duration=2500, className="text-center mt-2"),

        # Modal ajout aux prospects
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="lf-modal-title")),
            dbc.ModalBody([
                html.P("Ajouter à un groupe existant :", className="text-muted mb-2"),
                html.Div(id="lf-modal-groups"),
                html.Hr(),
                html.P("Ou créer un nouveau groupe :", className="text-muted mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Input(id="lf-modal-new-group", placeholder="Nom du groupe...", size="sm"), md=8),
                    dbc.Col(dbc.Button("Créer & Ajouter", id="lf-modal-btn-create", color="primary", size="sm"), width="auto"),
                ], className="g-2", align="center"),
            ]),
        ], id="lf-prospect-modal", is_open=False),

    ], fluid=True)


# ── Callbacks ────────────────────────────────────────────────────────

def register_callbacks(app):

    # 1) Démarrer une recherche (clic bouton OU touche Entrée dans un champ)
    @app.callback(
        Output("lf-search-token", "data"),
        Output("lf-progress-interval", "disabled"),
        Output("lf-progress-wrap", "children"),
        Output("lf-error-alert", "is_open"),
        Input("lf-btn-search", "n_clicks"),
        Input("lf-input-city", "n_submit"),
        Input("lf-input-activity", "n_submit"),
        State("lf-input-city", "value"),
        State("lf-input-activity", "value"),
        prevent_initial_call=True,
    )
    def start_search(n_clicks, ns_city, ns_activity, city, activity):
        if not city or not activity:
            warn = dbc.Alert(
                "Saisis une ville ET une activité avant de lancer la recherche.",
                color="secondary", className="py-2 mb-0 small",
            )
            return no_update, True, warn, False

        token = uuid.uuid4().hex
        with _search_lock:
            _SEARCH_STATE.clear()  # on ne garde que la recherche en cours
            _SEARCH_STATE[token] = {
                "pct": 3, "message": "Démarrage…",
                "done": False, "error": False, "results": [],
            }
        threading.Thread(
            target=_run_search_job, args=(token, city, activity), daemon=True
        ).start()
        return token, False, _progress_view(3, "Démarrage…"), False

    # 2) Suivre la progression (polling) → alimente la barre, puis livre les résultats
    @app.callback(
        Output("lf-progress-wrap", "children", allow_duplicate=True),
        Output("lf-progress-interval", "disabled", allow_duplicate=True),
        Output("lf-store-data", "data"),
        Output("lf-error-alert", "children"),
        Output("lf-error-alert", "is_open", allow_duplicate=True),
        Input("lf-progress-interval", "n_intervals"),
        State("lf-search-token", "data"),
        prevent_initial_call=True,
    )
    def poll_progress(_n, token):
        if not token:
            return no_update, True, no_update, no_update, no_update
        with _search_lock:
            st = dict(_SEARCH_STATE.get(token, {}))
        if not st:
            return no_update, True, no_update, no_update, no_update

        if st.get("done"):
            if st.get("error"):
                err = html.Span([html.I(className="bi bi-exclamation-triangle-fill me-2"), st["message"]])
                return "", True, no_update, err, True
            # succès (résultats, éventuellement liste vide)
            return "", True, st.get("results", []), no_update, False

        # en cours
        return _progress_view(st.get("pct", 0), st.get("message", "")), False, no_update, no_update, no_update

    # Toggle panneau filtres
    @app.callback(
        Output("lf-collapse-filters", "is_open"),
        Output("lf-filter-inputs-container", "children"),
        Input("lf-btn-toggle-filters", "n_clicks"),
        State("lf-collapse-filters", "is_open"),
        State("lf-col-visibility", "value"),
        State("lf-col-filters", "data"),
        prevent_initial_call=True,
    )
    def toggle_filters(n, is_open, visible_cols, current_filters):
        visible = visible_cols or ALL_COLS
        current_filters = current_filters or {}
        inputs = dbc.Row([
            dbc.Col([
                html.Small(c, className="text-muted d-block mb-1"),
                dbc.Input(
                    id=f"lf-filter-{c.lower().replace(' ', '-').replace('é', 'e').replace('è', 'e').replace('ê', 'e')}",
                    value=current_filters.get(c, ""),
                    placeholder=f"Filtrer {c}...",
                    size="sm",
                    debounce=True,
                    className="lf-filter-input",
                ),
            ], md=True)
            for c in visible if c != "Google Maps"
        ], className="g-2")
        return not is_open, inputs

    # Agréger les filtres colonnes dans le Store
    @app.callback(
        Output("lf-col-filters", "data"),
        Input("lf-filter-nom", "value"),
        Input("lf-filter-localisation", "value"),
        Input("lf-filter-telephone", "value"),
        Input("lf-filter-note", "value"),
        Input("lf-filter-avis", "value"),
        Input("lf-filter-site-web", "value"),
        prevent_initial_call=True,
    )
    def aggregate_filters(nom, loc, tel, note, avis, site):
        return {
            "Nom": nom or "",
            "Localisation": loc or "",
            "Téléphone": tel or "",
            "Note": note or "",
            "Avis": avis or "",
            "Site web": site or "",
        }

    # Inverser l'ordre du tri
    @app.callback(
        Output("lf-sort-order-state", "data"),
        Output("lf-sort-order", "children"),
        Input("lf-sort-order", "n_clicks"),
        State("lf-sort-order-state", "data"),
        prevent_initial_call=True,
    )
    def toggle_sort_order(n_clicks, is_ascending):
        new_order = not is_ascending
        icon = html.I(className="bi bi-arrow-up" if new_order else "bi bi-arrow-down")
        return new_order, icon

    @app.callback(
        Output("lf-table-results", "children"),
        Output("lf-result-count", "children"),
        Input("lf-store-data", "data"),
        Input("lf-filter-no-site", "value"),
        Input("lf-col-filters", "data"),
        Input("lf-col-visibility", "value"),
        Input("lf-sort-by", "value"),
        Input("lf-sort-order-state", "data"),
    )
    def update_table(records, filters, col_filters, visible_cols, sort_col, ascending):
        if records is None:
            return _welcome_state(), ""
        if not records:
            return _no_results_state(), "0 résultat"

        df = pd.DataFrame(records)

        total = len(df)
        if "no_site" in (filters or []):
            df = df[df["Site web"].fillna("").astype(str).str.strip() == ""]

        # Appliquer filtres par colonne
        for col, val in (col_filters or {}).items():
            if val and col in df.columns:
                df = df[df[col].astype(str).str.contains(val, case=False, na=False)]

        # Appliquer le tri
        if sort_col and sort_col in df.columns:
            df = df.sort_values(by=sort_col, ascending=ascending, na_position="last")

        shown = len(df)
        cols = [c for c in ALL_COLS if c in (visible_cols or ALL_COLS)]

        header = html.Thead(html.Tr(
            [html.Th("", style={"width": "32px"})] +
            [html.Th(c, style={"whiteSpace": "nowrap"}) for c in cols]
        ))

        rows = []
        for i, row in enumerate(df.reset_index(drop=True).to_dict("records")):
            no_site = not str(row.get("Site web") or "").strip()
            cells = [html.Td(
                dbc.Button(
                    html.I(className="bi bi-plus-circle"),
                    id={"type": "lf-add-prospect-btn", "idx": i},
                    color="success", outline=True, size="sm",
                    title="Ajouter aux prospects",
                    style={"padding": "2px 6px"},
                    n_clicks=0,
                ),
                style={"padding": "4px 6px"},
            )]
            for c in cols:
                val = str(row.get(c, ""))
                if c == "Google Maps" and val:
                    cells.append(html.Td(html.A("Voir", href=val, target="_blank", className="lf-link")))
                elif c == "Site web" and val:
                    cells.append(html.Td(html.A(val, href=val, target="_blank", className="lf-link",
                                                style={"wordBreak": "break-all"}), style={"maxWidth": "200px"}))
                else:
                    cls = "lf-cell-nosite" if (c == "Nom" and no_site) else None
                    cells.append(html.Td(val, className=cls))
            rows.append(html.Tr(cells))

        table = dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, color="dark", hover=True, size="sm",
            className="lf-table align-middle",
        )

        count_text = f"{shown} affichés / {total} trouvés"
        return table, count_text

    @app.callback(
        Output("lf-download-csv", "data"),
        Input("lf-btn-csv", "n_clicks"),
        State("lf-store-data", "data"),
        State("lf-filter-no-site", "value"),
        State("lf-col-filters", "data"),
        State("lf-col-visibility", "value"),
        prevent_initial_call=True,
    )
    def export_excel(n, records, filters, col_filters, visible_cols):
        if not records:
            return no_update
        df = pd.DataFrame(records)
        # Appliquer les mêmes filtres que le tableau affiché
        if "no_site" in (filters or []):
            df = df[df["Site web"].fillna("").astype(str).str.strip() == ""]
        for col, val in (col_filters or {}).items():
            if val and col in df.columns:
                df = df[df[col].astype(str).str.contains(val, case=False, na=False)]
        cols = [c for c in ALL_COLS if c in (visible_cols or ALL_COLS)]
        df = df[[c for c in cols if c in df.columns]]

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Leads")
            ws = writer.sheets["Leads"]
            # Largeurs automatiques
            for col_cells in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col_cells), default=10)
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)
        return dcc.send_bytes(buf.getvalue(), "leads.xlsx")

    # Ouvrir le modal ajout prospect
    @app.callback(
        Output("lf-prospect-modal", "is_open"),
        Output("lf-modal-title", "children"),
        Output("lf-modal-groups", "children"),
        Output("lf-pending-prospect", "data"),
        Input({"type": "lf-add-prospect-btn", "idx": ALL}, "n_clicks"),
        State("lf-store-data", "data"),
        State("lf-filter-no-site", "value"),
        State("lf-col-filters", "data"),
        prevent_initial_call=True,
    )
    def open_prospect_modal(n_clicks_list, records, filters, col_filters):
        from pages.prospects import get_groups
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks_list):
            return no_update, no_update, no_update, no_update

        triggered_id = ctx.triggered[0]["prop_id"]
        import json as _json
        try:
            idx = _json.loads(triggered_id.replace(".n_clicks", ""))["idx"]
        except Exception:
            return no_update, no_update, no_update, no_update

        if not records:
            return no_update, no_update, no_update, no_update

        # IMPORTANT : reconstruire le DataFrame avec EXACTEMENT les mêmes filtres
        # que le tableau affiché (no_site + filtres colonne), sinon l'index `idx`
        # ne pointe pas sur la bonne ligne et on ajoute le mauvais lead.
        df = pd.DataFrame(records)
        if "no_site" in (filters or []):
            df = df[df["Site web"].fillna("").astype(str).str.strip() == ""]
        for col, val in (col_filters or {}).items():
            if val and col in df.columns:
                df = df[df[col].astype(str).str.contains(val, case=False, na=False)]
        df = df.reset_index(drop=True)

        if idx >= len(df):
            return no_update, no_update, no_update, no_update

        row = df.iloc[idx].to_dict()
        groups = get_groups()

        # Vérifier lesquels contiennent déjà ce prospect
        already_in = set()
        for g in groups:
            for p in g["prospects"]:
                if p["Nom"] == row.get("Nom") and p.get("Localisation") == row.get("Localisation"):
                    already_in.add(g["id"])

        if groups:
            group_btns = [
                dbc.Button(
                    [g["name"], html.Span(" (déjà ajouté)", className="text-muted ms-1 small") if g["id"] in already_in else ""],
                    id={"type": "lf-modal-group-btn", "gid": g["id"]},
                    color="secondary" if g["id"] in already_in else "primary",
                    outline=True,
                    disabled=g["id"] in already_in,
                    className="me-2 mb-2",
                    n_clicks=0,
                )
                for g in groups
            ]
        else:
            group_btns = [html.P("Aucun groupe existant.", className="text-muted")]

        return True, f"Ajouter : {row.get('Nom', '')}", group_btns, row

    # Ajouter au groupe existant via modal
    @app.callback(
        Output("lf-prospect-modal", "is_open", allow_duplicate=True),
        Output("lf-prospect-feedback", "children"),
        Output("lf-prospect-feedback", "color"),
        Output("lf-prospect-feedback", "is_open"),
        Input({"type": "lf-modal-group-btn", "gid": ALL}, "n_clicks"),
        State("lf-pending-prospect", "data"),
        prevent_initial_call=True,
    )
    def add_to_existing_group(n_clicks_list, prospect):
        from pages.prospects import get_groups, add_prospect_to_group
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks_list):
            return no_update, no_update, no_update, no_update
        import json as _json
        triggered_id = ctx.triggered[0]["prop_id"].replace(".n_clicks", "")
        try:
            gid = _json.loads(triggered_id)["gid"]
        except Exception:
            return no_update, no_update, no_update, no_update

        groups = get_groups()
        group_name = next((g["name"] for g in groups if g["id"] == gid), "?")
        add_prospect_to_group(gid, prospect)
        return False, f"✓ Ajouté à « {group_name} »", "success", True

    # Créer groupe et ajouter via modal
    @app.callback(
        Output("lf-prospect-modal", "is_open", allow_duplicate=True),
        Output("lf-prospect-feedback", "children", allow_duplicate=True),
        Output("lf-prospect-feedback", "color", allow_duplicate=True),
        Output("lf-prospect-feedback", "is_open", allow_duplicate=True),
        Output("lf-modal-new-group", "value"),
        Input("lf-modal-btn-create", "n_clicks"),
        State("lf-modal-new-group", "value"),
        State("lf-pending-prospect", "data"),
        prevent_initial_call=True,
    )
    def create_group_and_add(n, group_name, prospect):
        from pages.prospects import add_group, add_prospect_to_group
        if not group_name or not group_name.strip() or not prospect:
            return no_update, "Saisis un nom de groupe.", "warning", True, no_update
        gid = add_group(group_name)
        add_prospect_to_group(gid, prospect)
        return False, f"✓ Groupe « {group_name.strip()} » créé et prospect ajouté.", "success", True, ""
