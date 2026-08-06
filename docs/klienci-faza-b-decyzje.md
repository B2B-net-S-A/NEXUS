# Faza B ticketów Klienci — decyzje i realizacja

> Kontynuacja [Fazy A](klienci-faza-a-completion-report.md) (analiza:
> [klienci-tickety-analiza.md](klienci-tickety-analiza.md) + [weryfikacja Codexa](klienci-tickety-weryfikacja-codex.md)).
> Decyzje podjęte przez Artura 2026-08-06 na podstawie zmierzonych faktów (niżej).

## Fakty, na których oparto decyzje (zmierzone na prod `304e146`)

| Fakt | Wartość |
|---|---|
| Traffit sync | **WŁĄCZONY** (`/api/health.checks.traffit = healthy`) — ręczny status na kliencie z Traffita cofał się <24h |
| Macierz sekcja×status | Aktywni: 30/30 „active" · Relacyjni: 3/3 „active" (nie „prospect"!) · Nieaktywni: **130× „active"** + 2 prospect + 2 inactive |
| Nieaktywni z aktywnymi konsultantami | **0 ze 134** — sekcje są merytorycznie poprawne; to badge statusu kłamie (default „active" z `normalize_client_status`) |
| Przenoszenie między sekcjami | już istnieje: „Przenieś w portfelu" (#1050, placement override, admin-only, manifest-safe) |
| Duplikat e-Zdrowia | żywy duplikat = **id 37721 „E-Zdrowie"** (0 kontraktorów/konsultantów, 16 historycznych jobów) obok kanonicznego **115 „Centrum e-Zdrowia"** (9 konsultantów); oba widoczne w dropdownie generatora B2B; id 5257 ze starych komentarzy już nie istnieje w powierzchniach appki |
| Needle klauzul §10/PFRON | `"e-zdrowia"` NIE łapie nazwy „E-Zdrowie" → wybór duplikatu w generatorze = umowa bez klauzul Centrum |

## Decyzje

1. **Status klienta = NEXUS-owned.** Importer Traffita seeduje status przy pierwszym
   imporcie, ale **przestaje go nadpisywać** przy kolejnych syncach (`_UPSERT_CLIENT`
   bez `status` w `DO UPDATE SET`). Ręczna edycja statusu z UI (działała od zawsze)
   od teraz się trzyma. Po deployu: jednorazowa kuracja — klienci w sekcji Nieaktywni
   dostają status `inactive` (bezpieczna: 0 z nich ma aktywnych konsultantów).
   Relacyjni (3× active) świadomie nietknięci.
2. **Sekcje NIE wiążą się ze statusem.** Sekcja = `ClientPortfolioScope.category`
   (+ placement override #1050), status = niezależna etykieta lifecycle. Zmiana
   statusu nie przenosi klienta; do przenoszenia służy „Przenieś w portfelu".
   (Odpowiedź na bug 3 ticketa #1: świadome ODRZUCENIE związania — model
   pracownika był oparty na błędnym założeniu, patrz analiza.)
3. **e-Zdrowie: scalić 37721 → 115.** Nowy endpoint `POST /api/clients/{id}/merge-into/{target}`
   (AdminUser): archiwizuje duplikat i wskazuje kanoniczny rekord — historia zostaje,
   wiersz znika z katalogu/lookupów (w tym z dropdownu B2B), detail przekierowuje 307.
   Kolejni kandydaci ścieżki: rodzina „BNP *". Do tego needle klauzul poszerzone
   o `"e-zdrowie"`/`"ezdrowie"` (świadomie BEZ gołego „zdrow" — Zdrowit).
4. **„Przenieś w portfelu" zostaje admin-only.** Kuratela katalogu w jednych rękach;
   pracownicy zgłaszają przeniesienia adminowi.

## Realizacja

- PR Fazy B: importer (`status` poza `DO UPDATE`), endpoint merge + testy
  (`test_client_merge.py`, `test_traffit_client_status_ownership.py`), needle
  `e-zdrowie`/`ezdrowie` + test wariantów nazw, aktualizacja stałego komentarza
  w `ContractRegisterDialog`.
- Po deployu (operacje przez authed API, w tej kolejności — sync nie może cofnąć kuracji):
  1. `POST /api/clients/37721/merge-into/115`,
  2. kuracja: 134 klientów z sekcji Nieaktywni → `PATCH {"status": "inactive"}`,
  3. re-pomiar macierzy sekcja×status (oczekiwane: Nieaktywni bez „active").

## Otwarte na Fazę C

- #3 project_part (bramka po `client_id=115`, enum nullable + mirror w entrypoint).
- #5 epic zakończenia projektu (serwis sync Contract↔Order + drobne bugi z weryfikacji).
- Usunięcie listy „Otwarte rekrutacje" po re-homingu `CloseJobAsLostModal`.
- (Obserwacja bez decyzji: Relacyjni 3× status „active" — jeśli badge ma coś znaczyć,
  wart rozważenia ręczny update na `prospect` przez UI; status już się nie cofnie.)
