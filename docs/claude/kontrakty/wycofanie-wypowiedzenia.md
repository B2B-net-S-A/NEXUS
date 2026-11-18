# „Wycofaj wypowiedzenie” — konsultant wycofał wypowiedzenie zapisane aneksem
<!-- indeks: zgłoszenie Finansów 17.11.2026, pętla Cofnij zakończenie ↔ Przedłuż, aneks early_termination, wybór daty końca (B2B bezterminowo), plan cofnięcia z nadpisaną datą, wpis custom_change z withdrawn_amendment_id, korekta kontraktu 216 -->

Zgłoszenie Finansów z 17.11.2026, wariant B z makiet (decyzja Artura). Umowa
B2B skrócona aneksem „Wcześniejsze zakończenie” (15.12 → 31.10) skończyła się
w nocy, a konsultant wycofał wypowiedzenie. Wszystkie trzy drogi odsyłały do
siebie: „Cofnij zakończenie” brało stan „przed” z migawki nocnego zakończenia
(już po wypowiedzeniu, data 31.10 minęła) i radziło „przedłuż aneksem”;
„Przedłuż” dla B2B był wyłączony z podpowiedzią „Cofnij zakończenie”; zmiana
statusu na „Aktywny” jest przechwytywana. Aneks przedłużający i tak by nie
pomógł: `reopen_contract` zamyka migawkę, więc zamówienia zostają zakończone.

- **Gdzie:** zakładka „Aneksy”, przycisk przy wierszu „Wcześniejsze
  zakończenie”. Bramka jak „Cofnij zakończenie” (Admin, Finanse, TCM;
  `ContractTerminationRecoveryUser` + `notice-withdrawal` w
  `_TERMINATION_RECOVERY_COMMANDS`), niezależna od edycji kontraktu.
- **Które wypowiedzenie:** najnowszy aneks `early_termination`, jeszcze nie
  wycofany, którego data końca dalej stoi na kontrakcie (status aktywny,
  kończący się albo zakończony). Inna data = ktoś ją zmienił po wypowiedzeniu
  i przycisku nie ma (`withdrawable_notice`).
- **Data końca wybiera człowiek:** B2B domyślnie bezterminowo, dalej data
  sprzed wypowiedzenia (gdy nie minęła) albo inna od dziś. Umowa zlecenie
  i o pracę muszą mieć datę (data jest w treści umowy).
- **Wykonanie:** gdy zakończenie ruszyło zamówienia (`reversal_available`)
  — `execute_reversal` z `end_date_override`: zamówienia, sprawy MD i importy
  wracają jak przy „Cofnij zakończenie”, kontrakt na „Aktywny” bez pól
  zakończenia. Wypowiedzenie jeszcze biegnie — tylko kontrakt (data, status,
  `undo_contract_termination`, alert „kontrakt się kończy”).
- **Ślad:** wpis `custom_change` z `annex_title` „Wycofanie wypowiedzenia”
  i `withdrawn_amendment_id`; wycofany aneks ma w tabeli status „Wycofany”
  i nie liczy się już jako ręczne zakończenie
  (`has_early_termination_amendment` pomija go przez `withdrawn_notice_ids`).
  Dokument wycofania wybiera się z Dokumentów kontraktu (opcjonalnie).
- **Blokada `end_date_passed`** w „Cofnij zakończenie” wskazuje „Wycofaj
  wypowiedzenie”, gdy kontrakt ma takie wypowiedzenie (`notice_amendment_id`
  w blokadzie); bez niego zostaje stara rada o aneksie.
- **Korekta zgłoszenia:** kontrakt 216 (trójka ID w
  `contract_notice_withdrawal_repair.py`), umowa bezterminowa, krok
  `repair-notice-withdrawal-2026-11` w entrypoincie, znacznik
  `notice_withdrawal_ticket_2026_11_17`.
- Testy: `backend/tests/test_contract_notice_withdrawal.py`,
  `frontend/src/components/contracts/__tests__/NoticeWithdrawal.test.tsx`.
