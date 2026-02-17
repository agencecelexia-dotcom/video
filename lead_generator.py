#!/usr/bin/env python3
"""
Générateur de leads CSV — Sociétés < 6 mois sans site web
Niches : Artisans du bâtiment, Beauté/Coiffure/Bien-être
Source : API SIRENE (INSEE)
"""

import csv
import requests
import socket
import time
import sys
from datetime import datetime, timedelta

# ─── Configuration ───────────────────────────────────────────────────────────
API_KEY = "fb76cf7e-e820-461a-b6cf-7ee820d61a92"
BASE_URL = "https://api.insee.fr/api-sirene/3.11"

# Date limite : 6 mois en arrière
DATE_LIMIT = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

# Niches et leurs codes NAF associés
NICHES = {
    "Artisan Bâtiment": [
        "43.21A",  # Installation électrique
        "43.22A",  # Installation eau et gaz
        "43.22B",  # Installation thermique/clim
        "43.34Z",  # Peinture et vitrerie
        "43.31Z",  # Plâtrerie
        "43.32A",  # Menuiserie bois/PVC
        "43.32B",  # Menuiserie métallique/serrurerie
        "43.33Z",  # Revêtement sols et murs
        "43.39Z",  # Autres travaux de finition
        "43.91B",  # Couverture
        "43.99C",  # Maçonnerie générale
        "43.29A",  # Travaux d'isolation
        "43.12A",  # Terrassement
    ],
    "Beauté / Coiffure / Bien-être": [
        "96.02A",  # Coiffure
        "96.02B",  # Soins de beauté
        "96.04Z",  # Entretien corporel
    ],
}

OUTPUT_FILE = "leads.csv"
MAX_PER_NICHE = 200  # nombre max de résultats par niche


# ─── Fonctions ───────────────────────────────────────────────────────────────

def get_headers():
    return {
        "X-INSEE-Api-Key-Integration": API_KEY,
        "Accept": "application/json",
    }


def build_naf_query(naf_codes):
    """Construit la partie requête pour les codes NAF."""
    parts = [f'activitePrincipaleUniteLegale:"{code}"' for code in naf_codes]
    return "(" + " OR ".join(parts) + ")"


def search_sirene(naf_codes, cursor="*"):
    """Interroge l'API SIRENE pour trouver les entreprises récentes."""
    naf_filter = build_naf_query(naf_codes)
    date_filter = f'dateCreationUniteLegale:[{DATE_LIMIT} TO *]'
    # Uniquement les établissements actifs (siège) et diffusables
    active_filter = 'etablissementSiege:true AND etatAdministratifUniteLegale:A AND statutDiffusionUniteLegale:O'

    query = f"{naf_filter} AND {date_filter} AND {active_filter}"

    params = {
        "q": query,
        "nombre": 100,
        "curseur": cursor,
    }

    try:
        resp = requests.get(
            f"{BASE_URL}/siret",
            headers=get_headers(),
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            print("ERREUR 401 : Clé API invalide ou expirée.")
            print("Vérifie ta clé sur https://api.insee.fr")
            sys.exit(1)
        elif resp.status_code == 403:
            print("ERREUR 403 : Accès refusé. Vérifie ton abonnement à l'API Sirene.")
            sys.exit(1)
        elif resp.status_code == 429:
            print("Trop de requêtes, pause de 5 secondes...")
            time.sleep(5)
            return search_sirene(naf_codes, cursor)
        elif resp.status_code != 200:
            print(f"Erreur API : {resp.status_code} — {resp.text[:300]}")
            return [], None

        data = resp.json()
        etablissements = data.get("etablissements", [])
        next_cursor = data.get("header", {}).get("curseurSuivant")

        return etablissements, next_cursor

    except requests.exceptions.RequestException as e:
        print(f"Erreur réseau : {e}")
        return [], None


def has_website(company_name):
    """Vérifie simplement si un domaine évident existe pour cette société."""
    if not company_name:
        return False

    # Nettoie le nom pour en faire un domaine potentiel
    clean = company_name.lower().strip()
    clean = clean.replace(" ", "").replace("'", "").replace("-", "")
    clean = clean.replace("è", "e").replace("é", "e").replace("ê", "e")
    clean = clean.replace("à", "a").replace("â", "a")
    clean = clean.replace("ô", "o").replace("ù", "u").replace("î", "i")
    clean = clean.replace("ç", "c")

    # Domaines à tester
    domains = [f"{clean}.fr", f"{clean}.com"]

    for domain in domains:
        try:
            socket.setdefaulttimeout(1)
            socket.gethostbyname(domain)
            return True  # Le domaine existe
        except (socket.gaierror, socket.timeout, OSError):
            continue

    return False


def extract_lead(etab, niche_name):
    """Extrait les infos utiles d'un établissement SIRENE."""
    ul = etab.get("uniteLegale", {})
    adresse = etab.get("adresseEtablissement", {})
    periodes_ul = ul.get("periodesUniteLegale", [{}])
    periode = periodes_ul[0] if periodes_ul else {}

    # Personne physique (entrepreneur individuel)
    prenom = ul.get("prenomUsuelUniteLegale") or ul.get("prenom1UniteLegale", "") or ""
    nom = ul.get("nomUniteLegale", "") or ""

    # Nom de la société (denomination ou nom usuel)
    denomination = (
        periode.get("denominationUniteLegale")
        or periode.get("denominationUsuelle1UniteLegale")
        or ul.get("denominationUniteLegale")
        or f"{prenom} {nom}".strip()
    )

    # Adresse complète
    rue = " ".join(filter(None, [
        adresse.get("numeroVoieEtablissement"),
        adresse.get("typeVoieEtablissement"),
        adresse.get("libelleVoieEtablissement"),
    ]))
    code_postal = adresse.get("codePostalEtablissement", "")
    ville = adresse.get("libelleCommuneEtablissement", "")
    adresse_complete = f"{rue}, {code_postal} {ville}".strip(", ")

    # SIRET et date de création
    siret = etab.get("siret", "")
    date_creation = ul.get("dateCreationUniteLegale", "")

    # Code NAF
    naf = periode.get("activitePrincipaleUniteLegale", "")

    return {
        "prenom": prenom,
        "nom": nom,
        "nom_societe": denomination,
        "niche": niche_name,
        "code_naf": naf,
        "telephone": "",  # pas dispo directement via SIRENE
        "email": "",      # pas dispo directement via SIRENE
        "adresse": adresse_complete,
        "code_postal": code_postal,
        "ville": ville,
        "date_creation": date_creation,
        "siret": siret,
    }


def main():
    print("=" * 60)
    print("  GÉNÉRATEUR DE LEADS — Sociétés < 6 mois sans site web")
    print("=" * 60)
    print(f"Date limite : créées après le {DATE_LIMIT}")
    print(f"Niches : {', '.join(NICHES.keys())}")
    print()

    all_leads = []

    for niche_name, naf_codes in NICHES.items():
        print(f"[→] Recherche : {niche_name} ({len(naf_codes)} codes NAF)...")

        collected = []
        cursor = "*"
        page = 0

        while len(collected) < MAX_PER_NICHE:
            page += 1
            print(f"    Page {page}...", end=" ", flush=True)

            etabs, next_cursor = search_sirene(naf_codes, cursor)

            if not etabs:
                print("aucun résultat.")
                break

            print(f"{len(etabs)} établissements trouvés.", flush=True)

            for etab in etabs:
                if len(collected) >= MAX_PER_NICHE:
                    break

                lead = extract_lead(etab, niche_name)

                # Ignorer les entrées sans nom exploitable
                if not lead["nom_societe"] or lead["nom_societe"] == "[ND]":
                    continue

                # Ignorer les entrées sans prénom/nom (données incomplètes)
                if not lead["prenom"] and not lead["nom"] and not lead["nom_societe"]:
                    continue

                # Vérification : pas de site web détecté
                print(f"    [{len(collected)+1}/{MAX_PER_NICHE}] {lead['nom_societe'][:45]}...", end=" ", flush=True)
                if has_website(lead["nom_societe"]):
                    print("site detecte, skip.")
                    continue
                else:
                    print("OK")

                collected.append(lead)

            # Passer à la page suivante
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

            # Pause pour respecter les limites API
            time.sleep(0.5)

        print(f"    → {len(collected)} leads collectés pour {niche_name}")
        all_leads.extend(collected)

    # ─── Export CSV ───────────────────────────────────────────────────────
    if not all_leads:
        print("\n⚠️  Aucun lead trouvé. Vérifie ta clé API et ta connexion.")
        return

    fieldnames = [
        "prenom", "nom", "nom_societe", "niche", "code_naf",
        "telephone", "email", "adresse", "code_postal", "ville",
        "date_creation", "siret",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(all_leads)

    print()
    print("=" * 60)
    print(f"✅ {len(all_leads)} leads exportés dans '{OUTPUT_FILE}'")
    print("=" * 60)
    print()
    print("CONSEIL : Pour enrichir les numéros de téléphone et emails,")
    print("tu peux utiliser :")
    print("  - pagesjaunes.fr (recherche par SIRET/nom)")
    print("  - societe.com (infos publiques)")
    print("  - pappers.fr (données légales)")


if __name__ == "__main__":
    main()
