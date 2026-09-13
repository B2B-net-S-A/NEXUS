# Scalenie duplikatu kontraktu (korekta 0308) — raport

## Co i dlaczego

Czytnik poczty zamówień (09.09.2026, zanim weszła reguła „jedyny imiennik
w bazie wymaga człowieka") dopiął zamówienie do innego rekordu osoby o tym
samym imieniu i nazwisku i założył mu drugi kontrakt u tego samego klienta.
Zgłoszenie: zostawić kontrakt z podpisaną umową B2B, duplikat scalić i usunąć
trwale.

## Jak

Jednorazowa korekta `app/services/contract_duplicate_merge_repair.py`,
odpalana z `entrypoint.sh` (marker `0308_contract_duplicate_merge` + advisory
lock). Para przypięta po ID kontraktów, rekordów osób i klienta — bez nazwisk
w repo. Mechanika jak w sierpniowym scaleniu duplikatów (`contract_merge`):

1. blokady obu kontraktów, sprawdzenie identyfikatorów i bezpieczeństwa
   (podpisy/umowy B2B na duplikacie, konflikt ręcznych kroków stawek, różne
   jednostki/waluty, dwa wiersze szczegółów B2B) — niespełnione = pominięcie
   z kodem powodu w paragonie, oba kontrakty nietknięte;
2. uzupełnienie wyłącznie PUSTYCH pól kontraktu zachowanego; data końca
   i wypowiedzenie duplikatu nie przechodzą;
3. przepięcie wszystkich wierszy potomnych z katalogu FK (zamówienia, kroki
   stawek, dokumenty, faktury, notatki…), historii polimorficznej (Activity,
   powiadomienia, deduplikacja alertów), kontrola, że nic nie wskazuje na
   duplikat, fizyczne `DELETE`;
4. szkic zamówienia z maila przechodzi bramkę `complete_signed_mail_drafts`
   (na kontrakcie z podpisaną umową staje się aktywny i dostaje koszt
   z kontraktu), potem synchronizacja kontrakt ↔ zamówienia;
5. audyt: Activity `contracts_merged` na kontrakcie zachowanym (jak w
   `contract_merge`) + wpis „Usunięcie kontraktu" w Ustawienia → Historia
   zdarzeń (wykonawca: System, powód: scalenie duplikatu).

Paragon `0308_…` — liczniki, ID, kody powodów. Migawka usuniętego wiersza
(do ręcznego odwrócenia) pod `repair_details_0308_…`, niedrukowana przez
workflow `migration-receipts`.

## Weryfikacja

- `tests/test_contract_duplicate_merge_repair.py` — korekta wykonywana na
  prawdziwej bazie: scalenie, idempotencja, pominięcia (niezgodna para,
  konflikt stawek), blok w entrypoincie.
- Po wdrożeniu: paragon (`coolify-ops` → `migration-receipts`,
  klucz `0308_contract_duplicate_merge`) i lista kontraktów.

## Znane ograniczenia

- Rekord osoby, na którym powstał duplikat, zostaje (zgłoszenie dotyczy
  kontraktów).
- Dokument w kolejce poczty zamówień może w swoim JSON-ie planu wciąż
  wskazywać usunięty kontrakt — zamówienie (`applied_order_id`) jest poprawne.
