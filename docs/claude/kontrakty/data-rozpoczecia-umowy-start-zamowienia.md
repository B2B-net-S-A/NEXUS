# Data rozpoczęcia umowy ≠ start zamówienia (korekta 21.09.2026)

`contracts.start_date` to dzień, od którego obowiązuje UMOWA z konsultantem —
nie początek bieżącego zamówienia (ten żyje w `client_order_start_date`).
Import rejestrów 23–26.06.2026 wpisał w nią start zamówienia/zaślepkę (291
z 475 kontraktów błędnych); korekta z arkusza działu:
`services/contract_start_date_repair.py` + blok `repair-contract-start-dates`
w `entrypoint.sh` (marker `0334_contract_start_date_correction`, przypięta do
trójki ID i stanu z 21.09). Raport: `docs/contract-start-date-correction-completion-report.md`.

- **Żaden import ani automat nie wypełnia `start_date` okresem zamówienia**
  przy istniejącym kontrakcie. Zmierzone przed korektą: w 30 dziennych zrzutach
  nic poza ludźmi tej daty nie zmieniało — tak ma zostać.
- Formularz edycji odsyła datę przy KAŻDYM zapisie; dziennik „updated" niesie
  `previous_start_date` tylko przy realnej zmianie — po nim szukaj, kto zmienił datę.
- „Start date" w profilu klienta czyta `contracts.start_date` wprost; nie
  dokładaj tam drugiego źródła.
