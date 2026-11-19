# Jedna lista powodów odrzucenia w „Nowych” i „Screeningu”

<!-- indeks: rozbudowana lista także dla karty ręcznej (`decisionColumn`), bez „Skąd to wiesz?”; od „Zweryfikowanego” lista z szablonu -->

Decyzja Artura z 19.11.2026. Okno „Zamknij proces — odrzucenie” miało w tych
samych kolumnach dwie różne listy: osoba od systemu dostawała rozbudowaną
(„Nie pasuje do wymagań” / „Pieniądze i dane” / „Sprawa osoby”), karta dodana
ręcznie krótką listę z szablonu. Zespół porównał oba okna i wybrał rozbudowane,
a Artur kazał je ujednolicić.

- Odrzucenie z „Nowych” albo „Screeningu” zawsze pokazuje rozbudowaną listę
  (`AUTOFILL_REASON_GROUPS`), niezależnie od tego, kto dodał kartę
  (`isDecisionColumn` w `lib/autofill-feedback.ts`, prop `decisionColumn`
  w `RejectionV2`). Przy kilku osobach naraz — gdy wszystkie są z tych kolumn.
- Karta ręczna: bez „Skąd to wiesz?”, bez podpowiedzi koszyka raportu
  wyszukiwania i bez „na cały klient” (`AutofillFeedbackField fromSystem={false}`).
  Serwer odrzuca `autofill_*` przy osobie spoza systemu (422), więc idzie tylko
  powód z szablonu z `templateReasonFor`; powód bez odpowiednika to „Inne”
  z nazwą powodu w opisie, a „Nie szuka pracy” niesie datę w `not_looking_until`.
- Od „Zweryfikowanego” dalej zostaje lista z szablonu (z grupą „Klient”
  i powodami po rozmowie u klienta) — tam pytanie o powód jest inne.
- Nie wracaj do krótkiej listy dla kart ręcznych w tych kolumnach i nie dodawaj
  trzeciej wersji okna. Zmiana listy = zmiana `AUTOFILL_REASON_GROUPS`
  i jej lustra w `backend/app/services/autofill_feedback.py`.
