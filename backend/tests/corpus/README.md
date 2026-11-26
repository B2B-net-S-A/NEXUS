# Korpus czytników

Prawdziwe przypadki, na których czytnik się mylił, w postaci, którą da się uruchomić
na dowolnej rewizji. Każda poprawka czytnika z ostatnich 30 dni daje co najmniej
jeden przypadek; poprawka, która czytnika nie dotyczy, ma wpis z powodem
w `<czytnik>/_poprawki.json`.

- `czytniki.json` — czytniki, ich pola i ścieżki kodu (z nich korzysta hook
  `eval-czytnikow-gate.js`: PR zmieniający te pliki potrzebuje świeżego wyniku evalu).
- `<czytnik>/*.json` — przypadki zanonimizowane (repo jest publiczne: osoby, adresy,
  numery umów i nazwy klientów fikcyjne, domeny `example.com` / `example.pl`;
  prawdziwe domeny tylko z rejestru `known_clients`, bo od nich zależy odczyt).
- `~/.nexus-staging/corpus/<czytnik>/` — pełne przypadki z kopii produkcji, tylko lokalnie
  (`scripts/eval_reader_export.py`).

Uruchomienie (z `backend/`, venv z `requirements.txt`):

```bash
python scripts/eval_reader.py rozliczenia --przed origin/main --po HEAD
python scripts/eval_reader.py cv --przed origin/main --po HEAD
# czy przypadek łapie poprawkę: przed nią pada, po niej przechodzi
python scripts/eval_reader.py cv --przed 697c9117a^ --po 697c9117a --filtr 4033 --tylko-repo
```

Pliki zaczynające się od `_` nie są przypadkami. Plik może mieć jeden przypadek
(obiekt) albo listę. `id` jest unikalne w czytniku i zaczyna się od numeru PR-a
poprawki, `poprawka` to `"<sha> #<PR>"`, `opis` jednym zdaniem mówi, co czytnik
robił źle. `znany_blad` (tekst) = przypadek, którego czytnik dziś nie przechodzi,
świadomie zostawiony; test w CI go pomija, eval liczy.

## `rozliczenia` — poczta rozliczeń end-to-end

Eval zakłada czystą bazę (schemat z `Base.metadata` rewizji), sieje osoby z przypadku,
woła `mailbox.run_once` na atrapie skrzynki i czyta zapisane `CpDocument`.
Każdy przypadek biegnie w transakcji cofanej na końcu. Domena firmy: `firma.example.com`.

```json
{
  "id": "rozl-3876-nazwisko-po-zmianie",
  "poprawka": "9371d812f #3876",
  "opis": "Plik ze starym nazwiskiem trafia do osoby z kartoteką „Nowa (Stara)”",
  "dzis": "2026-10-05",
  "portal": "internal",
  "ustawienia": {"NAZWA_FLAGI": true},
  "uzytkownicy": {"DL": {"email": "dl.korpus@firma.example.com", "rola": "delivery_lead"}},
  "klienci": {"K1": {"nazwa": "Bank Przykładowy", "kontakty": ["koordynator@bank.example.com"], "dl": "DL", "id": 18, "nip": "..."}},
  "osoby": {
    "A": {"imie": "Kornelia", "nazwisko": "Nowa (Stara)", "email": "kartoteka@example.com",
          "email_kontraktu": "kornelia@example.com", "klient": "K1", "status": "active",
          "od": "2026-01-01", "do": null,
          "kontrakty": [{"klient": "K1"}, {"klient": "K2", "od": "2026-10-01"}]}
  },
  "zamowienia": [{"numer": "AbC/77/2026", "klient": "K1", "osoby": ["A"]}],
  "maile": [{
    "id": "m1", "od": "koordynator@bank.example.com", "do": ["rozliczenia@firma.example.com"],
    "temat": "Protokół wrzesień 2026", "odebrano": "2026-10-02T08:00:00Z", "tresc": "…",
    "pliki": [
      {"nazwa": "Protokół Kornelia Stara 09.2026.pdf", "pdf": "linia 1\nkolumna\tkolumna"},
      {"nazwa": "TS.xlsx", "arkusz": {"Arkusz1": [["Imię i nazwisko", "Kornelia Nowa"], ["Suma", 21]]}},
      {"nazwa": "Raport.docx", "docx": ["akapit", [["wiersz", "tabeli"]]]},
      {"nazwa": "skan.png", "b64": "…"}, {"nazwa": "x.pdf", "plik": "pliki/x.pdf"}
    ],
    "eml": "surowy mail (dla .eml i maili w mailu)", "graph": {"pole Graph": "nadpisanie"}
  }],
  "oczekiwane": [
    {"plik": "Protokół Kornelia Stara 09.2026.pdf", "rodzaj": "report", "osoba": "A", "okres": "2026-09"},
    {"plik_zawiera": "TS", "osoba": null}
  ],
  "liczba_dokumentow": 2
}
```

- `osoba`: klucz osoby (`"A"`, drugi kontrakt `"A#2"`) albo `null` = plik czeka na
  ręczne przypisanie. `rodzaj`: `report` / `invoice` (jak `CpDocument.kind`).
  `okres`: `RRRR-MM`.
- Klucze klientów w `osoby.*.klient` bez wpisu w `klienci` tworzą klienta o tej nazwie.
- `id` klienta tylko wtedy, gdy czytnik ma politykę po ID produkcji (BIK 18 itd.).
- `pdf` to tekst (linie, kolumny po tabulatorze) zapisany jako PDF z polskimi literami.

## `cv` — treść Nowego CV

Bez bazy. Dwa etapy, przypadek używa jednego:

- **odczyt pliku** (`cv_parser`): `wejscie.odczyt = {"tekst": "tekst CV", "model": {…}}` —
  wynik modelu zapisany przy odczycie przechodzi `finalize_claude_cv_output`
  (nazwa z nagłówka, kontakt z regexu, normalizacja dat i szkół); `model: null` =
  sama heurystyka. Pola: `daty` (`od`, `do`, `firma`, `stanowisko`), `edukacja`
  (`uczelnia`, `kierunek`, `stopien`, `rok`), `nazwa` (`imie`, `nazwisko`), `jezyki`.
- **treść Nowego CV** — wejście jak w generatorze: `generator` (zapis `render_payload`), opcjonalnie
`zrodlo` (tekst oryginału CV → `restore_experience_dates`) i `html` (HTML edytora →
`cv_json_from_editor_html` z `generator` jako `fallback`), potem
`NewCvDocument.from_cv_json`.

```json
{
  "id": "cv-4033-ma-in-economics",
  "poprawka": "697c9117a #4033",
  "opis": "…",
  "dzis": "2026-11-25",
  "wejscie": {"jezyk": "en", "blind": false, "generator": {"name": "…", "experience": [], "education": [], "languages": []},
              "zrodlo": "tekst oryginału", "html": "<h1>…</h1>"},
  "oczekiwane": {
    "daty": [{"daty": "03.2023 - obecnie", "staz": "3 years 9 mo.", "firma": "…", "stanowisko": "…"}],
    "edukacja": [{"uczelnia": "…", "kierunek": "Economics", "stopien": "MA", "rok": "2017"}],
    "nazwa": [{"imie_nazwisko": "…", "stanowisko": "…"}, {"stanowisko_roli": "…"}],
    "jezyki": [{"jezyk": "Polish", "kod": "PL", "poziom": "…", "stopien": 6}, {"_brak": true, "jezyk": "Java Developer"}],
    "liczba_jezyki": 2
  }
}
```

Każdy wpis listy porównuje się z wpisem o tym samym numerze i tylko po podanych
kluczach. `nazwa[0]` to osoba i tytuł CV, dalsze wpisy to nazwy stanowisk po kolei.
`_brak: true` = wpisu z tymi polami nie może być pod tym numerem; `liczba_<pole>` =
dokładna liczba wpisów.
