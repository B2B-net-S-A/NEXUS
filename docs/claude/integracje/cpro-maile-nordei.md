# Maile CPro od Nordei zmieniają statusy w NEXUSIE (02.11.2026)
<!-- indeks: `noreply@onevms.se`, `services/cpro_mail.py`, pętla `cpro_mail`, dziennik `/settings/cpro`, zamknięcie i odrzucenie z maila, Authentication-Results -->

CPro (`nordea.onevms.se`) to system Nordei do zamawiania konsultantów. Wysyła
Delivery Leadom maile z `noreply@onevms.se`, a numer w tytule to
`jobs.client_reference`. Pomiar 12.10–02.11.2026 w skrzynkach obu DL-i: 334
maile, 24 rekrutacje zamknięte ręcznie po mailu (16 w ciągu 15 minut), 2 otwarte
dalej mimo zamknięcia w CPro, 40 ze 115 odrzuconych przez klienta nadal „w toku”.
Makiety: https://claude.ai/artifact/NDLBxLTB1GZZpWMQst5Hnk.

## Decyzje Artura (02.11.2026)

- **Zamknięty request:** NEXUS zamyka wszystkie otwarte rekrutacje z tym numerem.
  „consultant contracted” → `competitor`, „demand change” → `budget`, reszta →
  `other` (wtedy trafia do przeglądu zamknięć). Autor pusty, notatka z powodem.
- **Odrzucenie:** karta do „Zamknięci”, `ended_by="client"`, „Candidate withdrew”
  jako rezygnacja. **Kandydat nie dostaje nic**, prowadzący dostaje dzwonek
  i „Napisz do kandydata”. Karta przesunięta po mailu zostaje na miejscu.
- **Wiadomość przy zamknięciu:** dzwonek i mail do każdego rekrutera z kartą
  w toku, także w „Nowych” (`notify_closed_from_cpro`). To wyjątek od reguły
  „automaty nie piszą do rekruterów” z `rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md`.
- **Start od razu, bez okresu próbnego;** zaległości od `CPRO_MAIL_SINCE` (12.10)
  automat nadrabia w pierwszym przebiegu, także 42280 i 42693.

## Reguły, które łatwo cofnąć

- **Osoba w „Akceptacji i umowie” albo zatrudniona zatrzymuje zamknięcie.**
  Automat pyta DL-a dzwonkiem `cpro_close_needs_decision`. Cztery rekrutacje
  wygrane przez nas nie miały maila o zamknięciu, więc „consultant contracted”
  to zwykle cudza osoba, ale automat nie wpisze przegranej przy naszej umowie.
- **Prośba o rozmowę, wycofanie, zmiana terminów = tylko dzwonek.** Mail nie
  podaje terminów, są wyłącznie w CPro. Mail starszy niż 2 dni nie dzwoni.
- **Nadawca jest sprawdzany przy każdym mailu** (`verify_with_graph`): adres,
  `Authentication-Results` (`sender_authenticated`) i link do `nordea.onevms.se`.
  Domena ma DMARC `p=none`, więc nikt inny nie odrzuci podszytego maila; samo pole
  „Od” nie wystarcza. Brak potwierdzenia = wiersz „Do ręcznego”, zero zmian.
  Treść bierzemy z Grapha, bo `emails` bywa puste.
  Wiersz odmowy jest ostateczny: gdyby kontrola okazała się za ostra, po poprawce
  usuń z `cpro_mail_events` wiersze „Nie potwierdzono nadawcy…” i kolejny przebieg
  przeczyta te maile jeszcze raz.
- **Numeru nie zgadujemy.** Brak numeru w NEXUSIE albo osoby w rekrutacji =
  „Do ręcznego”. 42845 i 42846 to dwa requesty, a w NEXUSIE jest tylko 42846:
  mail o 42845 nie może zamknąć 42846.
- **Stary mail nie zamyka rekrutacji otwartej ponownie** po jego dacie.
- **Jeden mail = jeden wiersz** `cpro_mail_events` (klucz `internetMessageId`),
  więc kopia w drugiej skrzynce i restart niczego nie powtarzają.
- Automat nie obsługuje: `Offer:`, `Re:`, zmian w umowach, nowych zapytań
  `Request:`. Temat spoza `SUBJECT_FILTER` nic nie zmienia.

## Gdzie to siedzi

- Odczyt bez bazy: `services/cpro_mail_parse.py`. Przebieg: `services/cpro_mail.py`.
- Pętla `cpro_mail` co 3 minuty (`tasks/cpro_mail.py`), na stagingu zablokowana.
  Kill-switch `CPRO_MAIL_ENABLED`, wyłączniki reguł w `app_settings['cpro_mail:rules']`.
- Trasy `api/cpro_mail.py`: `GET /api/cpro/log`, `PUT /api/cpro/rules` (HoR, admin),
  `GET /api/jobs/{id}/cpro-events`. Front: `JobCproBanner`, `CproSettings`,
  `/settings/cpro`. Dziennik ostrzega, gdy skrzynka nie synchronizuje się od godziny:
  24 z 34 maili o zamknięciu przyszły tylko do jednej osoby.
- Migracja 0630, DDL w `services/cpro_mail_schema.py` (czyta go też `entrypoint.sh`).
