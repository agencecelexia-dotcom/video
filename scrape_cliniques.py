#!/usr/bin/env python3
"""
Scraper de cliniques de chirurgie esthetique en France
Sources :
  1. Mappy / PagesJaunes API — recherche directe "chirurgie esthetique"
  2. Annuaire Entreprises API — dirigeants / medecins
  3. SIRENE API — donnees complementaires (SIRET, date creation)

Output : CSV avec nom_clinique, docteur, telephone, email, site_web, adresse, ville
"""

import csv
import requests
import time
import sys
import re
from datetime import datetime

# ─── Configuration ───────────────────────────────────────────────────────────
MAPPY_API_KEY = "f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z"
MAPPY_SEARCH_URL = "https://api-search.mappy.net/search/1.1/find"

OUTPUT_FILE = "cliniques_chirurgie_esthetique.csv"

# Termes de recherche pour maximiser les resultats
SEARCH_TERMS = [
    "chirurgie esthetique",
    "chirurgien esthetique",
    "clinique esthetique",
    "medecine esthetique",
    "chirurgie plastique",
    "chirurgien plasticien",
]

# Grandes villes et agglomerations francaises (la ou se trouvent les cliniques)
CITIES = [
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes",
    "Strasbourg", "Montpellier", "Bordeaux", "Lille", "Rennes",
    "Reims", "Saint-Etienne", "Toulon", "Le Havre", "Grenoble",
    "Dijon", "Angers", "Nimes", "Villeurbanne", "Clermont-Ferrand",
    "Le Mans", "Aix-en-Provence", "Brest", "Tours", "Amiens",
    "Limoges", "Perpignan", "Metz", "Besancon", "Orleans",
    "Rouen", "Caen", "Mulhouse", "Nancy", "Avignon",
    "Cannes", "Antibes", "La Rochelle", "Pau",
    "Neuilly-sur-Seine", "Boulogne-Billancourt", "Levallois-Perret",
    "Versailles", "Saint-Cloud", "Courbevoie",
]


# ─── Mappy / PagesJaunes ────────────────────────────────────────────────────

def mappy_search(query, city, max_results=20):
    """Recherche Mappy/PagesJaunes pour une requete + ville."""
    try:
        resp = requests.get(
            MAPPY_SEARCH_URL,
            params={
                "q": f"{query} {city}",
                "max_results": max_results,
                "favorite_country": 250,
                "language": "fr",
            },
            headers={
                "apikey": MAPPY_API_KEY,
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Origin": "https://fr.mappy.com",
                "Referer": "https://fr.mappy.com/",
            },
            timeout=15,
        )

        if resp.status_code == 429:
            print("    429 rate limit, pause 5s...", flush=True)
            time.sleep(5)
            return mappy_search(query, city, max_results)

        if resp.status_code != 200:
            return []

        return resp.json().get("pois", [])

    except (requests.exceptions.RequestException, ValueError):
        return []


def is_relevant_clinic(poi):
    """Verifie que le POI est bien lie a la chirurgie/medecine esthetique."""
    name = (poi.get("name") or "").lower()
    rubrics = " ".join([r.get("label", "") for r in poi.get("rubrics", [])]).lower()
    all_text = f"{name} {rubrics}"

    keywords = [
        "esthetique", "esth\u00e9tique", "plastique", "plasticien",
        "chirurgi", "beaute", "beaut\u00e9", "laser", "liposuccion",
        "rhinoplastie", "lifting", "botox", "injections",
        "medecin", "m\u00e9decin", "docteur", "clinique", "cabinet",
    ]

    return any(kw in all_text for kw in keywords)


def extract_clinic_info(poi):
    """Extrait les informations d'une clinique depuis un POI Mappy."""
    name = poi.get("name", "")

    # Communication
    comm = poi.get("communication", {})

    # Telephone
    phone_data = comm.get("phone", {})
    phone = phone_data.get("number")
    if phone_data.get("againstDirectMarketing"):
        phone = None

    # Email
    email = comm.get("email") or poi.get("mail")

    # Site web
    website = comm.get("website") or poi.get("website") or ""

    # Adresse
    address = poi.get("address", "")
    way = poi.get("way", "")
    house_number = poi.get("houseNumber", "")
    town = poi.get("town", "")
    pcode = poi.get("pCode", "")

    if not address and way:
        address = f"{house_number} {way}".strip()

    full_address = f"{address}, {pcode} {town}".strip(", ")

    # Rubriques (categories PagesJaunes)
    rubrics = [r.get("label", "") for r in poi.get("rubrics", [])]

    return {
        "nom_clinique": name,
        "telephone": phone or "",
        "email": email or "",
        "site_web": website,
        "adresse": full_address,
        "code_postal": pcode or "",
        "ville": town or "",
        "categories": " | ".join(rubrics),
        "docteur": "",
        "siret": "",
    }


# ─── Annuaire Entreprises — recherche dirigeant ────────────────────────────

def search_annuaire_entreprises(clinic_name, city):
    """Recherche dans l'Annuaire Entreprises pour trouver SIRET + dirigeant."""
    try:
        resp = requests.get(
            "https://recherche-entreprises.api.gouv.fr/search",
            params={
                "q": clinic_name,
                "commune": city,
                "page": 1,
                "per_page": 3,
                "mtm_campaign": "clinic-scraper",
            },
            timeout=10,
        )

        if resp.status_code != 200:
            return None, None, None

        results = resp.json().get("results", [])
        if not results:
            return None, None, None

        company = results[0]
        siret = company.get("siege", {}).get("siret", "")

        # Dirigeants
        dirigeants = company.get("dirigeants", [])
        docteur = ""
        if dirigeants:
            d = dirigeants[0]
            prenom = d.get("prenoms", "")
            nom = d.get("nom", "")
            qualite = d.get("qualite", "")
            if prenom and nom:
                docteur = f"{prenom} {nom}"
                if qualite:
                    docteur += f" ({qualite})"

        return siret, docteur, company.get("nom_complet", "")

    except (requests.exceptions.RequestException, ValueError):
        return None, None, None


# ─── Pipeline principal ─────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  SCRAPER CLINIQUES CHIRURGIE ESTHETIQUE")
    print("=" * 65)
    print(f"  Date         : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Villes       : {len(CITIES)}")
    print(f"  Recherches   : {len(SEARCH_TERMS)} termes")
    print(f"  Sources      : Mappy/PagesJaunes + Annuaire Entreprises")
    print("=" * 65)
    print()

    # ─── ETAPE 1 : Collecte via Mappy/PagesJaunes ─────────────────────────
    print("ETAPE 1/2 : Recherche Mappy / PagesJaunes")
    print("-" * 50)

    all_clinics = {}  # cle = (nom, code_postal) pour deduplier
    total_queries = len(SEARCH_TERMS) * len(CITIES)
    query_count = 0

    for term in SEARCH_TERMS:
        print(f"\n  [TERME] \"{term}\"")
        for city in CITIES:
            query_count += 1
            print(f"    [{query_count}/{total_queries}] {city}...", end=" ", flush=True)

            pois = mappy_search(term, city)

            found = 0
            for poi in pois:
                if not is_relevant_clinic(poi):
                    continue

                info = extract_clinic_info(poi)
                key = (info["nom_clinique"].lower().strip(), info["code_postal"])

                if key not in all_clinics:
                    all_clinics[key] = info
                    found += 1

            print(f"+{found} (total: {len(all_clinics)})", flush=True)
            time.sleep(0.25)

    print(f"\n=> {len(all_clinics)} cliniques uniques trouvees")

    # ─── ETAPE 2 : Enrichissement — dirigeant + SIRET ─────────────────────
    print(f"\nETAPE 2/2 : Enrichissement (Annuaire Entreprises)")
    print("-" * 50)

    clinics = list(all_clinics.values())
    stats = {"docteur": 0, "siret": 0, "phone": 0, "email": 0, "website": 0}

    for i, clinic in enumerate(clinics):
        name = clinic["nom_clinique"]
        city = clinic["ville"]

        print(f"  [{i+1}/{len(clinics)}] {name[:45]}", end=" ", flush=True)

        # Recherche dans l'Annuaire Entreprises
        if name and city:
            siret, docteur, _ = search_annuaire_entreprises(name, city)

            if siret:
                clinic["siret"] = siret
                stats["siret"] += 1

            if docteur:
                clinic["docteur"] = docteur
                stats["docteur"] += 1
                print(f"DR:{docteur[:25]}", end=" ", flush=True)

        print("OK")
        time.sleep(0.2)

    # Compter les stats
    for clinic in clinics:
        if clinic["telephone"]:
            stats["phone"] += 1
        if clinic["email"]:
            stats["email"] += 1
        if clinic["site_web"]:
            stats["website"] += 1

    # ─── Export CSV ───────────────────────────────────────────────────────
    fieldnames = [
        "nom_clinique", "docteur", "telephone", "email", "site_web",
        "adresse", "code_postal", "ville", "categories", "siret",
    ]

    # Trier par ville puis nom
    clinics.sort(key=lambda c: (c["ville"], c["nom_clinique"]))

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clinics)

    # ─── Resultats ────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  RESULTATS")
    print("=" * 65)
    print(f"  Cliniques trouvees     : {len(clinics)}")
    print(f"  Avec TELEPHONE         : {stats['phone']}")
    print(f"  Avec EMAIL             : {stats['email']}")
    print(f"  Avec SITE WEB          : {stats['website']}")
    print(f"  Avec DOCTEUR/DIRIGEANT : {stats['docteur']}")
    print(f"  Avec SIRET             : {stats['siret']}")
    print(f"  ─────────────────────────────────────")
    print(f"  Fichier                : {OUTPUT_FILE}")
    print("=" * 65)
    print()


if __name__ == "__main__":
    main()
