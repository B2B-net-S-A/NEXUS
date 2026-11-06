# Data podpisu umowy B2B z podpisu konsultanta w pliku (0654, 06.11.2026)

Decyzja Artura z 06.11.2026 (premia 200% na listopad i grudzień): dzień podpisu
umowy pochodzi z podpisu kwalifikowanego konsultanta w podpisanym PDF-ie, nie
z kliknięcia „Oznacz jako podpisaną”. Płace sprawdziły 7 umów: w 6
dzień kliknięcia wypadał w tym samym miesiącu co podpis, ale w jednej
(Nordea) DL oznaczył podpis 30.10, a konsultant podpisał 02.11
07:32 — premia 200% trafiłaby do października. Okno podpowiadało wtedy
dzisiejszą datę, a plik był dobrowolny (na produkcji 9 z 9 sprawdzonych umów
nie miało pliku).

## Reguły

- **Plik podpisanej umowy jest obowiązkowy.** `POST
  /api/b2b-generator/generated/{id}/confirm-fully-signed` jest multipart: `file`
  (PDF, JPG, PNG, do 20 MB, jak skan aneksu) i `payload` (JSON:
  `candidate_id`, `job_id`, `keep_existing_contract_terms`, przy podpisie
  odręcznym `signed_on` i `signed_on_reason`). Plik trafia do Dokumentów
  kontraktu jako „Umowa” w tej samej transakcji co podpis (`signed_file.attach`),
  więc nie ma już podpisu bez pliku ani drugiego kroku, który mógł się nie udać.
  „Dołącz podpisaną umowę” z wiersza zostaje dla starych wierszy i podmiany.
- **Odczyt podpisów: `services/b2b_contract_generator/signed_on_evidence.py`.**
  pyHanko bez sieci (`approval_signatures` z `signing/pades.py`): podpisujący
  z certyfikatu (CN, a bez CN imię i nazwisko z osobnych pól), czas ze
  znacznika czasu w podpisie, a bez niego czas deklarowany w podpisie,
  spójność podpisu (plik zmieniony po podpisie = naruszony). Strona podpisu:
  konsultant, gdy nazwa z certyfikatu zawiera imię i nazwisko z umowy
  (`partner_name`, `b2b_esign/verdict.name_matches`), firma — gdy pasuje do
  aktywnego konta w NEXUSIE, inaczej „inna osoba”.
- **Dzień podpisu = dzień najwcześniejszego nienaruszonego podpisu konsultanta**
  w kalendarzu firmy (`signed_on_source = 'pdf'`, `consultant_signed_at` =
  chwila podpisu). Ręczna data z okna wtedy się nie liczy.
- **PDF z podpisami, ale bez podpisu konsultanta = 422**, umowy nie da się
  oznaczyć jako podpisanej obustronnie (także gdy podpis konsultanta jest
  naruszony). Komunikat wymienia podpisujących z pliku, nie dane umowy.
- **Skan bez podpisu elektronicznego (podpis odręczny)**: data wpisana ręcznie
  (bez domyślnej daty w oknie) i obowiązkowy powód, np. „podpis odręczny 09.10”
  (`signed_on_source = 'manual'`, `signed_on_reason`, `signed_on_set_by`).
  Granice daty jak dotąd: nie z przyszłości, nie sprzed wygenerowania umowy.
- **E-podpis w NEXUSIE** (`b2b_esign._after_both_signed`): `signed_on` = dzień
  `contractor_signed_at`, `signed_on_source = 'esign'`.
- **Podgląd w oknie**: `POST /api/b2b-generator/generated/{id}/signatures`
  (multipart, nic nie zapisuje, te same bramki co `signed-file`, wyjątek sekcji
  Sourcing jak `confirm-fully-signed`). Okno pokazuje listę podpisów (imię
  i nazwisko, data i godzina, konsultant/firma) i „Data podpisu konsultanta”.
  Potwierdzenie czyta plik jeszcze raz — podgląd nie jest dowodem.
- **To nie jest walidacja podpisu kwalifikowanego.** Ta droga nie sprawdza listy
  zaufanych UE (to robi droga e-podpisu, `b2b_esign/qualified.py`); okno mówi
  to wprost. Potwierdzenie zostaje deklaracją uprawnionej osoby, a plik daje
  datę i ślad.
- **Płace poprawiają dzień podpisu** z powodem w karcie „Premia 200%”
  (`ludzie/premia-200-tcm-gwarancja.md`). Pierwsza poprawka na produkcji:
  umowa z października na 02.11.2026 — robi Artur albo Płace w UI po wdrożeniu.

## Kolumny (0654, lustro w `entrypoint.sh`)

`b2b_generated_contracts.signed_on_source` (`pdf` | `manual` | `esign`, CHECK
`ck_b2b_generated_contracts_signed_on_source`), `signed_on_reason`,
`signed_on_set_by` (FK users), `consultant_signed_at`. Starszych wierszy nie
uzupełniamy: NULL = oznaczenie sprzed 06.11.2026.
