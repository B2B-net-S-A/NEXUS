# Numer u klienta przy nazwie rekrutacji — raport (15.10.2026)

## Skąd zmiana

Prośba Delivery Leada Nordei: tytuły dla rekrutera są uogólnione („IT Analyst”,
trzy otwarte „Senior IT Analyst”), więc bez numeru requestu nie wiadomo, która
rekrutacja to który projekt — na liście `/jobs`, w nagłówku rekrutacji i na
szynie „Otwarte karty”. Makiety i decyzje D1–D6:
https://claude.ai/artifact/NWv2twJNrZkp9c5x8ruAwz (wariant A, wszyscy klienci).

## Co się zmieniło

- **Znacznik numeru** (`ClientReferenceChip`) przed nazwą: wiersz listy, linia 1
  nagłówka (także po „Zwiń”), szyna „Otwarte karty” (numer w miejscu ikony)
  i okruszki. Klik kopiuje cały numer; kilka numerów = pierwszy i „+N”.
  Pole „Szukaj” listy: „Numer, tytuł, klient, technologia…” (szukało po numerze od 0380).
- **Numer z nazwy od klienta** (`reference_from_title`): ZOB, `RITM…`,
  `PKN…`/`EITE…`, 4–6 cyfr w nawiasie. Nowe rekrutacje: numer z nazwy wygrywa
  z kodem PEP/TP#, który brał odczyt maila (D5).
- **Jednorazowe uzupełnienie** (faza `client-reference-from-title`
  w `entrypoint.sh`, marker `client_reference_from_title_2026_10`) — tylko puste
  pola; wyjątki: PEP/TP → numer z nawiasu (D4), „(42855)” → „42855”.
- **Tytuł dla rekrutera** bez prefiksu klienta i swojego numeru, gdy rola
  w Championie jest przepisaną nazwą od klienta (D6).
- **Dzwonek Cpro** nie dubluje numeru, który stoi już w nazwie.
- Reguły: `docs/claude/rekrutacja-tworzenie/trzy-nazwy-rekrutacji.md` (nowa
  sekcja), wyjątek w regule wiersza listy v3 i w K-D3 nagłówka.

## Sucha próba na danych produkcji (odczyt, 15.10.2026)

Nowa funkcja na nazwach wszystkich 4467 rekrutacji, lokalnie:

| Klient | Otwarte: dojdzie numer | Zamknięte: dojdzie numer |
|---|---|---|
| Nordea | 61 (3 z dwoma numerami) | 1965 |
| Orlen | 9 | 14 |
| Alior | 7 | 4 |
| BNP Paribas | 6 | 214 |
| Energa | 3 | 4 |
| PKO BP | 2 | 6 |

D4: dwie otwarte rekrutacje Nordei (PEP… → numer z nawiasu, TP#… → numer
z nawiasu). Zgadza się z pomiarem SQL sprzed zmiany.

## Weryfikacja

- Backend bez bazy: 147 testów zielonych (`test_job_working_title.py`,
  `test_stage_handoff_notifications.py`, `test_cv_role_title.py`,
  `test_startup_timing_logs_script.py`, `test_job_request_intake.py`); testy
  z Postgresem (w tym uzupełnienie) — CI.
- Front: 10 plików, 593 testy zielone; `type-check` czysty.
- Harnessy 1280×720: lista (`ZOB 48213`, `SAP 4500123456`, `41228 +1`), szyna,
  nagłówek rozwinięty i po „Zwiń” (nagłówek 56 px, „Nowi” na 0,20 okna — bez zmian).

## Po wdrożeniu

1. `/api/health` = SHA z maina ze zmianą.
2. Paragon w `app_settings` (`client_reference_from_title_2026_10`) — liczby jak wyżej.
3. Lista `/jobs` z filtrem Nordei: numery przy wszystkich rekrutacjach z numerem w nazwie.

## Wiadomość dla DL Nordei (wysyła Artur)

> Numer requestu jest już widoczny: na liście rekrutacji przed nazwą, w nagłówku
> rekrutacji (klik kopiuje) i na pasku otwartych kart. Szukanie po numerze działa
> w polu „Szukaj”. Jedno pytanie: przyjęliśmy, że numer Nordei to ten w nawiasie
> na końcu nazwy (np. 42946), a PEP i TP# to kody projektu — zgadza się?
