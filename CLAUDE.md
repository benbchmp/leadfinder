# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet
Outil interne de prospection B2B pour une activité de création/vente de sites web à des professionnels qui n'en ont pas encore.

## Rôles
- **L'utilisateur (Benjamin) n'est PAS développeur.** Il est le manager/product owner et décide de la direction du produit. Claude est le développeur. Toujours expliquer les choix techniques de manière accessible, proposer les meilleurs outils/intermédiaires possibles, et guider pas à pas pour tout ce qui touche au code, déploiement, infrastructure.

## Modèle par défaut
- Utiliser **Sonnet** (`sonnet`) par défaut pour toutes les tâches courantes (édition de code, debug, ajout de features, questions).
- Utiliser **Opus** (`opus`) uniquement pour la planification de tâches complexes (architecture, refactoring majeur, nouveaux modules importants).

## Stack
- **Framework**: Dash 4.0 (Python web framework with React frontend)
- **Backend**: Python 3.9+ (compatible with Mac deployment)
- **Data persistence**: JSON files (`prospects_data.json`) – not a database
- **APIs**: Google Places API (New) for lead search
- **Export**: Excel via openpyxl, CSV via pandas
- **UI**: Dash Bootstrap Components (DARKLY theme), Bootstrap Icons, Plotly charts

## Architecture

### Multi-page Routing
The app is a **single-page Dash application** with client-side routing using `dcc.Location`. All three pages are rendered in the DOM at startup with `display: none/block` to avoid flash/reload on navigation.

**Pages:**
- `leadfinder.py` – Search leads from Google Places API; supports filtering by activity/city, progress tracking, Excel export
- `prospects.py` – Watchlist organized by groups; data persisted in `prospects_data.json`
- `cold_calls.py` – Call tracking and analytics

Each page module exports:
- `layout()` – Returns the page's HTML/Dash component tree
- `register_callbacks(app)` – Registers Dash callbacks for that page

### Key Technical Details
- `app.py:threaded=True` – Required for progress bar tracking during long-running searches (Google API calls)
- `suppress_callback_exceptions=True` – Needed for multi-page layout pattern
- `dcc.Link` for navigation – Client-side navigation, no page refresh
- Progress tracking uses `threading` to run searches in background while updating UI via callback polling

### Data Persistence
- `prospects_data.json` – Stores prospect groups/records (flat JSON structure, no database)
  - Schema: `{"groups": [{id, name, prospects: [{id, name, phone, email, ...}]}]}`
  - Loaded/saved via `prospects.load_data()` / `prospects.save_data()`

## Development

### Run the app
```bash
python app.py
```
Starts on `http://localhost:8060` (configurable via `PORT` env var)

### Setup (first time)
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env: add GOOGLE_API_KEY (Google Places API key)
```

### Run on Mac (for distribution)
```bash
bash run.sh
```
This script handles venv setup, dependencies, and opens the browser automatically.

### Key Environment Variables
- `GOOGLE_API_KEY` – Required for Google Places API search
- `PORT` – Server port (default: 8060)

## Constraints
- **Python 3.9 compatibility** – Code must run on Python 3.9 (mac distribution requirement)
- **No database** – Use JSON files for persistence, not SQL/NoSQL
- **Lead data** – Search results are transient (not persisted); only prospects added to watchlist are kept
