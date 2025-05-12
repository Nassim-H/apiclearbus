# 1️⃣ Utilisation d'une image Linux légère avec Python
FROM python:3.10-slim

# 2️⃣ Définition du dossier de travail
WORKDIR /app

# 3️⃣ Installation des dépendances système requises pour aClic
RUN apt update && apt install -y libssl-dev libicu-dev && rm -rf /var/lib/apt/lists/*

# 4️⃣ Copier l’API Flask
COPY api_clearbus.py .
COPY requirements.txt .
COPY storageid.py .

# 5️⃣ Copier `aClic` et `calculerTOTP`
COPY aClic/aClic /usr/local/bin/aClic
COPY aClic/calculerTOTP /usr/local/bin/calculerTOTP

# 6️⃣ Copier le dossier de config de `aClic`
COPY aClic/config /usr/local/bin/config
COPY aClic/config /app/config
COPY aClic/certs /app/certs

# 7️⃣ Attribution des permissions d’exécution
RUN chmod +x /usr/local/bin/aClic /usr/local/bin/calculerTOTP

# 8️⃣ Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# 9️⃣ Exécution de Flask au démarrage du conteneur
CMD ["python", "api_clearbus.py"]
