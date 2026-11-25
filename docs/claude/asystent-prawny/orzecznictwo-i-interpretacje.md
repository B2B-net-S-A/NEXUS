# Orzecznictwo i interpretacje jako źródło asystenta prawnego (część C, 25.11.2026)

Plan: `docs/asystent-prawny-plan.md` (część C). Asystent działa w tle ekranów
kontraktów i Generatora (decyzja Artura 25.11.2026); ta część daje mu
orzeczenia jako `SourcePassage(kind="case", ref=<sygnatura>, text, url, label)`.

## Źródła — co pobieramy, a co tylko linkujemy

Stan sprawdzony 25.11.2026 (robots.txt, dokumentacja, próbne zapytania).

| Źródło | Co daje | Jak korzystamy | Dlaczego |
|---|---|---|---|
| SAOS (`saos.org.pl/api`) | SN, sądy powszechne, TK, KIO | API: wyszukiwanie i treść | Publiczne API tylko GET, dokumentacja zaprasza do „programowego API” |
| CBOSA (`orzeczenia.nsa.gov.pl`) | NSA i WSA | sam link | Brak API (formularz HTML); serwis nie odpowiadał (brak połączenia / HTTP 500), regulaminu automatu nie dało się przeczytać |
| EUREKA (`eureka.mf.gov.pl`) | interpretacje KIS | sam link | Aplikacja na wewnętrznym API `/api/public/v1` bez dokumentacji i zgody na automat — nie odtwarzamy cudzego API |
| `sn.pl` | SN po 2016 r. | sam link | Bramka antybotowa; SAOS ma SN tylko do 2016 r. |

- **SAOS a `robots.txt`.** SAOS ma `Disallow: /api/`. Czytamy to jako zakaz
  dla robotów indeksujących, nie dla klienta udokumentowanego API: nie
  chodzimy po linkach, pytamy celowanymi zapytaniami, najwyżej **jedno
  zapytanie na sekundę**, User-Agent `NEXUS-legal-sources/1.0` (bez osób,
  adresów i nazwy firmy). Decyzja odwracalna sesji części C; gdyby SAOS
  zgłosił sprzeciw albo opublikował regulamin z zakazem — wyłączyć zasilenie.
- **Zasięg SAOS:** sądy powszechne na bieżąco (orzeczenia z XI 2026), SN do
  2016 r., sądów administracyjnych brak. Nowsze stanowiska SN dają więc
  w zasileniu sądy apelacyjne, a asystent pokazuje link do bazy SN.
- Pobranie z CBOSA, EUREKA albo `sn.pl` to nowa decyzja Artura i zmiana tej
  reguły, nie „przy okazji”. Linki: `services/legal_case_law/links.py`;
  zapytanie użytkownika nie trafia do adresu.

## Pamięć i wyszukiwanie

- Tabela `legal_cases` (0786, DDL w `services/legal_case_law/schema.py`,
  lustro w `entrypoint.sh` przez `hr_schema_bundle`, sonda w `/api/health/deep`):
  sygnatura, sąd, data, rodzaj, adres, teza, tekst, `content_sha256`, tematy,
  `fetched_at`. Klucz: (źródło, id w źródle).
- **Tekst może trafić do modelu:** orzeczenia nie są przedmiotem prawa
  autorskiego (art. 4 pkt 2 pr. aut.). Orzeczenia sądów powszechnych są
  zanonimizowane u źródła; NEXUS nie dopisuje do nich danych.
- Wyszukiwanie (`search_case_law(db, query, *, courts=None, since=None, limit=5)`)
  czyta **tylko bazę**: po słowach (`search_tsv` z tekstu bez polskich znaków,
  `to_tsvector('simple', …)`, najpierw orzeczenia z największą liczbą słów
  pytania) i po znaczeniu (Qdrant `nexus_legal_cases`, id punktu = id wiersza,
  bez tekstu w payloadzie), złączone RRF. Bez Voyage/Qdranta — same słowa.
- Pozycja ma tezę (jeśli źródło ją podaje) i fragment wokół pierwszego słowa
  pytania (~1200 znaków); weryfikator cytatów fundamentu porównuje cytat
  z tym tekstem.
- **Awaria źródła nie jest wyjątkiem:** klient (`legal_case_law/http.py`)
  ponawia 2× przy błędzie sieci, 429 i 5xx (z `Retry-After` do 30 s), a potem
  zwraca `None`; wyszukiwanie i tak nie woła źródeł.

## Zasilenie

`python -m scripts.seed_legal_case_law` (z `backend/`) — tematy w
`services/legal_case_law/ingest.py` (`TOPICS`): umowa B2B a stosunek pracy
(art. 22 KP), przeniesienie autorskich praw majątkowych, kara umowna
i miarkowanie (art. 484 § 2 KC), wypowiedzenie umów o świadczenie usług
(art. 746/750 KC), zakaz konkurencji. SAOS nie sortuje po trafności; bierzemy
orzeczenia najczęściej powoływane (`REFERENCING_JUDGMENTS_COUNT`). Bez pętli
w lifespanie — uruchomienie ręczne (na produkcji po wdrożeniu 0786).

## API

`GET /api/legal/cases/search?q=…&courts=supreme&courts=common&since=RRRR-MM-DD&limit=5`
→ `items` (kształt `SourcePassage`), `retrieval` (`hybrid` / `keywords` /
`none`), `links` (źródła bez API). Bramka jak reszta `/api/legal` (część A):
sekcja Sourcing i Generator umów B2B (`B2BGeneratorAccess`), bo asystent
stoi w tle Generatora i kontraktów. Wzorzec:
`tests/data/authz_golden/legal_case_law.json`.
