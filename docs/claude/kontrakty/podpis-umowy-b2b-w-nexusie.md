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
  (`tasks/b2b_esign_sweeper.py`, co 30 min): kontraktor milczy 3 dni → mail BEZ
  linku (w bazie jest tylko skrót tokenu, link zostaje w pierwszym mailu)
  i dzwonek do nadawcy; podpis firmy czeka 3 dni → dzwonek do reprezentanta;
  po terminie link wygasa (`expired`) i nadawca dostaje dzwonek. Pętla działa
  także przy wyłączonym przełączniku.
- **Pliki przed podpisem leżą w `b2b_signing/{id}/`**, nie w Dokumentach
  kontraktu — kontraktu jeszcze nie ma.

## Stary tor z czerwca (`api/signing.py`, `services/signing/sender.py`)

Wyłączony od 22.09.2026 (`SIGNING_ENABLED=false`) i NIE do włączenia: podpisuje
szkic HTML kontraktu zamiast PDF-a z Worda, kończy się po samym kontraktorze,
sprawdza kwalifikowany tylko pierwszy podpis, pozwala zamówić podpis zwykły
i wymaga kontraktu przed podpisem (audyt 21.10.2026). Z niego zostają:
`ValidationService` (DSS, od 0499 z poziomem każdego podpisu), `ValidationReport`,
`signer_identity`. Do usunięcia osobnym PR-em.

## Plan

PR 1 plik przy „Oznacz jako podpisaną” (#2530) · PR 2 rdzeń (ten plik) ·
PR 2b usunięcie starego toru · PR 3 walidator pyHanko z listą UE (DSS później) · PR 4 ekrany, mail z linkiem,
przypomnienia · PR 5 automatyka po podpisie i powiadomienia · etap 2 „Podpisz
w przeglądarce” u dostawcy (SIGNIUS / KIR mSzafir) po ofertach.
