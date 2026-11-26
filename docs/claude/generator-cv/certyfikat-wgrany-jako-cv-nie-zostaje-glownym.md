# Certyfikat wgrany jako CV nie zostaje głównym CV (26.11.2026)
<!-- indeks: `cv_certificate.looks_like_certificate_text`, `_set_aside_certificate`, `certificate_check` w `_after_cv_commit`, `restore_previous_primary`, źródło kopii etapu `certificate_restore`, akcja `cv_upload_is_certificate` -->

Decyzja Artura z 26.11.2026 (wariant „poprawa + strażnik w kodzie”).

## Skąd

Zgłoszenie DL CEZ „NEXUS wypełnia tylko 50% CV do CEZ”. U jednej osoby
formularz CV klienta czytał certyfikat PRINCE2 zamiast CV. Plik wgrano
z rekrutacji jako „CV” i jako najnowszy wygrywał wybór, a podsumowanie profilu
brzmiało „kandydat posiadający certyfikat PRINCE2”.

Pomiar na kopii produkcji 26.11.2026: tekst CV był certyfikatem u 2 z 66 675
osób (PRINCE2 i certyfikat Pega jako główne CV). Oba profile poprawione ręcznie
na produkcji (rodzaj „Certyfikat”, prawdziwe CV jako główne). Rodzaju
„certyfikat” nie miał wtedy żaden plik w bazie.

## Reguła

- **Odczyt nowo wgranego pliku CV sprawdza tekst, zanim pójdzie do modelu**
  (`_enrich_candidate_from_document_task(certificate_check=True)`, włączane
  w `_after_cv_commit`). Dotyczy to wgrania w profilu, „Dodaj plik” jako CV,
  CV z integracji (scrapery) i nowego CV z rekrutacji. Certyfikat to tekst
  do 4000 znaków z formułą certyfikatu („This is to certify”, „Certificate
  of Achievement”, „Certificate Number”, „zaświadcza się”…) i bez żadnej
  sekcji CV („experience”, „doświadczenie”, „education”, „skills”…).
  Detektor na wszystkich 66 675 tekstach z kopii: 2 trafienia, oba prawdziwe.
- **Certyfikat:** plik dostaje rodzaj „certyfikat” i traci „główne”, główne CV
  i `cv_filename` wracają do poprzedniego pliku (`restore_previous_primary`,
  ta sama logika co kwarantanna tożsamości), a kopie CV etapu do CV osoby
  ze źródłem `certificate_restore`. Panel mówi wtedy: „Oryginał CV: poprzednie
  CV · … — wgrany plik to certyfikat”. Profil zostaje bez zmian, model
  nie jest wołany. Ślad: `Activity` `cv_upload_is_certificate`.
- **Świadomy wybór nie jest sprawdzany:** „Ustaw jako główne”, „Ponów odczyt”
  i plik z profilu wskazany jako oryginał CV etapu. Rekruter, który wie, że
  plik to CV, zmienia rodzaj z powrotem i ustawia go jako główne.

## Czego to nie robi

- Nie zmienia nazwy pliku ani pliku w magazynie i niczego nie kasuje.
- Nie sprawdza nowej osoby zakładanej z CV (`POST /api/candidates/from-cv`).

Testy: `backend/tests/test_cv_certificate.py`,
`frontend/src/lib/__tests__/dock-cv-summary.test.ts`.
