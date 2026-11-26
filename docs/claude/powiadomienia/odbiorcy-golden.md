# Odbiorcy powiadomień pilnuje notify_golden
<!-- indeks: tests/data/notify_golden, NOTIFY_GOLDEN_WRITE, bell_roles, mail_roles, relations, relations_db, _notify_matrix, test_historia_*, do_decyzji, persony z _authz_matrix -->

Powiadomienia trafiały do złych ludzi, a każdy taki błąd był rozszerzeniem
odbiorców, którego nikt nie zobaczył w PR-ze: 02.11.2026 „Podsumowanie Rady”
z przychodem i marżą firmy dostało 11 osób, w tym 5 z Finansów; dzwonki
z czatu rekrutacji szły do nieprzypisanych (18.11.2026); ruchy etapu do
prowadzących o cudzych kandydatach (10.11 i 18.11.2026). Wzorzec odbiorców
robi z takiej zmiany diff do przeglądu, tak jak `authz_golden` robi to
z dostępem do tras.

## Co jest we wzorcu

`backend/tests/data/notify_golden/`, persony te same co w
`tests/_authz_matrix.py` (polityka produkcji):

- `bell_roles.json` — brama dzwonka (`notification_access.user_can_receive_notification`,
  ta sama w `emit`, liście, mailu i dymku) dla każdego `NotificationType`;
  typy kontekstowe w wariantach (czat rekrutacji albo kandydata, link wzmianki).
- `mail_roles.json` — brama maila (`notification_email_prefs.APPLIES`) dla
  każdego rodzaju z `CATALOG`; maile do kandydata i maile bezpieczeństwa
  w `poza_regula_konta`.
- `relations.json` i `relations_db.json` — wybór odbiorców przez funkcję
  producenta na obsadzie fikcyjnych kont: Rada i admini, przypisani do
  rekrutacji, rekruter kandydata, DL klienta, alarmy firmy. Wersja z bazą
  zakłada obsadę w transakcji i ją wycofuje.

Brama mówi, kto może dostać, producent wybiera, kto dostaje. Dzwonek idzie do
części wspólnej, więc wzorzec trzyma obie warstwy.

## Zasady

- **Zmiana odbiorców = diff wzorca w PR-ze.** Czerwony test wypisuje rodzaj
  i personę z „było/jest”. Zamierzoną zmianę przegeneruj i opisz w PR-ze, kto
  zaczyna albo przestaje dostawać:
  `cd backend && NOTIFY_GOLDEN_WRITE=1 python -m pytest tests/test_notify_golden.py tests/test_notify_golden_db.py`.
- **Nowy typ albo rodzaj maila też wywraca test**, bo jego odbiorcy to
  decyzja, a nie skutek uboczny. Nowy typ kontekstowy dostaje warianty
  w `CONTEXT_VARIANTS`; nowy producent z własnym wyborem odbiorców — wpis
  w `relations*.json` (funkcja producenta, nie kopia jej logiki).
- **Przypadki z historii mają osobne asercje** (`test_historia_*` w obu
  plikach). Przegenerowanie ich nie zmienia — rozszerzenie Rady, czatu albo
  ruchu etapu wymaga świadomej zmiany testu i decyzji Artura.
- **`do_decyzji` w pliku wzorca** to rodzaj, którego odbiorcy dziś różnią się
  od reguły. Wzorzec zapisuje stan kodu; wpis (`TO_DECIDE` w
  `tests/_notify_matrix.py`) przeżywa przegenerowanie, dopóki ktoś nie
  rozstrzygnie sprawy. Dzwonki Rady (`board_krs_entry`, `board_meeting_pack`,
  `board_vote`) wpuszcza brama każdemu z odczytem Insights; dziś zawęża je
  tylko producent.
- `test_notify_golden.py` biegnie bez bazy jako strażnik repo na każdym PR-ze;
  `test_notify_golden_db.py` potrzebuje Postgresa (sito PR-a i kolejka).
