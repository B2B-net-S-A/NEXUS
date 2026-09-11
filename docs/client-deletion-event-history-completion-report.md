# Usuwanie klienta z profilu + Historia zdarzeń — raport końcowy

Migracja `0307_client_deletion_event_history` (+ lustro w `backend/entrypoint.sh`).

## Co powstało

| Obszar | Zmiana |
|---|---|
| Profil klienta | Przycisk **„Usuń klienta"** (obok „Edytuj") — widoczny wyłącznie dla osób z imiennym uprawnieniem, niezależnie od statusu klienta |
| Okno usuwania | Ocena po otwarciu → blokada (lista powodów) albo potwierdzenie „Czy na pewno chcesz usunąć tego klienta? Wpisz 0, jak chcesz usunąć." Klient z historią dostaje nad nim zdanie „U tego klienta występują: …" |
| Ustawienia | Nowa zakładka **„Historia zdarzeń"** (Admin + Finanse) — kto, kiedy, jaka operacja, jaki obiekt, wynik i powód; filtry obiekt / wynik / tekst, stronicowanie |
| Administracja → użytkownicy | Pole „Może usuwać klientów" w edycji konta + znacznik „Usuwa klientów" na liście |

## Zasady

1. **Uprawnienie imienne** (`users.can_delete_clients`, domyślnie `false`).
   Nie wynika z żadnej roli — administrator bez zaznaczonego pola też nie
   usunie klienta. Każde nadanie/odebranie trafia do Historii zdarzeń.
   W trybie „podgląd jako" usuwanie jest zablokowane.
2. **Blokada twarda** — niezależnie od `clients.status`:
   * otwarte zamówienia okresowe (szkic / aktywne / wstrzymane), także przez
     kontrakt klienta,
   * otwarte zamówienia MD/kosztowe (szkic / aktywne / zaplanowane),
   * aktywni kontraktorzy (kontrakt aktywny / kończący się / w podpisie),
   * kandydaci w niezamkniętych rekrutacjach klienta.

   Kliknięcie „Usuń klienta" przy blokadzie zapisuje zablokowaną próbę; próba
   wykonania (ponowna ocena pod blokadą wiersza klienta) — też.
3. **Klient pusty** (ta sama ocena co czyszczenie „Nieaktywnych", 0303) →
   usunięcie trwałe z nagrobkiem dla syncu Traffita i znacznikiem w manifeście
   portfela.
4. **Klient z historią** → znika ze wszystkich list (`deleted_at` +
   `archived_at`), ale wiersz zostaje: zakończone kontrakty, zamówienia, umowy,
   archiwum konsultantów, kontakty — nic nie jest kasowane.
5. **Potwierdzenie „0"** w każdym przypadku; serwer odrzuca inne wartości (422).

## Historia zdarzeń — co trafia na start

| Operacja | Obiekt | Uwagi |
|---|---|---|
| Usunięcie klienta | Klient | wykonane (trwale / z zachowaniem historii) i zablokowane (blokada, brak uprawnienia, podgląd) |
| Usunięcie kandydata / kontraktora | Kontraktor | **bez imienia i nazwiska** (usunięcie z art. 17 RODO) — `Kandydat #id` + pseudonim z odpiętych umów |
| Usunięcie konsultanta z zamówienia MD/kosztowego | Kontraktor | także pozostawienie jako historia, gdy osoba miała rozliczenia |
| Usunięcie kontraktu | Kontrakt | także wymuszone usunięcie przy podpisanej umowie B2B; odmowy (podpis kwalifikowany, podpisana B2B) jako zablokowane |
| Usunięcie umowy ramowej | Umowa | szkic — trwale; pozostałe — „zastąpiona" |
| Usunięcie wygenerowanej umowy B2B | Umowa | odmowy (podpisana, cudza umowa) jako zablokowane |
| Usunięcie zamówienia okresowego | Zamówienie | szkic — trwale; pozostałe — anulowane (opis w kolumnie wyniku) |
| Usunięcie zamówienia MD/kosztowego | Zamówienie | odmowa przy rozliczeniach jako zablokowana |
| Zmiana uprawnienia do usuwania klientów | Uprawnienia użytkownika | nadanie / odebranie |

Wpisy nie mają kluczy obcych — przeżywają usunięcie obiektu i konta osoby,
która je wykonała. API nie pozwala ich edytować ani kasować, dlatego **nie
niosą imion i nazwisk kontraktorów/kandydatów** — obiekty identyfikują numery
(kontrakt, zamówienie, linia, umowa B2B), a zablokowana próba usunięcia klienta
zapisuje rodzaj i liczbę blokad (nazwiska widać tylko na żywo w oknie).

## Przegląd adwersarialny — co poprawiono przed wdrożeniem

* Blokada nie widziała konsultanta pracującego na zamówieniu MD zamkniętym
  z datą w przyszłości / z wyczerpaną pulą (linia `active` pod grupą
  `completed`/`exhausted`, kontrakt-szkic) — linie są teraz sprawdzane same.
* Nazwiska kontraktorów w etykietach i szczegółach wpisów — usunięte (RODO).
* Usunięty klient wisiał w Pomoc → Klienci i był osiągalny przez profil /
  zapisy zamówień po ewentualnym cofnięciu archiwizacji — odrzucany po
  `deleted_at`.
* Odmowy „brak uprawnienia" deduplikowane (10 min na osobę i klienta).

## Nowe / zmienione endpointy

| Metoda | Ścieżka | Kto |
|---|---|---|
| POST | `/api/clients/{id}/deletion-check` | osoby z `can_delete_clients` |
| DELETE | `/api/clients/{id}?confirmation=0` | osoby z `can_delete_clients` (zastępuje dawny admin-only `DELETE`) |
| GET | `/api/settings/event-history` | Admin, Finanse |
| PUT | `/api/admin/users/{id}` | Admin — nowe pole `can_delete_clients` |

## Schemat (0307)

* `users.can_delete_clients BOOLEAN NOT NULL DEFAULT false`
* `clients.deleted_at TIMESTAMPTZ`, `clients.deleted_by → users(id) ON DELETE SET NULL`
* `purged_clients.run_id` — `DROP NOT NULL` (ręczne usunięcie nie należy do przebiegu czyszczenia)
* `critical_events` (+ 3 indeksy), sonda w `/api/health/deep`

## Aktywacja

Po wdrożeniu **nikt** nie ma uprawnienia do usuwania. Administrator w
Ustawieniach → Administracja → edycja użytkownika zaznacza „Może usuwać
klientów" dla czterech osób wskazanych w zgłoszeniu. Imiona nie są zaszyte
w kodzie ani w migracji (repo jest publiczne).

## Testy

* `backend/tests/test_client_deletion.py` — uprawnienie imienne (admin bez flagi
  → 403 + wpis), blokada przy błędnym statusie „nieaktywny", kandydaci
  w otwartej rekrutacji, klient pusty (wymagane „0", nagrobek), klient z historią
  (dane zostają, profil 404), dostęp do Historii (Admin/Finanse vs DL/rekruter),
  wpis przy nadaniu uprawnienia, wpisy umowy ramowej i zamówienia, zapis
  odmowy w osobnej sesji.
* `backend/tests/test_finance_role_endpoint_guards.py` — bramka usuwania to
  uprawnienie imienne, a dawny `DELETE` z `clients.py` zniknął.
* Front: `DeleteClientDialog.test.tsx`, `EventHistoryTab.test.tsx`,
  `UserModal.test.tsx`, `settings/page.test.tsx`.

## Znane ograniczenia

* Przywrócenie klienta usuniętego z zachowaniem historii nie ma przycisku —
  wymaga zdjęcia `deleted_at`/`archived_at` w bazie.
* Pozostałe krytyczne operacje (np. usunięcia notatek, dokumentów) nie trafiają
  jeszcze do Historii zdarzeń — dołożenie to `audited_deletion` w endpoincie
  i etykieta w `EVENT_TYPE_LABELS`.
