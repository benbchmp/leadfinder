#!/bin/bash
# LeadFinder – Script de lancement automatique

set -e

echo "==============================="
echo "   LeadFinder – Démarrage"
echo "==============================="
echo ""

# 1. Vérifier que Python 3 est installé
if command -v python3 &>/dev/null; then
    PY=python3
    PIP=pip3
elif command -v python &>/dev/null; then
    PY=python
    PIP=pip
else
    echo "ERREUR : Python 3 n'est pas installé sur ce Mac."
    echo ""
    echo "Pour l'installer :"
    echo "  1. Va sur https://www.python.org/downloads/"
    echo "  2. Télécharge la dernière version pour Mac"
    echo "  3. Installe-la, puis relance ce script"
    echo ""
    exit 1
fi

echo "Python trouvé : $($PY --version)"
echo ""

# 2. Vérifier que le fichier .env existe
if [ ! -f .env ]; then
    echo "ERREUR : Le fichier .env est manquant."
    echo ""
    echo "Pour le créer :"
    echo "  1. Copie le fichier .env.example et renomme-le en .env"
    echo "  2. Remplace COLLE_TA_CLE_GOOGLE_ICI par ta vraie clé Google API"
    echo ""
    exit 1
fi

echo "Fichier .env trouvé."
echo ""

# 3. Créer / activer un environnement isolé (.venv)
#    Évite de polluer le Python du Mac et contourne le blocage
#    "externally-managed-environment" rencontré sur certains Mac.
if [ ! -d ".venv" ]; then
    echo "Création de l'environnement isolé (première fois)..."
    $PY -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 4. Installer les dépendances (dans le .venv)
echo "Installation des dépendances (peut prendre 1-2 minutes la première fois)..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
echo "Dépendances OK."
echo ""

# 5. Lancer l'application
PORT=8060
echo "Lancement de LeadFinder sur http://127.0.0.1:$PORT"
echo "Pour arrêter : appuie sur Ctrl+C dans ce terminal"
echo ""

# 6. Ouvrir le navigateur DÈS QUE le serveur répond (max ~30s d'attente).
#    Évite la page "connexion impossible" sur un Mac lent : on attend que
#    le serveur soit prêt au lieu d'ouvrir aveuglément après 2 secondes.
(
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT"; then break; fi
    sleep 1
  done
  open "http://127.0.0.1:$PORT"
) &

# 7. Démarrer le serveur
python app.py
