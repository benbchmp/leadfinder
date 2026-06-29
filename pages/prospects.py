"""
Prospects – Watchlist par groupes
Données persistées dans prospects_data.json
"""
from __future__ import annotations

import io
import json
import os
import re
import uuid
from datetime import datetime

import pandas as pd

from dash import html, dcc, Input, Output, State, callback_context, no_update, ALL, MATCH
import dash_bootstrap_components as dbc

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prospects_data.json")

# ── Data helpers ─────────────────────────────────────────────────────

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"groups": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"groups": []}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_groups() -> list[dict]:
    return load_data().get("groups", [])


def get_group_names() -> list[dict]:
    """Return list of {id, name} for all groups."""
    return [{"id": g["id"], "name": g["name"]} for g in get_groups()]


def add_group(name: str) -> str:
    """Create a new group, return its id."""
    data = load_data()
    gid = uuid.uuid4().hex
    data["groups"].append({"id": gid, "name": name.strip(), "prospects": []})
    save_data(data)
    return gid


def rename_group(gid: str, new_name: str) -> None:
    data = load_data()
    for g in data["groups"]:
        if g["id"] == gid:
            g["name"] = new_name.strip()
            break
    save_data(data)


def delete_group(gid: str) -> None:
    data = load_data()
    data["groups"] = [g for g in data["groups"] if g["id"] != gid]
    save_data(data)


def add_prospect_to_group(gid: str, prospect: dict) -> bool:
    """Add prospect to group. Returns False if already present."""
    data = load_data()
    for g in data["groups"]:
        if g["id"] == gid:
            # Deduplicate by Nom + Localisation
            existing = {(p["Nom"], p.get("Localisation", "")) for p in g["prospects"]}
            if (prospect["Nom"], prospect.get("Localisation", "")) in existing:
                return False
            p = dict(prospect)
            p["notes"] = ""
            p["added_at"] = datetime.now().isoformat(timespec="seconds")
            g["prospects"].append(p)
            save_data(data)
            return True
    return False


def remove_prospect(gid: str, idx: int) -> None:
    data = load_data()
    for g in data["groups"]:
        if g["id"] == gid:
            if 0 <= idx < len(g["prospects"]):
                g["prospects"].pop(idx)
            break
    save_data(data)


def move_prospect(from_gid: str, idx: int, to_gid: str) -> None:
    data = load_data()
    prospect = None
    for g in data["groups"]:
        if g["id"] == from_gid:
            if 0 <= idx < len(g["prospects"]):
                prospect = g["prospects"].pop(idx)
            break
    if prospect:
        for g in data["groups"]:
            if g["id"] == to_gid:
                g["prospects"].append(prospect)
                break
    save_data(data)


def update_notes(gid: str, idx: int, notes: str) -> None:
    data = load_data()
    for g in data["groups"]:
        if g["id"] == gid:
            if 0 <= idx < len(g["prospects"]):
                g["prospects"][idx]["notes"] = notes
            break
    save_data(data)


# ── Layout ───────────────────────────────────────────────────────────

def layout():
    groups = get_groups()
    group_options = [{"label": g["name"], "value": g["id"]} for g in groups]
    default_gid = groups[0]["id"] if groups else None

    return dbc.Container([
        html.H5("Prospects", className="mt-3 mb-3 text-light"),

        # ── Barre de gestion des groupes ─────────────────────────────
        dbc.Row([
            # Sélecteur de groupe
            dbc.Col(dcc.Dropdown(
                id="pr-group-select",
                options=group_options,
                value=default_gid,
                placeholder="Sélectionner un groupe...",
                clearable=False,
                style={"color": "#000", "minWidth": "200px"},
            ), width="auto"),

            # Bouton nouveau groupe
            dbc.Col(dbc.Button(
                [html.I(className="bi bi-plus-circle me-1"), "Nouveau groupe"],
                id="pr-btn-new-group",
                color="primary", outline=True, size="sm",
            ), width="auto"),

            # Bouton renommer
            dbc.Col(dbc.Button(
                [html.I(className="bi bi-pencil me-1"), "Renommer"],
                id="pr-btn-rename",
                color="secondary", outline=True, size="sm",
            ), width="auto"),

            # Bouton supprimer groupe
            dbc.Col(dbc.Button(
                [html.I(className="bi bi-trash me-1"), "Supprimer le groupe"],
                id="pr-btn-delete-group",
                color="danger", outline=True, size="sm",
            ), width="auto"),

            # Export Excel
            dbc.Col(dbc.Button(
                html.I(className="bi bi-file-earmark-excel", style={"fontSize": "1.1rem"}),
                id="pr-btn-export",
                color="success", outline=True, size="sm",
                title="Exporter le groupe en Excel",
            ), width="auto"),
        ], className="mb-3 g-2", align="center"),

        # Formulaire nouveau groupe (caché par défaut)
        dbc.Collapse(
            dbc.Row([
                dbc.Col(dbc.Input(id="pr-new-group-name", placeholder="Nom du groupe...", size="sm"), md=4),
                dbc.Col(dbc.Button("Créer", id="pr-btn-create-group", color="primary", size="sm"), width="auto"),
                dbc.Col(dbc.Button("Annuler", id="pr-btn-cancel-group", color="secondary", outline=True, size="sm"), width="auto"),
            ], className="mb-3 g-2", align="center"),
            id="pr-collapse-new-group",
            is_open=False,
        ),

        # Formulaire renommer (caché par défaut)
        dbc.Collapse(
            dbc.Row([
                dbc.Col(dbc.Input(id="pr-rename-input", placeholder="Nouveau nom...", size="sm"), md=4),
                dbc.Col(dbc.Button("Valider", id="pr-btn-rename-confirm", color="primary", size="sm"), width="auto"),
                dbc.Col(dbc.Button("Annuler", id="pr-btn-rename-cancel", color="secondary", outline=True, size="sm"), width="auto"),
            ], className="mb-3 g-2", align="center"),
            id="pr-collapse-rename",
            is_open=False,
        ),

        # Modal confirmation suppression groupe
        dbc.Modal([
            dbc.ModalHeader("Supprimer le groupe"),
            dbc.ModalBody(id="pr-delete-modal-body"),
            dbc.ModalFooter([
                dbc.Button("Supprimer", id="pr-btn-delete-confirm", color="danger"),
                dbc.Button("Annuler", id="pr-btn-delete-cancel", color="secondary", outline=True),
            ]),
        ], id="pr-delete-modal", is_open=False),

        # Feedback
        dbc.Alert(id="pr-feedback", is_open=False, duration=2500, className="text-center"),

        # Tableau des prospects
        html.Div(id="pr-table-container"),

        # Store pour trigger
        dcc.Store(id="pr-trigger", data=0),
        dcc.Store(id="pr-pending-delete-gid", data=None),
        dcc.Download(id="pr-download-excel"),

    ], fluid=True)


# ── Helpers layout ────────────────────────────────────────────────────

def _build_table(gid: str, groups: list[dict]) -> html.Div:
    group = next((g for g in groups if g["id"] == gid), None)
    if not group:
        return html.Div("Aucun groupe sélectionné.", className="text-muted mt-3")

    prospects = group["prospects"]
    other_groups = [g for g in groups if g["id"] != gid]

    if not prospects:
        return html.Div([
            html.P("Ce groupe est vide.", className="text-muted mt-3"),
            html.Small(f"0 prospect", className="text-muted"),
        ])

    header = html.Thead(html.Tr([
        html.Th("Nom", style={"padding": "8px 10px"}),
        html.Th("Localisation", style={"padding": "8px 10px"}),
        html.Th("Téléphone", style={"padding": "8px 10px"}),
        html.Th("Note", style={"padding": "8px 10px"}),
        html.Th("Site web", style={"padding": "8px 10px"}),
        html.Th("Maps", style={"padding": "8px 10px"}),
        html.Th("Notes perso", style={"padding": "8px 10px", "minWidth": "200px"}),
        html.Th("Actions", style={"padding": "8px 10px", "whiteSpace": "nowrap"}),
    ]))

    rows = []
    for i, p in enumerate(prospects):
        website = p.get("Site web", "")
        maps_url = p.get("Google Maps", "")

        # Dropdown pour déplacer vers un autre groupe
        move_dropdown = dbc.DropdownMenu(
            label=html.I(className="bi bi-arrow-right-circle"),
            children=[
                dbc.DropdownMenuItem(
                    g["name"],
                    id={"type": "pr-move-btn", "gid": gid, "idx": i, "to": g["id"]},
                    n_clicks=0,
                ) for g in other_groups
            ] if other_groups else [dbc.DropdownMenuItem("Aucun autre groupe", disabled=True)],
            color="secondary",
            size="sm",
        )

        rows.append(html.Tr([
            html.Td(p.get("Nom", ""), style={"padding": "6px 10px", "fontWeight": "500"}),
            html.Td(p.get("Localisation", ""), style={"padding": "6px 10px"}),
            html.Td(p.get("Téléphone", ""), style={"padding": "6px 10px"}),
            html.Td(p.get("Note", ""), style={"padding": "6px 10px"}),
            html.Td(
                html.A(website[:30] + "..." if len(website) > 30 else website, href=website, target="_blank", style={"color": "#4dabf7"}) if website else "—",
                style={"padding": "6px 10px"}
            ),
            html.Td(
                html.A("Voir", href=maps_url, target="_blank", style={"color": "#4dabf7"}) if maps_url else "—",
                style={"padding": "6px 10px"}
            ),
            html.Td(
                dbc.Input(
                    id={"type": "pr-notes-input", "gid": gid, "idx": i},
                    value=p.get("notes", ""),
                    placeholder="Ajouter une note...",
                    size="sm",
                    debounce=True,
                    className="lf-filter-input",
                ),
                style={"padding": "4px 10px"},
            ),
            html.Td(
                html.Div([
                    move_dropdown,
                    dbc.Button(
                        html.I(className="bi bi-trash"),
                        id={"type": "pr-delete-prospect-btn", "gid": gid, "idx": i},
                        color="danger", outline=True, size="sm",
                        title="Supprimer",
                        n_clicks=0,
                    ),
                ], style={"display": "flex", "gap": "4px"}),
                style={"padding": "4px 10px"},
            ),
        ]))

    table = dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, color="dark", hover=True, size="sm",
        className="lf-table align-middle",
    )

    return html.Div([
        table,
        html.Small(f"{len(prospects)} prospect{'s' if len(prospects) > 1 else ''} dans ce groupe", className="text-muted"),
    ])


# ── Callbacks ────────────────────────────────────────────────────────

def register_callbacks(app):

    # Toggle formulaire nouveau groupe
    @app.callback(
        Output("pr-collapse-new-group", "is_open"),
        Output("pr-collapse-rename", "is_open", allow_duplicate=True),
        Input("pr-btn-new-group", "n_clicks"),
        Input("pr-btn-cancel-group", "n_clicks"),
        State("pr-collapse-new-group", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_new_group(n_open, n_cancel, is_open):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update
        btn = ctx.triggered[0]["prop_id"]
        if "pr-btn-new-group" in btn:
            return not is_open, False
        return False, False

    # Créer un groupe
    @app.callback(
        Output("pr-group-select", "options"),
        Output("pr-group-select", "value"),
        Output("pr-collapse-new-group", "is_open", allow_duplicate=True),
        Output("pr-new-group-name", "value"),
        Output("pr-trigger", "data"),
        Output("pr-feedback", "children", allow_duplicate=True),
        Output("pr-feedback", "color", allow_duplicate=True),
        Output("pr-feedback", "is_open", allow_duplicate=True),
        Input("pr-btn-create-group", "n_clicks"),
        State("pr-new-group-name", "value"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def create_group(n, name, trigger):
        if not name or not name.strip():
            return no_update, no_update, no_update, no_update, no_update, "Saisis un nom de groupe.", "warning", True
        gid = add_group(name)
        groups = get_groups()
        opts = [{"label": g["name"], "value": g["id"]} for g in groups]
        return opts, gid, False, "", trigger + 1, f"Groupe « {name.strip()} » créé.", "success", True

    # Toggle formulaire renommer
    @app.callback(
        Output("pr-collapse-rename", "is_open"),
        Output("pr-rename-input", "value"),
        Output("pr-collapse-new-group", "is_open", allow_duplicate=True),
        Input("pr-btn-rename", "n_clicks"),
        Input("pr-btn-rename-cancel", "n_clicks"),
        State("pr-collapse-rename", "is_open"),
        State("pr-group-select", "value"),
        prevent_initial_call=True,
    )
    def toggle_rename(n_rename, n_cancel, is_open, gid):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update
        btn = ctx.triggered[0]["prop_id"]
        if "pr-btn-rename-cancel" in btn:
            return False, "", False
        if not gid:
            return False, "", False
        groups = get_groups()
        current_name = next((g["name"] for g in groups if g["id"] == gid), "")
        return not is_open, current_name, False

    # Valider renommage
    @app.callback(
        Output("pr-group-select", "options", allow_duplicate=True),
        Output("pr-collapse-rename", "is_open", allow_duplicate=True),
        Output("pr-trigger", "data", allow_duplicate=True),
        Output("pr-feedback", "children", allow_duplicate=True),
        Output("pr-feedback", "color", allow_duplicate=True),
        Output("pr-feedback", "is_open", allow_duplicate=True),
        Input("pr-btn-rename-confirm", "n_clicks"),
        State("pr-group-select", "value"),
        State("pr-rename-input", "value"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def confirm_rename(n, gid, new_name, trigger):
        if not gid or not new_name or not new_name.strip():
            return no_update, no_update, no_update, "Saisis un nom valide.", "warning", True
        rename_group(gid, new_name)
        groups = get_groups()
        opts = [{"label": g["name"], "value": g["id"]} for g in groups]
        return opts, False, trigger + 1, f"Groupe renommé en « {new_name.strip()} ».", "success", True

    # Ouvrir modal suppression groupe
    @app.callback(
        Output("pr-delete-modal", "is_open"),
        Output("pr-delete-modal-body", "children"),
        Output("pr-pending-delete-gid", "data"),
        Input("pr-btn-delete-group", "n_clicks"),
        Input("pr-btn-delete-cancel", "n_clicks"),
        State("pr-group-select", "value"),
        prevent_initial_call=True,
    )
    def toggle_delete_modal(n_delete, n_cancel, gid):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update
        btn = ctx.triggered[0]["prop_id"]
        if "pr-btn-delete-cancel" in btn:
            return False, "", None
        if not gid:
            return False, "", None
        groups = get_groups()
        group = next((g for g in groups if g["id"] == gid), None)
        if not group:
            return False, "", None
        n = len(group["prospects"])
        msg = f"Supprimer le groupe « {group['name']} » et ses {n} prospect{'s' if n != 1 else ''} ?"
        return True, msg, gid

    # Confirmer suppression groupe
    @app.callback(
        Output("pr-group-select", "options", allow_duplicate=True),
        Output("pr-group-select", "value", allow_duplicate=True),
        Output("pr-delete-modal", "is_open", allow_duplicate=True),
        Output("pr-trigger", "data", allow_duplicate=True),
        Output("pr-feedback", "children", allow_duplicate=True),
        Output("pr-feedback", "color", allow_duplicate=True),
        Output("pr-feedback", "is_open", allow_duplicate=True),
        Input("pr-btn-delete-confirm", "n_clicks"),
        State("pr-pending-delete-gid", "data"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def confirm_delete_group(n, gid, trigger):
        if not gid:
            return no_update, no_update, False, no_update, no_update, no_update, no_update
        delete_group(gid)
        groups = get_groups()
        opts = [{"label": g["name"], "value": g["id"]} for g in groups]
        new_val = groups[0]["id"] if groups else None
        return opts, new_val, False, trigger + 1, "Groupe supprimé.", "warning", True

    # Mettre à jour les notes (debounced input)
    @app.callback(
        Output("pr-trigger", "data", allow_duplicate=True),
        Input({"type": "pr-notes-input", "gid": ALL, "idx": ALL}, "value"),
        State({"type": "pr-notes-input", "gid": ALL, "idx": ALL}, "id"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def save_notes(values, ids, trigger):
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        import json as _json
        changed = False
        # On identifie le champ modifié par SON prop_id (et non par sa position
        # dans ctx.triggered, qui ne contient que les inputs réellement changés)
        # — sinon la note d'un prospect est écrite sur un autre.
        for triggered in ctx.triggered:
            if triggered.get("value") is None:
                continue
            id_str = triggered["prop_id"].rsplit(".", 1)[0]  # retire le ".value" final
            try:
                id_dict = _json.loads(id_str)
            except Exception:
                continue
            update_notes(id_dict["gid"], id_dict["idx"], triggered["value"])
            changed = True
        return trigger + 1 if changed else no_update

    # Supprimer un prospect
    @app.callback(
        Output("pr-trigger", "data", allow_duplicate=True),
        Output("pr-feedback", "children", allow_duplicate=True),
        Output("pr-feedback", "color", allow_duplicate=True),
        Output("pr-feedback", "is_open", allow_duplicate=True),
        Input({"type": "pr-delete-prospect-btn", "gid": ALL, "idx": ALL}, "n_clicks"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def delete_prospect(n_clicks_list, trigger):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update, no_update
        triggered = ctx.triggered[0]
        if not triggered["value"]:
            return no_update, no_update, no_update, no_update
        import json as _json
        id_str = triggered["prop_id"].replace(".n_clicks", "")
        try:
            id_dict = _json.loads(id_str)
        except Exception:
            return no_update, no_update, no_update, no_update
        remove_prospect(id_dict["gid"], id_dict["idx"])
        return trigger + 1, "Prospect supprimé.", "secondary", True

    # Déplacer un prospect
    @app.callback(
        Output("pr-trigger", "data", allow_duplicate=True),
        Output("pr-feedback", "children", allow_duplicate=True),
        Output("pr-feedback", "color", allow_duplicate=True),
        Output("pr-feedback", "is_open", allow_duplicate=True),
        Input({"type": "pr-move-btn", "gid": ALL, "idx": ALL, "to": ALL}, "n_clicks"),
        State("pr-trigger", "data"),
        prevent_initial_call=True,
    )
    def move_prospect_cb(n_clicks_list, trigger):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update, no_update
        triggered = ctx.triggered[0]
        if not triggered["value"]:
            return no_update, no_update, no_update, no_update
        import json as _json
        id_str = triggered["prop_id"].replace(".n_clicks", "")
        try:
            id_dict = _json.loads(id_str)
        except Exception:
            return no_update, no_update, no_update, no_update
        groups = get_groups()
        to_name = next((g["name"] for g in groups if g["id"] == id_dict["to"]), "?")
        move_prospect(id_dict["gid"], id_dict["idx"], id_dict["to"])
        return trigger + 1, f"Prospect déplacé vers « {to_name} ».", "info", True

    # Afficher le tableau du groupe sélectionné
    @app.callback(
        Output("pr-table-container", "children"),
        Input("pr-group-select", "value"),
        Input("pr-trigger", "data"),
    )
    def update_table(gid, _trigger):
        if not gid:
            return html.P("Aucun groupe — crée-en un pour commencer.", className="text-muted mt-3")
        groups = get_groups()
        return _build_table(gid, groups)

    # Export Excel du groupe
    @app.callback(
        Output("pr-download-excel", "data"),
        Input("pr-btn-export", "n_clicks"),
        State("pr-group-select", "value"),
        prevent_initial_call=True,
    )
    def export_group_excel(n, gid):
        if not gid:
            return no_update
        groups = get_groups()
        group = next((g for g in groups if g["id"] == gid), None)
        if not group or not group["prospects"]:
            return no_update

        export_cols = ["Nom", "Localisation", "Téléphone", "Note", "Avis", "Site web", "Google Maps", "notes", "added_at"]
        rows = []
        for p in group["prospects"]:
            rows.append({c: p.get(c, "") for c in export_cols})
        df = pd.DataFrame(rows)
        df = df.rename(columns={"notes": "Notes perso", "added_at": "Ajouté le"})

        buf = io.BytesIO()
        safe_name = re.sub(r'[\\/*?:\[\]]', '_', group["name"])
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=safe_name[:31])
            ws = writer.sheets[safe_name[:31]]
            for col_cells in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col_cells), default=10)
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)
        filename = f"prospects_{safe_name}.xlsx"
        return dcc.send_bytes(buf.getvalue(), filename)
