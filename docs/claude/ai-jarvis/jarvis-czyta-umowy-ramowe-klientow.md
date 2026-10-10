# Jarvis czyta umowy ramowe klientów (0426, 09.10.2026)

Zgłoszenie: na pytanie „ile Bank Pocztowy ma czasu na akceptację Karty Czasu
Pracy” Jarvis odpowiadał, że nie ma dostępu do treści umów. Decyzje Artura
09.10.2026: wyszukiwanie po znaczeniu (embeddingi), treść umów może iść do
Voyage i Anthropic, bramka jak pobranie PDF-a. Raport:
`docs/jarvis-client-agreements-completion-report.md`.

- **Tekst mieszka w Postgresie, w Qdrancie same wektory.** Tabela
  `client_framework_contract_chunks` (ciągłe fragmenty ok. 800 znaków) jest
  źródłem treści; kolekcja `nexus_client_documents` trzyma wektory z
  **id punktu = id wiersza fragmentu** i bez tekstu w payloadzie. Trafienie
  bez wiersza w bazie (usunięta umowa, podmieniony plik, klient usunięty
  kaskadą) odpada samo, a o dostępie rozstrzyga baza. Nazwa kolekcji nie może
  zaczynać się od `nexus_candidates` — `delete_candidate_embedding` kasuje
  punkt o id kandydata z każdej takiej kolekcji.
- **Bez pętli i bez outboxu** (outbox jest zaszyty pod kandydata i ofertę).
  Plik czyta zadanie w tle po wgraniu i podmianie (`index_after_upload`),
  a gdy stan nie zgadza się z plikiem (`text_file_path != file_path`) —
  pierwsze pytanie o umowę (`ensure_indexed`, czeka najwyżej 30 s, bieg trwa
  dalej w tle). Dlatego pliki wgrane przed 0426 nie potrzebują backfillu.
  Kod: `services/framework_contract_index.py` (zapis, Qdrant, wyszukiwanie),
  `framework_contract_text.py` (czyste funkcje).
- **Wektory są dodatkiem.** Stan `text_status`: `indexed` | `text_only`
  (fragmenty bez wektorów — Voyage albo Qdrant nie odpowiedział; ponowienie
  najwcześniej po 10 min) | `unreadable` (pusty tekst) | `failed`. Bez wektorów
  odpowiada ranking po słowach (rdzenie bez polskich znaków, waga IDF);
  z wektorami oba rankingi łączy `reciprocal_rank_fusion`, a odpowiedź niesie
  `retrieval` (`hybrid` | `keywords` | `none`). Wyłącznik
  `FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED=false` = nic nie idzie do Voyage.
- **Po co embeddingi:** umowy nazywają rzeczy inaczej niż ludzie. Umowa Banku
  Pocztowego nie zna frazy „Karta Czasu Pracy” (pisze „Karta Ewidencji
  Świadczenia…”). Koszt nie jest argumentem w żadną stronę: embedding całej
  umowy to ok. 0,002 USD, a jedno dodatkowe wywołanie modelu w turze Jarvisa
  ok. 0,03 USD — dlatego jedno narzędzie szuka od razu we wszystkich umowach
  klienta.
- **Trasy** (bramka `LegalDocsReader`, ta sama co `/file`: „Stawki i kwoty:
  podgląd” u klienta z zakresu): `GET …/framework-contracts/search?q=`
  (zarejestrowana PRZED `/{fc_id}`) i `GET …/framework-contracts/{fc_id}/text
  ?from_chunk=`. Narzędzia Jarvisa `search_framework_contracts`
  i `read_framework_contract` mają własny `shape` bez `trim` na tekście
  fragmentu — limit znaków (`PASSAGE_BUDGET`) pilnuje serwer. Nie dopisuj ich
  do `WEB_SAFE_TOOLS`.
- **Stan odczytu nie rusza `updated_at` umowy** (jawne
  `updated_at=ClientFrameworkContract.updated_at` w każdym UPDATE).
- **Skan:** OCR czyta 10 pierwszych stron (limit ekstraktora CV), a
  `reading_note` mówi to przy umowie, gdy znaków na stronę jest mniej niż 200.
- Stan indeksu: `GET /api/admin/index-coverage` → `client_documents`.
  Kolekcji nie sprawdza żadna sonda `/api/health`.
- Poza zakresem: aneksy, PDF-y zamówień, umowy kontraktorów, plakietka stanu
  odczytu w zakładce „Umowy”.
