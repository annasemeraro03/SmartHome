#!/bin/bash

# -----------------------------
# START SCRIPT PER FLASK + POSTGRES
# -----------------------------

# Controllo Python
if ! command -v python3 &> /dev/null 
then
    echo "Python3 non trovato. Installa python3-full e python3-venv prima di continuare."
    exit 1
fi

# Creazione virtual environment solo se non esiste
if [ ! -d "venv" ]; then
    echo -e "\033[1;32m>> Creating virtual environment...\033[0m"
    python3 -m venv venv
fi

# Attivazione venv
echo -e "\033[1;32m>> Activating virtual environment...\033[0m"
source venv/bin/activate

# Aggiornamento pip e installazione requirements
echo -e "\033[1;32m>> Installing Python packages...\033[0m"
#pip install --upgrade pip
pip install -r requirements.txt --quiet

# Avvio server Flask
echo -e "\033[1;32m>> Starting Flask server...\033[0m"
export FLASK_APP=app.py
export FLASK_ENV=development
echo -e "\033[1;32m>> Flask server is running. Open your browser at http://localhost:5000\033[0m"
flask run --host=127.0.0.1 --port=5000