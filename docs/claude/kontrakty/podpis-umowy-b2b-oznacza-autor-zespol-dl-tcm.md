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

## Dokumenty do umowy i wypowiedzenie Partnera (19.10.2026)

Ta sama reguła obejmuje aneksy, wypowiedzenia, porozumienia i pozostałe
dokumenty do umowy (`api/b2b_documents.py`): „Oznacz jako podpisany”
(`/documents/{id}/confirm-signed`), skan podpisanego aneksu
(`/documents/{id}/signed-scan`) i „Zarejestruj wypowiedzenie Partnera”
(`/documents/partner-notice`). Posiadacz uprawnienia potwierdza, gdy:

- ma rolę z `_SIGNS_EVERY_CONTRACT_ROLES` (DL dalej tylko w portfelu),
- jest autorem dokumentu albo umowy bazowej,
- jest w zespole rekrutacji umowy bazowej (dokument bez umowy bazowej —
  jego własnej rekrutacji).

Inaczej niż w rejestrze umów, przy dokumencie nikt nie wskazuje rekrutacji,
więc umowa bez rekrutacji (np. wiersz z Excela) zostaje autorowi i rolom
z listy. `_may_confirm_document_signature` woła `_may_confirm_row_signature`
z `open_without_job=False` — bez drugiej kopii reguły. Ta sama funkcja liczy
`can_confirm_signed` dokumentu na liście i 403 na trasach
(„Podpis tego dokumentu oznacza…”).

Bez zmian: aneks stawki potwierdza też posiadacz „Stawki i kwoty: zmiana”
u klienta, u którego zmienia kwoty (Finanse, decyzja 27.09.2026) — ta droga
nie patrzy na autora ani zespół.

## Kto ma uprawnienie

- Generowanie umów: domyślnie rekruter, DL, HoR, TCM, Finanse (poziom
  „zarządzanie”, `action_permissions._GENERATOR_DEFAULTS`).
- Oznaczanie podpisu: w katalogu (`permission_catalog.SIGNATURE`) domyślnie
  DL, TCM i od 19.10.2026 rekruter. Uprawnienie ma `seeded=False`: wiersz
  roli w bazie pochodzi z migracji 0282 (rekruter = `none`) i zasiew go nie
  nadpisuje, więc całej roli Rekruter nadaje je Artur w Ustawienia → Osoby
  i role. Wcześniej rekruterom nadawał je imiennie.
