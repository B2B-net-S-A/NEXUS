# Jarvis czyta umowy ramowe klientów — raport

Data: 09.10.2026. Migracja `0426_framework_contract_text`.

## Problem

Na pytanie „ile Bank Pocztowy ma czasu na akceptację Karty Czasu Pracy” Jarvis
odpowiadał, że nie ma dostępu do treści umów. Plik umowy był w NEXUSIE, ale
Jarvis nie miał żadnego narzędzia do umów ramowych.

## Pomiar przed budową (produkcja, tylko odczyt)

- 40 umów ramowych, 2 z plikiem: plik testowy (14 bajtów) i umowa Banku
  Pocztowego (43 strony, PDF z warstwą tekstu, 109 tys. znaków, odczyt 4 s).
  Pozostałe 38 to daty z importu bez PDF-a. Aneksów z plikiem: 0.
- Umowa Banku Pocztowego nie zawiera frazy „Karta Czasu Pracy” ani razu;
  używa nazwy „Karta Ewidencji Świadczenia…” (9 wystąpień).
- Koszt: embedding umowy ok. 0,002 USD (ok. 35 tys. tokenów, voyage-3,
  liczba tokenów oszacowana z liczby słów), jedna tura Jarvisa średnio
  0,08 USD (14 tur z 14 dni), jedno wywołanie modelu w turze ok. 0,03 USD.

## Decyzje Artura (09.10.2026)

1. Wersja z embeddingami, wyszukiwanie po słowach jako zapas.
2. Treść umów może iść do Voyage (wektory) i Anthropic (odpowiedź Jarvisa).
3. Dostęp jak do pliku umowy: admin, Finanse, Delivery Lead u swoich klientów.

## Co powstało

- Tabela `client_framework_contract_chunks` i kolumny stanu odczytu
  `client_framework_contracts.text_*`; lustro DDL w `entrypoint.sh`, sondy
  w `/api/health/deep`.
- Kolekcja Qdranta `nexus_client_documents` (same wektory; id punktu = id
  wiersza fragmentu).
- Odczyt pliku w tle po wgraniu i podmianie oraz leniwie przy pierwszym
  pytaniu — pliki wgrane wcześniej nie wymagają backfillu.
- Trasy `GET /api/clients/{id}/framework-contracts/search?q=` i
  `GET …/framework-contracts/{fc_id}/text?from_chunk=`.
- Narzędzia Jarvisa `search_framework_contracts` i `read_framework_contract`,
  sekcja promptu „UMOWY Z KLIENTAMI”, zdanie w procedurze Pomocy o Jarvisie.
- Wyłącznik `FRAMEWORK_CONTRACT_EMBEDDINGS_ENABLED` i blok `client_documents`
  w `GET /api/admin/index-coverage`.

## Poza zakresem

Aneksy, PDF-y zamówień, umowy kontraktorów; plakietka stanu odczytu
w zakładce „Umowy”; OCR ponad 10 stron; wyciąganie warunków umowy do pól
karty klienta; umowy na scalonych duplikatach klienta.

## Weryfikacja

Uzupełniana po wdrożeniu — patrz opis PR-a.
