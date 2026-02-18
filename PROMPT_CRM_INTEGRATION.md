# INTEGRATION : Generateur de Prospects dans le CRM

## Contexte

J'ai un pipeline de generation de prospects B2B qui fonctionne parfaitement en Python standalone. Je veux l'integrer directement dans ce CRM pour pouvoir :

1. Cliquer sur un bouton "Generer des prospects"
2. Choisir la niche (ex: "Artisan Batiment", "Beaute / Coiffure / Bien-etre") et le nombre de prospects souhaite
3. Le systeme collecte, enrichit et insere les prospects directement dans la base du CRM
4. Voir les nouveaux prospects apparaitre dans la liste

## Ce que tu dois faire

Analyse le code du CRM (stack, DB, API, modeles existants) et integre le pipeline ci-dessous. Adapte-le a la stack du CRM (JS/TS, Python, ou autre). Cree :

1. **Une route API backend** `POST /api/prospects/generate` qui accepte `{ niche: string, quantity: number }` et execute le pipeline
2. **Un composant UI** (bouton + modal/formulaire) dans la section appropriee du CRM pour declencher la generation
3. **Le mapping en base** : les prospects generes doivent etre inseres dans le modele de donnees existant du CRM (adapte les noms de champs si necessaire)
4. **Un feedback temps reel** (progress bar ou log) car le pipeline prend quelques minutes

## Architecture du pipeline (3 etapes)

### ETAPE 1 : Collecte depuis l'API SIRENE (INSEE)

On cherche les entreprises francaises recemment creees (< 6 mois) dans des codes NAF specifiques.

**API SIRENE :**
- Endpoint : `https://api.insee.fr/api-sirene/3.11/siret`
- Auth : Header `X-INSEE-Api-Key-Integration: fb76cf7e-e820-461a-b6cf-7ee820d61a92`
- Header : `Accept: application/json`
- Pagination : parametre `curseur` (commence a `"*"`, utiliser `curseurSuivant` de la reponse)
- Parametre `nombre: 100` (resultats par page)
- Rate limit : si 429, pause 5 secondes et retry

**Construction de la requete :**
```
q = (activitePrincipaleUniteLegale:"43.21A" OR activitePrincipaleUniteLegale:"43.22A" OR ...)
    AND dateCreationUniteLegale:[{date_6_mois_ago} TO *]
    AND etablissementSiege:true
    AND etatAdministratifUniteLegale:A
    AND statutDiffusionUniteLegale:O
```

**Niches et codes NAF disponibles :**
```json
{
  "Artisan Batiment": [
    "43.21A", "43.22A", "43.22B", "43.34Z", "43.31Z",
    "43.32A", "43.32B", "43.33Z", "43.39Z", "43.91B",
    "43.99C", "43.29A", "43.12A", "43.11Z", "43.91A",
    "43.99A", "43.99B", "43.12B", "43.13Z", "43.21B",
    "43.29B"
  ],
  "Beaute / Coiffure / Bien-etre": [
    "96.02A", "96.02B", "96.04Z", "96.09Z"
  ]
}
```

**Extraction des donnees d'un etablissement SIRENE :**
```
uniteLegale.prenomUsuelUniteLegale || uniteLegale.prenom1UniteLegale → prenom
uniteLegale.nomUniteLegale → nom
periodesUniteLegale[0].denominationUniteLegale || denominationUsuelle1UniteLegale → nom_societe
periodesUniteLegale[0].activitePrincipaleUniteLegale → code_naf
uniteLegale.dateCreationUniteLegale → date_creation
uniteLegale.categorieJuridiqueUniteLegale → forme_juridique
etab.siret → siret (14 chiffres)
etab.siren → siren (9 chiffres, ou siret[:9])

adresseEtablissement:
  numeroVoieEtablissement + typeVoieEtablissement + libelleVoieEtablissement → adresse
  codePostalEtablissement → code_postal
  libelleCommuneEtablissement → ville
  code_postal[:2] → departement
```

**Filtres a appliquer :**
- Ignorer si `nom_societe` est vide ou vaut `"[ND]"`
- Ignorer si `ville` est vide
- Dedupliquer par SIRET

### ETAPE 2 : Filtrage site web (DNS)

On exclut les entreprises qui ont deja un site web (elles n'ont pas besoin de nos services).

**Logique :**
1. Nettoyer le nom de la societe : minuscules, retirer espaces/tirets/apostrophes/accents
2. Tester DNS sur `{nom_nettoye}.fr` et `{nom_nettoye}.com`
3. Si le DNS resout (le domaine existe) → EXCLURE ce prospect
4. Timeout DNS : 0.5 seconde

**Nettoyage des accents :**
```
e/e/e/e → e, a/a → a, o → o, u/u → u, i/i → i, c → c
Retirer : espace, ', -, &, ., +, /, (, )
```

### ETAPE 3 : Enrichissement (telephone + email + dirigeant)

#### Source 1 : API Mappy / Pages Jaunes (telephone + email)

- Endpoint : `https://api-search.mappy.net/search/1.1/find`
- Headers :
  ```
  apikey: f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z
  User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36
  Origin: https://fr.mappy.com
  Referer: https://fr.mappy.com/
  ```
- Params : `q={nom_societe} {ville}`, `max_results=3`, `favorite_country=250`, `language=fr`
- Timeout : 10 secondes

**Extraction de la reponse Mappy :**
```
reponse.pois[0] → poi (premier resultat)

Verification de correspondance :
  - poi.town doit contenir la ville OU
  - poi.name doit contenir au moins un mot significatif (>3 lettres) du nom de la societe
  - Sinon, ignorer ce resultat

poi.communication.phone.number → telephone
poi.communication.phone.againstDirectMarketing → si true, NE PAS utiliser le telephone (RGPD)
poi.communication.email || poi.mail → email
poi.communication.website || poi.website → si site web trouve (>10 chars), EXCLURE le prospect
```

#### Source 2 : API Annuaire Entreprises (dirigeant)

- Endpoint : `https://recherche-entreprises.api.gouv.fr/search`
- Params : `q={siren}` (9 premiers chiffres du SIRET), `mtm_campaign=lead-enrichment`
- Pas d'authentification (API publique gratuite)
- Timeout : 10 secondes

**Extraction :**
```
results[0].dirigeants[0].prenoms → prenom (si pas deja renseigne)
results[0].dirigeants[0].nom → nom (si pas deja renseigne)
results[0].dirigeants[0].qualite → role/fonction
```

On n'ecrase le prenom/nom que s'ils sont vides (les donnees SIRENE sont prioritaires).

### Logique de priorite

Le pipeline collecte beaucoup plus que le nombre demande, car seule une fraction aura un telephone. La logique :

1. Collecter `quantity * 3` leads bruts depuis SIRENE (pour avoir assez de marge)
2. Pour chaque lead : filtrer site web → enrichir Mappy → enrichir dirigeant
3. Separer en 2 listes : `avec_telephone` et `sans_telephone`
4. Le resultat final = tous ceux `avec_telephone` en priorite, puis completer avec `sans_telephone` si besoin
5. S'arreter quand on a `quantity * 3` leads avec telephone (largement assez)

### Delais entre requetes

- 0.3s entre chaque page SIRENE
- 0.2s entre chaque lead enrichi (Mappy + Annuaire Entreprises)
- 5s de pause si erreur 429 sur SIRENE

## Modele de donnees du prospect

Voici les 15 champs a mapper dans le CRM :

| Champ | Type | Description | Exemple |
|-------|------|-------------|---------|
| `prenom` | string | Prenom du dirigeant | "ISMAEL" |
| `nom` | string | Nom du dirigeant | "KADDURI" |
| `nom_societe` | string | Raison sociale | "SANI PLOMBERIE" |
| `niche` | string | Categorie metier | "Artisan Batiment" |
| `code_naf` | string | Code activite NAF | "43.22A" |
| `telephone` | string | Numero de telephone | "06 18 31 04 11" |
| `email` | string | Adresse email | "contact@example.com" |
| `adresse` | string | Adresse complete | "8 ALLEE DES ALISIERS, 45500 GIEN" |
| `code_postal` | string | Code postal (5 chiffres) | "45500" |
| `ville` | string | Commune | "GIEN" |
| `departement` | string | Departement (2 chiffres) | "45" |
| `date_creation` | string (YYYY-MM-DD) | Date de creation | "2026-01-15" |
| `siret` | string | SIRET (14 chiffres) | "10000055300014" |
| `siren` | string | SIREN (9 chiffres) | "100000553" |
| `forme_juridique` | string | Code forme juridique | "5499" |

## Contraintes importantes

1. **Les cles API sont hardcoded** (pas de .env necessaire) :
   - SIRENE : `fb76cf7e-e820-461a-b6cf-7ee820d61a92`
   - Mappy : `f2wjQp1eFdTe26YcAP3K92m7d9cV8x1Z`
   - Annuaire Entreprises : pas de cle (public)

2. **Le pipeline prend du temps** (~5-15 min pour 1000 prospects). Il faut :
   - L'executer en arriere-plan (job asynchrone, worker, ou subprocess)
   - Envoyer un feedback de progression au frontend (WebSocket, SSE, ou polling)
   - Ne pas bloquer la requete HTTP

3. **Seule dependance externe** : `requests` (Python) ou `fetch`/`axios` (JS/TS)

4. **RGPD** : respecter le flag `againstDirectMarketing` de Mappy — si true, ne pas stocker le telephone

5. **Deduplication** : utiliser le SIRET comme identifiant unique. Ne pas inserer de doublons si le prospect existe deja en base.

## Interface utilisateur souhaitee

```
┌──────────────────────────────────────────┐
│  Generer des prospects                   │
│                                          │
│  Niche : [Artisan Batiment        ▼]     │
│  Nombre : [500________________]          │
│                                          │
│  [Lancer la generation]                  │
│                                          │
│  ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ 60%              │
│  312 / 500 prospects enrichis            │
│  287 avec telephone                      │
└──────────────────────────────────────────┘
```

Le bouton doit etre accessible depuis la page principale des prospects/contacts du CRM. Adapte le style au design system existant du CRM.

## Resume

Analyse la stack du CRM, adapte le pipeline a cette stack, cree la route API + l'UI + le job asynchrone, et mappe les prospects dans le modele existant. Si le CRM n'a pas de modele "prospect" ou "contact", cree-le. L'objectif : un clic, une niche, un nombre, et les prospects apparaissent dans le CRM.
