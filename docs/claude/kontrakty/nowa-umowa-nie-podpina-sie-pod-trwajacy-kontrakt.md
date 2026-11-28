# Nowa umowa nie podpina się pod trwający kontrakt (28.11.2026)

Decyzja Artura z 28.11.2026 po przeglądzie marży na liście placementów.

**Co się stało.** 18.11.2026 potwierdzono podpis umowy z Generatora (start
01.12.2026, nowa stawka konsultanta) z zaznaczonym „zachowaj dotychczasowe
warunki”. Automat podpiął ją pod kontrakt tej osoby u klienta, który trwał od
02.2025 (import z 26.06.2026). Activity `linked_to_generated_contract` miało
`acknowledged_conflicts = [data rozpoczęcia, stawka kandydata]`. Kontrakt
zachował start z 2025 r. i starą stawkę, a krok stawki od 01.12 nie powstał.
W efekcie placement z 18.11 liczył się od 2025 r. po starych stawkach: lista
placementów, premie z placementów (`contract_margin`) i Płace. Odczyt
produkcji 28.11: 11 podpięć `linked_to_generated_contract`, z czego tylko to
jedno było nową umową na trwającym kontrakcie.

**Reguła.** „Zachowaj warunki” (`keep_existing_contract_terms`) jest dla tej
samej umowy zapisanej dwa razy, np. 68 zł/h w dokumencie i 544 zł/dzień
w kontrakcie (`generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`).
Inny przypadek to podpisana umowa, która startuje PÓŹNIEJ niż kontrakt
aktywny albo kończący się, gdy ten kontrakt już trwa (start przed dziś,
`business_today()`). To nowa umowa, więc
`_new_agreement_on_running_contract` w `services/b2b_contract_automation.py`
zwraca twardy 409 bez `can_keep_existing_terms`. Checkboxa wtedy nie ma,
a komunikat podaje trzy wyjścia:

- dodać w kontrakcie zmianę stawki konsultanta od dnia startu umowy, ze stawką
  z umowy, i potwierdzić podpis jeszcze raz (blokada puszcza, gdy taki etap
  jest w `contract_candidate_rates`; potem działa zwykłe „zachowaj warunki”);
- zakończyć dotychczasowy kontrakt, wtedy podpis zakłada nowy;
- poprawić datę startu kontraktu, jeśli to jednak ta sama umowa.

Automat sam nie dopisuje kroku stawki ani nie zakłada drugiego kontraktu, bo
nie wie, czy umowa to kontynuacja, czy inny projekt. Szkic z „Zatrudniony” ani
kontrakt, który jeszcze nie ruszył, nie są blokowane: różnica dat to tam
zwykły konflikt do potwierdzenia.

E-podpis (`b2b_esign._after_both_signed`) woła to samo potwierdzenie bez flagi.
Przy blokadzie nadawca dostaje dzwonek „oznacz ją w rejestrze”, a w oknie
„Oznacz jako podpisaną” widzi komunikat 409.

Testy: `test_new_agreement_never_links_to_a_running_contract` (z flagą i bez)
i `test_new_agreement_links_once_its_rate_step_is_on_the_contract`
w `backend/tests/test_b2b_signature_automation.py`.
