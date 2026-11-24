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
- **Kolejność stała: kontraktor → reprezentant B2Bnetwork.** Kontraktor
  podpisuje z linku (`/sign/b2b/{token}`, API `/api/public/b2b-sign/{token}`,
  token w bazie tylko jako SHA-256), bez konta. Plik za firmę wgrywa osoba
  wskazana przy wysyłce (z listy `company_signer_ids`), a w pliku wystarczy
  podpis kwalifikowany JEDNEJ z osób z tej listy (`judge(any_of_signers=…)`;
  decyzja Artura 26.10.2026: Olaf wgrywa plik podpisany podpisem Artura —
  Artur musi być na liście). Imienny reprezentant — pieczęć firmy nie
  zastępuje podpisu osoby; podpis kontraktora się nie liczy za firmę.
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
- **Listy krajowe pobiera się z własnymi nagłówkami** (22.11.2026): `User-Agent`
  `qualified.USER_AGENT` bez słowa „aiohttp” i `Accept` z `*/*;q=0.1`
  (middleware `_accept_any_type`, bo pyHanko ustawia `Accept` przy każdym
  żądaniu). Z domyślnymi nagłówkami aiohttp lista estońska dawała 403, a czeska
  (`text/plain`) 406, także z serwera produkcji. Podpis kwalifikowany z Czech
  albo Estonii nie miał wtedy zaufanego wystawcy i był odrzucany jako
  niekwalifikowany. Start workera i web loguje `lista zaufanych UE: N błędów list`;
  około 49 to historyczne wpisy usług z `TakenOverBy` (IT, SK, CZ) bez znaczenia.
  Nieudana lista kraju ma osobną linię `nie pobrano list krajowych`.
- **Lista UE wczytuje się z wyprzedzeniem w obu procesach** (22.11.2026). Plik
  waliduje trasa w web, a lista jest pamięcią procesu, więc web ma własne
  jednorazowe zadanie `trusted_list_prewarm` (`WEB_ONLY_TASKS`), a worker robi to
  na starcie `b2b_esign_sweeper`. Wcześniej web nie miał listy do pierwszego
  wgrania po wdrożeniu i to żądanie czekało na jej pobranie (ok. 20 s, limit
  120 s). Start i healthcheck na nie nie czekają (pomiar lokalny: 22 s, z tego
  3,2 s CPU, najdłuższa przerwa pętli zdarzeń 0,55 s); awaria to ostrzeżenie
  w logu, a lista pobierze się przy pierwszej walidacji. Udane pobranie loguje
  `lista zaufanych UE pobrana w N s`. Na stagingu zadanie stoi (zapora wyjścia).
- **Walidacja bez blokady, zapis pod blokadą.** DSS trwa do 30 s, więc
  walidacja idzie bez blokady wiersza, a potem `SELECT … FOR UPDATE` sprawdza
  stan i odcisk jeszcze raz — wycofanie w trakcie walidacji wygrywa (w torze
  z czerwca kończyło się „Zakończona”).
- **Najwyżej jeden wniosek w toku na wiersz rejestru** (indeks częściowy
  `uq_b2b_signing_requests_open_per_row`). Wycofanie (`withdraw`) kasuje link
  i pozwala wysłać ponownie albo wrócić do drogi zwykłej.
- **Wysyła i wycofuje** ten, kto poprawia umowę (`_may_correct_generated`),
  albo ten, kto mógłby oznaczyć jej podpis (`may_confirm_row_signature`: te
  same bramki co „Oznacz jako podpisaną”, od 22.11.2026), zawsze z poziomem
  „Generowanie”, widocznymi stawkami i dostępem do klienta. Rejestr
  (`can_send_esign`) i trasy (`_assert_row_sender`) liczą to jedną regułą.
- **Mail z linkiem idzie ze skrzynki nadawcy** (M365, `services/b2b_esign/mail.py`);
  bez połączonej skrzynki okno pokazuje link do skopiowania. Przypomnienia
  (`tasks/b2b_esign_sweeper.py`, co 30 min): kontraktor milczy → JEDNO
  przypomnienie dzień przed końcem terminu (przy 1 dniu — po 12 h,
  `contractor_reminder_at`), mail BEZ linku (w bazie jest tylko skrót tokenu,
  link zostaje w pierwszym mailu) i dzwonek do nadawcy; po terminie link
  wygasa (`expired`) i nadawca dostaje dzwonek. Pętla działa także przy
  wyłączonym przełączniku.
- **DW przy wysyłce: tylko osoby z NEXUSA, mail zawsze z własnej skrzynki**
  (prośba zespołu i decyzja Artura 27.10.2026). Zespół chciał też wysyłki ze
  skrzynki innego rekrutera i osobnego uprawnienia „w zastępstwie” — odrzucone:
  odpowiedź kontraktora idzie do skrzynki nadawcy (przy urlopie nikt jej nie
  przeczyta), użycie cudzego połączenia M365 to mail za kogoś bez jego udziału,
  a za pierwszym mailem idą przypomnienia i kopia. Zamiast tego
  `b2b_signing_requests.cc_user_ids` (0604): kandydaci do DW
  (`EsignDefaultsOut.cc_candidates`) to zespół rekrutacji z nadania
  (prowadzący — podpowiedziany, TAC, DL, aktywne przypisanie) i autor umowy,
  każdy tylko gdy sam mógłby ją wysłać (`_may_send` — w linku jest PDF ze
  stawkami); inne id = 422. DW sprawdza się jeszcze raz przed każdym mailem
  (`_cc_for_mail`): kto wypadł z zespołu, nie dostaje nowego linku ani kopii.
  DW dostaje pierwszy mail, nowy link, mail
  o przedłużeniu i kopię podpisanej umowy (bez przypomnień), a dzwonki
  o wygaśnięciu, prośbie kontraktora i podpisie obu stron idą do
  `service.watchers` (nadawca + DW).
- **Zastępstwo: „Przejmij obsługę”, nie nowe uprawnienie** (decyzja Artura
  27.10.2026). `b2b_signing_requests.handled_by` (0605, pusta = nadawca,
  `service.handler_id`): przejmuje ten, kto mógłby wysłać tę umowę
  (`POST /esign/{id}/take-over` z `_assert_row_sender`) i tylko z połączoną
  skrzynką M365 (inaczej 409, bo dalsze maile obiegu przepadłyby po cichu), wpis
  `taken_over` w historii i dzwonek do poprzedniej osoby. Przypomnienia
  kontraktora, mail do reprezentanta i kopia umowy idą odtąd ze skrzynki
  obsługującego. Dzwonki (`service.bell_recipients`): obsługujący, nadawca,
  DW i — gdy obsługujący jest dziś na zatwierdzonym całodniowym urlopie —
  zastępca z modułu „Urlopy” (`service.absences`, ta sama reguła co
  `hr.leave_substitute`). Rejestr pokazuje „Obsługuje”, urlop do kiedy
  i zastępcę. Zastępca spoza zespołu rekrutacji dostaje dzwonek, ale nie
  przejmie wysyłki (stawki) — przejmuje ktoś z zespołu albo TCM/admin.
- **Wygasły link: ten sam PDF, nie nowa wysyłka** (pytanie zespołu
  27.10.2026, ocena i makiety: https://claude.ai/artifact/EmKfARRXm5DYHnjwXocec2).
  LibreOffice z tego samego Worda daje za każdym razem inne bajty (data
  utworzenia, /ID), więc nowa wysyłka odrzucała plik podpisany przed terminem
  i kontraktor podpisywał drugi raz. Dlatego:
  - „Przedłuż termin” (`POST /esign/{id}/extend`, link działa) przesuwa
    `expires_at`; link z pierwszego maila działa dalej, kontraktor dostaje
    mail z datą (`mail.contractor_extended_message`);
  - „Wyślij nowy link” (`POST /esign/{id}/relink`, po terminie) wraca TEN SAM
    wniosek do `sent` z nowym tokenem, na zamrożonym PDF-ie — tylko gdy umowy
    nikt nie poprawił: `source_payload_sha256` = odcisk numeru i
    `render_payload` z chwili wysyłki (`service.payload_fingerprint`). Po
    poprawce zostaje „Wyślij do podpisu” z nowym PDF-em. Rejestr chowa
    „Wyślij do podpisu”, gdy jest `can_relink_esign`;
  - skrót wygasłego linku zostaje `EXPIRED_LINK_DAYS` = 30 dni: strona
    kontraktora mówi, kiedy minął termin, i ma „Poproś o nowy link”
    (`POST /api/public/b2b-sign/{token}/renewal`, dzwonek
    `signature_renewal_requested` do nadawcy, najwyżej raz na dobę). Pliku po
    terminie nie przyjmie (410);
  - każdy termin ma jedno przypomnienie (klucz maila z datą terminu);
    przedłużenia, nowe linki, prośby i wcześniejsze przypomnienia leżą
    w `b2b_signing_requests.events` (0603) i trafiają do historii umowy.
- **Reprezentant firmy dostaje maila** (Olaf 26.10.2026: „nic mi nie
  przyszło” — był tylko dzwonek bez ikony na pasku): od razu po podpisie
  kontraktora (`_after_contractor_signed`, klucz `…-company`), potem
  przypomnienie po 1 dniu i dalej co 3 dni, zawsze w dzień roboczy
  8:00–18:00 (`company_reminder_due`) — dzwonek i mail. Mail idzie ze
  skrzynki nadawcy (`mail.company_signer_message`); bez niej zostaje dzwonek
  i pas „Czeka na Twój podpis za B2Bnetwork” na pulpicie.
  Konto reprezentanta wyłączone (`service.active_company_signer` → `None`,
  audyt 24.11.2026): bez maila na jego adres, a dzwonek „czeka na podpis
  B2Bnetwork” po podpisie i przy każdym przypomnieniu dostają osoby wysyłki
  (`bell_recipients`: obsługujący, nadawca, DW, zastępca z urlopu).
- **Kontraktor dostaje swój egzemplarz** (26.10.2026; wcześniej nie dostawał
  nic, a link gasł po podpisie firmy): po podpisie obu stron mail ze
  skrzynki nadawcy z PDF-em w załączniku (`_send_contractor_copy`,
  `m365_sender.FileAttachment`, nazwa „Umowa B2B … podpisana.pdf”) —
  niezależnie od tego, czy kontrakt powstał automatycznie. Link zostaje
  `SIGNED_COPY_DAYS` = 30 dni tylko do pobrania kopii
  (`GET /api/public/b2b-sign/{token}/signed-pdf`, widok ma
  `signed_pdf_until`); potem pętla kasuje skrót tokenu.
- **Jeden wzór wszystkich maili obiegu** (uwaga Klaudii 27.10.2026, Artur
  wybrał wariant „przycisk i kroki”): treści buduje tylko `mail.py`
  (`contractor_sign_message`, `contractor_reminder_message`,
  `company_signer_message`, `contractor_copy_message`). Bez „Pozdrawiamy,
  B2Bnetwork”, bo pod treścią NEXUS dokleja stopkę Outlooka nadawcy z jej
  własnym „Pozdrawiam”, i wtedy wychodziły dwa pożegnania. Powitanie
  „Dzień dobry,” bez imienia, bo imienia nie odmieniamy, a do reprezentanta
  „Cześć,”. Bez „podpisał(a)”: zdanie zaczyna się od umowy. Akcja to
  przycisk z tabeli, a termin stoi pod nim. `send_from` wysyła ze
  `styled_body=True`, więc treść idzie przez `sanitize_signature_html`
  (style z listy), a nie przez `sanitize_html`, który wycina style. Bez
  tego treść szła domyślną czcionką, a stopka swoją.
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
  reprezentanta. Tę datę pokazuje eksport „Placementy”. Od 0654 (06.11.2026)
  wiersz ma `signed_on_source = 'esign'` i `consultant_signed_at` = chwila
  podpisu kontraktora; premia 200% liczy ten dzień
  (`data-podpisu-z-podpisu-konsultanta.md`).

## Paczka do podpisu: umowa i dokumenty do startu pod jednym linkiem (0687, 13.11.2026)

Decyzja Artura z 13.11.2026: kontraktor podpisuje za jednym razem umowę, NDA,
oświadczenie o niekaralności i każdy inny wzór z listy klienta „Dokumenty do
startu” (`dokumenty-do-startu.md`), zamiast dostawać NDA osobnym mailem.

- **Co wchodzi do paczki** (`services/b2b_esign/documents.candidates`): każda
  pozycja listy klienta typu „plik” z wgranym wzorem (DOCX albo PDF), której
  para (kandydat, rekrutacja) jeszcze nie ma. Klient bez listy = sama umowa, jak
  dotąd. Okno wysyłki zaznacza wszystkie, nadawca może odznaczyć
  (`start_document_ids`; pozycja spoza listy = 422).
- **PDF dokumentu** powstaje przy wysyłce i jest zamrożony jak umowa
  (`b2b_signing_documents`, odcisk i długość): PDF wzoru bez zmian, DOCX
  z danymi z umowy (`fill_from_agreement`) przez ten sam konwerter co umowa.
  Awaria konwersji = 503 z nazwą dokumentu, wysyłka nie powstaje.
- **Dokument podpisuje tylko kontraktor**, podpisem kwalifikowanym z jego
  nazwiskiem w certyfikacie (`judge(required_signers=[kontraktor])`) albo,
  od 0754, kodem z maila, gdy dokument nie ma wymogu kwalifikowanego; te same
  bramki co umowa: plik zaczyna się bajtami wydanego PDF-a, limit nieudanych
  prób linku, walidacja bez blokady, zapis pod blokadą wiersza, wniosku
  i dokumentu. Reprezentant B2Bnetwork podpisuje nadal tylko umowę.
- **Umowa idzie do reprezentanta po ostatnim podpisanym pliku**
  (`service.finish_contractor_if_complete`), niezależnie od kolejności. Do tego
  czasu wniosek zostaje `sent` (plakietki „U kontraktora”, przypomnienia
  i termin działają jak dotąd), a umowy nie da się wgrać drugi raz (409).
- **Dzień podpisu umowy = dzień podpisu samej umowy**, nie ostatniego
  dokumentu: przy paczce zapis `contract_signed` w `events`, a
  `service.contract_signed_at` daje go `_after_both_signed` (premia 200%,
  „Placementy”). `contractor_signed_at` to chwila przekazania do firmy.
- **Podpisany dokument od razu trafia do „Dokumentów do startu”** pary jako
  plik pozycji (`documents.deliver_to_pair`, nazwa „… (podpis w NEXUSIE).pdf”,
  `delivered_by` puste, bo wgrał kontraktor z linku). Liczy się od razu, DL
  może go zwrócić jak każdy plik. Awaria tego kroku nie cofa podpisu.
- **Strona kontraktora** (`/sign/b2b/{token}`) przy paczce pokazuje listę
  plików do pobrania, wspólny przewodnik po narzędziach i osobne wgranie
  każdego pliku z licznikiem „podpisane X z N”. Trasy:
  `GET /api/public/b2b-sign/{token}/documents/{id}/pdf` i
  `POST /api/public/b2b-sign/{token}/documents/{id}` (ten sam token, limit żądań).
- **Mail z linkiem** wymienia umowę i dokumenty (`mail.contractor_sign_message(documents=…)`).
- **Historia umowy** dostaje „Kontraktor podpisał umowę, czekają pozostałe
  dokumenty” i „Kontraktor podpisał: <dokument>”.
- Przy integracji z dostawcą podpisu w przeglądarce (oferta KIR mSzafir,
  certyfikat „multi” na kilka podpisów po jednym potwierdzeniu tożsamości)
  paczka zostaje bez zmian: dostawca zastępuje tylko „pobierz i wgraj”.

## mObywatel na stronie kontraktora: podpis osobisty nie jest kwalifikowany (22.11.2026)

Strona `/sign/b2b/{token}` radziła „Najszybciej mObywatel z e-dowodem (za darmo)”
i w zakładce „mObywatel” kazała „wybrać podpis kwalifikowany”. Odczyt listopadowych
PDF-ów z produkcji (22.11.2026): 1 z 7 umów z e-podpisem kontraktora miała podpis
osobisty z e-dowodu (wystawca MSWiA „pl.ID Authorization CA”, polityka
`1.2.616.1.101.5.2.1.1.1.2`, bez QcStatements). NEXUS by ją odrzucił.

Co daje mObywatel (stan 22.11.2026):
- **Podpis osobisty** (usługa „Podpisz dokument” od 25.02.2025, e-dowód, NFC,
  kod PIN2): podpis zaawansowany, nie kwalifikowany. Równoważny odręcznemu
  tylko w kontaktach z administracją, z firmą tylko po umowie stron (gov.pl).
  MSWiA nie jest kwalifikowanym dostawcą (rejestr NCCert). W pliku: wystawca
  MSWiA, bez QcStatements.
- **Podpis kwalifikowany** (Usługi → Sprawy urzędowe → „Podpis kwalifikowany”,
  od 23.10.2025): certyfikat od dostawcy (Cencert, SimplySign, Sigillum, mSzafir,
  doPodpisu), tożsamość przez e-dowód i NFC. W pliku wystawca to kwalifikowane CA
  dostawcy z QcStatements, więc NEXUS go przyjmie. 5 darmowych na miesiąc, ale
  **tylko w sprawach prywatnych, niezwiązanych z działalnością zawodową**
  (Ministerstwo Cyfryzacji, FAQ Certum). Umowa B2B dotyczy firmy kontraktora.
  Kolejne podpisy są płatne u dostawcy.

Reguły:
- **Strona nie poleca mObywatela jako drogi do podpisu kwalifikowanego.**
  Zakładka „mObywatel” zostaje, bo kontraktorzy jej szukają, ale mówi: PIN2 to
  podpis osobisty i NEXUS go nie przyjmie, darmowe kwalifikowane są do spraw
  prywatnych, a do umowy jednorazowy podpis kwalifikowany (mSzafir przez bank,
  ok. 15 zł). Zdanie pod ramką PAdES: „Najszybciej jednorazowy podpis mSzafir
  przez bank… Podpis osobisty z e-dowodu i profil zaufany nie wystarczą.”
  Pilnuje tego test „mObywatel nie obiecuje podpisu kwalifikowanego”
  w `esign.test.tsx`.
- **Podpis od wystawcy spoza listy UE to „niekwalifikowany”, nie „nie przeszedł
  weryfikacji”.** pyHanko zwraca wtedy podpis cały i ważny, ale `trusted` = false
  z `NO_CERTIFICATE_CHAIN_FOUND`; `qualified._untrusted_issuer` dopisuje
  `untrusted_issuer`, a `verdict.judge` daje `not_qualified` z `MSG_NOT_QUALIFIED`
  (podpis osobisty, PIN2, „Pobierz PDF jeszcze raz”). Wcześniej kontraktor
  dostawał `invalid` i podpisywał drugi raz tak samo. Gdy obok pękł inny podpis,
  zostaje `invalid`.
- **„Pobierz PDF jeszcze raz” jest celowe:** podpis kwalifikowany dołożony do
  pliku, który ma już podpis osobisty, nie przejdzie, bo kwalifikowany musi być
  każdy podpis w pliku.
- Ten sam walidator ma umowa szkoleniowa trenera (`services/trainings/signing.py`),
  więc w portalu konsultanta „Jak podpisać” też nie podsuwa mObywatela.
- Sprawdzone 22.11.2026 na pliku testowym o tym samym kształcie (CA spoza listy,
  bez QcStatements), z prawdziwą listą UE: przed zmianą `invalid`, po zmianie
  `not_qualified`. Test bez sieci:
  `test_issuer_outside_the_eu_list_is_not_qualified_rather_than_broken`.
- Sprawdzone też na produkcji 22.11.2026 (za zgodą Artura, tylko odczyt, po
  wdrożeniu #3697): prawdziwy podpisany plik z listopada, walidator z listą UE.
  Podpis kontraktora (wystawca „pl.ID Authorization CA”) `TOTAL_FAILED`
  z `untrusted_issuer`, podpis za B2Bnetwork (KIR „COPE SZAFIR - Kwalifikowany”)
  `TOTAL_PASSED`, `QESig`. Werdykt `not_qualified` z `MSG_NOT_QUALIFIED`.
- **Podmiot certyfikatu nie trafia do logów.** pyHanko przy takim podpisie
  loguje na WARNING „Failed to build path for Common Name: …; Serial Number:
  PNOPL-<PESEL>; …” i ten sam podmiot w tracebacku. Do 22.11.2026 szło to na
  stdout (Loki) przy każdym pliku spoza listy UE, także przy „Oznacz jako
  podpisaną” (data z pliku, `signed_on_evidence.py`). `redact_sensitive` maskuje
  teraz pola podmiotu w zapisie asn1crypto i identyfikatory ETSI
  (`PNO`/`IDC`/`PAS`/`TIN` + kraj). Pilnuje tego
  `test_log_certificate_subject_redaction.py` z prawdziwym logiem pyHanko.
  Sentry tego nie dostawało: `scrub_event` zostawia z breadcrumbs tylko
  kategorię i poziom.

Źródła: gov.pl „Podpisz dokument w aplikacji mObywatel” (11.03.2025) i „Podpis
osobisty – zaawansowany podpis elektroniczny”, KIR o mSzafir w mObywatelu
(23.10.2025), rp.pl o 5 darmowych podpisach (23.10.2025), Certum o SimplySign
w mObywatelu (05.11.2025), rejestr kwalifikowanych dostawców NCCert.

## Dokumenty bez wymogu kwalifikowanego: akceptacja kodem z maila (0754, 22.11.2026)

Decyzja Artura z 22.11.2026: podpis kwalifikowany jest wymagany tylko przy
umowie, która przenosi autorskie prawa majątkowe (art. 53 pr. aut.). NDA,
umowy przedwstępne, oświadczenia i inne dokumenty paczki mogą iść innym
podpisem, a sposób wybiera kontraktor. Zmienia to zdanie „Dokument podpisuje
tylko kontraktor, podpisem kwalifikowanym” z sekcji o paczce.

- **Wymóg per dokument:** `b2b_signing_documents.requirement` =
  `qualified` albo `any`. Przy wysyłce każdy dokument dostaje `any`, chyba że
  nadawca zaznaczy „klient wymaga kwalifikowanego”
  (`EsignSendIn.qualified_document_ids`, id spoza wybranych = 422). Umowa
  zawsze kwalifikowanym. Wiersze sprzed 0754 zostają `qualified`.
- **Jak podpisano:** `signed_via` = `qualified` (plik z podpisem, jak dotąd)
  albo `email_code`. Dokument `any` kontraktor może też wgrać podpisany
  kwalifikowanym; plik z podpisem niekwalifikowanym walidator odrzuca jak
  dotąd, a komunikat (`documents.MSG_ANY_NOT_QUALIFIED`) podpowiada kod.
- **Kod z maila** (`services/b2b_esign/accept_code.py`, trasy
  `POST /api/public/b2b-sign/{token}/accept-code` i `…/accept`): 6 cyfr,
  ważny 15 minut, jednorazowy, nowy najwcześniej po minucie. W bazie tylko
  skrót HMAC z `SECRET_KEY` powiązany z wnioskiem
  (`b2b_signing_requests.accept_code_hash`, `accept_code_expires_at`,
  `accept_code_sent_at`). Zły albo przeterminowany kod liczy się do
  `contractor_failed_attempts` (ten sam limit co nieudane wgrania). Mail idzie
  ze skrzynki osoby obsługującej wysyłkę na adres z wysyłki
  (`mail.contractor_accept_code_message`); bez skrzynki kod nie wychodzi
  (503), a niewysłany kod od razu przestaje działać.
- **Zaakceptowany dokument** dostaje kopię wydanego PDF-a jako plik
  „podpisany” (te same bajty i odcisk), dowód w `validation` (metoda, chwila,
  adres, imię i nazwisko z umowy, odcisk pliku, IP, przeglądarka), wpis
  `document_accepted` w historii i trafia do „Dokumentów do startu” pary jako
  „… (zaakceptowane w NEXUSIE).pdf”. Liczy się do kompletu tak samo jak
  podpisany: umowa idzie do reprezentanta po ostatnim gotowym dokumencie.
- **Strona kontraktora** pokazuje przy każdym pliku „podpis kwalifikowany”
  albo „dowolny podpis”, krok wgrania tylko dla umowy (i dokumentów z wymogiem
  klienta) oraz blok „Wyślij kod / Akceptuję” z zamaskowanym adresem
  (`PublicSignView.accept_code_email`). „Wolę wgrać pozostałe dokumenty
  podpisane kwalifikowanym” zostawia drogę z plikiem.
- Przy integracji z dostawcą podpisu w przeglądarce (kierunek K1, 22.11.2026)
  kontraktor z podpisem w chmurze podpisze dokumenty `any` tym samym
  zatwierdzeniem co umowę; kod z maila zostaje dla tych, którzy wolą.

## Dane do długiej weryfikacji (PAdES-LT) w umowie po podpisie obu stron (E6, 23.11.2026)

Dostawcy (np. KIR) dają podpis PAdES-BES albo PAdES-T: w pliku nie ma odpowiedzi
OCSP ani list CRL z chwili podpisu, więc za kilka lat, gdy responder przestanie
odpowiadać, a certyfikaty wygasną, podpisu nie da się sprawdzić. Umowa przenosi
prawa autorskie (oba podpisy kwalifikowane), więc NEXUS dopisuje te dane sam,
bez opłat: słownik DSS (certyfikaty ścieżek, OCSP, CRL, wpis VRI każdego
podpisu, także znacznika czasu podpisu) jako jedną aktualizację przyrostową,
bez nowego podpisu (`services/b2b_esign/long_term.py`).

- **Za przełącznikiem `B2B_ESIGN_ADD_LTV`, domyślnie wyłączonym**, dopóki Artur
  nie zdecyduje (zmiana zmiennej tylko workflow „Coolify set env”). Działa
  tylko z `B2B_ESIGN_VALIDATOR=pyhanko`; z sidecarem DSS nic nie dopisuje,
  bo nie ma listy UE w procesie.
- **Gdzie:** `service.company_long_term`, wołane z `service.company_submit`
  i z podpisu reprezentanta przez API CSC (E1), po przyjęciu pliku, przed
  `SELECT … FOR UPDATE` (sieć i druga walidacja bez blokad i bez transakcji).
  Zapisany jest jeden plik końcowy (`final_pdf_path`), więc Dokumenty
  kontraktu (`_after_both_signed`), kopia kontraktora
  (`_send_contractor_copy`) i oba pobrania „podpisana” dostają ten sam plik.
  `validation.long_term` = chwila i `size_before`: wgrany plik to pierwsze
  `size_before` bajtów pliku końcowego.
- **To samo pobieranie co walidacja:** `QualifiedValidator.revocation_context`
  (lista UE, `hard-fail`, adresy OCSP/CRL tylko z certyfikatów, bez nowych
  hostów) i `fetcher_backend` (jeden na bieg, zamykany w `finally`). Limit
  całości `long_term.TIMEOUT_S` = 60 s (pojedyncze żądanie 10 s).
- **Najlepszy wysiłek:** awaria pobrania, przekroczenie czasu albo wynik, który
  nie zaczyna się bajtami wgranego pliku (`builds_on`) lub nie przechodzi tej
  samej walidacji i `judge` z tymi samymi osobami, zostawia wgrany plik bez
  zmian i jedno ostrzeżenie `LT: umowa zostaje bez danych…`. Komunikat
  przechodzi przez `redact_sensitive` (pyHanko wpisuje tam podmiot
  certyfikatu). Podpisu obu stron to nie blokuje i nie cofa. Brak danych
  samego znacznika czasu (TSA spoza listy) zostawia dane podpisującego.
- Testy: `test_b2b_esign_long_term.py` z testowym kwalifikowanym CA
  i serwerem OCSP/CRL na 127.0.0.1 (`tests/_qualified_ca.py`), w tym PAdES-T
  i przebieg na bazie.
- Przed włączeniem: sprawdzić na prawdziwej umowie (KIR, Certum), że plik
  z DSS otwiera się w Acrobacie z „LTV włączone”, a walidator dalej daje
  `QESig` obu podpisom.

## Podpis u dostawcy przez API CSC (E1, 0758, kierunek K1 z 22.11.2026)

Decyzja Artura z 22.11.2026 (kierunek „K1”): NEXUS zostaje przy swoich
ekranach podpisu, a od kwalifikowanego dostawcy usług zaufania kupuje tylko
potwierdzenie tożsamości, certyfikat (własny w chmurze albo jednorazowy)
i podpis skrótu. Dostawca nie jest wybrany (SIGNIUS, Certum, KIR; pytamy,
czy mają API Cloud Signature Consortium), więc klient zna tylko specyfikację
CSC v1, nie dostawcę z nazwy.

- **Wyłączone, dopóki konfiguracja jest pusta.** `B2B_ESIGN_CSC_BASE_URL`
  (adres przed `/csc/v1/...`), `B2B_ESIGN_CSC_CLIENT_ID`,
  `B2B_ESIGN_CSC_CLIENT_SECRET`, `B2B_ESIGN_CSC_PROVIDER_LABEL` (nazwa na
  ekranie) i opcjonalnie `B2B_ESIGN_CSC_SCOPES` (puste = `service`). Brak
  któregoś = `remote_signing.available: false` i 404 na trasach startu
  i powrotu. Zmienne ustawia tylko workflow „Coolify set env”. U dostawcy
  rejestruje się dwa adresy powrotu z `PUBLIC_API_BASE_URL`:
  `/api/public/b2b-sign/remote/callback` (kontraktor) i
  `/api/b2b-generator/esign/company-remote/callback` (reprezentant).
- **Przebieg** (`services/b2b_esign/csc.py`, `remote.py`): `POST /csc/v1/info`
  (adres OAuth `oauth2`), przekierowanie na `{oauth2}/oauth2/authorize` z
  `state` i PKCE S256, powrót do NEXUSA, `oauth2/token` (formularz RFC 6749),
  `credentials/list` + `credentials/info` (certyfikat osoby: pierwszy, którego
  podmiot pasuje do nazwiska z umowy), `credentials/authorize` RAZ ze skrótami
  wszystkich plików (SCAL 2) i `signatures/signHash` RAZ dla całej paczki.
  CMS i PAdES składa pyHanko (`CSCSigner` z `batch_size` = liczba plików):
  podpis dopisuje się przyrostowo na końcu zamrożonych bajtów, więc
  `verdict.builds_on` zachodzi jak przy pliku z dysku.
- **Te same bramki co wgranie pliku.** Każdy podpisany plik idzie przez
  `service.validate_upload` (walidator z listą UE i `verdict.judge`) i zapis
  pod blokadą (`service.store_contract`, `documents.store_document`,
  `service.store_company`), potem `_after_contractor_files` (Dokumenty do
  startu, `_after_contractor_signed`) albo `_after_both_signed`. Trasy wgrania
  z dysku używają tych samych funkcji. Nieudana walidacja pliku od dostawcy
  nie zużywa prób linku (pliku nie przygotował kontraktor).
- **Kontraktor: umowa zawsze w paczce.** `POST /api/public/b2b-sign/{token}/remote/start`
  z `include_document_ids` (dokumenty `any` i `qualified` tej paczki) i
  `method` (`own_certificate` / `one_time`, na razie tylko zapisywane: jak
  dostawca je rozróżnia, wyjdzie po wyborze dostawcy). Po wgraniu umowy
  z dysku `available` = false, a reszta paczki idzie dotychczasową drogą.
  Wszystko albo nic: najpierw walidacja wszystkich plików, potem zapis
  w jednej transakcji.
- **Reprezentant: kilka umów jednym zatwierdzeniem.**
  `POST /api/b2b-generator/esign/company-remote/start` z `request_ids`; każdy
  wniosek przechodzi `company_precheck` (czeka na podpis tej osoby). Każda
  umowa przechodzi bramki osobno, więc zła jedna nie cofa pozostałych
  (`done_request_ids`, powód reszty w `message`).
- **Sesja** (`b2b_esign_remote_sessions`, 0758): `state` w bazie tylko jako
  SHA-256, ważna 15 minut, jednorazowa; obcy `state` = 400, drugi powrót = 409,
  powrót po czasie albo z `error` (rezygnacja u dostawcy) = `cancelled`
  i wniosek bez zmian. Token linku kontraktora potrzebny do adresu powrotu
  (`/sign/b2b/{token}?remote={session_id}`) leży przy sesji zaszyfrowany
  kluczem z `state` i znika przy powrocie albo w pętli przypomnień po czasie.
  Kod autoryzacji i token dostępu dostawcy nie trafiają do bazy, a sekret
  klienta idzie tylko do `oauth2/token`. Podpis biegnie w tle po
  przekierowaniu (`BackgroundTasks`); front pyta o stan
  (`GET …/remote/{session_id}`), a sesja „w podpisie” dłużej niż 30 minut
  (restart procesu) kończy się `failed`. `evidence`: dostawca, metoda,
  `credentialID`, odcisk certyfikatu, liczba plików (bez podmiotu
  certyfikatu).
- **Powrót reprezentanta wymaga zalogowania** (ciasteczko sesji, `SameSite=Lax`
  przechodzi przy przekierowaniu); sesja należy do konta, które ją zaczęło.
- Testy: `tests/test_b2b_esign_remote.py` z lokalnym udawanym dostawcą CSC
  i testowym CA. Niesprawdzone na prawdziwym dostawcy: tryb `authMode`
  (PIN/OTP albo drugie przekierowanie `scope=credential` zamiast samego
  `credentials/authorize`), forma `oauth2/token` (formularz czy JSON)
  i rozróżnienie `own_certificate` / `one_time`. Do sprawdzenia po wyborze
  dostawcy, przed włączeniem konfiguracji.

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
  Lista UE wczytywana przy starcie pętli przypomnień w workerze i zadaniem
  `trusted_list_prewarm` w web (pierwsze pobranie ok. 20 s).
- **Ekrany znają stan wysyłki** (część „Ważne”): karta Tablicy dostaje
  `agreement.esign` (`agreement_status.latest_esign_for_rows`, jedno zapytanie
  na tablicę) i plakietki „U kontraktora · link do …”, „Czeka na podpis firmy”,
  „Link wygasł — wyślij ponownie” (`lib/b2b-agreement.ts`; wygasły link liczy
  się od `expires_at`, zanim zamiatacz zmieni stan). Wycofana wysyłka wraca do
  zwykłej plakietki. Panel osoby mówi, u kogo jest umowa, zamiast „Przesuń na
  „Zatrudniony”…” pokazuje blokadę, a zakładka „Umowa” tłumaczy brak „Popraw”.
- **„Czeka na Twój podpis za B2Bnetwork” to pas nad pulpitem**
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
- **„Wyślij do podpisu” jest w trzech miejscach i jest główną akcją**
  (26.10 i 22.11.2026): w przyklejonej kolumnie „Akcje” rejestru Generatora,
  w kroku „Podpisana obustronnie” wąskiego panelu osoby (`EsignSendStep`)
  i w zakładce „Umowa” (`AgreementPanelTab`) — to samo okno
  `SendForSignatureDialog`, widoczne, gdy serwer zwróci `can_send_esign`.
  Obok zostaje „Pobierz DOCX” i „Oznacz jako podpisaną” (droga mailowa,
  podpis offline), obrysowane (`AgreementSignatureAction secondary`).
  Nie chowaj ich i nie pytaj „dlaczego mailem” przed pomiarem: DL potwierdza
  też umowy, które wróciły mailem.

## Dlaczego wysyłka jest na wierzchu (22.11.2026)

Od włączenia trybu `all` (26.10) do 22.11 przez NEXUS nie poszła żadna z 19
umów, choć każdy autor miał uprawnienia i skrzynkę M365. Przeszkody były
w interfejsie: przy 1280 px przyklejona kolumna „Akcje” zasłaniała przycisk
w kolumnie „Status podpisu” do ikony, wąski panel osoby nie miał wysyłki,
zielonym przyciskiem było „Oznacz jako podpisaną”, a konto Administracji
(Finanse z „Oznaczaniem podpisu”, autor 8 z 19 umów) nie mogło wysłać cudzej
umowy, którą potwierdzało. W listopadzie 5 z 7 kontraktorów podpisało umowę
podpisem kwalifikowanym (odczyt PDF-ów z produkcji), więc to nie brak podpisu
blokował drogę. Makiety i plan pomiaru przed decyzją o dostawcy podpisu
w przeglądarce: https://claude.ai/artifact/UyyBZKNWJKia9ekX357r8W.
Akcje podpisu w rejestrze stoją w kolumnie „Akcje”, nie w „Status podpisu”:
przyklejona kolumna zasłania to, co pod nią leży (por. #1346).
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
- **Tabela zostaje:** `document_signatures` (Autenti i historia starego toru),
  bez migracji; wiersze starego toru są tylko historią. Pustą `signature_links`
  usunęła migracja 0667 (decyzja z 08.11.2026).
- **`signature_reconciler` obsługuje już tylko Autenti** (`provider='autenti'`,
  działa przy `AUTENTI_ENABLED`). Autenti zostaje — używa go moduł „Ludzie”
  (`hr_agreements`).
- **Ścieżka `/sign/` w `middleware.ts` zostaje publiczna** — pod nią jest
  `/sign/b2b/{token}`.

## Plan

PR 1 plik przy „Oznacz jako podpisaną” (#2530) · PR 2 rdzeń (ten plik) ·
PR 2b usunięcie starego toru (21.10.2026) · PR 3 walidator pyHanko z listą UE (DSS później) · PR 4 ekrany, mail z linkiem,
przypomnienia · PR 5 automatyka po podpisie i powiadomienia · paczka umowa + dokumenty do
startu (0687, 13.11.2026) · etap 2 „Podpisz w przeglądarce” u dostawcy
(SIGNIUS / KIR mSzafir) po ofertach.
