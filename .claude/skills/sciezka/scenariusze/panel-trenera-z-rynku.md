# Scenariusz: panel trenera z rynku (0808)

Reguła: `docs/claude/ludzie/panel-trenera-z-rynku.md`. Backend gałęzi na własnej kopii
bazy (zmiana schematu). Trener z rynku i jego firma fikcyjni (Anna Przykładowa,
NIP syntetyczny z poprawną sumą, adres `@example.com`); mail czyta się z Mailpita.

Kto → co robi → co widzi następny:

1. **Admin** — Szkolenia → „Zgłoszenia trenerów”: pasek „Panel trenerów z rynku:
   wyłączony” → „Włącz”.
2. **TCM** — kandydat w „W bazie trenerów” → „Otwórz panel trenera”: NIP, „Biała Lista”
   (na stagingu zapora: rejestr nie odpowie, dane wpisać ręcznie), firma, adres, e-mail →
   zapis. Pasek „Panel otwarty”, w Mailpicie zaproszenie z linkiem `#trener=`.
3. **Trener z rynku** (osobna karta) — link z maila → `/konsultant/szkolenia`, menu tylko
   „Szkolenia” i „Dane do umowy”, dane firmy jak wpisał TCM. Wejście na
   `/konsultant/rozliczenia` wraca do „Szkoleń”.
4. **TCM** — „Zamów szkolenie” (`/trainings/new?market=`), trener z rynku wybrany,
   zapis szkicu, „Wyślij do trenera”.
5. **Trener z rynku** — zamówienie w „Prowadzę”, wycena A–E → „Wyślij wycenę”.
6. **TCM** — przyjęcie wyceny, „Dane do umowy” z firmy trenera (NIP, adres) bez kontraktu.
7. **Rekruter** i **Finanse** — nie otwierają panelu ani włącznika (403 z API), brak
   przycisków.
8. **Konsultant** — `/konsultant` przy panelu konsultanta w stanie stagingu: bez zmian
   (stan `internal` = brak logowania konsultanta; formularz linku prowadzi do panelu trenera).
9. **TCM** — „Zamknij panel” → trener przy odświeżeniu traci sesję.
