# Podpis umowy B2B oznacza autor, zespół rekrutacji, DL klienta albo TCM (19.10.2026)

Zgłoszenie z 19.10.2026: rekruterka z uprawnieniem „Umowy B2B: oznaczanie
jako podpisane” wygenerowała umowy w rekrutacjach, w których nie była w zespole,
i rejestr pokazywał przy nich „Brak przypisania do powiązanej rekrutacji”. Od
#2020 (04.10.2026) współpracownik dopisany automatycznie z kategorii nie liczy
się do zespołu, więc blokada wróciła. Serwer (`ensure_job_membership`) i tak by
ją przepuścił — blokowała sama lista.

## Reguła (decyzja Artura 19.10.2026)

Posiadacz uprawnienia oznacza podpis wiersza rejestru, gdy spełnia JEDNO z:

- ma rolę admin, Head of Recruitment, TCM albo Delivery Lead (DL — tylko
  u klientów z portfela, jak dotąd: `_assert_signature_client_access`),
- jest autorem umowy (`created_by`),
- jest w zespole rekrutacji umowy (`_jobs_run_by`: prowadzący, TAC, DL
  rekrutacji, aktywne przypisanie, ręczny współpracownik — bez `auto_cc`).

Jedna funkcja `_may_confirm_row_signature` w `api/b2b_contract_generator.py`
liczy to dla listy (`can_confirm_signed`, `blocked_reason`) i dla
`POST /generated/{id}/confirm-fully-signed` (403 z tym samym komunikatem).
Lista i endpoint nie mogą się znowu rozjechać.

## Kto ma uprawnienie

- Generowanie umów: domyślnie rekruter, DL, HoR, TCM, Finanse (poziom
  „zarządzanie”, `action_permissions._GENERATOR_DEFAULTS`).
- Oznaczanie podpisu: domyślnie DL i TCM; rekruterom Artur nadaje je
  **imiennie** w Ustawienia → Osoby i role.
- Nie nadawaj go całej roli Rekruter, dopóki aneksy, wypowiedzenia
  i zawiadomienia partnera (`api/b2b_documents.py`, `_confirmer_entry`,
  `/documents/partner-notice`) nie mają tej samej reguły „autor albo zespół”:
  dziś posiadacz uprawnienia potwierdza je w całej firmie.
