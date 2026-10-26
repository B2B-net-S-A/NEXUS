# Podpis umowy B2B w NEXUSIE — druga droga obok „Oznacz jako podpisaną” (0499, 21.10.2026)

Zgłoszenie Administracji 21.10.2026: umowa krąży mailem (Sandra → kontraktor
→ Olaf → rekruter → Dominik → Administracja), a do NEXUSA nic nie wraca. Artur
wybrał „własny tor + dostawca podpisu” zamiast pełnej platformy (Autenti), jako
OPCJĘ obok drogi zwykłej. Makiety: https://claude.ai/artifact/EgDmMEUdfLf5tFhQ2unyQE.

## Reguły

- **Droga zwykła zostaje zawsze.** Nowa działa za przełącznikiem
  `app_settings['b2b_esign']`: `off` (domyślnie), `pilot` (wysyłają tylko konta
  z `pilot_user_ids`), `all`. Ustawienia zmienia admin
  (`PUT /api/b2b-generator/esign/settings`).
- **Każdy podpis kwalifikowany, obu stron.** Wzór umowy przenosi autorskie
  prawa majątkowe → art. 53 pr. aut. (forma pisemna pod rygorem nieważności,
  projekt „formy dokumentowej” Sejm odrzucił) → elektronicznie tylko podpis
  kwalifikowany. Droga nie zna podpisu zwykłego ani zaawansowanego.
  `services/b2b_esign/verdict.judge`: brak autorytatywnego walidatora (EU DSS)
  = odmowa; każdy podpis ważny i kwalifikowany; wymagane osoby po nazwisku
  z certyfikatu (słowa z NEXUSA ⊆ słowa z certyfikatu).
- **Podpisuje się PDF z tego samego Worda** co „Pobierz DOCX”
  (`_render_generated_row_docx` → `cv_pdf_preview.pdf_from_docx`), zamrożony przy
  wysyłce odciskiem. Każde wgranie musi zaczynać się bajtami poprzedniej wersji
  (`verdict.builds_on`) — podpis PAdES dopisuje się na końcu pliku.
- **Kolejność stała: kontraktor → reprezentant B2B Network.** Kontraktor
  podpisuje z linku (`/sign/b2b/{token}`, API `/api/public/b2b-sign/{token}`,
  token w bazie tylko jako SHA-256), bez konta. Za firmę podpisuje osoba
  wskazana przy wysyłce, z listy `company_signer_ids` w ustawieniach (imienny
  reprezentant — pieczęć firmy nie zastępuje podpisu osoby).
- **Kontrakt nie powstaje przy wysyłce** (reguła „jedna droga do kontraktu”,
  17.09.2026). Wniosek `completed` uruchamia tę samą automatykę co „Oznacz jako
  podpisaną” (PR 5).
- **Kto rozstrzyga „kwalifikowany”** (decyzja Artura 21.10.2026: pyHanko teraz,
  EU DSS później): `B2B_ESIGN_VALIDATOR=pyhanko` (domyślnie) —
  `services/b2b_esign/qualified.py`, lista zaufanych UE (LOTL) pobierana
  w procesie, odświeżana co 12 h, nieudane odświeżenie zostawia poprzednią;
  bez listy walidator nie jest autorytatywny i nic nie przechodzi. `QESig` =
  certyfikat kwalifikowany do podpisu (`qct_esign`) z kluczem na QSCD (także
  zdalnym: SimplySign, mSzafir); pieczęć (`qct_eseal`) nie wystarcza. Zmiany po
  podpisie dozwolone do poziomu „wypełnianie formularza” (kolejne podpisy).
  `B2B_ESIGN_VALIDATOR=dss` przełącza na sidecar EU DSS (`DSS_VALIDATION_URL`).
  Przed pilotażem sprawdzić na prawdziwych plikach (Certum, KIR, mObywatel).
- **Walidacja bez blokady, zapis pod blokadą.** DSS trwa do 30 s, więc
  walidacja idzie bez blokady wiersza, a potem `SELECT … FOR UPDATE` sprawdza
  stan i odcisk jeszcze raz — wycofanie w trakcie walidacji wygrywa (w torze
  z czerwca kończyło się „Zakończona”).
- **Najwyżej jeden wniosek w toku na wiersz rejestru** (indeks częściowy
  `uq_b2b_signing_requests_open_per_row`). Wycofanie (`withdraw`) kasuje link
  i pozwala wysłać ponownie albo wrócić do drogi zwykłej.
- **Wysyła i wycofuje** ten, kto poprawia umowę (`_may_correct_generated`),
  z poziomem „Generowanie”, widocznymi stawkami i dostępem do klienta.
- **Mail z linkiem idzie ze skrzynki nadawcy** (M365, `services/b2b_esign/mail.py`);
  bez połączonej skrzynki okno pokazuje link do skopiowania. Przypomnienia
  (`tasks/b2b_esign_sweeper.py`, co 30 min): kontraktor milczy → JEDNO
  przypomnienie dzień przed końcem terminu (przy 1 dniu — po 12 h,
  `contractor_reminder_at`), mail BEZ linku (w bazie jest tylko skrót tokenu,
  link zostaje w pierwszym mailu) i dzwonek do nadawcy; podpis firmy czeka
  3 dni → dzwonek do reprezentanta; po terminie link wygasa (`expired`)
  i nadawca dostaje dzwonek. Pętla działa także przy wyłączonym przełączniku.
- **Terminy w oknie wysyłki: 1, 3, 5, 7 dni, domyślnie 3** (prośba Sandry,
  decyzja Artura 26.10.2026). API przyjmuje 1–30 dni, ale okno pokazuje tylko
  te cztery — przy dawnym „co 3 dni” termin 1 albo 3 dni nie dawał żadnego
  przypomnienia.
- **Nazwa pobieranego pliku: „Umowa B2B 1555-2026 Kowalski Jan”** (Sandra
  i Klaudia, 26.10.2026), bez polskich znaków (decyzja Artura):
  `services/b2b_contract_filename.contract_file_name`. Ta sama dla „Pobierz
  DOCX”, PDF-a do podpisu (kontraktor i reprezentant, z dopiskiem „podpisana
  przez kontraktora”) i podpisanej umowy („… podpisana”). Imię i nazwisko leżą
  w jednym polu `partner_name` — nazwisko to ostatnie słowo. Front bierze
  nazwę z `Content-Disposition`, nie układa jej sam.
- **Tekst dla konsultanta bez myślników „—”** (Klaudia, 26.10.2026): strona
  `/sign/b2b/{token}` i komunikaty, które z niej widać (`service.MSG_*`
  kontraktora, `verdict.MSG_*`, `signedPdfProblem`). Pilnują tego testy
  `test_messages_for_the_contractor_have_no_em_dash` i „bez myślników”
  w `esign.test.tsx`; zamiast „—” dwukropek, przecinek albo nowe zdanie.
- **Pliki przed podpisem leżą w `b2b_signing/{id}/`**, nie w Dokumentach
  kontraktu — kontraktu jeszcze nie ma.
- **Dzień podpisu umowy = dzień podpisu kontraktora** (0514, 23.10.2026):
  po podpisie firmy `_after_both_signed` przekazuje do potwierdzenia
  `signed_on` = dzień `contractor_signed_at` w Europe/Warsaw, nie dzień podpisu
  reprezentanta. Tę datę pokazuje eksport „Placementy”.

## Reszta systemu przy umowie w podpisie (etap 1b, 21.10.2026)

- **Dzwonki `signature_*` stoją za sekcją Sourcing** (bramka Generatora), nie
  Delivery — inaczej rekruter, który wysłał umowę, nie dostawał żadnego.
- **Umowa w podpisie nie jest zadaniem „Potwierdź podpis”**: pulpit
  (`agreement_tasks`) ją pomija (`esign_service.open_request_exists()`),
  „Poproś o potwierdzenie” odmawia 409, panel osoby pokazuje kroki zamiast
  „Oznacz jako podpisaną”.
- **Ręczny ruch na „Zatrudniony” przy umowie w podpisie = 409
  `ESIGN_IN_PROGRESS`** (`pipeline_move_rules.assert_no_esign_in_progress`) —
  najpierw „Przejdź na zwykłą drogę”, bo link działałby dalej, a podpis obu
  stron zatrudniłby drugi raz.
- **Walidator czyta PDF w trybie nieścisłym** (`strict=False`): Word, część
  narzędzi do podpisu i Dziennik Ustaw robią „mieszany” spis obiektów, który
  tryb ścisły odrzucał w całości — prawdziwy podpis kwalifikowany dostawał
  „nie przeszedł” (test na akcie z Dz.U. 2025 poz. 1, 21.10.2026). Ukrytą
  treść łapie analiza zmian po podpisie i porównanie z wysłanym plikiem.
  Połączenia OCSP/CRL: jeden backend na walidację, zamykany w `finally`.
  Lista UE wczytywana przy starcie pętli przypomnień (pierwsze pobranie ok. 20 s).
- **Ekrany znają stan wysyłki** (część „Ważne”): karta Tablicy dostaje
  `agreement.esign` (`agreement_status.latest_esign_for_rows`, jedno zapytanie
  na tablicę) i plakietki „U kontraktora · link do …”, „Czeka na podpis firmy”,
  „Link wygasł — wyślij ponownie” (`lib/b2b-agreement.ts`; wygasły link liczy
  się od `expires_at`, zanim zamiatacz zmieni stan). Wycofana wysyłka wraca do
  zwykłej plakietki. Panel osoby mówi, u kogo jest umowa, zamiast „Przesuń na
  „Zatrudniony”…” pokazuje blokadę, a zakładka „Umowa” tłumaczy brak „Popraw”.
- **„Czeka na Twój podpis za B2B Network” to pas nad pulpitem**
  (`EsignCompanyBand`), nie kafelek — jak „Do wysłania do klienta”: widać go
  tylko, gdy coś czeka na tę osobę (`/esign/mine`, teraz z numerem umowy
  i klientem). Lista „Umowy B2B czekają na podpis” dostaje znacznik
  „NEXUS · u kontraktora / czeka na firmę” (`ContractRow.esign_status`).
- **Historia umowy składa wpisy z wysyłek** (`b2b_esign/history.py`): wysłana,
  przypomnienie, podpis kontraktora, podpis firmy, wycofana z powodem, wygasła.
  Bez migracji — `status-history` dokłada je jako `kind: "esign"` z treścią
  w `label` i ujemnym `id`.
- **Strona kontraktora ma zakładki narzędzi** (mObywatel, SimplySign, Szafir,
  inne) i stałą ramkę „podpis w pliku PDF (PAdES)”.
- **„Wyślij do podpisu” jest w dwóch miejscach** (26.10.2026): w wierszu
  rejestru Generatora i w zakładce „Umowa” panelu osoby / rekrutacji
  (`AgreementPanelTab`) — to samo okno `SendForSignatureDialog`, widoczne,
  gdy serwer zwróci `can_send_esign`. Rekruterzy generują umowę w panelu,
  więc przycisk tylko w Generatorze był dla nich niewidoczny. Obok zostaje
  „Pobierz DOCX” i „Oznacz jako podpisaną” (droga mailowa, podpis offline).
- **Wysyłka NIE przesuwa karty na „Umowa wysłana”** (świadomie): to ruch na etap
  szablonu, który Insights liczy jako kamień milowy; plakietka karty mówi to samo.

## Stary tor z czerwca — usunięty 21.10.2026 (PR 2b)

Tor „in-house QES” z czerwca 2026 (PR-y #506–#516: `/api/signing/*`,
`/api/public/sign/{token}`, strona `/sign/{token}`, providery KIR Szafir
i mSzafir, `signing_sweeper`, model `SignatureLink`, `SIGNING_*` i `QTSP_*`
w konfiguracji) był wyłączony od 22.09.2026 i został usunięty z kodu, bo
podpisywał szkic HTML zamiast PDF-a z Worda, kończył się po samym
kontraktorze, sprawdzał kwalifikowany tylko pierwszy podpis i wymagał
kontraktu przed podpisem (audyt 21.10.2026). Nie przywracaj go.

- **Zostało w `services/signing/` tylko to, czego używa ta droga:**
  `provider.py` (`ValidationReport`, `signer_identity`, `normalize_person_text`,
  `is_positive_indication`), `validation.py` (`ValidationService`, DSS)
  i `pades.py` (pyHanko, `approval_signatures`).
- **Tabele zostają:** `document_signatures` (Autenti i historia starego toru)
  i `signature_links` — bez migracji. Wiersze starego toru w
  `document_signatures` są tylko historią.
- **`signature_reconciler` obsługuje już tylko Autenti** (`provider='autenti'`,
  działa przy `AUTENTI_ENABLED`). Autenti zostaje — używa go moduł „Ludzie”
  (`hr_agreements`).
- **Ścieżka `/sign/` w `middleware.ts` zostaje publiczna** — pod nią jest
  `/sign/b2b/{token}`.

## Plan

PR 1 plik przy „Oznacz jako podpisaną” (#2530) · PR 2 rdzeń (ten plik) ·
PR 2b usunięcie starego toru (21.10.2026) · PR 3 walidator pyHanko z listą UE (DSS później) · PR 4 ekrany, mail z linkiem,
przypomnienia · PR 5 automatyka po podpisie i powiadomienia · etap 2 „Podpisz
w przeglądarce” u dostawcy (SIGNIUS / KIR mSzafir) po ofertach.
