# Strażnik parametrów płac na 1 stycznia (16.11.2026)

Jeden z trzech strażników po „Przepisach” (radar zmian w prawie, decyzja Artura
z 15.11.2026). Lista płac bierze wersję parametrów z dnia wypłaty, więc bez
wersji od 1 stycznia styczniowe listy liczą się na stawkach z poprzedniego roku
(lista zatrzymuje się dopiero przy zatwierdzeniu: `params_previous_year`).

## Co robi

- Od 30 dni przed 1 stycznia (`business_today()`, od 2 grudnia) do chwili, gdy
  jest żywa wersja z `effective_from` = 1 stycznia, odczyt
  `GET /api/hr/payroll-lists/parameters` ma pole `next_year` ze szkicem.
  Po Nowym Roku pilnuje dalej roku bieżącego, dopóki wersji od 1.01 nie ma.
  Wersja od 1 lutego nie wycisza komunikatu.
- Komunikat „Brak parametrów płac od 01.01.RRRR” stoi na: Księgowość → Lista płac
  (widok „Lista płac” i „Parametry”) oraz Ludzie → Rozliczenia (`/people/payroll`,
  tylko osoby z Płacami i admin; moduł płac wyłączony = 404 = brak komunikatu).
- Przycisk otwiera formularz „Nowa wersja od…” wypełniony szkicem: wartości
  bieżącej wersji (brakujące klucze K7b z `LATER_DEFAULTS`) plus wartości
  ogłoszone na nowy rok. Pod każdą wartością wstępną jest źródło z linkiem
  (akt, data ogłoszenia, poprzednia wartość), a uwaga wersji wymienia akty.
- **Nic nie zapisuje się samo.** Odczyt niczego nie dopisuje; zapis to ten sam
  `POST /parameters` co zawsze (wersja „Do potwierdzenia”), a potwierdzenie
  robią Płace jak dotąd. Uprawnienia bez zmian.

## Jak dopisać kolejny rok

- `backend/app/services/hr/payroll_lists/next_year.py`, słownik `KNOWN`:
  rok → wpisy `KnownValue(klucz, wartość, akt, adres ELI, data ogłoszenia)`.
  Tylko wartości z ogłoszonych aktów, sprawdzone w treści aktu (nie w metadanych).
- 2027: płaca minimalna 4950 zł i 32,30 zł/h (Dz.U. 2026 poz. 1213, ogł. 15.09.2026),
  limit 30-krotności 300 990 zł (M.P. 2026 poz. 1098, ogł. 4.11.2026; prognozowane
  przeciętne wynagrodzenie 10 033 zł).
- Nie zgadujemy reszty: progi i kwoty PIT 2027 zostają jak w bieżącej wersji
  (16.11.2026 zmiana ustawy po Senacie), a komunikat `UNCHANGED_NOTE` każe je
  sprawdzić razem z limitem dobrowolnej chorobowej i stopą wypadkową.
- Testy: `tests/test_payroll_params_next_year.py` (daty, szkic, źródła),
  `test_next_year_guard_drafts_but_never_saves` w `tests/test_payroll_lists_db.py`,
  `frontend/.../payroll/__tests__/next-year-guard.test.tsx`.
