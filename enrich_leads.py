#!/usr/bin/env python3
"""
Enrichissement des leads — Ajout téléphone + email + dirigeant
Sources :
  1. Google Places API (téléphone, site web) — gratuit via $200 crédit/mois
  2. Annuaire Entreprises API (dirigeants) — gratuit, illimité
"""

import csv
import requests
import time
import sys
import json

# ─── Configuration ───────────────────────────────────────────────────────────
GOOGLE_API_KEY = ""  # <-- Colle ta clé Google Cloud ici
INPUT_FILE = "leads.csv"
OUTPUT_FILE = "leads_enriched.csv"

# ─── Google Places API ───────────────────────────────────────────────────────

def google_find_phone(company_name, city, api_key):
    """Cherche le téléphone d'une entreprise via Google Places API."""
    query = f"{company_name} {city}"

    # Étape 1 : Trouver le lieu
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        params={
            "input": query,
            "inputtype": "textquery",
            "fields": "place_id,name,formatted_phone_number",
            "language": "fr",
            "key": api_key,
        },
        timeout=10,
    )

    if resp.status_code != 200:
        return None, None

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return None, None

    place_id = candidates[0].get("place_id")
    if not place_id:
        return None, None

    # Étape 2 : Détails du lieu (téléphone + website)
    resp2 = requests.get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        params={
            "place_id": place_id,
            "fields": "formatted_phone_number,website,international_phone_number",
            "language": "fr",
            "key": api_key,
        },
        timeout=10,
    )

    if resp2.status_code != 200:
        return None, None

    result = resp2.json().get("result", {})
    phone = result.get("formatted_phone_number") or result.get("international_phone_number")
    website = result.get("website")

    return phone, website


# ─── Annuaire Entreprises API (gouv.fr) ─────────────────────────────────────

def get_dirigeant(siren):
    """Récupère le dirigeant principal via l'API Annuaire Entreprises."""
    siren_9 = siren[:9] if len(siren) > 9 else siren

    try:
        resp = requests.get(
            f"https://recherche-entreprises.api.gouv.fr/search",
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

    except requests.exceptions.RequestException:
        return None, None, None


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    # Vérifier la clé Google
    if not GOOGLE_API_KEY:
        print("=" * 60)
        print("  ERREUR : Clé Google API manquante")
        print("=" * 60)
        print()
        print("Ouvre enrich_leads.py et colle ta clé Google Cloud")
        print("à la ligne : GOOGLE_API_KEY = \"\"")
        print()
        print("Pour obtenir une clé :")
        print("  1. https://console.cloud.google.com")
        print("  2. Crée un projet")
        print("  3. Active 'Places API' (ancien) ou 'Places API (New)'")
        print("  4. Identifiants > Créer > Clé API")
        print()
        print("C'est GRATUIT (200$/mois de crédit offert par Google)")
        sys.exit(1)

    # Lire le CSV existant
    try:
        with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            leads = list(reader)
    except FileNotFoundError:
        print(f"Fichier '{INPUT_FILE}' introuvable. Lance d'abord lead_generator.py")
        sys.exit(1)

    print("=" * 60)
    print("  ENRICHISSEMENT DES LEADS")
    print("=" * 60)
    print(f"  Leads à enrichir : {len(leads)}")
    print(f"  Sources : Google Places API + Annuaire Entreprises")
    print("=" * 60)
    print()

    enriched = []
    stats = {"phone_found": 0, "dirigeant_found": 0, "total": len(leads)}

    for i, lead in enumerate(leads):
        company = lead.get("nom_societe", "")
        city = lead.get("ville", "")
        siret = lead.get("siret", "")

        print(f"[{i+1}/{len(leads)}] {company[:40]}...", end=" ", flush=True)

        # ─── Source 1 : Google Places (téléphone) ────────────────────────
        phone = lead.get("telephone", "")
        website = ""

        if not phone:
            try:
                phone, website = google_find_phone(company, city, GOOGLE_API_KEY)
                if phone:
                    stats["phone_found"] += 1
                    print(f"TEL:{phone}", end=" ", flush=True)
                else:
                    phone = ""
                    print("pas de tel", end=" ", flush=True)
            except Exception as e:
                print(f"err Google: {e}", end=" ", flush=True)
                phone = ""

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

        # Si le site web a été trouvé via Google, on note mais on garde le lead
        # (peut-être un simple Google My Business, pas un vrai site)

        lead["telephone"] = phone or ""
        lead["email"] = lead.get("email", "")
        lead["prenom"] = prenom
        lead["nom"] = nom

        enriched.append(lead)
        print("OK")

        # Pause pour respecter les limites API
        time.sleep(0.2)

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
    print(f"  RESULTATS")
    print("=" * 60)
    print(f"  Total leads     : {stats['total']}")
    print(f"  Telephones      : {stats['phone_found']} ({stats['phone_found']*100//max(1,stats['total'])}%)")
    print(f"  Dirigeants      : {stats['dirigeant_found']} enrichis")
    print(f"  Fichier         : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
