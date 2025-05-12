import csv
import os

UPLOAD_DIR = "/app/courriers"
CSV_PATH = os.path.join(UPLOAD_DIR, "historique_envois.csv")


def enregistrer_envoi_csv(facture_id, pli_id, date_envoi):
    fichier_existe = os.path.exists(CSV_PATH)

    with open(CSV_PATH, mode="a", newline="") as fichier:
        writer = csv.writer(fichier)
        if not fichier_existe:
            writer.writerow(["facture_id", "pli_id", "date_envoi"])  # en-têtes

        writer.writerow([facture_id, pli_id, date_envoi])
