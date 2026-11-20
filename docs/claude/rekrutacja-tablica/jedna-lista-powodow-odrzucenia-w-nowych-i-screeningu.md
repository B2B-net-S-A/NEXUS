# Jedna lista powodów odrzucenia w „Nowych” i „Screeningu”

<!-- indeks: rozbudowana lista także dla karty ręcznej (`decisionColumn`), bez „Skąd to wiesz?”; od „Zweryfikowanego” lista z szablonu -->

Decyzja Artura z 19.11.2026. Okno „Zamknij proces — odrzucenie” miało w tych
samych kolumnach dwie różne listy: osoba od systemu dostawała rozbudowaną
(„Nie pasuje do wymagań” / „Pieniądze i dane” / „Sprawa osoby”), karta dodana
ręcznie krótką listę z szablonu. Zespół porównał oba okna i wybrał rozbudowane,
a Artur kazał je ujednolicić.

- Odrzucenie z „Nowych” albo „Screeningu” zawsze pokazuje rozbudowaną listę
  (od 19.11.2026 słownik z `lib/close-reasons.ts`), niezależnie od tego, kto dodał kartę
  (`isDecisionColumn` w `lib/autofill-feedback.ts`, prop `decisionColumn`
  w `RejectionV2`). Przy kilku osobach naraz — gdy wszystkie są z tych kolumn.
- Karta ręczna: bez „Skąd to wiesz?”, bez podpowiedzi koszyka raportu
  wyszukiwania i bez „na cały klient” (`AutofillFeedbackField fromSystem={false}`).
  Serwer odrzuca `autofill_*` przy osobie spoza systemu (422), więc idzie tylko
  powód z szablonu z `templateReasonFor`; powód bez odpowiednika to „Inne”
  z nazwą powodu w opisie, a „Nie szuka pracy” niesie datę w `not_looking_until`.
- Od 19.11.2026 (etap 2 jednego słownika, `jeden-slownik-powodow-zamkniecia-procesu.md`)
  ta sama lista jest w każdej kolumnie, nie tylko w „Nowych”/„Screeningu”.
  Grupy liczy `closeReasonGroups` z „Kto kończy?” i etapu: „Klient” tylko
  przy „Odrzuca klient”, „Dane w bazie” tylko w „Nowych”/„Screeningu”, „Inne”
  zawsze na końcu. Listy z szablonu w oknie odrzucenia już nie ma; panel DL
  i karta rozmowy u klienta pokazują wiersze szablonu w kolejności i z
  etykietami słownika (`closeTemplateOptions`).
- Nie wracaj do listy z szablonu i nie dodawaj osobnej wersji okna. Zmiana
  listy = zmiana `frontend/src/lib/close-reasons.ts` i jej lustra
  `backend/app/services/close_reasons.py` (`test_close_reasons.py`).
