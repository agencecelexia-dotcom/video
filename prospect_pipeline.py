#!/usr/bin/env python3
"""
Pipeline complet : Collecte SIRENE → Enrichissement Mappy/PJ + Annuaire Entreprises
Objectif : 1000+ prospects AVEC telephone, societes < 6 mois, sans site web
Niches : Artisans du batiment, Beaute/Coiffure/Bien-etre
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

MAPPY_API_KEY = "f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z"
MAPPY_SEARCH_URL = "https://api-search.mappy.net/search/1.1/find"

DATE_LIMIT = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

NICHES = {
    "Artisan Batiment": [
        "43.21A", "43.22A", "43.22B", "43.34Z", "43.31Z",
        "43.32A", "43.32B", "43.33Z", "43.39Z", "43.91B",
        "43.99C", "43.29A", "43.12A", "43.11Z", "43.91A",
        "43.99A", "43.99B", "43.12B", "43.13Z", "43.21B",
        "43.29B",
    ],
    "Beaute / Coiffure / Bien-etre": [
        "96.02A", "96.02B", "96.04Z", "96.09Z",
    ],
}

# On collecte beaucoup pour filtrer ensuite ceux AVEC telephone
MAX_PER_NICHE = 3000
OUTPUT_FILE = "prospects_1000.csv"
TARGET_WITH_PHONE = 1000  # objectif minimum


# ─── SIRENE ──────────────────────────────────────────────────────────────────

def get_headers():
    return {
        "X-INSEE-Api-Key-Integration": API_KEY,
        "Accept": "application/json",
    }


def search_sirene(naf_codes, cursor="*"):
    parts = [f'activitePrincipaleUniteLegale:"{c}"' for c in naf_codes]
    naf_filter = "(" + " OR ".join(parts) + ")"
    date_filter = f'dateCreationUniteLegale:[{DATE_LIMIT} TO *]'
    active_filter = 'etablissementSiege:true AND etatAdministratifUniteLegale:A AND statutDiffusionUniteLegale:O'
    query = f"{naf_filter} AND {date_filter} AND {active_filter}"

    try:
        resp = requests.get(
            f"{BASE_URL}/siret",
            headers=get_headers(),
            params={"q": query, "nombre": 100, "curseur": cursor},
            timeout=30,
        )
        if resp.status_code == 401:
            print("ERREUR 401 : Cle API invalide.")
            sys.exit(1)
        elif resp.status_code == 429:
            print("429 rate limit, pause 5s...", flush=True)
            time.sleep(5)
            return search_sirene(naf_codes, cursor)
        elif resp.status_code != 200:
            print(f"Erreur API : {resp.status_code}")
            return [], None

        data = resp.json()
        return data.get("etablissements", []), data.get("header", {}).get("curseurSuivant")
    except requests.exceptions.RequestException as e:
        print(f"Erreur reseau : {e}")
        return [], None


def extract_lead(etab, niche_name):
    ul = etab.get("uniteLegale", {})
    adresse = etab.get("adresseEtablissement", {})
    periodes_ul = ul.get("periodesUniteLegale", [{}])
    periode = periodes_ul[0] if periodes_ul else {}

    prenom = ul.get("prenomUsuelUniteLegale") or ul.get("prenom1UniteLegale", "") or ""
    nom = ul.get("nomUniteLegale", "") or ""

    denomination = (
        periode.get("denominationUniteLegale")
        or periode.get("denominationUsuelle1UniteLegale")
        or ul.get("denominationUniteLegale")
        or f"{prenom} {nom}".strip()
    )

    rue = " ".join(filter(None, [
        adresse.get("numeroVoieEtablissement"),
        adresse.get("typeVoieEtablissement"),
        adresse.get("libelleVoieEtablissement"),
    ]))
    code_postal = adresse.get("codePostalEtablissement", "")
    ville = adresse.get("libelleCommuneEtablissement", "")
    adresse_complete = f"{rue}, {code_postal} {ville}".strip(", ")

    naf = periode.get("activitePrincipaleUniteLegale", "")

    return {
        "prenom": prenom,
        "nom": nom,
        "nom_societe": denomination,
        "niche": niche_name,
        "code_naf": naf,
        "telephone": "",
        "email": "",
        "adresse": adresse_complete,
        "code_postal": code_postal,
        "ville": ville,
        "departement": code_postal[:2] if code_postal else "",
        "date_creation": ul.get("dateCreationUniteLegale", ""),
        "siret": etab.get("siret", ""),
        "siren": etab.get("siren", ""),
        "forme_juridique": ul.get("categorieJuridiqueUniteLegale", ""),
    }


def has_website(company_name):
    if not company_name or len(company_name) < 4:
        return False
    clean = company_name.lower().strip()
    for ch in " '-&.+/()":
        clean = clean.replace(ch, "")
    for old, new in [("é","e"),("è","e"),("ê","e"),("ë","e"),("à","a"),("â","a"),
                     ("ô","o"),("ù","u"),("û","u"),("î","i"),("ï","i"),("ç","c")]:
        clean = clean.replace(old, new)
    if len(clean) < 3:
        return False
    for ext in [".fr", ".com"]:
        try:
            socket.setdefaulttimeout(0.5)
            socket.gethostbyname(clean + ext)
            return True
        except (socket.gaierror, socket.timeout, OSError):
            continue
    return False


# ─── Mappy / Pages Jaunes ───────────────────────────────────────────────────

def mappy_search(company_name, city):
    try:
        resp = requests.get(
            MAPPY_SEARCH_URL,
            params={"q": f"{company_name} {city}", "max_results": 3,
                    "favorite_country": 250, "language": "fr"},
            headers={"apikey": MAPPY_API_KEY,
                     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                     "Origin": "https://fr.mappy.com",
                     "Referer": "https://fr.mappy.com/"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None, None, None

        pois = resp.json().get("pois", [])
        if not pois:
            return None, None, None

        poi = pois[0]

        # Verifier correspondance
        poi_town = (poi.get("town") or "").lower()
        if city.lower() not in poi_town and poi_town not in city.lower():
            poi_name = (poi.get("name") or "").lower()
            words = [w for w in company_name.lower().split() if len(w) > 3]
            if not any(w in poi_name for w in words):
                return None, None, None

        comm = poi.get("communication", {})
        phone_data = comm.get("phone", {})
        phone = phone_data.get("number")
        if phone_data.get("againstDirectMarketing"):
            phone = None

        email = comm.get("email") or poi.get("mail")
        website = comm.get("website") or poi.get("website")

        return phone, email, website

    except (requests.exceptions.RequestException, ValueError, KeyError):
        return None, None, None


# ─── Annuaire Entreprises (dirigeants) ───────────────────────────────────────

def get_dirigeant(siren):
    try:
        resp = requests.get(
            "https://recherche-entreprises.api.gouv.fr/search",
            params={"q": siren[:9], "mtm_campaign": "lead-enrichment"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None, None, None

        results = resp.json().get("results", [])
        if not results:
            return None, None, None

        dirigeants = results[0].get("dirigeants", [])
        if dirigeants:
            d = dirigeants[0]
            return d.get("prenoms", ""), d.get("nom", ""), d.get("qualite", "")
        return None, None, None
    except (requests.exceptions.RequestException, ValueError):
        return None, None, None


# ─── Pipeline principal ─────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  PIPELINE PROSPECTS — Objectif 1000+ avec telephone")
    print("=" * 65)
    print(f"  Criteres :")
    print(f"    - Societes creees apres le {DATE_LIMIT}")
    print(f"    - Sans site web")
    print(f"    - Niches : {', '.join(NICHES.keys())}")
    print(f"  Sources : SIRENE + Mappy/PJ + Annuaire Entreprises")
    print("=" * 65)
    print()

    # ─── ETAPE 1 : Collecte massive SIRENE ───────────────────────────────
    print("ETAPE 1/3 : Collecte SIRENE")
    print("-" * 40)

    all_raw = []
    seen_siret = set()

    for niche_name, naf_codes in NICHES.items():
        print(f"\n[NICHE] {niche_name} ({len(naf_codes)} codes NAF)")
        collected = []
        cursor = "*"
        page = 0

        while len(collected) < MAX_PER_NICHE:
            page += 1
            etabs, next_cursor = search_sirene(naf_codes, cursor)
            if not etabs:
                print(f"    Page {page}: aucun resultat.")
                break

            for etab in etabs:
                if len(collected) >= MAX_PER_NICHE:
                    break
                siret = etab.get("siret", "")
                if siret in seen_siret:
                    continue

                lead = extract_lead(etab, niche_name)

                if not lead["nom_societe"] or lead["nom_societe"] == "[ND]":
                    continue
                if not lead["ville"]:
                    continue

                seen_siret.add(siret)
                collected.append(lead)

            print(f"    Page {page}: +{len(etabs)} => {len(collected)} collectes", flush=True)

            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(0.3)

        print(f"    => {len(collected)} leads pour {niche_name}")
        all_raw.extend(collected)

    print(f"\n=> TOTAL BRUT : {len(all_raw)} leads collectes")

    # ─── ETAPE 2 : Enrichissement + filtrage site web ────────────────────
    print(f"\nETAPE 2/3 : Enrichissement (Mappy + Annuaire Entreprises)")
    print("-" * 40)

    enriched_with_phone = []
    enriched_no_phone = []
    stats = {"phone": 0, "email": 0, "dirigeant": 0, "website_skip": 0, "total": 0}

    for i, lead in enumerate(all_raw):
        company = lead["nom_societe"]
        city = lead["ville"]
        siret = lead["siret"]

        stats["total"] += 1
        progress = f"[{i+1}/{len(all_raw)}]"
        found_phone = len(enriched_with_phone)

        # Si on a atteint l'objectif, on peut s'arreter
        if found_phone >= TARGET_WITH_PHONE * 3:
            print(f"\n=> Objectif largement atteint ({found_phone} tel), arret.")
            break

        print(f"{progress} ({found_phone} tel) {company[:40]}", end=" ", flush=True)

        # Verification site web rapide (DNS)
        if has_website(company):
            print("SITE->skip")
            stats["website_skip"] += 1
            continue

        # Mappy : telephone + email
        phone, email, website = None, None, None
        if company and city:
            phone, email, website = mappy_search(company, city)

            # Si Mappy trouve un site web, on skip aussi
            if website and len(website) > 10:
                print("SITE(mappy)->skip")
                stats["website_skip"] += 1
                continue

        if phone:
            lead["telephone"] = phone
            stats["phone"] += 1
            print(f"TEL:{phone}", end=" ", flush=True)

        if email:
            lead["email"] = email
            stats["email"] += 1

        # Annuaire Entreprises : dirigeant
        prenom = lead.get("prenom", "")
        nom = lead.get("nom", "")
        if siret and (not prenom or not nom):
            d_prenom, d_nom, d_qualite = get_dirigeant(siret)
            if d_prenom and d_nom:
                lead["prenom"] = d_prenom
                lead["nom"] = d_nom
                stats["dirigeant"] += 1

        print("OK")

        if phone:
            enriched_with_phone.append(lead)
        else:
            enriched_no_phone.append(lead)

        time.sleep(0.2)

    # ─── ETAPE 3 : Export CSV ────────────────────────────────────────────
    print(f"\nETAPE 3/3 : Export CSV")
    print("-" * 40)

    # Priorite : leads avec telephone, puis sans (pour atteindre le volume)
    final = enriched_with_phone.copy()
    if len(final) < TARGET_WITH_PHONE:
        # Ajouter des leads sans telephone pour compenser
        extra = enriched_no_phone[:TARGET_WITH_PHONE - len(final)]
        final.extend(extra)

    fieldnames = [
        "prenom", "nom", "nom_societe", "niche", "code_naf",
        "telephone", "email", "adresse", "code_postal", "ville",
        "departement", "date_creation", "siret", "siren", "forme_juridique",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final)

    # Stats finales
    print()
    print("=" * 65)
    print("  RESULTATS FINAUX")
    print("=" * 65)
    print(f"  Leads collectes (SIRENE)     : {stats['total']}")
    print(f"  Exclus (site web detecte)    : {stats['website_skip']}")
    print(f"  Avec TELEPHONE               : {len(enriched_with_phone)}")
    print(f"  Avec EMAIL                   : {stats['email']}")
    print(f"  Dirigeants enrichis          : {stats['dirigeant']}")
    print(f"  ─────────────────────────────────")
    print(f"  TOTAL EXPORTE                : {len(final)}")
    print(f"  Fichier                      : {OUTPUT_FILE}")
    print("=" * 65)

    # Export aussi un CSV "avec telephone uniquement"
    phone_only_file = "prospects_avec_tel.csv"
    with open(phone_only_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched_with_phone)

    print(f"\n  CSV telephone uniquement     : {phone_only_file} ({len(enriched_with_phone)} lignes)")
    print()


if __name__ == "__main__":
    main()
