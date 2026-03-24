import sqlite3 as sql
import pandas as pd
from bs4 import BeautifulSoup
import requests
import re


import os

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BazaDate.db")


# ===================== SETUP BAZĂ DE DATE =====================

def setup_db():
    conn = sql.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Rezultate (
        NumeAnunt TEXT,
        Pret REAL,
        Moneda TEXT,
        Link TEXT UNIQUE,
        Zona TEXT
    )
    """)
    conn.commit()
    conn.close()


# ===================== FUNCTII UTILE =====================

def get_dataframe():
    """Încarcă toate anunțurile din DB într-un DataFrame."""
    conn = sql.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM Rezultate", conn)
    conn.close()
    return df


def obtine_curs_eur_ron():
    try:
        r = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=10)
        data = r.json()
        return data["rates"]["RON"]
    except Exception:
        return 5.0


def _normalizeaza(text):
    """Elimină diacritice și convertește la lowercase pentru matching robust."""
    replacements = {
        'ă': 'a', 'â': 'a', 'î': 'i', 'ș': 's', 'ț': 't',
        'Ă': 'a', 'Â': 'a', 'Î': 'i', 'Ș': 's', 'Ț': 't',
        'ş': 's', 'ţ': 't', 'Ş': 's', 'Ţ': 't',  # variante Unicode vechi
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.lower()


def detecteaza_zona(titlu):
    """
    Detectează zona din Brașov dintr-un text (titlu sau text locație).
    Matching insensibil la diacritice și majuscule.
    Fiecare intrare: (nume_canonical, [cuvinte_cheie_de_căutat])
    """
    zone_brasov = [
        ("Centrul Vechi",   ["centrul vechi", "centru vechi", "old town"]),
        ("Centrul Civic",   ["centrul civic", "centru civic", "civic"]),
        ("Centru",          ["centru", "central", "ultracentral", "piata sfatului",
                             "piata unirii", "str. muresenilor", "muresenilor"]),
        ("Schei",           ["schei", "warthe"]),
        ("Bartolomeu",      ["bartolomeu", "bartholomew"]),
        ("Tractorul",       ["tractorul", "tractor"]),
        ("Astra",           ["astra"]),
        ("Racadau",         ["racadau", "racădău", "racadău"]),
        ("Florilor",        ["florilor"]),
        ("Noua",            ["noua", "cartier nou"]),
        ("Calea Bucuresti", ["calea bucuresti", "calea bucurestilor", "cal. bucuresti",
                             "bd. bucuresti", "bulevardul bucuresti"]),
        ("Grivitei",        ["grivitei", "grivița", "grivita"]),
        ("Scriitorilor",    ["scriitorilor"]),
        ("Craiter",         ["craiter"]),
        ("Blumana",         ["blumana"]),
        ("Valea Cetatii",   ["valea cetatii", "valea cetații", "val. cetatii"]),
        ("Stupini",         ["stupini"]),
        ("Brasovechi",      ["brasovechi", "brașovechi", "orasul vechi"]),
        ("Triaj",           ["triaj"]),
        ("Darste",          ["darste"]),
        ("Avantgarden",     ["avantgarden", "avant garden"]),
        ("Coresi",          ["coresi", "kasper coresi", "urban coresi",
                             "afi brasov", "afi brașov", "pieton coresi",
                             "parcul coresi", "coresi shopping"]),
        ("Urban Residence", ["urban residence", "urban invest", "urban inverst",
                             "urban rezidence"]),
        ("Poiana Brasov",   ["poiana brasov", "poiana brașov", "poiana"]),
        ("Dealul Melcilor", ["dealul melcilor", "melcilor"]),
        ("Saturn",          ["saturn"]),
        ("Carpatilor",      ["carpatilor", "carpați", "carpatii"]),
        ("Steagu",          ["steagu", "steagului"]),
        ("Harman",          ["harman"]),
        ("Sanpetru",        ["sanpetru", "sânpetru"]),
        ("Cristian",        ["cristian"]),
    ]

    text_norm = _normalizeaza(titlu)

    for zona_canon, cuvinte_cheie in zone_brasov:
        for kw in cuvinte_cheie:
            if _normalizeaza(kw) in text_norm:
                return zona_canon
    return 'Necunoscut'


def parseaza_pret(text_pret):
    """
    Extrage prețul numeric și moneda dintr-un șir de text.
    Suportă formate: '2 140,17 lei', '2 804 RON', '350 EUR', '1.500 RON',
    și cazuri cu două prețuri concatenate: '2,142 RON 2,295 RON' (ia primul).

    Returnează (pret_float, moneda_string) sau (None, None).
    """
    text = text_pret.strip()

    # Regex: extrage primul bloc de forma "număr [spații] MONEDĂ"
    # Numărul poate conține cifre, virgule, puncte și spații (separator de mii)
    # Exemplu: "2,142 RON", "2 804 RON", "350 EUR", "1.500 lei"
    m = re.search(
        r'([\d][(\d\s.,]*\d|\d)\s*(RON|EUR|LEI|lei|ron|eur|€)',
        text
    )
    if not m:
        return None, None

    sir_numar = m.group(1).strip()
    sir_moneda = m.group(2).upper()

    # Normalizează monedă
    if sir_moneda in ('LEI', 'RON'):
        moneda = 'RON'
    elif sir_moneda in ('EUR', '€'):
        moneda = 'EUR'
    else:
        moneda = 'RON'

    # Elimină spațiile (separator de mii cu spațiu: "2 804" → "2804")
    sir_numar = sir_numar.replace(' ', '')

    # Normalizare separator . și ,
    if '.' in sir_numar and ',' in sir_numar:
        # ex: "1.234,56" → punct=mii, virgulă=zecimal
        sir_numar = sir_numar.replace('.', '').replace(',', '.')
    elif ',' in sir_numar:
        parts = sir_numar.split(',')
        # Dacă toate grupurile după primul au exact 3 cifre → virgulele sunt separatori de mii
        # ex: "2,142" → ["2","142"] ✓   "2,037,600" → ["2","037","600"] ✓   "1,5" → ["1","5"] ✗
        if all(len(p) == 3 for p in parts[1:]):
            sir_numar = sir_numar.replace(',', '')   # eliminăm toți separatorii de mii
        else:
            sir_numar = sir_numar.replace(',', '.')  # singura virgulă e zecimală
    elif '.' in sir_numar:
        parts = sir_numar.split('.')
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            sir_numar = sir_numar.replace('.', '')   # "1.500" → mii

    try:
        return float(sir_numar), moneda
    except (ValueError, TypeError):
        return None, None


def converteste_la_ron(pret, moneda, curs_eur):
    """Dacă prețul e în EUR, convertește la RON. Altfel returnează ca atare."""
    if moneda == 'EUR':
        return round(pret * curs_eur), 'RON'
    return round(pret), 'RON'


# ===================== SCRAPER OLX =====================

def scrape_olx():
    print("\n=== Pornire scraper OLX ===")

    curs_eur = obtine_curs_eur_ron()
    print(f"[OLX] Curs EUR/RON: {curs_eur:.4f}")

    conn = sql.connect(DB_NAME)
    cursor = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:110.0) Gecko/20100101 Firefox/110.0"
    }

    # Fără ?currency=RON ca să vedem moneda reală a anunțului
    url_baza = "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/brasov/"

    # Prima pagină pentru paginare
    r = requests.get(url_baza, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    pagination = soup.select("a[data-testid^='pagination-link']")
    pagini = [int(p.get_text()) for p in pagination if p.get_text().isdigit()]
    max_pagini = max(pagini) if pagini else 1
    print(f"[OLX] Total pagini: {max_pagini}")

    pagina = 1
    while pagina <= max_pagini:
        print(f"[OLX] Procesare pagina {pagina}/{max_pagini}...")

        url_pagina = f"{url_baza}?page={pagina}"
        r = requests.get(url_pagina, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")

        # Container principal: data-testid="l-card"
        anunturi = soup.find_all('div', {'data-testid': 'l-card'})
        anunturi_reale = [a for a in anunturi if a.find('p', {'data-testid': 'ad-price'})]

        if not anunturi_reale:
            print("[OLX] Nu mai sunt anunțuri. Oprire.")
            break

        for a in anunturi_reale:
            # Titlu: primul heading găsit în card
            titlu_tag = a.find(['h4', 'h3', 'h6', 'h2'])
            titlu = titlu_tag.get_text(strip=True) if titlu_tag else "Titlu indisponibil"

            # Preț
            pret_el = a.find('p', {'data-testid': 'ad-price'})
            text_pret = pret_el.get_text(strip=True) if pret_el else ''
            pret_numeric, moneda = parseaza_pret(text_pret)
            if pret_numeric is None:
                print(f"  [SKIP] Preț neparsabil: '{text_pret}'")
                continue

            pret, moneda = converteste_la_ron(pret_numeric, moneda, curs_eur)

            # Link: clasa css-1tqlkj0 este cel mai stabil selector OLX pentru link-ul cardului
            link_tag = a.find('a', class_='css-1tqlkj0')
            if not link_tag:
                # Fallback: orice <a> cu href care conține /d/
                link_tag = a.find('a', href=re.compile(r'/d/'))
            if link_tag and link_tag.get('href'):
                href = link_tag['href']
                if href.startswith('http'):
                    link = href  # deja absolut (ex: storia.ro)
                else:
                    link = 'https://www.olx.ro' + href
            else:
                link = 'Link indisponibil'

            # Zonă: 1) extrage din elementul de locație al cardului OLX
            #        format: "Brasov, Coresi - Azi la 14:02" → vrem "Coresi"
            zona = 'Necunoscut'
            loc_el = a.find('p', {'data-testid': 'location-date'})
            if loc_el:
                loc_text = loc_el.get_text(strip=True)
                # elimină partea cu data/ora (după " - ")
                loc_text = loc_text.split(' - ')[0].strip()
                # dacă formatul e "Brasov, Zona" → luăm ce e după virgulă
                if ',' in loc_text:
                    loc_text = loc_text.split(',', 1)[1].strip()
                zona = detecteaza_zona(loc_text)
            # 2) Fallback: caută în titlu
            if zona == 'Necunoscut':
                zona = detecteaza_zona(titlu)

            cursor.execute("""
            INSERT OR IGNORE INTO Rezultate (NumeAnunt, Pret, Moneda, Link, Zona)
            VALUES (?, ?, ?, ?, ?)
            """, (titlu, pret, moneda, link, zona))

        conn.commit()
        pagina += 1

    conn.close()
    print("=== Scraper OLX terminat ===\n")


# ===================== SCRAPER PUBLI24 =====================

def scrape_publi24():
    print("\n=== Pornire scraper Publi24 ===")

    curs_eur = obtine_curs_eur_ron()
    print(f"[Publi24] Curs EUR/RON: {curs_eur:.4f}")

    conn = sql.connect(DB_NAME)
    cursor = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:110.0) Gecko/20100101 Firefox/110.0",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
        "Referer": "https://www.google.ro/"
    }

    # Prima pagină pentru paginare
    url_prima = "https://www.publi24.ro/anunturi/brasov/?q=chirie&pag=1"
    r = requests.get(url_prima, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    # Detectează numărul maxim de pagini din link-urile de paginare
    # Caută toate link-urile care conțin pag=N în URL
    max_pagini = 1
    for a_tag in soup.find_all('a', href=re.compile(r'pag=\d+')):
        m = re.search(r'pag=(\d+)', a_tag['href'])
        if m:
            nr = int(m.group(1))
            if nr > max_pagini:
                max_pagini = nr
    print(f"[Publi24] Total pagini detectate: {max_pagini}")

    pagina = 1
    while pagina <= max_pagini:
        print(f"[Publi24] Procesare pagina {pagina}/{max_pagini}...")

        url = f"https://www.publi24.ro/anunturi/brasov/?q=chirie&pag={pagina}"
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")

        anunturi = soup.find_all('div', class_='article-item')
        if not anunturi:
            print("[Publi24] Nu mai sunt anunțuri. Oprire.")
            break

        for a in anunturi:
            # Titlu și link: primul <a> semnificativ din card
            titlu = "Titlu indisponibil"
            link = 'Link indisponibil'

            # Caută <h2 class="article-title"> sau direct primul <a> cu text
            titlu_tag = a.find('h2', class_='article-title')
            if titlu_tag:
                a_tag = titlu_tag.find('a')
            else:
                # Fallback: primul <a> cu text din card
                a_tag = a.find('a', href=True)

            if a_tag:
                titlu = a_tag.get_text(strip=True) or titlu
                href = a_tag.get('href', '')
                if href.startswith('http'):
                    link = href
                elif href:
                    link = 'https://www.publi24.ro' + href

            # Zonă
            zona_el = a.find('p', class_='article-location')
            if not zona_el:
                zona_el = a.find(class_=re.compile(r'locat', re.I))
            zona = zona_el.get_text(strip=True) if zona_el else detecteaza_zona(titlu)

            # Preț: span.article-price — Publi24 folosește spațiu ca separator de mii!
            pret_el = a.find('span', class_='article-price')
            if not pret_el:
                # Fallback: cauta orice element cu clasa ce conține 'price'
                pret_el = a.find(class_=re.compile(r'price', re.I))
            if not pret_el:
                continue

            # getText complet (inclusiv copii) pentru a prinde "2 804 RON"
            text_pret = pret_el.get_text(separator=' ', strip=True)
            pret_numeric, moneda = parseaza_pret(text_pret)
            if pret_numeric is None:
                print(f"  [SKIP] Preț neparsabil: '{text_pret}'")
                continue

            pret, moneda = converteste_la_ron(pret_numeric, moneda, curs_eur)

            cursor.execute("""
            INSERT OR IGNORE INTO Rezultate (NumeAnunt, Pret, Moneda, Link, Zona)
            VALUES (?, ?, ?, ?, ?)
            """, (titlu, pret, moneda, link, zona))

        conn.commit()
        pagina += 1

    conn.close()
    print("=== Scraper Publi24 terminat ===\n")


# ===================== FUNCTII PENTRU AFISARE / FILTRARE =====================

def afiseaza_toate_anunturile():
    df = get_dataframe()
    if df.empty:
        print("\nNu există anunțuri în baza de date.\n")
        return

    print(df)
    print("\nDoriți exportarea datelor în Excel? (da/nu)")
    raspuns = input().strip().lower()
    if raspuns == 'da':
        df.to_excel("anunturi_total.xlsx", index=False)
        print("Datele au fost exportate în 'anunturi_total.xlsx'.")
    else:
        print("Datele nu au fost exportate.")


def filtreaza_dupa_pret(prag_inf, prag_sup):
    df = get_dataframe()
    filtrat_df = df[(df['Pret'] >= prag_inf) & (df['Pret'] <= prag_sup)].reset_index(drop=True)

    print(f"\nAm găsit {len(filtrat_df)} anunțuri între {prag_inf} și {prag_sup}:\n")
    print(filtrat_df[['NumeAnunt', 'Pret', 'Link']])

    print("\nDoriți exportarea datelor filtrate în Excel? (da/nu)")
    raspuns = input().strip().lower()
    if raspuns == 'da':
        filtrat_df.to_excel("filtru_pret.xlsx", index=False)
        print("Datele au fost exportate în 'filtru_pret.xlsx'.")
    else:
        print("Datele nu au fost exportate.")


def filtreaza_dupa_zona(zona_cautata):
    df = get_dataframe()
    filtrat_df = df[df['Zona'].str.lower().str.contains(zona_cautata.lower(), na=False)].reset_index(drop=True)

    print(f"\nAm găsit {len(filtrat_df)} anunțuri în zona '{zona_cautata}':\n")
    print(filtrat_df[['NumeAnunt', 'Zona', 'Pret', 'Link']])

    print("\nDoriți exportarea datelor filtrate în Excel? (da/nu)")
    raspuns = input().strip().lower()
    if raspuns == 'da':
        filtrat_df.to_excel("filtru_zona.xlsx", index=False)
        print("Datele au fost exportate în 'filtru_zona.xlsx'.")
    else:
        print("Datele nu au fost exportate.")


def filtreaza_dupa_pret_si_zona(prag_inf, prag_sup, zona_cautata):
    df = get_dataframe()
    filtrat_df = df[
        (df['Pret'] >= prag_inf) &
        (df['Pret'] <= prag_sup) &
        (df['Zona'].str.lower().str.contains(zona_cautata.lower(), na=False))
    ].reset_index(drop=True)

    print(f"\nAm găsit {len(filtrat_df)} anunțuri între {prag_inf} și {prag_sup} în zona '{zona_cautata}':\n")
    print(filtrat_df[['NumeAnunt', 'Pret', 'Zona', 'Link']])

    print("\nDoriți exportarea datelor filtrate în Excel? (da/nu)")
    raspuns = input().strip().lower()
    if raspuns == 'da':
        filtrat_df.to_excel("filtru_pret_zona.xlsx", index=False)
        print("Datele au fost exportate în 'filtru_pret_zona.xlsx'.")
    else:
        print("Datele nu au fost exportate.")


# ===================== MENIU PRINCIPAL =====================

def main():
    setup_db()

    while True:
        print("""
========== MENIU ==========
1. Rulează scrapers (OLX + Publi24)
2. Afișează toate anunțurile
3. Filtrează anunțurile în funcție de preț
4. Filtrează anunțurile în funcție de zonă
5. Filtrează anunțurile în funcție de preț și zonă
6. Ieșire
===========================
""")
        optiune = input("Alege o opțiune (1-6): ").strip()

        if optiune == '1':
            scrape_olx()
            scrape_publi24()
        elif optiune == '2':
            afiseaza_toate_anunturile()
        elif optiune == '3':
            try:
                print("Doriți să filtrați în RON sau EUR? (introduceți RON sau EUR)")
                moneda = input().strip().upper()
                if moneda == 'EUR':
                    curs = obtine_curs_eur_ron()
                    prag_inf_eur = float(input("Introduceți pragul inferior de preț în EUR: "))
                    prag_sup_eur = float(input("Introduceți pragul superior de preț în EUR: "))
                    prag_inf = int(prag_inf_eur * curs)
                    prag_sup = int(prag_sup_eur * curs)
                    filtreaza_dupa_pret(prag_inf, prag_sup)
                else:
                    prag_inf = int(input("Introduceți pragul inferior de preț (RON): "))
                    prag_sup = int(input("Introduceți pragul superior de preț (RON): "))
                    filtreaza_dupa_pret(prag_inf, prag_sup)
            except ValueError:
                print("Trebuie să introduceți valori numerice pentru preț.")
        elif optiune == '4':
            zona_cautata = input("Introduceți zona dorită: ")
            filtreaza_dupa_zona(zona_cautata)
        elif optiune == '5':
            try:
                print("Doriți să filtrați în RON sau EUR? (introduceți RON sau EUR)")
                moneda = input().strip().upper()
                zona_cautata = input("Zona dorită: ")
                if moneda == 'EUR':
                    curs = obtine_curs_eur_ron()
                    prag_inf_eur = float(input("Pragul inferior de preț în EUR: "))
                    prag_sup_eur = float(input("Pragul superior de preț în EUR: "))
                    prag_inf = int(prag_inf_eur * curs)
                    prag_sup = int(prag_sup_eur * curs)
                else:
                    prag_inf = int(input("Pragul inferior de preț (RON): "))
                    prag_sup = int(input("Pragul superior de preț (RON): "))
                filtreaza_dupa_pret_si_zona(prag_inf, prag_sup, zona_cautata)
            except ValueError:
                print("Trebuie să introduceți valori numerice pentru preț.")
        elif optiune == '6':
            print("Ieșire din program.")
            break
        else:
            print("Opțiune invalidă. Încearcă din nou.")


if __name__ == "__main__":
    main()