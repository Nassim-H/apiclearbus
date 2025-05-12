# 1️⃣ Image de base légère avec Python
FROM python:3.10-slim

# 2️⃣ Dossier de travail
WORKDIR /app

# 3️⃣ Dépendances système pour aClic
RUN apt update && apt install -y libssl-dev libicu-dev && rm -rf /var/lib/apt/lists/*

# 4️⃣ Copier requirements.txt d’abord pour profiter du cache Docker
COPY requirements.txt .

# 5️⃣ Installer les dépendances Python (upgrade pip et install requirements)
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# 6️⃣ Copier le code applicatif
COPY api_clearbus.py .
COPY storageid.py .
COPY wsgi.py .

# 7️⃣ Vérifier gunicorn (debug, optionnel — peut être retiré en prod stable)
RUN which gunicorn && gunicorn --version

# 8️⃣ Copier les binaires aClic
COPY aClic/aClic /usr/local/bin/aClic
COPY aClic/calculerTOTP /usr/local/bin/calculerTOTP

# 9️⃣ Copier les fichiers de config et certificats
COPY aClic/config /usr/local/bin/config
COPY aClic/config /app/config
COPY aClic/certs /app/certs

# 🔐 Donner les permissions d’exécution aux binaires
RUN chmod +x /usr/local/bin/aClic /usr/local/bin/calculerTOTP

# 🔁 Lancer Gunicorn au démarrage (4 workers, écoute sur le port 5000)
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "wsgi:app"]
