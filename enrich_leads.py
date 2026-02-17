#!/usr/bin/env python3
"""
Enrichissement des leads — Ajout téléphone + email + dirigeant
Sources :
  1. Mappy/PagesJaunes API (téléphone, email, avis) — gratuit, sans inscription
  2. Annuaire Entreprises API (dirigeants) — gratuit, illimité
"""

import csv
import requests
import time
import sys

# ─── Configuration ───────────────────────────────────────────────────────────
INPUT_FILE = "leads.csv"
OUTPUT_FILE = "leads_enriched.csv"

MAPPY_API_KEY = "f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z"
MAPPY_SEARCH_URL = "https://api-search.mappy.net/search/1.1/find"


# ─── Source 1 : Mappy / Pages Jaunes (téléphone + email) ────────────────────

def mappy_search(company_name, city):
    """Cherche téléphone + email via l'API Mappy (données Pages Jaunes)."""
    query = f"{company_name} {city}"

    try:
        resp = requests.get(
            MAPPY_SEARCH_URL,
            params={
                "q": query,
                "max_results": 3,
                "favorite_country": 250,
                "language": "fr",
            },
            headers={
                "apikey": MAPPY_API_KEY,
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Origin": "https://fr.mappy.com",
                "Referer": "https://fr.mappy.com/",
            },
            timeout=10,
        )

        if resp.status_code != 200:
            return None, None

        data = resp.json()
        pois = data.get("pois", [])

        if not pois:
            return None, None

        # Prendre le premier résultat
        poi = pois[0]

        # Vérifier que le résultat correspond bien (même ville)
        poi_town = (poi.get("town") or "").lower()
        if city.lower() not in poi_town and poi_town not in city.lower():
            # Vérifier le code postal
            poi_pcode = poi.get("pCode", "")
            # On accepte quand même si le nom correspond bien
            poi_name = (poi.get("name") or "").lower()
            company_lower = company_name.lower()
            # Au moins un mot significatif du nom doit matcher
            words = [w for w in company_lower.split() if len(w) > 3]
            if not any(w in poi_name for w in words):
                return None, None

        # Extraire téléphone et email
        comm = poi.get("communication", {})
        phone_data = comm.get("phone", {})
        phone = phone_data.get("number")

        # Vérifier "againstDirectMarketing" — respect RGPD
        if phone_data.get("againstDirectMarketing"):
            phone = None

        email = comm.get("email") or poi.get("mail")

        return phone, email

    except (requests.exceptions.RequestException, ValueError):
        return None, None


# ─── Source 2 : Annuaire Entreprises API (dirigeants) ────────────────────────

def get_dirigeant(siren):
    """Récupère le dirigeant principal via l'API Annuaire Entreprises."""
    siren_9 = siren[:9] if len(siren) > 9 else siren

    try:
        resp = requests.get(
            "https://recherche-entreprises.api.gouv.fr/search",
            params={"q": siren_9, "mtm_campaign": "lead-enrichment"},
            timeout=10,
        )

        if resp.status_code != 200:
            return None, None, None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None, None, None

        company = results[0]
        dirigeants = company.get("dirigeants", [])

        if dirigeants:
            d = dirigeants[0]
            prenom = d.get("prenoms", "")
            nom = d.get("nom", "")
            qualite = d.get("qualite", "")
            return prenom, nom, qualite

        return None, None, None

    except (requests.exceptions.RequestException, ValueError):
        return None, None, None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    # Lire le CSV existant
    try:
        with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            leads = list(reader)
    except FileNotFoundError:
        print(f"Fichier '{INPUT_FILE}' introuvable. Lance d'abord lead_generator.py")
        sys.exit(1)

    if not leads:
        print("Aucun lead dans le fichier.")
        sys.exit(1)

    print("=" * 60)
    print("  ENRICHISSEMENT DES LEADS")
    print("=" * 60)
    print(f"  Leads a enrichir : {len(leads)}")
    print(f"  Sources :")
    print(f"    1. Mappy / Pages Jaunes (telephone + email)")
    print(f"    2. Annuaire Entreprises  (dirigeants)")
    print("=" * 60)
    print()

    enriched = []
    stats = {
        "phone_found": 0,
        "email_found": 0,
        "dirigeant_found": 0,
        "total": len(leads),
    }

    for i, lead in enumerate(leads):
        company = lead.get("nom_societe", "")
        city = lead.get("ville", "")
        siret = lead.get("siret", "")

        print(f"[{i+1}/{len(leads)}] {company[:45]}", end=" ", flush=True)

        # ─── Source 1 : Mappy (téléphone + email) ───────────────────────
        phone = lead.get("telephone", "")
        email = lead.get("email", "")

        if not phone and company and city:
            try:
                m_phone, m_email = mappy_search(company, city)
                if m_phone:
                    phone = m_phone
                    stats["phone_found"] += 1
                    print(f"TEL:{phone}", end=" ", flush=True)
                if m_email and not email:
                    email = m_email
                    stats["email_found"] += 1
                    print(f"EMAIL:{email[:25]}", end=" ", flush=True)
                if not m_phone and not m_email:
                    print(".", end=" ", flush=True)
            except Exception as e:
                print(f"err:{e}", end=" ", flush=True)

        # ─── Source 2 : Annuaire Entreprises (dirigeant) ─────────────────
        prenom = lead.get("prenom", "")
        nom = lead.get("nom", "")

        if siret and (not prenom or not nom):
            try:
                d_prenom, d_nom, d_qualite = get_dirigeant(siret)
                if d_prenom and d_nom:
                    prenom = d_prenom
                    nom = d_nom
                    stats["dirigeant_found"] += 1
                    print(f"DIR:{prenom} {nom}", end=" ", flush=True)
            except Exception:
                pass

        lead["telephone"] = phone or ""
        lead["email"] = email or ""
        lead["prenom"] = prenom
        lead["nom"] = nom

        enriched.append(lead)
        print("OK")

        # Pause entre les requêtes
        time.sleep(0.3)

    # ─── Export CSV enrichi ──────────────────────────────────────────────
    fieldnames = [
        "prenom", "nom", "nom_societe", "niche", "code_naf",
        "telephone", "email", "adresse", "code_postal", "ville",
        "date_creation", "siret",
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched)

    print()
    print("=" * 60)
    print("  RESULTATS")
    print("=" * 60)
    pct_phone = stats["phone_found"] * 100 // max(1, stats["total"])
    pct_email = stats["email_found"] * 100 // max(1, stats["total"])
    print(f"  Total leads     : {stats['total']}")
    print(f"  Telephones      : {stats['phone_found']} ({pct_phone}%)")
    print(f"  Emails          : {stats['email_found']} ({pct_email}%)")
    print(f"  Dirigeants      : {stats['dirigeant_found']} enrichis")
    print(f"  Fichier         : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
