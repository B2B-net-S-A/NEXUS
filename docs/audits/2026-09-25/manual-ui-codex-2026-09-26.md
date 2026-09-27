# Manualne testy UI Codexa (26–27.09.2026) — raport i lekcje

Raport poniżej napisał Codex po testach przez przeglądarkę na produkcji (Admin, fikcyjne rekordy).
Wszystkie 27 pozycji (F01–F27) naprawiono w PR rundy 10 audytu (tabela na końcu). Zrzuty i pliki
dowodowe (`evidence/`, `findings.json`, `*.json`) zostały poza repo — linki w treści raportu do nich
nie działają.

## Lekcje na potem

1. **Audyt kodu nie zastępuje przeklikania.** Rundy 1–9 czytały kod i nie złapały ani jednego z 27
   błędów widocznych w UI, bo każdy z nich wymagał złożenia kilku ekranów w łańcuch (formularz →
   zapis → odświeżenie → inny ekran). Po każdej większej rundzie — test A–Z w przeglądarce na
   fikcyjnych rekordach, z tym samym kryterium „odbiór” co tu.
2. **Automat nie może omijać bramki, którą człowiek widzi** (F09). Bramka QC CV była pilnowana w
   `/move`, a przesunięcie przez „Terminy od klienta” szło obok. Każdą nową bramkę sprawdzaj we
   wszystkich ścieżkach zmiany etapu (ręczny ruch, zbiorczy, automat, import).
3. **Walidacja na granicy obu warstw** (F01, F13, F27, F12). Formularz dopuszczał to, czego serwer
   nie chciał (grosze), albo serwer przyjmował to, czego biznes nie dopuszcza (pusta faktura, koniec
   przed startem). Zakres wartości ustalaj raz i sprawdzaj go na froncie i w API tym samym testem.
4. **Jedno źródło danych dla jednej etykiety** (F17, F18, F23). Profil pokazywał umiejętności z
   dwóch kolumn, a wyszukiwarka i porównanie czytały jedną. Jeśli ekran pokazuje fakt, każdy filtr i
   porównanie tego faktu musi czytać to samo źródło.
5. **Komunikat błędu to część funkcji** (F05, F12, F14). Surowy tekst walidatora, „Request failed
   with status code 422” albo „Otworzyłem zakładkę” zamiast „użyj linku” — użytkownik nie wie, co
   poprawić. `apiErrorMessage` przy polu, po polsku.
6. **Generator treści ma trzymać się źródła** (F19–F21). Staż z CV, stanowisko wybrane w formularzu i
   brak zgody w źródle muszą przejść bez „ulepszeń”; test na konkretnym CV, nie na przykładzie z głowy.

## Raport Codexa (bez zmian treści)

**Wynik: proces doprowadzony do fikcyjnego zatrudnienia i zaplanowanego zakończenia współpracy; pełny system niezaliczony.** Użytkownik zatwierdził konkretny upload i końcowe zatrudnienie wiadomością „tak dzialaj”. Te działania wykonano. Pozostałe granice to inne persony, rzeczywiste integracje, podpisy i wykonanie przyszłego zakończenia. Raport nie utożsamia ukończonej próby z poprawnością całego produktu.

Zarejestrowano **148 scenariuszy: 95 PASS, 28 FAIL, 21 PARTIAL, 2 BLOCKED, 2 NOT_RUN**. Potwierdzono **27 problemów zachowania/treści UI: 17 P2 i 10 P3**. Zachowano **432 obserwacje**. Liczba kliknięć i scenariuszy nie jest procentem pokrycia systemu. Brak P0/P1 w tym zakresie nie dowodzi ich nieobecności.

Najważniejsze wyniki: zapis pustych faktur, utrata pól zamówienia, obejście screeningu/CV/QC przez kalendarz (starsza próba i nowy wyzwalacz), rozbieżność dat PDF, błędne dane generatora CV, zatrzymanie automatycznego przygotowania kontraktu przy przyszłym przedłużeniu oraz zapis końca współpracy przed początkiem kontraktu. Nie wykonywano napraw kodu, PR ani wdrożenia.

## A–Z: wykonany łańcuch i wynik

| Odcinek | Wynik rzeczywistej próby |
|---|---|
| Klient → kontakt → karta współpracy | Własny fikcyjny klient #77196, kontakt bez emaila/telefonu, karta wersja1 i szkic MSA; zapis i ponowny odczyt |
| Rekrutacja → Champion | Szkic #693762, Python/PostgreSQL MUST,160PLN/h,2pytania i wzorce; przejęcie przez Artura |
| Kandydat → Screening → Zweryfikowany | Fikcyjny #593528; wymagane odpowiedzi, negatywna walidacja, Pasuje i120,50PLN/h |
| PDF → parser → generator | Jedna strona fikcyjnego CV wgrana; profil i podgląd utrwalone. Dwie generacje wykonane; błędy treści F19–F21 |
| Korekta → QC | 5lat, prawidłowy tytuł i testowe oznaczenia zapisane. Druga generacja przygotowała CV dla bieżącego etapu. QC 0/7blokujących, uwagi zielone; bez Przepuść mimo QC |
| CV wysłane → rozmowa → Umowa | Normalne przejścia poQC;160PLN/h wymagane i zapisane. Wykorzystano wcześniej zakończony syntetyczny cykl rozmowy/debrief; bez faktycznej rozmowy/prepuTeams i wysyłkiCV |
| Zatrudniony | Końcowe potwierdzenie wykonane; po reload Zatrudniony: 1 i obsada1/1. Automatyczne przygotowanie kontraktu nie powiodło się: F24 |
| Dokumenty PL/EN | Niepodpisane szkice wygenerowane w nowych kartach; osoba, klient, początek i progresywne stawki podstawione. EN miesza język opisu stawek (F25); załączniki puste, Autenti bez wysyłek |
| Kontrakt/zamówienia → onboarding → sprzęt/faktury | Istniejący675 pochodzi z osobnego wcześniejszego formularza;#733 i #734; onboarding 1/9, laptop zwrócony, testowe faktury. Nie jest dowodem automatycznego stworzenia kontraktu przez zatrudnienie |
| Zakończenie współpracy | Zaplanowano31.03.2027, Koniec projektu, opisTEST; bez rozwiązania prawnej umowy. Kontrakt Kończący się,2 zamówienia zsynchronizowane, Timeline i reload potwierdzone. Przyszłe przełączenie na Zakończony niewykonane |
| CV spoza bazy | Ten sam zatwierdzonyPDF sparsowany: QA Manual Tester, Warszawa,5lat i technologie. Brak dopasowań ponad próg. Ponowna próba przy szkicu702337 również pusta; Draft nie rozstrzyga jakości rankingu otwartych rekrutacji; nie sprawdzono DB |

**Ocena A–Z: PARTIAL/FAIL dla pełnej automatyzacji.** Pipeline przeszedł do zatrudnienia, ale wymagał ręcznej korektyCV i drugiej generacji, używa wcześniejszego syntetycznego debriefu oraz osobno utworzonego kontraktu. Nie było podpisów, realnych zewnętrznych wiadomości ani płatności. Nie można ogłosić, że jeden nieprzerwany, automatyczny proces produkcyjny został zaliczony.

Dowody nowego odcinka: [źródłoCV](evidence/r4-333-source-cv-preview-python-two-hits.png), [powtórzona generacja](evidence/r4-344-second-generation-repeats-six-years-consent-title.png), [QC](evidence/r4-345-qc-all-rules-pass-without-override.png), [CV wysłane](evidence/r4-346-cv-sent-stage-rate160-no-mail.png), [zatrudnienie i ostrzeżenie](evidence/r4-347-hired-saved-contract-sideeffect-blocked-two-orders.png), [trwałość zatrudnienia](evidence/r4-348-hired-after-reload-one-filled-slot.png), [zamówienia](evidence/r4-350-hiring-orders-nonoverlap-current-future.png), [koniec współpracy](evidence/r4-352-contract675-planned-end-date-persisted.png), [Timeline po reload](evidence/r4-354-planned-offboarding-persists-after-reload.png).

## Środowisko, wersje i granice

Produkcja https://nexus.dynaminds.pl, natywny Chrome w profilu Artur, zalogowany Admin. Dodatkowo zapisany profil Bruce bez sesji NEXUS wykorzystano do testów anonimowych(E407–E423). Wszystkie kroki biznesowe wykonywano przez UI. Kontrole HTTP health/Alembic i lokalne renderowanie pobranych plików są osobnymi warstwami dowodu. Nie uruchamiano Dockera, automatycznych E2E ani API zapisujących dane biznesowe.

- Pierwsze okno 26 września: backend/frontendowy deskryptor2fd2397699cc5a98599eb229fa07e33df2a4b84b.
- Wcześniejsze wznowienie 27 września:03564bcfaa94a9321971ebbcf1febe1f09f25acb; F01/F02/F03/F05/F06/F07/F10 odtworzono; F04/F08 pozostają starszymi obserwacjami. F09 ma dodatkowo nowy wariant opisany niżej na backend7814fdf; nie jest to powtórzenie identycznej starej ścieżki.
- Nowy autoryzowany odcinekE330 i kolejne: backend **7814fdf4009d69f43a245571ec1a14a7034f6f14**, health/deep healthy na początku i końcu. [Health](health-authorized-end-2026-09-27.json), [deep](health-deep-authorized-end-2026-09-27.json). Nie potwierdzono aktualnej rewizji frontendu; wcześniejszy deskryptor03564bc nie dowodzi jej obecnej wersji. Starszych usterek nie retestowano automatycznie na7814fdf.
- [Alembic](alembic-authorized-end-2026-09-27.json): DB/code 0388_purged_candidates, orphaned=[], reconcilable=true. To nie dowód poprawności modułów.
- Jedna personaAdmin nie potwierdza RBAC ani pracy Rekrutera/DL/HR/Praktykanta. S61/S92 wymagają istniejących sesji testowych; uprawnień nie rozszerzano.
- Rzeczywiste Teams/Graph/mail/Traffit/COMPASS, podpisy i transakcje nie zostały zaliczone. Uzgodnienie danych źródłowych i walut również pozostaje poza wynikiem tej próby.

## Stan własnych rekordów pozostawiony w produkcji

| Rekord | Stan po końcowej kontroli |
|---|---|
| [Klient77196](https://nexus.dynaminds.pl/clients/77196) | Prospekt, testowy kontakt i karta; NDA i MSA niepodpisane |
| [Rekrutacja693762](https://nexus.dynaminds.pl/jobs/693762) | Niepublikowana; po zatrudnieniu Obsadzona, 1/1; zakładka Projekt klienta nadal opisuje ją jako Szkic |
| [Kandydat593528](https://nexus.dynaminds.pl/candidates/593528) | TEST_SYNTETYCZNY, bez kontaktu; główne CV i wygenerowane CV; pipeline Zatrudniony |
| [Kontrakt675](https://nexus.dynaminds.pl/contracts/675) | Kończący się,01.10.2026–31.03.2027; koniec planowany z opisemTEST; brak załączników i wysyłek Autenti; szkice PL/EN tylko w nowych kartach |
| Zamówienia733/734 | Bieżący okres01.10–31.12.2026 oraz przyszły01.01–31.03.2027; Timeline zakończenia pokazuje synchronizację2 |
| Onboarding/sprzęt/faktury | Pełny cykl checklisty9/9→8/8N/A→0/9 sprawdzony, przywrócono1/9 po reload; fikcyjny laptop — Zwrócony;2 puste faktury 0 PLN iTEST-FV123PLN z metadanymi Zapłacona, bez płatności |
| Rozmowa7512 | Syntetycznie zakończona25.09, debrief; bez zewnętrznego zaproszenia |
| Akademia1/pula | Własny program i syntetycznie zaliczone zadanie;Podpisali0. Osobista pula z593528 |
| Kandydat598805/kontrakt676/zamówienie735 | Po F27:676Kończący się z błędnym okresem01.11.2026–27.09.2026;735Anulowane. Cofnięcie czeka na konkretną zgodę(E396). Pipeline693762 nadal według ostatniej kontroli Rozmowa u klienta przezF09; bezCV, końcowego zatrudnienia i podpisu |
| Rekrutacja702337 | Osobny szkicQA ManualTester, ownerArtur,0/1; niepublikowany; brak dodatniego wyniku CV spoza bazy |

Rekordów nie usuwano. Nie należy wykorzystywać ich do rzeczywistych decyzji kadrowych i rozliczeń. [Źródłowy PDF](synthetic-cv-NEXUSQA-UIAZ20260926.pdf), [oryginalny wynik](generated-cv/original-generated-draft.docx), [poprawiona pierwsza wersja](generated-cv/corrected-approved-v1.docx). Oba DOCX mają po 2 strony; wszystkie 4 strony obejrzano. Poprawiona pierwsza wersja nie jest końcową wersją drugiej generacji wQC; jej treść i stanQC są udowodnione przez UI E345.

## Potwierdzone problemy

F01–F18 poniżej opisują datowane próby sprzed uploadu. F17/F18 odnoszą się do ręcznie wpisanych umiejętności przed parsowaniemPDF. Zmiana źródła i wyniku na86 po uploadzie nie jest retestem ich poprawki.


### F01 — P2: pusty formularz zapisuje fakturę jako wystawioną

**Odtworzenie:** kontrakt 675 → Faktury → Dodaj fakturę → bez numeru i kwoty → Zapisz → odświeżenie. **Wynik:** pusty numer, 0,00 PLN, Wystawiona. Formularz nie wymaga ani numeru, ani dodatniej kwoty. Nie oznaczano płatności. [Przed](evidence/011-contract-invoices-empty.txt), [po zapisie](evidence/012-invoice-empty-validation.png), [po reload](evidence/013-invoice-empty-persisted.png).

**Skutek:** rejestr dopuszcza niekompletny dokument rozliczeniowy i stwarza możliwość zaśmiecenia danych. Wpływ tego wpisu na raporty finansowe nie został sprawdzony.

**Naprawa/odbiór:** ustalić wymagane pola i zasady dokumentów zerowych; walidować frontend i backend. Pusty numer/kwota nie mogą utworzyć Wystawionej; ewentualny niekompletny draft musi być wyraźnie oddzielony. Zgodny komunikat w UI, brak nowego rekordu po negatywnej próbie.

### F02 — P2: zmiana typu zamówienia usuwa wprowadzone dane

**Odtworzenie:** klient 77196 → Zamówienia → nowy okresowy wpis; wybierz kandydata/job, wpisz daty 01–31.10.2026, 160/120,50 PLN/h i notatkę → MD → Okresowe. **Wynik:** pozostaje numer `QA-AZ-20260926-001`, a kandydat, rekrutacja, daty, stawki i notatka znikają; bez ostrzeżenia. [Wypełniony formularz](evidence/031-order-filled-review.png), [MD](evidence/033-order-switch-to-md.png), [powrót](evidence/034-order-switch-return-periodic.png).

**Skutek:** utrata pracy i ryzyko uzupełnienia formularza innymi danymi po powrocie. Nie zapisano zamówienia podczas tej próby przełączenia typu.

**Naprawa/odbiór:** zachowywać wspólne pola i roboczy stan obu typów albo ostrzegać przed utratą. Powrót do Okresowego odtwarza kandydat/job/datę/stawki/notatkę; zapis używa wybranego typu, bez przenoszenia niezgodnych pól.

**Retest 27.09 rano, 03564bc: nadal występuje.** [E273](evidence/r3-088-morning-order-type-filled.png), [E274](evidence/r3-089-morning-order-type-md-loss.png), [E275](evidence/r3-090-morning-order-periodic-return-loss.png).

### F03 — P2: instrukcja powiązania notatki z kontraktem nie ma odpowiadającej ścieżki w oglądanym UI

**Odtworzenie:** kontrakt 675 → Notatki/Rozmowy. Komunikat każe ustawić `contract_id` lub dodać rekord z kandydata. Kandydat 593528 → Dodaj notatkę oferuje treść i rekrutację, lecz nie wybór kontraktu. [Komunikat](evidence/010-contract-notes-empty-instructions.png), [formularz kandydata](evidence/019-candidate-note-no-contract-selector.png).

**Skutek:** użytkownik nie może wykonać wskazanej czynności przy użyciu dostępnego formularza. Nie sprawdzono alternatywnego formularza rozmowy ani API; nie jest to twierdzenie o braku możliwości w backendzie.

**Naprawa/odbiór:** przycisk dodania notatki bezpośrednio przy kontrakcie albo jawny selektor kontraktu w kandydacie. Nowa notatka powiązana z 675 pojawia się po odświeżeniu w obu widokach; komunikat nie wymaga operowania nazwą pola technicznego.

**Retest 27.09 rano, 03564bc: nadal występuje.** [E276](evidence/r3-091-morning-contract-notes-instruction.png), [E277](evidence/r3-092-morning-note-no-contract-selector.png).

### F04 — P3: ręczne przypisanie ma niespójne oznaczenie początkowego etapu/źródła

**Odtworzenie:** ręcznie przypisz nowego kandydata do job 693762. Profil/rekrutacje pokazuje etap „Ogłoszenia”, tablica procesu „Nowi”; początkowo karta pokazuje „Z ogłoszenia”. Nie użyto ogłoszenia ani publicznej aplikacji. [Profil](evidence/008-candidate-recruitment-tab.png), [pipeline](evidence/009-pipeline-new-to-screening.png), [historia](evidence/027-candidate-history-after-pipeline.png).

**Naprawa/odbiór:** spójna nazwa etapu; osobne i prawdziwe źródło ręcznego przypisania. Zweryfikować również raport źródeł, którego tutaj nie badano.

### F05 — P3: błąd emaila ujawnia surowy angielski tekst walidatora

**Odtworzenie:** nowy kandydat z `nexus-ui-az-20260926@example.invalid` → zapis. Backend poprawnie odrzuca zarezerwowaną domenę, lecz UI pokazuje `email: value is not a valid email address...` przy początku formularza obok Imienia. [Dowód](evidence/015-candidate-created-result.png).

**Naprawa/odbiór:** polski, zrozumiały komunikat przy Emailu; zachować wpisane dane i fokus na polu błędnym. To błąd prezentacji, nie błędna decyzja walidatora.

**Retest 27.09 rano, 03564bc: nadal występuje.** [E278](evidence/r3-093-morning-email-validator-English-after-save.png). Powtórzono wariant Edytuj dane; błąd wymagał ręcznego przewinięcia do początku. Anulowano, nie zapisano emaila.

### F06 — P3: automatyczny tryb wyszukiwania nazwiska zwraca 199 osób

**Odtworzenie:** wyszukaj unikalne `UIAZ20260926` w automatycznym trybie; uruchamia się semantyka i wynik ma 199 osób. Przełącz literalne wyszukiwanie → 1 właściwy kandydat. [Auto](evidence/017-candidate-search-result.png), [literalne](evidence/004-candidate-literal-result.png).

**Skutek:** odnalezienie rekordu po nazwisku wymaga świadomej zmiany trybu. Semantyczne wyniki same w sobie nie są dowodem wadliwego silnika; problem dotyczy doboru trybu do zapytania.

**Naprawa/odbiór:** literalne wyszukiwanie dla ID/nazwisk i ścisłe trafienie na początku, z jasno widocznym trybem; nie mieszać szerszych podobieństw z informacją o liczbie ścisłych trafień.

**Retest 27.09 rano, 03564bc: nadal występuje.** [E279](evidence/r3-094-morning-candidate-auto-199.png), [E280](evidence/r3-095-morning-candidate-literal-one.png).

### F07 — P3: prospekt bez umowy trafia do zakładki opisanej jako podpisana współpraca

**Odtworzenie:** utwórz klienta 77196 jako Prospekt bez NDA/MSA. Lista umieszcza go w „Aktywni klienci”, z opisem „Klienci z podpisaną współpracą”; profil pokazuje Prospekt i NDA niepodpisane. [Lista](evidence/002-client-create-search.png), [profil](evidence/003-client-detail.png).

**Naprawa/odbiór:** uzgodnić znaczenie aktywności i statusu biznesowego. Jeśli to niezależne osie, zmienić opis zakładki; jeśli warunkiem jest podpisana współpraca, nowy prospekt nie powinien tam trafiać. Nie stwierdzam, że status Prospekt został nadpisany.

### F08 — P3: domyślny prep nakłada się na rozmowę u klienta

**Odtworzenie:** potwierdź rozmowę 28.09.2026 10:00–11:00 → Prep → Zaplanuj. Termin domyślny prepu to 28.09.2026 10:00, czas 45 min. [Wybrana rozmowa](evidence/024-calendar-slot-selected.txt), [prep](evidence/025-prep-only-teams-default-overlap.png).

**Naprawa/odbiór:** proponować termin przed rozmową, ostrzegać o kolizji i niemożliwej kolejności. Zaproszenia nie wysłano; walidacja końcowego zapisu Teams pozostaje niewykonana.

### F09 — P2: kalendarz omija bramkę screeningu i CV/QC

**Odtworzenie:** własny kandydat #593528 jest Zweryfikowany i nie ma żadnego CV. Normalna próba QC jest blokowana. Wybierz i potwierdź termin rozmowy tylko w NEXUS. **Wynik:** proces automatycznie wskazuje „Rozmowa u klienta”; etapy QC i CV wysłane uznaje za przebyte. Po zapisaniu debriefu można wejść do Umowa. Nie użyto bezpośredniego API. [Etap w profilu](evidence/r2-012-candidate-recruitment-after-calendar.txt), [bramka](evidence/r2-014-interview-next-stage-gate.txt), [stan po reload](evidence/r2-003-contract-stage-ready-after-reload.txt).

**Skutek:** skuteczność bramki zależy od ścieżki UI. Nie twierdzę, że wysłano CV lub wiadomość — wykonano przeskok stanu wewnętrznego. **Odbiór:** potwierdzenie terminu nie pomija wymaganych etapów albo pokazuje uprawniony, audytowalny wyjątek; brak pliku ma zachowywać tę samą regułę co tablica.

**Nowy wariant 27.09, backend7814fdf:** druga własna fikcyjna osoba598805 nie ma CV, screeningu ani stawek w rekrutacji. Po ręcznym przypisaniu ma Ogłoszenia; samo powiązanie osobnego wydarzenia nie zmienia etapu ([E367](evidence/r4-367-secondary-candidate-assigned-no-cv-initial-ogloszenia.png), [E370](evidence/r4-370-secondary-stage-remains-ogloszenia-after-calendar-edit-no-cv.png)). Następnie zapisano normalne „Terminy od klienta”28.09 19:15. Tablica i świeży profil pokazują Rozmowa u klienta, a historia przyczynę „Auto: terminy od klienta” ([E379](evidence/r4-379-secondary-no-cv-screening-missing-in-client-interview-main-hired-one.png), [E380](evidence/r4-380-secondary-profile-client-interview-with-no-cv-or-rates.png), [E381](evidence/r4-381-secondary-history-auto-client-slots-skip-from-ogloszenia.png)). Nie wykonano końcowego potwierdzenia wyboru terminu. Ta osoba ma wcześniejszy osobny kontrakt676; nie jest to próba zupełnie nowego kandydata bez kontraktu. Wynik dowodzi nowego wyzwalacza pominięcia etapów w tej konkretnej parze, bez dowodu o wszystkich rolach czy konfiguracjach.

### F10 — P2: lista PDF pokazuje inne daty niż dokument

**Odtworzenie:** Finanse → Zamówienia PDF → Styczeń 2027 → klient 39 → zamówienie OIT/0569/2026/ITVM → podgląd. Lista i nazwa pliku pokazują `01.01.2027–31.12.2026`; plik jest w styczniu 2027. **Treść PDF:** okres `01.10.2026–31.12.2026`, wejście w życie `01.10.2026`. [Lista](evidence/r2-021-finance-pdfs-client-files.txt), [PDF i metadane razem](evidence/r2-023-finance-pdf-content-vs-metadata.png), [tekst PDF](evidence/r2-023-finance-pdf-content-vs-metadata.txt).

**Skutek:** mylący okres/miesiąc dokumentu i ryzyko pominięcia go przy kompletowaniu plików. Nie ustalono źródła błędnych metadanych; nazwa zawiera `UIv2-sig`, więc rekord może pochodzić ze starszego testu. Nie zmieniono go. **Odbiór:** naprawić metadane lub oznaczyć rozbieżność; okres kończący się przed początkiem nie może być pokazany jako poprawny. Sprawdzić spójność listy, PDF, zamówienia i eksportu.

**Retest 27.09 rano, 03564bc: nadal występuje.** [E281](evidence/r3-096-morning-pdf-dates-content-vs-metadata.png).

### F11 — P3: pusty wynik filtra sugeruje pusty cały Marketplace

**Odtworzenie:** Marketplace → Targ ręczny → wyszukaj `NEXUSQA UIAZ20260926`, którego nie wystawiono na targ. Wynik 0 wyświetla „Nikogo nie wystawiono na targ ręcznie”. Wyczyszczenie filtra przywraca trzy istniejące osoby. [Pusty wynik](evidence/r3-003-marketplace-filter-empty-misleading.png), [po resecie](evidence/r3-004-marketplace-filter-reset-restores-three.png).

**Skutek:** komunikat pomija aktywny filtr i mylnie opisuje cały moduł jako pusty. **Odbiór:** rozróżnić pustą bazę od braku trafień; pokazać aktywny filtr oraz akcję jego wyczyszczenia. Potwierdzone w sesji nowej rewizji 03564bc; nie zmieniano cudzych rekordów.

### F12 — P3: błąd dat MSA pokazuje tylko techniczny HTTP 422

**Odtworzenie:** klient #77196 → Umowy → Nowa umowa: nazwa testowa, Szkic, PLN; początek 01.10.2026, koniec 30.09.2026 → Zapisz. UI pozostawia formularz i pokazuje „Request failed with status code 422”. Po zmianie wyłącznie końca na 31.12.2026 ten sam szkic zapisuje się poprawnie. [Przed próbą](evidence/r3-011-msa-reversed-dates-before-save.txt), [komunikat w powtórnej próbie](evidence/r3-004-msa-dates-error-synchronized-capture.txt), [poprawny zapis](evidence/r3-013-msa-valid-draft-saved.png).

**Granica:** backend odrzucił błędny zakres. **Odbiór:** polski komunikat wskazuje konkretne pole i przyczynę, zachowuje dane do poprawy; nie pokazuje wyłącznie kodu HTTP. Formularz zamówienia ma już czytelny komunikat analogicznego błędu.

### F13 — P2: faktura z groszami jest odrzucana

**Odtworzenie:** na kontrakcie #675 dodaj fikcyjną fakturę z numerem `TEST-FV-QA-20260927-001`, walutą PLN i kwotą `123.45`. Zapis zwraca `amount: Input should be a valid integer, got a number with a fractional part`. Nie zapisuje faktury. Po zmianie wyłącznie kwoty na `123` zapis jest przyjęty; reload pokazuje 123,00 zł i właściwy numer. Formularz kwoty dopuszcza część ułamkową. Ponowne odrzucenie z innym testowym numerem TEST-FV-QA-20260927-002: [komunikat i wartości](evidence/r3-003-invoice-cents-error-synchronized-capture.txt), [ekran błędu](evidence/r3-003-invoice-cents-error-synchronized-capture.png). [Kontrola dodatnia po reload](evidence/r3-022-invoice-saved-visible-after-reload.png).

**Skutek:** faktury z kwotą w groszach nie można zarejestrować w badanym formularzu. Nie wnioskuję o wszystkich walutach ani o sposobie przechowywania w bazie.

**Odbiór:** 123,45 PLN zapisuje się i po odświeżeniu nadal pokazuje 123,45 PLN; kontrakt UI/API określa jednostkę kwoty, błędy są zrozumiałe po polsku. Warstwa: produkcyjny UI, fikcyjny rekord, rewizja 03564bcfaa94a9321971ebbcf1febe1f09f25acb.

### F14 — P3: Jarvis deklaruje otwarcie strony, choć jedynie podał link

**Odtworzenie:** poproś Jarvisa o otwarcie Zamówień własnego klienta #77196, tylko nawigacja. Odpowiedź mówi „Otworzyłem zakładkę”, ale bieżący URL nadal jest `/jobs/review-states`; pojawił się link do klienta. Dopiero kliknięcie linku zmienia ekran na `/clients/77196?tab=zamowienia`. [Deklaracja i stary ekran](evidence/r3-042-jarvis-says-opened-but-only-link-same-route.png), [odczyt po kliknięciu](evidence/r3-043-jarvis-link-opened-correct-client-orders.txt).

**Skutek:** nieprawdziwa deklaracja wykonania akcji w tym zaobserwowanym przebiegu. Nie twierdzę, że każdy wynik modelu będzie identyczny ani że link jest błędny.

**Odbiór:** gdy powstał tylko link, odpowiedź mówi „Użyj linku”; „otworzyłem” występuje dopiero po rzeczywistej nawigacji. Warstwa: produkcyjny UI/model, nowa rewizja.

### F15 — P2: przedłużenie dopuszcza nakładające się okresy zamówień

**Odtworzenie:** własny kontrakt #675 ma zamówienie #733 od 01.10 do 31.12.2026. Dodaj przedłużenie `QA-AZ-20260927-002` od 01.12.2026 do 31.03.2027, 165,50 PLN/h przychodu i 125,75 kosztu. Formularz przyjmuje zapis. Po odświeżeniu nadal są oba zakresy, nakładające się w grudniu, bez skrócenia poprzedniego lub ostrzeżenia. Timeline ujawnia nowe źródło #734. [Trwałe zakresy](evidence/r3-046-order-overlap-loaded-persistent-ranges.png). Pomoc mówi „Jedna osoba nie ma dwóch równoległych zamówień na to samo”.

**Skutek:** brak zabezpieczenia tej ścieżki przed kolizją okresów. Nie dowodzi podwójnego naliczenia ani rzeczywistego rozliczenia. Po utrwaleniu dowodu poprawiono wyłącznie własny rekord #734 na 01.01–31.03.2027 i dodano jawny opis fikcyjnego testu; nie usuwano danych. [Poprawiony stan](evidence/r3-047-order-extension-corrected-no-overlap-persisted.png).

**Odbiór:** kolizyjne przedłużenie jest odrzucane po polsku albo jawny proces zastąpienia uzgadnia poprzedni zakres. Poprawne przedłużenie od następnego dnia zachowuje oddzielne rekordy i właściwy harmonogram. Warstwa: produkcyjny UI, wyłącznie fikcyjne zamówienia, nowa rewizja.

### F16 — P2: publiczna klauzula dla kandydatów jest niedokończona

**Odtworzenie:** otwórz `/kariera` i kliknij `klauzula_rodo`. Strona `/kariera/rodo` wyświetla „Wersja robocza — do akceptacji prawnej”, pole `DO UZUPEŁNIENIA` zamiast adresu email do spraw ochrony danych oraz nieuzupełniony okres przechowywania. [Treść i adres](evidence/r3-069-career-public-privacy-draft-placeholders.txt), [ekran](evidence/r3-069-career-public-privacy-draft-placeholders.png).

**Skutek:** kandydat otrzymuje niedokończoną publiczną informację. To potwierdzony problem treści produkcyjnego UI; audyt nie rozstrzyga zgodności prawnej ani nie potwierdza, że ta wersja obsłużyła faktyczną aplikację.

**Naprawa/odbiór:** uzupełnić treść zatwierdzoną przez właściciela prawnego. Publiczny link ma prowadzić do kompletnej wersji bez placeholderów, z właściwym kontaktem i ustalonym okresem przechowywania.

### F17 — P2: słowa kluczowe pomijają umiejętności widoczne w profilu

**Odtworzenie:** Kandydaci → literalne UIAZ20260926 → Musi mieć/Python w słowach kluczowych → Szukaj w Wszędzie → Szukaj. Wynik: 0. Sam profil #593528 pokazuje Python i PostgreSQL, oba „potwierdzone na screeningu”. Powtórzenie z zakresem Umiejętności (q_in=skills) nadal daje 0, także po odświeżeniu. Osobny filtr Umiejętności → Musi mieć/Python (skills_q=Python) daje 1; usunięcie słowa kluczowego również przywraca 1. Próba Python AND PostgreSQL daje 0, lecz nie dowodzi osobno wady operatora AND.

**Dowody:** [Profil i umiejętności](evidence/r3-119-candidate-profile-keyword-source-skills.png), [Python/Wszędzie — zero](evidence/r3-120-candidate-keyword-python-zero.png), [Python/Umiejętności — zero po reload](evidence/r3-123-candidate-keyword-skills-python-zero-reload.png), [osobny filtr — jeden](evidence/r3-122-candidate-dedicated-python-one.png), [reset — jeden](evidence/r3-121-candidate-keyword-reset-restores-own.png).

**Skutek:** rekruter może pominąć profil spełniający widoczne wymaganie, zależnie od wybranego formularza filtra. Nie ustalono, czy przyczyną jest indeks, zakres źródeł umiejętności czy przesyłane parametry. Nie dowodzi to błędu oceny AI ani wszystkich profili.

**Naprawa/odbiór:** ujednolicić źródła umiejętności w profilu i filtrach albo jawnie opisać różnice zakresów. W zakresie „Umiejętności” i „Wszędzie” pozytywna próba Python powinna odnaleźć #593528; Python AND PostgreSQL również, a nieobecna umiejętność wykluczać. Zachować działanie dedykowanego filtra i ponowić próbę po reload. Potwierdzone w sesji 03564bc.

### F18 — P2: porównanie pokazuje brak potwierdzonych umiejętności must-have

**Odtworzenie:** literalne 20260926 → zaznacz fikcyjne #593528 i #593527 → Porównaj → wybierz własną rekrutację #693762. Dla #593528 wynik dopasowania 79/100 jest zgodny z oglądanym Radarem, lecz przy Python i PostgreSQL widnieje „brak w umiejętnościach” i kreska. Pełny profil pokazuje oba jako potwierdzone na screeningu. Ta sama pisownia technologii różni się jedynie wielkością liter. Wynik i oznaczenia utrzymują się po odświeżeniu.

**Dowody:** [Must-have i wynik 79](evidence/r3-125-compare-job-must-have-missing-visible-skills.png), [po reload](evidence/r3-126-compare-job-reload-persists.png), [profil](evidence/r3-119-candidate-profile-keyword-source-skills.png).

**Skutek:** porównanie podaje sprzeczny sygnał o spełnieniu wymagań. Nie wyciągam wniosku o błędnej punktacji 79, kwalifikacji realnej osoby ani wspólnej przyczynie z F17. #593527 służył tylko do odczytu porównania i nie był zmieniany.

**Naprawa/odbiór:** spójny odczyt widocznych umiejętności i normalizacja pisowni; ✓ dla Python/PostgreSQL na #593528, brak tylko dla faktycznie nieobecnej umiejętności. Osobno zachować źródło i poziom potwierdzenia, wynik AI, reset kontekstu oraz powrót z zaznaczeniem. Potwierdzone w sesji 03564bc.


### F19 — P2: Generator zmienia 5 lat doświadczenia na 6

**Odtworzenie/wynik:** Źródłowy PDF i profil podają 5 lat. Dwie generacje Pod rekrutację pokazują 6 lat, także po dodaniu jednoznacznej notatki o 5 latach. Oryginalny DOCX zawiera tę samą rozbieżność. QC po ręcznej korekcie potwierdza 5 vs 5 z historii.

**Dowody:** [E333](evidence/r4-333-source-cv-preview-python-two-hits.png), [E337](evidence/r4-337-generated-cv-original-six-years-and-added-consent.png), [E344](evidence/r4-344-second-generation-repeats-six-years-consent-title.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Generator zachowuje wartość ze źródła lub pokazuje jawnie wyjaśniony wynik obliczenia; nie zwiększa stażu przez liczenie obu lat granicznych jako pełnych. Ponowna generacja i DOCX dla tego źródła zawierają 5 lat.

### F20 — P2: CV dopisuje deklarację zgody nieobecną w źródle

**Odtworzenie/wynik:** Fikcyjny PDF wyraźnie wyklucza zgodę i umowę. Reguły klienta pokazują Zgoda RODO nie wymaga. Obie generacje dodają w pierwszej osobie Wyrażam zgodę oraz oświadczenia o administratorze i dobrowolności przekazania danych. To obserwacja treści dokumentu; nie stwierdzenie skutecznego udzielenia zgody ani ocena prawna.

**Dowody:** [E333](evidence/r4-333-source-cv-preview-python-two-hits.png), [E334](evidence/r4-334-cv-generator-authorized-job-file-mode-review.png), [E337](evidence/r4-337-generated-cv-original-six-years-and-added-consent.png), [E344](evidence/r4-344-second-generation-repeats-six-years-consent-title.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Treść zgody ma jawne, zweryfikowane źródło i status; generator nie przedstawia gotowego oświadczenia jako faktu pochodzącego od kandydata. Reguła klienta i test bez zgody mają oczekiwany, udokumentowany wynik.

### F21 — P3: Stanowisko z Zaawansowanych nie trafia do nagłówka CV

**Odtworzenie/wynik:** Generator obiecuje nagłówek i nazwę pliku ze stanowiska NEXUS QA UI A-Z 2026-09-26. Dwie generacje zaczynają się odpowiednio Manualny Tester QA oraz Tester manualny QA. Pierwszy plik ma również inną nazwę. Własny tytuł zachowano dopiero po ręcznej korekcie.

**Dowody:** [E334](evidence/r4-334-cv-generator-authorized-job-file-mode-review.png), [E337](evidence/r4-337-generated-cv-original-six-years-and-added-consent.png), [E344](evidence/r4-344-second-generation-repeats-six-years-consent-title.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Jawnie ustawione stanowisko trafia do nagłówka i nazwy pliku; ewentualna normalizacja jest pokazana przed generacją. QC akceptuje nagłówek wygenerowany z tej samej reguły.

### F22 — P2: Link z QC do edytora prowadzi do panelu tylko do odczytu

**Odtworzenie/wynik:** QC → Otwórz w edytorze CV otwiera panel osoby z tekstem CV jest tylko do odczytu; bez edytora. Powrót na tablicę i druga generacja pozwoliły otworzyć właściwy Edytuj CV. Zapis i ponowne otwarcie właściwego edytora działały.

**Dowody:** [E341](evidence/r4-341-qc-editor-link-opens-readonly-panel.png), [E342](evidence/r4-342-qc-stage-cv-binding-lost-card.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Odnośnik z wyniku QC otwiera edytowalną wersję wskazanego dokumentu i właściwy etap. Użytkownik poprawia i wraca do kontroli bez ponownej generacji.

### F23 — P2: Karta pokazuje brak CV po zmianie etapu mimo istniejącego dokumentu

**Odtworzenie/wynik:** Po zatwierdzeniu pierwszego CV powrót do Zweryfikowany i QC pokazuje gotowe nie podpięte, następnie brak. Po drugiej generacji w QC, korekcie i zaliczonym QC zwykłe przejście do CV wysłane znów pokazuje CV firmowe: brak i Generuj CV. Nie potwierdzono usunięcia dokumentu z magazynu; stwierdzono niespójny odczyt/powiązanie na karcie.

**Dowody:** [E338](evidence/r4-338-corrected-cv-reopened-persisted.png), [E339](evidence/r4-339-verified-stage-normal-cv-path.png), [E342](evidence/r4-342-qc-stage-cv-binding-lost-card.png), [E346](evidence/r4-346-cv-sent-stage-rate160-no-mail.png), [E347](evidence/r4-347-hired-saved-contract-sideeffect-blocked-two-orders.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Karta pokazuje właściwy dokument, wersję i etap źródłowy, także po zwykłym przejściu i reload. Brak dokumentu jest odróżniony od braku przypięcia do bieżącego etapu; zaakceptowane CV pozostaje dostępne bez ponownej generacji.

### F24 — P2: Przyszłe przedłużenie zatrzymuje automatyczne przygotowanie kontraktu

**Odtworzenie/wynik:** Końcowe zatrudnienie #593528/#693762 zapisuje Zatrudniony i obsadę1/1, ale ostrzega Nie założono szkicu kontraktu / więcej niż jedno otwarte zamówienie / zamknij duplikaty. Lista pokazuje jeden kontrakt675 z bieżącym zamówieniem733 (01.10–31.12.2026) i przyszłym734 (01.01–31.03.2027). Okresy nie nakładają się. Komunikat jest jawny; nie dowodzi awarii samego zapisu zatrudnienia. Automatyczny kontrakt przy czystej parze bez zamówień nie został przetestowany.

**Dowody:** [E347](evidence/r4-347-hired-saved-contract-sideeffect-blocked-two-orders.png), [E348](evidence/r4-348-hired-after-reload-one-filled-slot.png), [E350](evidence/r4-350-hiring-orders-nonoverlap-current-future.png). Backend 7814fdf; frontendSHA niepotwierdzony.

**Odbiór:** Przy prawidłowej kontynuacji system rozpoznaje istniejący kontrakt i właściwy okres albo jasno opisuje wymagane uzgodnienie, bez nazywania nienakładających się okresów duplikatami. Osobno sprawdzić czystą parę, rzeczywiste duplikaty i idempotentny powtórny krok.

### F25 — P3: Angielski szkic B2B podstawia polski opis stawek

**Odtworzenie:** kontrakt675 → Generuj z szablonu → Umowa B2B (EN). W §6 „Remuneration” wartości120,50 i125,75 PLN odpowiadają stawkom, lecz opisy słowne oraz łączniki dat pozostały polskie: „słownie” i „od dnia”. [Dowód E361](evidence/r4-361-contract-template-en-polish-rate-words-and-effective-dates.png).

**Skutek i odbiór:** gotowy szkic ma mieszaną wersję językową i wymaga korekty. Formatter powinien uwzględniać język szablonu dla obu kwot i dat wejścia. PL pozostaje polski, EN ma angielskie opisy. Nie podpisano ani nie wysłano dokumentu; brak wniosku o ważności prawnej. Backend7814fdf; bieżący frontend SHA niepotwierdzony.

### F26 — P2: nowe terminy łączą się ze starym cyklem, a „Wybierz termin” nie reaguje

**Odtworzenie:** przypisz fikcyjną osobę598805 do własnego job693762. Zapisz osobne zdarzenie27.09 08:15–08:30 i powiąż z parą. Następnie przez Terminy od klienta dodaj28.09 19:15–19:45. Panel pokazuje nowe terminy czekające na kandydata, ale Wybór terminu i Rozmowa są już „zrobione” z datą27.09; tablica kieruje do zaległego telefonu. „Wybierz termin” nie otwiera formularza ani komunikatu, także po reload. [Stan](evidence/r4-376-secondary-cycle-pending-future-choice-but-past-steps-done.png), [pierwsza próba](evidence/r4-377-secondary-cycle-choose-term-no-visible-reaction.png), [po reload](evidence/r4-378-secondary-cycle-choose-term-still-inert-after-reload.png).

**Skutek i odbiór:** nowa propozycja nie ma działającego wyboru w oglądanym panelu. Oddzielić historię poprzedniej rozmowy od nowego wyboru albo jawnie wskazać wspieraną ścieżkę ponownego terminu. Przycisk otwiera selektor lub konkretny komunikat; kroki i daty są spójne po reload. Nowe sloty pozostają widoczne, więc nie stwierdzono ich utraty. Nie przetestowano wszystkich rodzajów poprzednich zdarzeń. Backend7814fdf; frontendSHA niepotwierdzony.

### F27 — P2: koniec współpracy zapisany przed początkiem kontraktu

Dla fikcyjnego676 (start01.11.2026, bezterminowo;735 od01.11 do30.11) formularz Zakończ współpracę podstawił27.09.2026. Powód Koniec projektu, rozwiązanie prawnej umowyOFF, notatka jawnie wskazująca negatywną próbę. Zapis zaakceptowany. Po reload widoczny **Okres umowy01.11.2026–27.09.2026**, statusKończący się. [E393 — dane](evidence/r4-393-contract676-invalid-end-before-start-prepared-legal-flag-off.png), [E394 — zapis](evidence/r4-394-contract676-end-before-start-save-accepted-order-cancelled.png), [E395 — trwałość](evidence/r4-395-contract676-invalid-period-persists-after-reload.png).735 stało sięAnulowane, lista pokazujeBrak zamówienia i pustą stawkę klienta. Samo anulowanie zamówienia planowanego w przyszłości może mieć sens biznesowy; potwierdzona wada to zapis odwróconego okresu kontraktu bez walidacji.

**Przywrócenie przygotowane, niewykonane:** [E396 — podgląd](evidence/r4-396-contract676-undo-preview-awaiting-specific-ui-confirmation.png) proponuje676Aktywny/bezterminowo i735Aktywne z końcem30.11.2026. Końcowe potwierdzenie czeka na konkretną zgodę użytkownika wymaganą przez zasadę narzędzia UI. Nie usuwano rekordów, nie podpisywano dokumentów, nie rozwiązano prawnej umowy.675 nie zmieniano tą operacją.

Akceptacja: odrzucić end<start z czytelnym komunikatem bez skutków ubocznych albo jawnie modelować anulowanie planowanego startu bez ujemnego okresu. Retest dzień przed/na/po starcie, otwarta umowa, przyszłe zamówienia oraz pełne cofnięcie statusów/dat/stawek. Backend7814fdf; frontendSHA niepotwierdzony.

## Kolejność napraw i retestów

1. Spójność przejść CV/QC, linku edytora i powiązania wersji: F09(stary i nowy wyzwalacz),F22,F23; ponowny cykl rozmowyF26. Retestować główną tablicę, kalendarz i powrót po reload.
2. Fakty i treść generowanego dokumentu: F19–F21. Źródło → generator →QC →DOCX muszą zachować te same dane i reguły.
3. Zatrudnienie i okresy współpracy: F15,F24,F27. Osobne dodatnie próby: czysta para, istniejący kontrakt, przyszłe nienakładające się przedłużenie; negatywna: rzeczywisty duplikat.
4. Integralność finansowa i formularze: F01,F02,F10,F13; potem język dokumentuF25, wyszukiwanie/porównanieF17/F18 oraz pozostałe komunikatyUI.

Po poprawkach wymagany jest nowy retest UI na potwierdzonej wersji, z warstwami CI/deploy/health oddzielonymi od biznesowego wyniku. Ten audyt nie obejmował implementacji zmian.

## Końcowa kontrola powiązań i szkiców

Po zatrudnieniu i zaplanowaniu końca profil kandydata nadal wskazuje kontrakt675 oraz31.03.2027. Pliki i umowy pokazują źródłowe CV1, brak załączników kontraktu i brak wysyłek Autenti. [E357](evidence/r4-357-candidate-contract-end-date-and-no-autenti-send.png). Generacja PL/EN otwiera osobny niepodpisany podgląd; nie zapisuje automatycznie załącznika. Braki NIP/REGON/adresu pozostają jawne, bo fikcyjny profil ich nie zawiera. Nie oceniano kompletności prawnej szablonów.

Analityka klienta pokazuje3 indywidualne zamówienia,0 aktualnych kontraktów/konsultantów, a Projekty1 rekrutację. Początki obu testowych kontraktów są przyszłe, więc zerowych bieżących konsultantów nie sklasyfikowano jako usterki. [E355](evidence/r4-355-client-analytics-future-contracts-zero-orders-three.png), [E356](evidence/r4-356-client-projects-one-own-draft-linked-job.png). Nie jest to pełne uzgodnienie ekonomicznych agregatów. Ponowny [health](health-document-check-2026-09-27.json) i [deep](health-deep-document-check-2026-09-27.json) potwierdzają ten sam backend7814fdf; frontend nadal bez bieżącego SHA.

## Dodatkowa próba kalendarza i stan pozostawionego testu

Zakończone zdarzenie głównej osoby593528 nadal jest widoczne. Osobno utworzono „TEST QA UI — odwołanie — 20260927”,27.09 08:15–08:30, bez uczestników/emaili. Po powiązaniu z fikcyjną598805 i693762 pojawił się Odwołaj. Końcowe „Odwołać…?” nie zostało zaakceptowane; wybrano Nie i poproszono użytkownika o konkretną zgodę wymaganą przez zasadę narzędzia UI. [E371](evidence/r4-371-calendar-cancel-specific-confirmation-awaiting-user.png). Zdarzenie pozostaje Zaplanowane. Przypomnienie pozostało domyślne15min; nie ma opcji „brak” w oglądanym selektorze, termin jest przeszły. Brak faktycznej wysyłki zewnętrznej nie jest potwierdzony logami Graph; formularz nie zawierał uczestników.

Dla tej samej fikcyjnej pary zapisano przyszły slot28.09 19:15–19:45. To wewnętrzny krok „Wyślij rekruterowi”, nie rzeczywista rozmowa. Ujawnił F09 i F26. Główny job nadal Obsadzona1/1, główna593528 Zatrudniony; druga598805 Rozmowa u klienta, screening nieuzupełniony. Nie wykonywano jej końcowego zatrudnienia. iCal: pusty URL blokuje import; tekst TEST-NIE-URL został odrzucony jawnym komunikatem HTTPS/webcal ([E372](evidence/r4-372-ical-empty-url-import-disabled.png), [E373](evidence/r4-373-ical-invalid-text-rejected-https-webcal-required.png)). Dodatni import ważnego feedu i eksport kalendarza pozostają niezaliczone. [Health tej próby](health-calendar-check-2026-09-27.json) potwierdza ten sam backend7814fdf.

## Ponowna próba CV spoza bazy i osobny szkic

Utworzono własny szkic **702337**, „QA Manual Tester — TEST MATCH 20260927”, dla fikcyjnego klienta77196. Ma5lat, Python/PostgreSQL MUST, Playwright/REST API/SQL NICE,160PLN/h i2pytania z odpowiedziami. Artur przejął szkic; reload potwierdził właściciela i0/1. [E382 — formularz](evidence/r4-382-positive-match-job-draft-review-no-other-recruiter-selected.png), [E383 — trwałość](evidence/r4-383-positive-match-job702337-persisted-five-years-two-must-owner-artur.png). Nie zaznaczono przepięć, nie przypisywano innego rekrutera i nie zatrudniano kolejnej osoby. Główny693762 zachowuje wcześniejszy wynik1/1; w tym odcinku nie wykonywano nowego retestu głównej obsady.

Ten sam zatwierdzony syntetycznyPDF ponownie wgrano do Dopasuj CV (spoza bazy). Parser odczytał QA Manual Tester, Warsaw,5lat i8technologii, po czym pokazał brak wyników ponad próg. [E385 — wynik](evidence/r4-385-external-cv-again-no-match-after-own-draft702337.png). Status702337 to **Draft / Do uzupełnienia**; edytor oferuje Draft, Opublikowana, Zamknięta. Publikacji nie wykonano; zamknięto edycję bez zmian. [E386](evidence/r4-386-match-fixture-draft-status-publication-not-performed.png). Nie ustalono, czy taki szkic wchodzi do zbioru dopasowywania, dlatego pusty wynik **nie został uznany za wadę algorytmu**, a S72 nadal PARTIAL. Tekst proponuje edycję profilu/poluzowanie progu; na obserwowanym ekranie nie ma tych kontrolek. Odnotowano tę obserwację bez dodawania potwierdzonej usterki.

[Health tej próby](health-match-check-2026-09-27.json): healthy, backend7814fdf4009d69f43a245571ec1a14a7034f6f14; aktualnegoSHA frontendu nadal nie potwierdzono. Odczyt dostępnych przeglądarek ujawnił wyłącznie profil Chrome Artur, bez odrębnej sesji wymaganych person. Pozostałe role i rzeczywiste integracje pozostają jawnymi lukami. Starsze agregaty klienta były obserwowane przed utworzeniem702337 i nie są bieżącą liczbą jego rekrutacji.

## Checklist onboardingu — pełny cykl UI

Dla675 sprawdzono wszystkie9pozycji ręcznej checklisty.9/9=100% utrzymuje się po reload ([E388](evidence/r4-388-onboarding-nine-of-nine-persists-after-reload.png)); jednoN/A wyłącza pozycję z mianownika —8/8=100% ([E389](evidence/r4-389-onboarding-not-applicable-excluded-eight-of-eight.png)); po cofnięciu oznaczeń0/9=0% ([E390](evidence/r4-390-onboarding-zero-of-nine-after-reversible-status-cycle.png)). Przywrócono **stan pierwotny1/9**, osiem domyślnychdo zrobienia, tylko własnyTESTzrobione; reload potwierdzony ([E391](evidence/r4-391-onboarding-original-one-of-nine-restored-after-reload.png)). S23 obejmuje teraz pełny cykl statusów i licznika. To oznaczenia UI na fikcyjnym kontrakcie, nie dowód faktycznegoBHP, podpisu ani działaniaVPN/Slack/mail/repo. Nie wykonano rzeczywistego nadawania dostępów; nie weryfikowano logów integracji.

Dla osobnego676 wybórKończący się bez daty został odrzucony jawnym komunikatem i pozostałAktywny ([E392](evidence/r4-392-contract676-ending-status-without-date-rejected.png)). Następna próba zakończenia datą przed startem ujawniłaF27. Stan drugiego kontraktu w starszych dowodachActive jest historyczny; bieżący stan opisujeF27 iE395/E396. [Health](health-onboarding-date-check-2026-09-27.json) nadalhealthy na7814fdf.

## Małe okno Chrome — układ i klawiatura

Zmieniono natywnie rozmiar okna; bez zoomu strony i emulacji urządzenia. Rozmiary zapisanych obrazów są w [rejestrze próby](narrow-window-review.json); nie są pomiarem viewportuCSS. Podgląd cofnięcia676 ma przewijaną treść i stale dostępne akcje ([E397](evidence/r4-397-narrow-window-undo-modal-before-scroll.png), [E398](evidence/r4-398-narrow-window-undo-modal-scroll-content-actions-visible.png)). Przy mniejszej szerokości przyciski układają się pionowo ([E399](evidence/r4-399-minimum-width-undo-modal-stacked-actions.png)). Tab przechodziAnuluj→Cofnij→Zamknij→Anuluj, bez aktywowania żadnej akcji ([E400](evidence/r4-400-minimum-width-undo-modal-keyboard-focus-cycles.txt)).

Na693762 strzałki zmieniają **widok** etap6→7→8; kartaZatrudniony1/1 jest widoczna, następny etap na8wyłączony ([E401](evidence/r4-401-narrow-job-board-interview-stage-navigation-visible.png), [E402](evidence/r4-402-narrow-job-board-hired-card-one-of-one-last-step-disabled.png)). Selektor przeniósł widok naNowi1/8, poprzedni etapwyłączony ([E403](evidence/r4-403-narrow-job-board-first-step-selector-and-disabled-previous.png)). Nie przesuwano osób w pipeline.

Menu kompaktowe da się przewinąć doPomoc/Ustawienia, Escapeje zamyka, ponowne otwarcie i przejście doPomocy załadowało procedurę zamówień ([E404](evidence/r4-404-narrow-menu-scroll-bottom-links-accessible.png), [E405](evidence/r4-405-narrow-menu-navigates-to-help-and-procedure-loads.png)). PoEscapeAX wskazywał fokus naHTML, a nie na przyciskuOtwórzmenu; nie zaliczono osobno powrotu fokusu ani pełnej dostępności. Procedura potwierdza opisaną regułę anulowania zamówienia zaczynającego się po dacie końca umowy; nie wycofuje toF27, którego dowodem jest odwrócony okres.

Przywrócono poprzedni rozmiar okna i zamknięto wyłącznie utworzoną na tę próbę kartę. [E406](evidence/r4-406-window-size-restored-undo676-still-awaiting-confirmation.png) pokazuje nadal oczekujące cofnięcie676/735. Brak nowej zgody; nie zaakceptowano potwierdzenia. S145–S147PASS dotyczą opisanych interakcji; nie dowodzą poprawności wszystkich modułów na urządzeniach mobilnych.

## Mac, pokrycie i pakiet dowodowy

Podtrzymanie aktywności działa bez limitu przez LaunchAgent pl.dynaminds.keepawake i `caffeinate -d -i -u`, uruchamiany po zalogowaniu. [Weryfikacja](keepawake-verification.txt). Nie zmieniono zabezpieczeń hasła; ręczna blokada, zamknięta pokrywa, wyłączenie i brak zasilania nadal mogą przerwać pracę.

[Macierz pokrycia](COVERAGE.md), [rejestr scenariuszy](scenario-register.json), [rejestr usterek](findings.json), [chronologia](evidence/index.json), [manifest SHA256](evidence-manifest.json), [kontrola raportu](report-qa.json). [Poprzedni raport](HISTORY-before-authorized-resume.md) zachowuje szczegóły wcześniejszych modułów i historyczne ograniczenia; jego oczekujące zgody zostały już rozwiązane. [Inwentaryzacja tras](NEXT-UI-TESTS.md) jest planem, a nie dowodem wykonaniaUI.

## Dostęp anonimowy: dodatkowa sesja ChromeBruce

Menu natywnego Chrome ujawniło drugi zapisany profil, którego wcześniejszy inwentarz aktywnych przeglądarek nie pokazywał. Bruce nie ma zalogowanej sesji NEXUS. Nie klikano logowania Microsoft ani nie akceptowano nieoczekiwanej prośby rozszerzenia AdBlock o dostęp. Nazwa profilu nie dowodzi istnienia konta biznesowego lub określonej roli.

| Próba | Wynik | Dowód |
|---|---|---|
| Dashboard, kontrakt675, rekrutacja693762, kandydat593528, Finanse, regułyCV — bezpośrednie adresy | PASS S148: przekierowanie do login z next; chronione treści niewidoczne | E407–E412 |
| /kariera → link klauzuli | Landing i nawigacja dostępne bez logowania; S101 nadal PARTIAL, bez aplikacji | [E414](evidence/r4-414-anonymous-kariera-landing-public-loaded.png) |
| /kariera/rodo | FAIL S102/F16: wersja robocza, nieuzupełniony kontakt ochrony danych oraz retencja widoczne anonimowo; bez oceny zgodności prawnej | [E415](evidence/r4-415-anonymous-kariera-rodo-draft-placeholders-F16.png) |
| kariera/p, apply, engagement, share/champion-card, sign, cv, cv/i, kariera/r z wcześniejszym celowo błędnym tokenem/slugiem | PASS zakresu S103: komunikat nieważnego linku/404, bez danych rekordu | E416–E423 |
| Powrót do Artura | Sesja Admin zachowana; cofnięcie676/735 nadal oczekuje konkretnej zgody, bez zapisu | [E424](evidence/r4-424-artur-restored-after-anonymous-tests-undo676-still-pending.png) |

E413 dokumentuje /career, nierozpoznany angielski alias prowadzący do logowania. Publiczną stronę sprawdzono pod właściwym, wcześniej zaobserwowanym adresem /kariera. Nie zgłoszono błędu dla tego aliasu.

To ograniczony dowód zachowania UI. Nie zastępuje testów serwerowej autoryzacji, sesji Rekrutera/DL/Praktykanta, ważnych lub poprawnie wygasłych tokenów ani kompletnej publicznej aplikacji. Rewizji backendu/frontendu nie mierzono ponownie podczas tej próby; ostatni sprawdzony backend7814fdf pozostaje wcześniejszym pomiarem.

## Dostępność po końcowym zatrudnieniu593528

S123 rozszerzono o próbę po zatrudnieniu; poprzednie obserwacje z etapuUmowa pozostają historyczne. Literalne wyszukiwanie własnego nazwiska daje1rekord, termin dostępności nadal „brak”, etykieta procesu „Pracuje u nas”. Podgląd procesu pokazuje „Brak rekrutacji w toku” oraz własny projekt, co odpowiada zamkniętemu etapowiZatrudniony(E425–E426).

| Wariant dostępności | Jawne zastosowane warunki UI/URL | Wynik własnej osoby |
|---|---|---|
| Bez znaczenia | Brak employment/availability | 1 |
| Nie wiemy | employment=available AND availability=unknown | 0(E427) |
| Pracuje u naszego klienta | employment=at_client; wcześniejszy warunekunknown usunięty | 1(E428) |
| Tak — można zaproponować | employment=available AND availability=actively_looking,open_to_offers | 0(E429) |
| Nie szuka | employment=available AND availability=not_looking | 0(E430) |
| Wyczyść dostępność → Szukaj → reload | Zachowana fraza i tm=literal, usunięte warunki dostępności | 1(E431) |

Zmiana radia przygotowuje filtry; tabela zachowuje poprzedni wynik aż do „Szukaj”, co UI jawnie opisuje. Po zastosowaniu URL i chipy odpowiadają nowemu wariantowi. Nie znaleziono w tej próbie pozostałości poprzedniego wariantu. „Nie wiemy” nie oznacza samego pustego terminu — zawiera też warunek niezatrudnienia u klienta.

**S123 nadal PARTIAL:** próba potwierdza opisaną kompozycję filtrów i spójność z klasyfikacją UI po zatrudnieniu. Nie rozstrzyga, czy przyszły start675 powinien wykluczać bieżącą etykietę „Pracuje u nas”, ani automatycznej zmiany według dat. Nie zgłoszono nowego błędu bez potwierdzonej reguły biznesowej. Ostatnia zmiana biznesowa nie pochodzi z tej próby; nowe były wyłącznie odczyt i filtry. Zamknięto tylko nową kartę testową, wracając do niezaakceptowanego cofnięcia676/735(E432).

## Status dalszej pracy: zablokowany

Po trzech kolejnych turach bez postępu potwierdzono tę samą blokadę: brak sesji innych ról, odpowiedzi na konkretne potwierdzenia oraz kontrolowanego pilota rzeczywistych integracji. Artur pozostaje jedyną uwierzytelnioną personą; Bruce przy ponownym wejściu doDashboard prowadzi do logowania. Nie istnieje aktualny proces/job, na który weryfikowalnie czekamy. Cel oznaczono blocked, nie complete; statystyki148/27/432 nie wzrosły od powtórzeń sprawdzenia blokady.

Do wznowienia pełnego zakresu potrzebne są istniejące konta testowe Rekrutera, DeliveryLeada i Praktykanta oraz uzgodniony pilot integracji/podpisów/rozliczenia. Dwa konkretne potwierdzenia UI już przedstawiono: cofnięcie zakończenia wyłącznie syntetycznego676 i przywrócenie735 oraz odwołanie własnego syntetycznego zdarzenia27.09 08:15–08:30 dla598805/693762. Nie zaakceptowano ich bez odpowiedzi użytkownika, ponieważ zasady narzędziaCUA wymagają konkretnego potwierdzenia dodatkowego ostrzeżenia aplikacji. Nie dokonano zmian dostępu ani legalnego podpisu.

Szczegółowy audyt kompletności: [completion-audit.json](completion-audit.json). Raport wykonanych prób jest gotowy, lecz głęboki audyt całego systemu i kompletny produkcyjny procesA–Z pozostają nieukończone.
