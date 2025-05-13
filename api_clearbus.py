import csv
from datetime import datetime
import os
import re
import shutil
import subprocess
from flask import Flask, abort, request, jsonify, send_file
import xml.etree.ElementTree as ET
from PyPDF2 import PdfMerger
from PyPDF2.errors import PdfReadError
from urllib.parse import urlparse
import requests
from zipfile import ZipFile
import io
import shutil
import xml.etree.ElementTree as ET
from flask import jsonify
import glob
from storageid import enregistrer_envoi_csv  # ➕ à importer en haut


app = Flask(__name__)
UPLOAD_DIR = "/app/courriers"
CSV_PATH = os.path.join(UPLOAD_DIR, "historique_envois.csv")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Récupérer le chemin absolu du script

# 📌 Configuration directe avec l'URL et les chemins fixes
CONFIG = {
    "API_URL": "http://127.0.0.1:5000",  # URL de l'API
    "UPLOAD_FOLDER": "/app/courriers",
    "LOG_FILE": "traces.log",   
    "ACLIC_BIN": "/usr/local/bin/aClic",
    "TOTP_BIN": "/usr/local/bin/calculerTOTP",
    "CLEF_SECRETE_TOTP": "HVOAYKQY4EDZW==="  
}

ARCHIVE_FOLDER = os.path.join(CONFIG["UPLOAD_FOLDER"], "archives")
os.makedirs(ARCHIVE_FOLDER, exist_ok=True)
ENVOYES_FOLDER = os.path.join(CONFIG["UPLOAD_FOLDER"], "envoyes")
AVEC_AR_FOLDER = os.path.join(CONFIG["UPLOAD_FOLDER"], "avec_ar")
os.makedirs(ENVOYES_FOLDER, exist_ok=True)
os.makedirs(AVEC_AR_FOLDER, exist_ok=True)


# 📌 Assurer l'existence du dossier `courriers`
os.makedirs(CONFIG["UPLOAD_FOLDER"], exist_ok=True)


def enregistrer_envoi_csv(facture_id, pli_id, date_envoi):
    fichier_existe = os.path.exists(CSV_PATH)

    with open(CSV_PATH, mode="a", newline="") as fichier:
        writer = csv.writer(fichier)
        if not fichier_existe:
            writer.writerow(["facture_id", "pli_id", "date_envoi"])  # en-têtes

        writer.writerow([facture_id, pli_id, date_envoi])


def fusionner_pdfs(fichiers_pdf, chemin_sortie):
    merger = PdfMerger()
    for fichier in fichiers_pdf:
        try:
            print(f"🧩 Ajout de : {fichier}")
            merger.append(fichier)
        except PdfReadError:
            print(f"❌ Fichier illisible ou non-PDF ignoré : {fichier}")
        except Exception as e:
            print(f"⚠️ Erreur inattendue avec {fichier} : {str(e)}")
    merger.write(chemin_sortie)
    merger.close()


# 📌 Fonction pour générer un code TOTP
def calculer_totp():
    try:
        result = subprocess.run([CONFIG["TOTP_BIN"], CONFIG["CLEF_SECRETE_TOTP"]],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Erreur TOTP : {result.stderr}")
            return None
        return result.stdout.strip()
    except Exception as e:
        print(f"Erreur d'exécution de calculerTOTP : {str(e)}")
        return None


def telecharger_pieces_jointes_zapier(urls, dossier_destination=None):
    if dossier_destination is None:
        dossier_destination = CONFIG["UPLOAD_FOLDER"]

    os.makedirs(dossier_destination, exist_ok=True)
    fichiers_sauvegardes = []

    def is_zip_file(content):
        return content[:4] == b'PK\x03\x04'

    for i, url in enumerate(urls):
        try:
            response = requests.get(url)
            print(f"⬇️ Téléchargement depuis : {url}")
            response.raise_for_status()

            content = response.content

            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path) or f"piece_jointe_{i+1}"

            if is_zip_file(content):
                print(f"📦 ZIP détecté : {filename}")
                with ZipFile(io.BytesIO(content)) as zip_file:
                    entries = zip_file.namelist()
                    print(f"📦 Contenu ZIP : {entries}")

                    for name in entries:
                        if not name.lower().endswith(".pdf"):
                            print(f"❌ Ignoré (non-PDF) : {name}")
                            continue

                        # Lire et vérifier contenu
                        with zip_file.open(name) as source:
                            pdf_bytes = source.read()
                            if not pdf_bytes:
                                print(f"⚠️ Fichier vide ignoré : {name}")
                                continue

                            safe_name = f"{i+1}_{os.path.basename(name)}"
                            dest_path = os.path.join(dossier_destination, safe_name)

                            with open(dest_path, "wb") as out_file:
                                out_file.write(pdf_bytes)
                                fichiers_sauvegardes.append(safe_name)
                                print(f"✅ PDF extrait : {safe_name}")
            else:
                # Cas direct (PDF hors zip)
                if not filename.endswith(".pdf"):
                    filename = f"piece_jointe_{i + 1}.pdf"

                dest_path = os.path.join(dossier_destination, filename)
                with open(dest_path, "wb") as f:
                    f.write(content)
                fichiers_sauvegardes.append(filename)
                print(f"✅ Fichier PDF enregistré : {filename}")

        except Exception as e:
            print(f"❌ Erreur URL {url} : {e}")
            fichiers_sauvegardes.append(f"Erreur: {str(e)}")

    if not fichiers_sauvegardes or all(f.startswith("Erreur") for f in fichiers_sauvegardes):
        raise Exception("Aucune pièce jointe PDF valide téléchargée.")

    return fichiers_sauvegardes



def traiter_accuse_reception(numero, numeroparent):
    """
    Fusionne le PDF d'origine (dans envoyes/) avec l'AR reçu (fichier nommé AR_<numero>.pdf),
    puis déplace le résultat dans avec_ar/
    """
    ar_filename = f"AR_{numero}.pdf"
    ar_path = os.path.join(CONFIG["UPLOAD_FOLDER"], ar_filename)
    
    # Trouver le PDF d'origine
    dossier_base = f"courrier_{numeroparent}.pdf"
    origine_path = os.path.join(ENVOYES_FOLDER, dossier_base)

    if not os.path.exists(ar_path):
        print(f"⚠️ AR non trouvé : {ar_path}")
        return f"AR introuvable : {ar_filename}"

    if not os.path.exists(origine_path):
        print(f"⚠️ Courrier d'origine non trouvé : {origine_path}")
        return f"Courrier introuvable : {dossier_base}"

    try:
        fusion_path = os.path.join(AVEC_AR_FOLDER, f"{numeroparent}_avec_ar.pdf")
        fusionner_pdfs([origine_path, ar_path], fusion_path)

        print(f"✅ Fusion terminée : {fusion_path}")
        return f"Fusion réussie pour {numeroparent}"

    except Exception as e:
        print(f"❌ Erreur fusion AR : {e}")
        return f"Erreur : {str(e)}"


# 📌 1️⃣ Vérifier que l'API tourne
@app.route("/health/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "message": "L'API est en ligne"})

# 📌 2️⃣ Voir la configuration actuelle
@app.route("/config/", methods=["GET"])
def config_api():
    return jsonify({"status": "success", "config": CONFIG})


@app.route("/telecharger-ar/<numeroparent>", methods=["GET"])
def telecharger_ar(numeroparent):
    filename = f"AR_{numeroparent}.pdf"
    file_path = os.path.join("/app", numeroparent, filename)  # chemin absolu dans Docker

    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return abort(404, description="Fichier AR introuvable")


@app.route("/releve-abonne/", methods=["POST"])
def relever_abonne():
    data = request.get_json()
    identifiant = data.get("identifiant")
    motdepasse = data.get("mdp")

    if not identifiant or not motdepasse:
        return jsonify({"status": "error", "message": "Identifiant et mot de passe requis"}), 400

    xml_entree_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "relever_abonne.xml")
    sortie_xml_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "sortie_releve.xml")
    archive_dir = os.path.join(CONFIG["UPLOAD_FOLDER"], "archives")
    os.makedirs(archive_dir, exist_ok=True)

    # 📄 Génération dynamique du XML d’entrée
    xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<clearbus>
  <session>
    <service>relever_abonne</service>
    <identifiant>{identifiant}</identifiant>
    <motdepasse>{motdepasse}</motdepasse>
  </session>
  <xml>
    <sortie>{sortie_xml_path}</sortie>
  </xml>
  <traces>
    <activer>oui</activer>
  </traces>
</clearbus>
"""
    with open(xml_entree_path, "w") as f:
        f.write(xml_content)

    try:
        # 🔁 Exécuter aClic
        command = [
            CONFIG["ACLIC_BIN"],
            f"xml_entree={xml_entree_path}",
            f"xml_sortie={sortie_xml_path}"
        ]
        subprocess.run(command, capture_output=True, text=True)

        if not os.path.exists(sortie_xml_path):
            return jsonify({"status": "error", "message": "Fichier de sortie non trouvé"}), 500

        # 📂 Rechercher les fichiers AR générés dans /app/
        dossiers_clearbus = glob.glob("/app/[0-9]*")
        accuses = []

        for dossier in dossiers_clearbus:
            fichiers = os.listdir(dossier)
            for fichier in fichiers:
                if fichier.startswith("AR_") and fichier.endswith(".pdf"):
                    src_path = os.path.join(dossier, fichier)
                    dst_path = os.path.join(archive_dir, fichier)

                    try:
                        shutil.copy(src_path, dst_path)
                        accuses.append({
                            "numero": fichier.split("_")[1].replace(".pdf", ""),
                            "type": "accuse_de_reception",
                            "fichier_original": src_path,
                            "copie_archivee": dst_path,
                            "etat_copie": "copié"
                        })
                    except Exception as e:
                        accuses.append({
                            "fichier": fichier,
                            "etat_copie": f"erreur: {str(e)}",
                            "copie_archivee": None
                        })

        return jsonify({
            "status": "success",
            "message": "Accusés de réception relevés et copiés",
            "accuses": accuses,
            "identifiant": identifiant
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 📌 4️⃣ Envoyer un email avec aClic
@app.route("/envoyer-email/", methods=["POST"])
def envoyer_email():
    data = request.json

    # Champs requis
    factureid = data.get("factureid")
    destinataire = data.get("destinataire")
    nom = data.get("nom")       
    adresseL1 = data.get("adresseL1")
    commune = data.get("commune")
    codepostal = data.get("codepostal")
    contenu = data.get("contenu", "")
    piecesjointes_urls = data.get("piecesjointes", [])
    mot_de_passe = data.get("mdp")
    identifiant = data.get("identifiant")

    if isinstance(piecesjointes_urls, str):
        piecesjointes_urls = [piecesjointes_urls]

    if not all([factureid, destinataire, nom, adresseL1, commune, codepostal]):
        return jsonify({
            "status": "error",
            "message": "Les champs 'factureid', 'destinataire', 'nom', 'adresseL1', 'commune',  'codepostal', 'identifiant' et 'mdp' sont obligatoires."
        }), 400

    piecesjointes = telecharger_pieces_jointes_zapier(piecesjointes_urls)
    print(f"✅ Pièces jointes téléchargées : {piecesjointes}")

    fichiers_pdf = [os.path.join(CONFIG["UPLOAD_FOLDER"], f) for f in piecesjointes]
    courrier_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "courrier.pdf")
    fusionner_pdfs(fichiers_pdf, courrier_path)

    xml_file_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "signer_et_envoyer.xml")
    sortie_xml_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "sortie.xml")
    archive_dir = os.path.join(CONFIG["UPLOAD_FOLDER"], "archives")
    os.makedirs(archive_dir, exist_ok=True)

    if os.path.exists(sortie_xml_path):
        os.remove(sortie_xml_path)

    totp_code = calculer_totp()
    if not totp_code:
        return jsonify({"status": "error", "message": "Erreur lors du calcul du code TOTP"}), 500

    xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<clearbus>
  <session>
    <service>signer_et_envoyer</service>
    <identifiant>{identifiant}</identifiant>
    <motdepasse>{mot_de_passe}</motdepasse>
    <code>{totp_code}</code>
  </session>
  <destinataire>
    <categorie>professionnel</categorie>
    <entreprise>{nom}</entreprise>
    <civilite>Monsieur</civilite>
    <adresseL1>{adresseL1}</adresseL1>
    <commune>{commune}</commune>
    <codepostal>{codepostal}</codepostal>
    <email>{destinataire}</email>
    <tel_principal>+33 1 23 45 67 89</tel_principal>
  </destinataire>
  <enveloppe>
    <niveaudeservice>recommandeAR</niveaudeservice>
    <courrier>{courrier_path}</courrier>
  </enveloppe>
  <xml>
    <sortie>{sortie_xml_path}</sortie>
  </xml>
  <meta>
   <description>Email envoyé depuis l'API en recommandé</description>
  </meta>
  <traces>
    <activer>oui</activer>
  </traces>
</clearbus>"""

    with open(xml_file_path, "w") as xml_file:
        xml_file.write(xml_content)

    try:
        result = subprocess.run([CONFIG["ACLIC_BIN"], f"xml_entree={xml_file_path}"],
                                capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "message": f"aClic a retourné une erreur : {result.stderr}"
            }), 500

        if os.path.exists(sortie_xml_path):
            with open(sortie_xml_path, "r") as file:
                xml_result = file.read()


            reponse_node = ET.fromstring(xml_result)
            root = reponse_node.find("reponse")

            pli_id = root.find("numero").text if root.find("numero") is not None else "Inconnu"
            date_envoi = root.find("date").text if root.find("date") is not None else "Inconnue"

            # ✅ Sauvegarde CSV locale
            enregistrer_envoi_csv(factureid, pli_id, date_envoi)

            reponse = {
                "statut": root.find("reussi").text,
                "service": root.find("service").text,
                "reference": pli_id,
                "date_envoi": date_envoi,
                "xml-content": xml_content,
            }

            return jsonify({"status": "success", "message": "Email envoyé avec succès", "reponse": reponse})

        else:
            return jsonify({"status": "error", "message": "Fichier de sortie non trouvé"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def is_zip_file(content):
    return content[:4] == b'PK\x03\x04'


@app.route("/zapier-mail/", methods=["POST"])
def recevoir_email_test_zapier():
    logs = []  # pour collecter tous les logs
    try:
        json_body = request.get_json(silent=True)
        print("📨 Données reçues depuis Zapier")

        piecesjointes_urls = json_body.get("piecesjointes", [])
        if isinstance(piecesjointes_urls, str):
            piecesjointes_urls = [piecesjointes_urls]

        print(f"🔗 URLs de pièces jointes reçues : {piecesjointes_urls}")

        # Télécharger les fichiers
        fichiers_telecharges = telecharger_pieces_jointes_zapier(piecesjointes_urls)
        print(f"✅ Fichiers téléchargés / extraits : {fichiers_telecharges}")

        # Générer un PDF fusionné
        fichiers_pdf = [os.path.join(CONFIG["UPLOAD_FOLDER"], f) for f in fichiers_telecharges if f.endswith(".pdf")]
        print(f"📄 Fichiers PDF à fusionner : {fichiers_pdf}")
        fusion_path = os.path.join(CONFIG["UPLOAD_FOLDER"], "fusion_test.pdf")

        if fichiers_pdf:
            fusionner_pdfs(fichiers_pdf, fusion_path)
            print(f"📎 Fusion terminée dans : {fusion_path}")
        else:
            print("⚠️ Aucun fichier PDF valide à fusionner")

        return jsonify({
            "status": "success",
            "message": "Test de téléchargement et fusion réussi",
            "fichiers_telecharges": fichiers_telecharges,
            "fusion_pdf": fusion_path if fichiers_pdf else None,
            "logs": logs
        }), 200

    except Exception as e:
        logs.append(f"❌ Erreur inattendue : {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Erreur pendant le traitement",
            "logs": logs
        }), 500


@app.route("/historique-envois/", methods=["GET"])
def historique_envois():
    with open("historique_envois.csv") as f:
        reader = csv.DictReader(f)
        return jsonify(list(reader))


# # 📌 Lancer l'API
# if __name__ == "__main__":
#     app.run(debug=True, host="0.0.0.0", port=5000)
#     print("API Clearbus démarrée...")
