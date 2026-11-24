# Rozliczenia: projekty FIX — godziny podwykonawcy akceptuje PM firmy

<!-- indeks: FIX, FIX / produkt, engagement_model, EngagementModel.fixed, model rozliczeń, akceptacja PM-a, koszt firmy, protokół odbioru, numer DN, limit MD na etap, fix_senders, FIX_ACCEPTOR, Senders.who, mail_text.approved, Projekt FIX, Brak akceptacji PM-a firmy, 0767 -->

Decyzja Artura z 24.11.2026, po przeglądzie skrzynek z 23.11. Dotyczy projektów
testów bezpieczeństwa u klienta bankowego i projektu z limitem MD na fazę.

## Na czym polega FIX

Klient odbiera **produkt**, a nie godziny. Kolejność jest taka: protokół odbioru,
potem numer odbioru klienta, potem faktura. Kwota wynika z oferty cenowej.
Podwykonawca raportuje godziny (Time Sheet na szablonie firmy). Te godziny są
**kosztem firmy** i akceptuje je nasz PM, zwykle krótkim „Akceptuję rozliczenie”.
Akceptacji klienta przy godzinach nie ma i nie będzie.

## Gdzie to jest w NEXUSIE

- **Kontrakt, nie reguła klienta.** Pole „Model rozliczeń” w oknie „Edytuj kontrakt”
  ma wartość „FIX / produkt” (`Contract.engagement_model = fixed`, migracja 0767
  i lustro w `entrypoint.sh`). Wybór Artura: przy kontrakcie, bo u jednego klienta
  bywa i T&M, i FIX. Reguła klienta objęłaby wszystkich jego ludzi.
- **Kto akceptuje.** Ktoś z firmy (decyzja Artura). Liczy się słowo akceptacji
  („Akceptuję”, „Potwierdzam”, „Zatwierdzam”) w wiadomości z domeny firmy: w samym
  mailu albo w zacytowanej wiadomości. Domeny firmy to adresy rozliczeń i SSO
  (`service.fix_senders`). PM-a nie trzeba wpisywać przy kontrakcie.
- **Kontrole.** W rozliczeniu kontraktu FIX:
  - `proof.excel_with_mail`, `extra.mail_accept` i `proof.accept_has_hours` pytają
    o akceptację PM-a, a nie klienta (`mail_text.Senders(..., who="PM-a firmy")`);
  - brak akceptacji daje „Brak akceptacji PM-a firmy” z poziomem reguły klienta;
  - samo „Akceptuję” bez liczby wystarcza, gdy godziny są w Time Sheet za
    rozliczany miesiąc, tak jak przy kliencie;
  - wiadomość podwykonawcy z prośbą o akceptację albo nasz mail bez słowa
    akceptacji nie wystarcza;
  - „Akceptuję” samego podwykonawcy też nie wystarcza, nawet ze skrzynki firmy
    (`Senders.consultant`, od 24.11.2026, opis w
    `finanse-insights/rozliczenia-akceptacja-od-klienta-orlen-cez.md`).
- **Notka na karcie.** Grupa „Projekt FIX”: „Godziny to koszt firmy: akceptuje PM
  firmy”. Faktura do klienta idzie z protokołu odbioru, a nie z godzin.
- **Limit MD na etap.** Każdy etap to osobne zamówienie MD z pulą etapu, np. 35 MD
  i 15 MD. Przekroczenie daje istniejącą uwagę „Ponad zamówienie o X MD”
  (`engine.compute`). Pusta pula działa według `order.no_md_holds_invoice` klienta.

## Czego tu nie ma

- Faktury do klienta z protokołu i numeru odbioru. Rozliczenie FIX nadal wylicza
  pozycje z MD × stawka, jak każde. Finanse wystawiają fakturę FIX z protokołu.
- Godzin „ofertowych” (praca na rzecz firmy bez klienta) w jednym Time Sheet z
  projektem. Liczą się do MD jak reszta wierszy.

## Pomiar

Kopia `nexus_staging_klodko_v5`, IX–X. Pliki projektów FIX (oferty, protokoły,
TS) leżą tam bez kontraktu (`contract_id` NULL). Klient bankowy ma 2 kontrakty
czasowe. Gdy w procesie potraktować je jak FIX, statusy się nie zmieniają (ok → ok),
a dochodzi tylko notka „Projekt FIX”. W tych miesiącach nie mają maili.

Powiązane: `finanse-insights/rozliczenia-akceptacja-od-klienta-orlen-cez.md`
(akceptacja tylko od klienta, wyjątkiem jest FIX).
