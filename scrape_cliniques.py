#!/usr/bin/env python3
"""
Scraper de cliniques de chirurgie esthetique en France
Sources (essayees dans l'ordre) :
  1. PagesJaunes.fr — scraping direct HTML (le plus fiable)
  2. Mappy API — recherche POI (backup)
  3. Annuaire Entreprises API — dirigeants / medecins / SIRET

Output : CSV avec nom_clinique, docteur, telephone, email, site_web, adresse, ville
"""

import csv
import requests
import time
import sys
import re
import json
from datetime import datetime
from html.parser import HTMLParser

# ─── Configuration ───────────────────────────────────────────────────────────
MAPPY_API_KEY = "f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z"
MAPPY_SEARCH_URL = "https://api-search.mappy.net/search/1.1/find"

OUTPUT_FILE = "cliniques_chirurgie_esthetique.csv"

# Headers navigateur pour PagesJaunes
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Termes de recherche PagesJaunes
PJ_SEARCH_TERMS = [
    "chirurgie+esthetique",
    "chirurgien+esthetique",
    "medecine+esthetique",
    "clinique+esthetique",
    "chirurgie+plastique",
]

# Grandes villes francaises
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


# ─── Source 1 : PagesJaunes.fr scraping ─────────────────────────────────────

def scrape_pagesjaunes(search_term, city, page=1):
    """Scrape PagesJaunes.fr pour trouver des cliniques."""
    url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={search_term}&ou={city}&page={page}"

    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)

        if resp.status_code != 200:
            print(f"PJ:{resp.status_code}", end=" ", flush=True)
            return []

        html = resp.text
        results = []

        # Extraire les blocs JSON-LD (structured data) si disponibles
        json_ld_matches = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        for match in json_ld_matches:
            try:
                data = json.loads(match)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("LocalBusiness", "MedicalBusiness",
                                              "Physician", "MedicalClinic",
                                              "Dentist", "Hospital"):
                        clinic = _parse_jsonld_item(item)
                        if clinic:
                            results.append(clinic)
            except (json.JSONDecodeError, TypeError):
                continue

        # Si pas de JSON-LD, parser le HTML directement
        if not results:
            results = _parse_pj_html(html)

        return results

    except requests.exceptions.RequestException as e:
        print(f"ERR:{type(e).__name__}", end=" ", flush=True)
        return []


def _parse_jsonld_item(item):
    """Parse un item JSON-LD PagesJaunes."""
    name = item.get("name", "")
    if not name:
        return None

    phone = item.get("telephone", "")
    email = item.get("email", "")
    website = item.get("url", "") or item.get("sameAs", "")

    address_obj = item.get("address", {})
    street = address_obj.get("streetAddress", "")
    postal = address_obj.get("postalCode", "")
    city = address_obj.get("addressLocality", "")
    full_address = f"{street}, {postal} {city}".strip(", ")

    return {
        "nom_clinique": name,
        "telephone": phone or "",
        "email": email or "",
        "site_web": website,
        "adresse": full_address,
        "code_postal": postal or "",
        "ville": city or "",
        "categories": "",
        "docteur": "",
        "siret": "",
    }


def _parse_pj_html(html):
    """Parse le HTML PagesJaunes pour extraire les pros."""
    results = []

    # Pattern pour les blocs de resultats
    # Nom de l'entreprise
    names = re.findall(
        r'class="[^"]*denomination-links[^"]*"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    # Telephones
    phones = re.findall(
        r'data-phone-number="(\d+)"', html
    )
    # Alternative phone pattern
    if not phones:
        phones = re.findall(r'href="tel:(\+?\d[\d\s]+)"', html)

    # Adresses
    addresses = re.findall(
        r'class="[^"]*bi-address[^"]*"[^>]*>(.*?)</',
        html, re.DOTALL
    )

    # Sites web
    websites = re.findall(
        r'class="[^"]*pj-lb[^"]*"[^>]*href="(https?://[^"]+)"[^>]*>.*?(?:Site|site|web)',
        html, re.DOTALL
    )

    for i, name_raw in enumerate(names):
        name = re.sub(r'<[^>]+>', '', name_raw).strip()
        if not name:
            continue

        results.append({
            "nom_clinique": name,
            "telephone": phones[i] if i < len(phones) else "",
            "email": "",
            "site_web": websites[i] if i < len(websites) else "",
            "adresse": re.sub(r'<[^>]+>', '', addresses[i]).strip() if i < len(addresses) else "",
            "code_postal": "",
            "ville": "",
            "categories": "",
            "docteur": "",
            "siret": "",
        })

    return results


# ─── Source 2 : Mappy / PagesJaunes API ─────────────────────────────────────

def mappy_search(query, city, max_results=20):
    """Recherche Mappy/PagesJaunes API pour une requete + ville."""
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
            print("429-pause", end=" ", flush=True)
            time.sleep(5)
            return mappy_search(query, city, max_results)

        if resp.status_code != 200:
            print(f"M:{resp.status_code}", end=" ", flush=True)
            return []

        pois = resp.json().get("pois", [])
        results = []

        for poi in pois:
            if not _is_relevant_clinic(poi):
                continue
            results.append(_extract_from_mappy(poi))

        return results

    except requests.exceptions.RequestException as e:
        print(f"M-ERR:{type(e).__name__}", end=" ", flush=True)
        return []


def _is_relevant_clinic(poi):
    """Verifie que le POI Mappy est lie a la chirurgie/medecine esthetique."""
    name = (poi.get("name") or "").lower()
    rubrics = " ".join([r.get("label", "") for r in poi.get("rubrics", [])]).lower()
    all_text = f"{name} {rubrics}"

    keywords = [
        "esthetique", "esthétique", "plastique", "plasticien",
        "chirurgi", "laser", "liposuccion", "rhinoplastie",
        "lifting", "botox", "injection", "medecin", "médecin",
        "docteur", "clinique", "cabinet", "dermato",
    ]

    return any(kw in all_text for kw in keywords)


def _extract_from_mappy(poi):
    """Extrait les informations d'un POI Mappy."""
    comm = poi.get("communication", {})
    phone_data = comm.get("phone", {})
    phone = phone_data.get("number")
    if phone_data.get("againstDirectMarketing"):
        phone = None

    email = comm.get("email") or poi.get("mail")
    website = comm.get("website") or poi.get("website") or ""

    address = poi.get("address", "")
    way = poi.get("way", "")
    house_number = poi.get("houseNumber", "")
    town = poi.get("town", "")
    pcode = poi.get("pCode", "")

    if not address and way:
        address = f"{house_number} {way}".strip()

    full_address = f"{address}, {pcode} {town}".strip(", ")
    rubrics = [r.get("label", "") for r in poi.get("rubrics", [])]

    return {
        "nom_clinique": poi.get("name", ""),
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


# ─── Source 3 : Annuaire Entreprises — dirigeant + SIRET ────────────────────

def search_annuaire_entreprises(clinic_name, city):
    """Recherche dans l'Annuaire Entreprises pour SIRET + dirigeant."""
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
    print(f"  Recherches   : {len(PJ_SEARCH_TERMS)} termes")
    print(f"  Sources      : PagesJaunes.fr + Mappy API + Annuaire Entreprises")
    print("=" * 65)
    print()

    # ─── ETAPE 1 : Collecte via PagesJaunes.fr + Mappy ────────────────────
    print("ETAPE 1/2 : Recherche PagesJaunes.fr + Mappy")
    print("-" * 50)

    all_clinics = {}  # cle = nom normalise pour deduplier
    errors_pj = 0
    errors_mappy = 0

    for term_idx, term in enumerate(PJ_SEARCH_TERMS):
        term_display = term.replace("+", " ")
        print(f"\n  [{term_idx+1}/{len(PJ_SEARCH_TERMS)}] \"{term_display}\"")

        for city_idx, city in enumerate(CITIES):
            print(f"    {city}...", end=" ", flush=True)
            found = 0

            # Source 1 : PagesJaunes.fr (scraping HTML)
            for page in range(1, 4):  # 3 pages max
                pj_results = scrape_pagesjaunes(term, city, page)
                if not pj_results:
                    if page == 1:
                        errors_pj += 1
                    break

                for clinic in pj_results:
                    key = _normalize_key(clinic["nom_clinique"], clinic.get("code_postal", ""), city)
                    if key and key not in all_clinics:
                        if not clinic["ville"]:
                            clinic["ville"] = city
                        all_clinics[key] = clinic
                        found += 1

                time.sleep(0.5)  # respecter PagesJaunes

            # Source 2 : Mappy API (backup)
            mappy_results = mappy_search(term_display, city)
            for clinic in mappy_results:
                key = _normalize_key(clinic["nom_clinique"], clinic.get("code_postal", ""), city)
                if key and key not in all_clinics:
                    all_clinics[key] = clinic
                    found += 1

            if not mappy_results and not pj_results:
                errors_mappy += 1

            print(f"+{found} (total: {len(all_clinics)})", flush=True)
            time.sleep(0.3)

    print(f"\n=> {len(all_clinics)} cliniques uniques trouvees")
    if errors_pj > 0:
        print(f"   ({errors_pj} erreurs PagesJaunes — normal si proxy/rate limit)")
    if errors_mappy > 0:
        print(f"   ({errors_mappy} erreurs Mappy — normal si API indisponible)")

    if not all_clinics:
        print("\nAucune clinique trouvee. Verifiez votre connexion internet.")
        print("Les APIs PagesJaunes et Mappy doivent etre accessibles.")
        sys.exit(1)

    # ─── ETAPE 2 : Enrichissement — dirigeant + SIRET ─────────────────────
    print(f"\nETAPE 2/2 : Enrichissement (Annuaire Entreprises)")
    print("-" * 50)

    clinics = list(all_clinics.values())
    stats = {"docteur": 0, "siret": 0, "phone": 0, "email": 0, "website": 0}

    for i, clinic in enumerate(clinics):
        name = clinic["nom_clinique"]
        city = clinic["ville"]

        print(f"  [{i+1}/{len(clinics)}] {name[:45]}", end=" ", flush=True)

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

    # Stats
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


def _normalize_key(name, postal, city):
    """Normalise un nom de clinique pour deduplication."""
    if not name:
        return None
    key = name.lower().strip()
    key = re.sub(r'[^a-z0-9]', '', key)
    if len(key) < 3:
        return None
    return f"{key}_{postal or city.lower()}"


if __name__ == "__main__":
    main()
