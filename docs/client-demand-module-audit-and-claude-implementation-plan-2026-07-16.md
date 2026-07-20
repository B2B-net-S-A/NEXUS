# Moduł 1 — Klient, relacje i zapotrzebowanie

## Audyt, rekomendacja docelowa i szczegółowy plan implementacyjny dla Claude Code

**Data audytu:** 2026-07-16  
**Repozytorium:** NEXUS  
**Zakres źródłowy:** <code>origin/main</code> na commicie <code>b94714295c77c2270a35616f84b696cf782e0aa7</code>  
**Wersja produkcyjna podczas audytu:** <code>a301ee433e7e298d16529352590dabea654f3db5</code>  
**Charakter dokumentu:** raport decyzyjny i plan wykonawczy; ten dokument nie zmienia działania systemu

---

## 1. Streszczenie zarządcze

Moduł ma dużo wartościowych elementów: profil klienta, zespół, kontakty, wiedzę, materiały, stanowiska, kontrakty i zamówienia. Nie tworzą one jednak jeszcze jednego bezpiecznego i spójnego przepływu od zgłoszonej potrzeby klienta do gotowego stanowiska.

Najważniejsze decyzje:

1. **Nie należy używać encji <code>ClientOrder</code> jako zapotrzebowania rekrutacyjnego.**  
   W obecnym modelu jest to zamówienie/PO tworzone dla konkretnego kontraktu po zatrudnieniu kandydata. Zapotrzebowanie klienta powinno dostać osobną encję <code>ClientDemand</code> albo <code>JobBrief</code>.

2. **Najpierw trzeba zamknąć luki dostępu i integralności.**  
   Obecne zależności API w kilku miejscach sprawdzają jedynie, czy użytkownik jest aktywny i zalogowany. Pozwala to zbyt szerokiej grupie użytkowników modyfikować kontakty, właścicieli relacji i wiedzę klienta oraz czytać pola prawne, finansowe i relacyjne.

3. **Stanowisko musi mieć obliczaną gotowość operacyjną.**  
   Niekompletny szkic może dziś wejść do pipeline’u, uruchomić klasyfikację, embeddingi i powiadomienia. Stanowisko powinno przejść przez walidowany próg gotowości przed publikacją, matchingiem, dodawaniem kandydatów i generowaniem części artefaktów AI.

4. **Klient musi być jedną kanoniczną tożsamością.**  
   Produkcja pokazuje duplikaty klientów oraz technicznego klienta importowego. Różne endpointy inaczej respektują <code>hidden</code> i <code>display_name</code>. To zniekształca listy, relacje, raporty i finanse.

5. **Finanse trzeba przeliczać zapytaniami agregującymi, per waluta i bez zależności od paginacji.**  
   Obecne MRR/LTV i liczby zamówień mogą powstawać z ograniczonego zbioru, mieszać waluty albo używać niezgodnych definicji.

6. **Pliki klienta wymagają transakcyjnego i bezpiecznego pipeline’u.**  
   Walidacja oparta na rozszerzeniu lub MIME, zapis przed utworzeniem encji i kasowanie starego pliku przed zatwierdzeniem transakcji tworzą ryzyko osieroconych albo brakujących plików.

Rekomendowany sposób realizacji to **7 małych, zależnych PR-ów**, a nie jeden duży refactor. Pierwszy PR ma charakter containmentu bezpieczeństwa. Nowe flow zapotrzebowania powinno być wdrażane za feature flagą, z migracją istniejących danych dopiero po pomiarze jakości.

---

## 2. Zakres modułu

### 2.1. W zakresie

Moduł 1 obejmuje:

- kanoniczną kartotekę klienta;
- kontakty i właścicieli relacji;
- zespół obsługujący klienta: DL, TAC, recruiterzy i inne role;
- prywatną oraz operacyjną wiedzę o kliencie;
- materiały, dokumenty wymagane i one-pagery;
- przyjęcie zapotrzebowania/briefu;
- zamianę kompletnego briefu w stanowisko;
- gotowość stanowiska do publikacji i pipeline’u;
- zależności z umową ramową, kontraktem konsultanta i zamówieniem klienta;
- podstawowe statystyki klienta, marżę i LTV;
- audyt, uprawnienia, obserwowalność i testy tego przepływu.

### 2.2. Świadomie poza zakresem

- przebudowa całego matchingu kandydatów;
- pełna przebudowa pipeline’u rekrutacyjnego po dodaniu kandydata;
- migracja Traffit jako całość;
- generowanie umów B2B niezwiązane z integralnością klienta;
- ogólnosystemowy redesign;
- zmiana mechanizmu logowania;
- zmiana infrastruktury deploymentu.

Te obszary mogą korzystać z nowych kontraktów modułu, ale nie powinny zostać wciągnięte do jego pierwszej implementacji.

---

## 3. Źródła dowodowe i ograniczenia audytu

### 3.1. Stan kodu

- Analiza kodu została zakotwiczona na najnowszym <code>origin/main</code>: <code>b947142</code>.
- Lokalny checkout był rescue branchem z dużą liczbą niezwiązanych zmian. Nie został potraktowany jako prawda produkcyjna.
- Żadna istniejąca zmiana lokalna nie została usunięta, zresetowana ani dołączona do raportu.

### 3.2. Stan produkcji

Podczas audytu endpoint <code>GET /api/health</code> zwrócił:

- status ogólny: <code>healthy</code>;
- wersję: <code>a301ee4...</code>;
- bazę danych: <code>healthy</code>;
- CloudTalk: <code>unhealthy</code>;
- Traffit: <code>degraded</code>.

Wersja produkcyjna była o 17 commitów za analizowanym <code>origin/main</code>. Dlatego dokument rozdziela:

- **objawy potwierdzone na produkcji**;
- **błędy i ryzyka potwierdzone w kodzie <code>origin/main</code>**;
- **hipotezy wymagające logów lub zapytań do bazy**.

### 3.3. Ograniczenie danych administracyjnych

Nie udało się pobrać <code>/api/admin/snapshot</code>:

- w lokalnym środowisku nie było pliku z tokenem ani zmiennej <code>NEXUS_SNAPSHOT_TOKEN</code>;
- bez tokenu endpoint zwrócił 401.

W konsekwencji nie należy traktować liczebności potencjalnych niespójności opisanych w raporcie jako zmierzonych. Przed migracjami Claude ma wykonać zapytania preflight z sekcji 13 na środowisku mającym bezpieczny dostęp administracyjny.

### 3.4. Produkcyjne flow sprawdzone w przeglądarce

Sprawdzono read-only:

- listę klientów;
- dwa profile klienta, w tym profil z aktywnymi stanowiskami i konsultantem;
- Moich klientów;
- Moje relacje;
- listę stanowisk;
- szczegóły i edycję szkicu stanowiska.

Nie wykonywano zmian danych produkcyjnych.

---

## 4. Obecny i docelowy przepływ

### 4.1. Obecny przepływ

~~~mermaid
flowchart LR
    A["Klient w clients"] --> B["Ręczne utworzenie Job"]
    B --> C["Job może pozostać niekompletnym draftem"]
    C --> D["Embedding, klasyfikacja, snapshot propozycji i powiadomienia"]
    C --> E["Dodawanie kandydatów do pipeline"]
    E --> F["Etap hired"]
    F --> G["Draft Contract"]
    F --> H["Draft ClientOrder / PO"]
    A --> I["Kontakty, wiedza, pliki i umowy ramowe"]
    I -. "brak jednego kontraktu gotowości" .-> B
~~~

Problemy obecnego modelu:

- brakuje trwałego rekordu opisującego, kto i kiedy zgłosił potrzebę;
- nie ma statusu „wymaga doprecyzowania”;
- nie ma jednego miejsca na wymagania, budżet, liczbę osób, deadline i decydenta;
- nie ma jednoznacznego progu gotowości;
- <code>ClientOrder</code> powstaje dopiero w kontekście kontraktu i nie może wiarygodnie pełnić roli briefu;
- efekty uboczne uruchamiają się dla niekompletnego szkicu;
- późniejsza zmiana klienta lub powiązań może stworzyć rekordy łączące różne firmy.

### 4.2. Docelowy przepływ

~~~mermaid
flowchart LR
    A["Kanoniczny klient"] --> B["ClientDemand: intake"]
    B --> C["needs_clarification"]
    C --> D["ready"]
    D --> E["Idempotentne promote do Job"]
    E --> F["Job readiness = ready"]
    F --> G["Publish / matching / pipeline / AI"]
    G --> H["Kandydat hired"]
    H --> I["Draft Contract"]
    H --> J["Draft ClientOrder / PO"]
    I --> K["Wspólna walidowana aktywacja"]
    J --> K
    A --> L["Kontakty, zespół, wiedza, materiały, framework"]
    L --> B
    L --> F
~~~

Kluczowe rozróżnienie:

- <code>ClientDemand</code> odpowiada na pytanie: **czego klient potrzebuje?**
- <code>Job</code> odpowiada na pytanie: **jak prowadzimy rekrutację na gotowe zapotrzebowanie?**
- <code>Contract</code> odpowiada na pytanie: **na jakich warunkach pracuje wybrany konsultant?**
- <code>ClientOrder</code> odpowiada na pytanie: **jakie zamówienie/PO klienta pokrywa konkretny kontrakt?**

---

## 5. Co warto zachować

Plan nie powinien przepisywać wszystkiego. Należy zachować i rozwinąć:

- istniejącą kartę klienta z zakładkami i kontekstowymi akcjami;
- model zespołu klienta;
- <code>display_name</code> i <code>hidden</code> jako zalążek kanonicznej prezentacji;
- istniejący helper dostępu finansowego w <code>backend/app/api/financial_access.py</code>;
- obecne mechanizmy draftów kontraktów;
- generowanie pary draft Contract + ClientOrder po zatrudnieniu;
- istniejące komponenty design systemu w <code>frontend/src/components/ds/</code>;
- obecne testy klienta, kontraktów, zespołu i pipeline’u;
- stabilny kontrakt <code>/api/health</code>;
- istniejący model wielu ról użytkownika, ale z konsekwentnym użyciem <code>has_any_role</code>.

---

## 6. Rejestr najważniejszych ustaleń

| ID | Priorytet | Ustalenie | Skutek |
|---|---:|---|---|
| M1-SEC-01 | P0 | Kontakty i wiedza klienta są modyfikowalne przy samym <code>CurrentUser</code> | Zbyt szeroka możliwość zmiany właścicieli relacji i kontekstu używanego przez AI |
| M1-SEC-02 | P0 | Wiele endpointów zwraca pola prawne, finansowe, pliki i prywatne notatki bez polityki per klient | Nadmierna ekspozycja danych i brak least privilege |
| M1-ID-01 | P1 | Listy klientów niespójnie respektują <code>hidden</code> i <code>display_name</code> | Duplikaty i rekordy techniczne w UI oraz raportach |
| M1-ID-02 | P1 | Brak spójnej procedury merge i bezpiecznego archive | Trwałe duplikaty; hard delete grozi konfliktami FK |
| M1-DATA-01 | P1 | Powiązane encje nie wymuszają zgodności <code>client_id</code> | Job, kontakt, kontrakt, framework i order mogą wskazywać różne firmy |
| M1-DOM-01 | P1 | Brak osobnej encji zapotrzebowania/briefu | Utrata historii intake i brak ścieżki doprecyzowania |
| M1-DOM-02 | P1 | Brak readiness gate stanowiska | Niekompletne drafty mogą wejść do pipeline’u i uruchamiać efekty uboczne |
| M1-LIFE-01 | P1 | Różne ścieżki inaczej aktywują kontrakt i zamówienie | Sprzeczne stany, np. aktywny kontrakt przy anulowanym zamówieniu |
| M1-LIFE-02 | P1 | Krytyczne hooki nie są wystarczająco idempotentne | Duplikaty przy retry lub równoległych żądaniach |
| M1-FIN-01 | P1 | LTV/MRR zależą od limitu, mieszają definicje lub waluty | Błędne decyzje handlowe i raportowanie |
| M1-FILE-01 | P1 | Upload i zamiana pliku nie są atomowe z transakcją DB | Osierocone pliki albo rekord wskazujący brakujący obiekt |
| M1-TEST-01 | P1 | Krytyczne testy modułu nie są objęte wymaganym jobem CI | Regresje mogą zostać zmergowane mimo istnienia testów |
| M1-RBAC-02 | P2 | Część kodu porównuje pojedyncze <code>user.role</code> | Użytkownik z wieloma rolami może dostać zły zakres danych |
| M1-PERF-01 | P2 | Kontakty, wiedza i portale DL są bez pełnej paginacji; występuje N+1 | Rosnący czas odpowiedzi i ciężki frontend |
| M1-UX-01 | P2 | Zakładka klienta nie jest synchronizowana z URL | Deep link z Moich klientów otwiera złą zakładkę |
| M1-UX-02 | P2 | Lookupy w edycji stanowiska mogą zakończyć się pustą listą bez błędu | Użytkownik nie wie, czy nie ma danych, czy API zawiodło |
| M1-UX-03 | P2 | Niespójny język, surowe statusy, hardcoded colors i braki a11y | Gorsza obsługa, dostępność i zgodność z design systemem |
| M1-OBS-01 | P2 | Brak kompletnego snapshotu jakości modułu | Niespójności są wykrywane dopiero przez użytkownika |

---

## 7. Szczegółowe ustalenia i rekomendacje

## 7.1. Bezpieczeństwo i polityka dostępu

### M1-SEC-01 — zapis kontaktów i wiedzy przy zbyt słabej zależności

**Dowód w kodzie**

- <code>backend/app/api/deps.py</code>: <code>CurrentUser</code> potwierdza aktywnego, zalogowanego użytkownika, ale nie rozstrzyga jego dostępu do konkretnego klienta.
- <code>backend/app/api/contacts.py</code>: lista oraz operacje create/update/delete opierają się na <code>CurrentUser</code>.
- Ten sam endpoint pozwala ustawić <code>key_relationship_owner_id</code>.
- <code>backend/app/api/client_knowledge.py</code>: tworzenie i usuwanie wpisów również używa samego <code>CurrentUser</code>.
- Wiedza klienta jest konsumowana m.in. przez:
  - <code>backend/app/services/ai_writer.py</code>;
  - <code>backend/app/services/prep_kit.py</code>;
  - <code>backend/app/services/question_suggestions.py</code>.

**Ryzyko**

- aktywny użytkownik bez właściwej roli może zmienić właściciela relacji;
- może usunąć albo dopisać dane wykorzystywane później przez AI;
- zmiana nie ma jednego, czytelnego śladu audytowego;
- prywatne notatki relacyjne obejmują w modelu m.in. urodziny, hobby, rodzinę, lokalizację i preferencje prezentowe.

**Rekomendacja**

Wprowadzić jeden resolver <code>ClientAccess</code>, który zwraca:

- <code>can_view_summary</code>;
- <code>can_view_contacts</code>;
- <code>can_view_private_relationship_notes</code>;
- <code>can_edit_contacts</code>;
- <code>can_reassign_relationship_owner</code>;
- <code>can_edit_knowledge</code>;
- <code>can_view_financials</code>;
- <code>can_view_legal_documents</code>;
- <code>can_manage_client</code>.

Resolver ma uwzględniać:

- role globalne: admin i HoR;
- przypisanie DL/TAC do klienta;
- przypisanie do stanowiska tego klienta;
- bycie właścicielem konkretnej relacji;
- ewentualny jawny grant, jeśli biznes faktycznie go potrzebuje.

Zmianę <code>key_relationship_owner_id</code>, merge klienta oraz dostęp do prawnych/finansowych danych należy ograniczyć bardziej niż zwykłą edycję telefonu kontaktu.

**Kryteria akceptacji**

- viewer/user nie może tworzyć, zmieniać ani kasować kontaktu bez jawnego uprawnienia;
- właściciel relacji może edytować dozwolone pola swojego kontaktu, ale nie może sam przepisać ownera;
- recruiter widzi tylko bezpieczną projekcję klienta w kontekście przypisanego stanowiska;
- admin/HoR ma pełny dostęp;
- każda odmowa ma 403, a brak encji 404; API nie ujawnia istnienia klienta osobie bez prawa podglądu;
- testy obejmują macierz rola × relacja × operacja;
- create/update/delete/reassign generują audit event z aktorem, klientem, encją i zestawem zmienionych pól.

### M1-SEC-02 — zbyt szeroka projekcja danych klienta

**Dowód w kodzie**

Ogólne endpointy klienta zwracają lub umożliwiają pobranie:

- legal name;
- adresu;
- NIP/REGON;
- notatek;
- statusu NDA;
- materiałów i dokumentów;
- danych powiązanych z kontraktami i zamówieniami.

Część tras materiałów, frameworków i wymaganych dokumentów również opiera się na ogólnej autoryzacji. Istnieje helper <code>backend/app/api/financial_access.py</code>, ale nie jest konsekwentnie używany w całym module.

**Rekomendacja**

Rozdzielić schematy odpowiedzi:

- <code>ClientSafeSummary</code> — id, display name, status, industry i pola niezbędne operacyjnie;
- <code>ClientRelationshipView</code> — kontakty i tylko dozwolone notatki;
- <code>ClientLegalView</code> — dane rejestrowe, framework, dokumenty;
- <code>ClientFinancialView</code> — stawki, marże, LTV i ordery;
- <code>ClientAdminView</code> — pola systemowe, źródła, merge i audit.

Nie należy polegać wyłącznie na ukrywaniu sekcji w UI. Backend musi zwracać projekcję odpowiednią do decyzji <code>ClientAccess</code>.

**Kryteria akceptacji**

- rola bez finansów nie dostaje pól finansowych nawet w JSON;
- rola bez prawa do prywatnych notatek nie dostaje ich jako <code>null</code>, tylko pole nie występuje w używanym kontrakcie;
- link bezpośredni do dokumentu przechodzi autoryzowany download, nie publiczny URL;
- test snapshotowy schematów nie pozwala przypadkowo rozszerzyć projekcji;
- frontend nie renderuje i nie cache’uje danych, do których użytkownik nie ma prawa.

### M1-RBAC-02 — pojedyncza rola zamiast modelu multi-role

**Dowód w kodzie**

W <code>my_clients.py</code>, <code>my_relationships.py</code> i <code>clients_team.py</code> występują bezpośrednie porównania roli. System ma jednak model wielu ról.

**Rekomendacja**

- używać jednego helpera <code>has_any_role</code>;
- nie wyprowadzać dostępu z pierwszej lub „głównej” roli;
- decyzje per klient delegować do <code>ClientAccess</code>;
- dodać test użytkownika z kombinacją np. recruiter + DL.

---

## 7.2. Kanoniczna tożsamość klienta

### M1-ID-01 — duplikaty i techniczne rekordy w widokach

**Potwierdzone na produkcji**

W widoku Moich klientów administrator widział wszystkie 157 firm. Widoczne były m.in. dokładne znormalizowane duplikaty:

- Bank Millennium: dwa rekordy;
- LOTTE Wedel: dwa rekordy;
- Visa: dwa rekordy.

Widoczny był też techniczny klient <code>__traffit_orphans</code>.

**Dowód w kodzie**

- <code>backend/app/api/clients.py</code> pobiera klientów bez konsekwentnego <code>hidden = false</code>, bez <code>coalesce(display_name, name)</code> i bez deterministycznego sortowania.
- Wyszukiwanie w tym endpointcie obejmuje tylko <code>Client.name</code>.
- Endpoint lookup w <code>backend/app/api/phase5.py</code> poprawnie wyklucza hidden i używa display name.
- Migracja <code>0127_client_display_override.py</code> opisuje <code>hidden</code> jako mechanizm ukrywania duplikatów.

**Rekomendacja**

Wprowadzić wspólny <code>ClientQueryService</code> i używać go we wszystkich listach oraz lookupach:

- domyślnie <code>hidden = false</code>;
- domyślnie <code>is_system = false</code>;
- label = <code>coalesce(display_name, legal_name, name)</code>;
- deterministyczne sortowanie: normalized label, potem id;
- wyszukiwanie po display name, name, legal name, NIP/REGON i — gdy użytkownik ma prawo — po emailu kontaktu;
- server-side pagination i sortowanie;
- możliwość jawnego <code>include_hidden</code> tylko dla admina.

Dodać:

- <code>normalized_name</code>;
- <code>is_system</code>;
- <code>merged_into_client_id</code>;
- <code>archived_at</code>, <code>archived_by</code>;
- audit zdarzeń merge/archive.

Nie wykonywać automatycznego fuzzy merge. Bezpieczne automatyczne kandydatury do merge można opierać na:

1. identycznym NIP;
2. identycznym stabilnym identyfikatorze źródłowym;
3. identycznej domenie i znormalizowanej nazwie jako sugestii do ręcznego zatwierdzenia.

**Kryteria akceptacji**

- wszystkie listy i lookupy pokazują tę samą nazwę;
- <code>__traffit_orphans</code> nie pojawia się w UI biznesowym;
- hidden/merged rekord nie może zostać wybrany dla nowego zapotrzebowania;
- stary deep link do merged klienta przekierowuje do klienta kanonicznego;
- merge jest transakcyjny i aktualizuje wszystkie zależne FK;
- przed merge dostępny jest dry-run z liczbą rekordów do przeniesienia;
- operacja zostawia pełny audit.

### M1-ID-02 — create/update/delete bez bezpiecznego cyklu życia

**Dowód w kodzie**

- create/update klienta nie mają wystarczającej normalizacji ani podpowiedzi duplikatu;
- schemat update pozwala na zbyt szerokie zerowanie pól;
- delete wykonuje bezpośrednie <code>db.delete</code> mimo wielu zależności.

**Rekomendacja**

- create: trim, NFC, normalizacja białych znaków, walidacja NIP/REGON i wyszukanie kandydatów duplikatu;
- update: jawny patch model, rozróżnienie „brak pola” od „wyczyść pole”;
- archive zamiast zwykłego delete;
- hard purge wyłącznie jako osobna operacja administracyjna z retencją i checklistą;
- merge zamiast kasowania duplikatu.

**Kryteria akceptacji**

- standardowy endpoint DELETE nie usuwa fizycznie klienta;
- klient z aktywnym demand/job/contract/order nie może być archiwizowany bez czytelnego powodu albo zatwierdzonego procesu;
- formularz tworzenia pokazuje potencjalne duplikaty przed zapisem;
- walidacja nie polega wyłącznie na frontendzie.

---

## 7.3. Integralność między encjami

### M1-DATA-01 — brak gwarancji, że powiązane rekordy należą do jednego klienta

**Dowód w kodzie**

<code>ClientOrder</code> przechowuje osobno:

- <code>client_id</code>;
- <code>contract_id</code>;
- <code>job_id</code>;
- <code>framework_contract_id</code>.

Każde pole ma zwykły FK, ale baza nie gwarantuje, że wszystkie wskazane encje mają ten sam <code>client_id</code>.

Dodatkowo:

- create order sprawdza część relacji, ale nie wszystkie;
- PATCH może bez pełnej walidacji podmienić job/framework;
- create contract przyjmuje klienta i job bez kompletnego same-client guard;
- framework parent/terms nie są konsekwentnie walidowane per klient;
- job może wskazać hiring managera z innej firmy;
- zmiana <code>Job.client_id</code> po utworzeniu zależności nie jest bezpiecznie ograniczona.

**Rekomendacja**

Zastosować dwa poziomy ochrony.

**Poziom aplikacji**

Jeden <code>ClientRelationValidator</code>, używany we wszystkich commandach:

- create/update Job;
- create/update Contract;
- create/update ClientOrder;
- create/update Framework;
- promote Demand → Job;
- merge/transfer klienta.

**Poziom bazy**

Po oczyszczeniu danych dodać unikalne pary:

- <code>contacts(id, client_id)</code>;
- <code>jobs(id, client_id)</code>;
- <code>contracts(id, client_id)</code>;
- <code>client_framework_contracts(id, client_id)</code>;
- <code>client_contract_terms(id, client_id)</code>.

Następnie kompozytowe FK:

- <code>client_orders(contract_id, client_id) → contracts(id, client_id)</code>;
- <code>client_orders(job_id, client_id) → jobs(id, client_id)</code>;
- <code>client_orders(framework_contract_id, client_id) → client_framework_contracts(id, client_id)</code>;
- <code>jobs(hiring_manager_contact_id, client_id) → contacts(id, client_id)</code>;
- <code>client_framework_contracts(parent_contract_id, client_id) → client_framework_contracts(id, client_id)</code>;
- <code>client_framework_contracts(contract_terms_id, client_id) → client_contract_terms(id, client_id)</code>.

Jeśli używana wersja Postgresa i Alembic na to pozwalają, constraints wdrażać etapowo:

1. preflight;
2. naprawa danych;
3. constraint <code>NOT VALID</code>;
4. walidacja;
5. dopiero potem usunięcie starych ścieżek obchodzących walidację.

**Kryteria akceptacji**

- nie da się przez API ani SQL utworzyć orderu z kontraktem innego klienta;
- nie da się wybrać hiring managera spoza firmy;
- zmiana klienta stanowiska z kandydatami/kontraktem/orderem kończy się 409 i listą blokujących zależności;
- jawny transfer jest osobną komendą administracyjną, nie zwykłym PATCH;
- migracja działa na wszystkich Alembic heads;
- każda nowa kolumna/tabela/constraint jest odzwierciedlona idempotentnie w <code>backend/entrypoint.sh</code>.

---

## 7.4. Brak intake zapotrzebowania i gotowości stanowiska

### M1-DOM-01 — <code>ClientOrder</code> nie jest briefem

**Dowód domenowy i kodowy**

<code>backend/app/models/client_order.py</code> opisuje order jako zamówienie klienta dla konkretnego kontraktu po placement. Obecny hook „hired” tworzy draft Contract i draft ClientOrder.

To oznacza, że zmiana nazwy tej encji albo wykorzystanie jej wcześniej:

- miesza pre-sales/delivery z finansowo-prawnym PO;
- wymusza fikcyjny kontrakt przed wybraniem osoby;
- nie obsługuje zapotrzebowania na kilka osób;
- utrudnia anulowanie briefu bez skutków księgowych;
- niszczy czytelną historię lejka popytu.

**Rekomendacja: nowa encja <code>ClientDemand</code>**

Minimalne pola:

| Grupa | Pola |
|---|---|
| Tożsamość | id, client_id, title, source, external_key |
| Treść | description, business_context, responsibilities, requirements |
| Kompetencje | must_have_skills, nice_to_have_skills, languages |
| Skala | headcount |
| Warunki | work_mode, location, remote_ratio, rate_min, rate_max, currency, rate_unit |
| Terminy | requested_start_date, response_deadline, priority |
| Relacje | hiring_manager_contact_id, delivery_lead_id, tac_id, recruiter_id |
| Stan | status, missing_fields, readiness_version, cancellation_reason |
| Lineage | converted_job_id, created_by, updated_by, created_at, updated_at, version |

Statusy:

- <code>intake</code>;
- <code>needs_clarification</code>;
- <code>ready</code>;
- <code>converted</code>;
- <code>cancelled</code>.

Inwarianty:

- <code>ready</code> jest wynikiem walidacji, nie dowolnym tekstem;
- <code>converted</code> wymaga <code>converted_job_id</code>;
- początkowo jeden demand tworzy najwyżej jeden job;
- create i promote obsługują <code>Idempotency-Key</code>;
- <code>(source, external_key)</code> jest unikalne, gdy external key istnieje;
- po konwersji zachowujemy immutable snapshot briefu albo wersjonowane zmiany.

**Proponowane API**

- <code>GET /api/client-demands</code>;
- <code>POST /api/client-demands</code>;
- <code>GET /api/client-demands/{id}</code>;
- <code>PATCH /api/client-demands/{id}</code>;
- <code>GET /api/client-demands/{id}/readiness</code>;
- <code>POST /api/client-demands/{id}/mark-ready</code>;
- <code>POST /api/client-demands/{id}/promote</code>;
- <code>POST /api/client-demands/{id}/cancel</code>.

Statusy HTTP:

- 400 — niepoprawna składnia lub zakres wartości;
- 403 — brak prawa do klienta/operacji;
- 404 — rekord niewidoczny albo nie istnieje;
- 409 — konflikt wersji, ponowna konwersja, blokująca zależność;
- 422 — poprawne żądanie, ale nie spełnia reguł gotowości;
- 201 — utworzenie demand/job;
- 200 — idempotentny retry zwracający istniejący rezultat.

### M1-DOM-02 — niekompletne Job może działać jak gotowe

**Potwierdzone na produkcji**

- lista stanowisk miała 4036 pozycji i 202 strony;
- pierwsze 20 pozycji było draftami;
- 20/20 nie miało TAC;
- 20/20 nie miało właściciela;
- jeden sprawdzony draft miał czterech kandydatów w pipeline i brak ownera/collaborators.

**Dowód w kodzie**

- <code>JobCreate</code> nie przechowuje lineage briefu;
- frontend waliduje obowiązkowo głównie tytuł, choć backend wymaga także klienta;
- create job od razu uruchamia embedding, klasyfikację, snapshot propozycji oraz część powiadomień;
- publish zmienia status bez pełnego readiness check;
- pipeline move oraz dodawanie kandydata nie mają wspólnej bramy gotowości.

**Rekomendacja**

Wprowadzić jeden, czysty <code>JobReadinessService</code>.

Przykładowe blokery gotowości:

- brak kanonicznego, aktywnego klienta;
- brak opisu zakresu i wymagań;
- brak co najmniej jednego must-have;
- brak work mode/lokalizacji;
- brak waluty i zakresu stawki, jeśli stanowisko jest rozliczane stawką;
- brak headcount;
- brak właściciela operacyjnego;
- hiring manager nie należy do klienta;
- brak zgód/warunków wymaganych przez konfigurację klienta;
- demand nie ma statusu ready, jeśli job powstał z demand.

Gotowość powinna zwracać:

~~~json
{
  "ready": false,
  "version": 1,
  "blockers": [
    {
      "code": "missing_owner",
      "field": "owner_id",
      "message": "Przypisz właściciela stanowiska"
    }
  ],
  "warnings": []
}
~~~

Ta sama usługa ma być wywoływana przez:

- publish;
- add candidate;
- move candidate do aktywnego etapu;
- matching;
- marketplace notification;
- podobne stanowiska;
- generowanie artefaktów AI wymagających kompletnego briefu.

Dozwolony wyjątek: użytkownik może zapisać niekompletny draft i opcjonalnie uruchomić jawny „preview”, ale preview nie może emitować biznesowych powiadomień ani otwierać pipeline’u.

**Kryteria akceptacji**

- draft może być niekompletny i zapisywalny;
- niekompletny draft nie przyjmuje kandydatów;
- publish dla niekompletnego joba zwraca 422 z tym samym zestawem blockerów, który pokazuje UI;
- promote demand jest idempotentne;
- efekty uboczne uruchamiają się dopiero po przejściu gotowości;
- zmiana danych po publikacji, która łamie readiness, wymaga świadomego powrotu do draftu albo jest blokowana;
- gotowość ma testy jednostkowe tabelaryczne i testy integracyjne dla każdej bramy.

---

## 7.5. Cykl życia kontraktu i zamówienia

### M1-LIFE-01 — kilka konkurujących definicji aktywacji

**Dowód w kodzie**

- flow <code>/contract-with-order</code> potrafi utworzyć od razu aktywny Contract i aktywny ClientOrder;
- wspólna walidacja w <code>backend/app/services/contract_service.py</code> wymaga większej liczby pól;
- hook hired tworzy drafty;
- UI produkcyjne pokazało aktywny kontrakt, którego jedyne widoczne zamówienie było anulowane.

Ostatni punkt jest potwierdzonym objawem niespójności, ale bez snapshotu i audytu rekordu nie przesądza, która konkretna ścieżka go utworzyła.

**Rekomendacja**

- wszystkie ścieżki tworzą draft;
- jedna komenda <code>activate_contract_package</code> aktywuje Contract i ClientOrder atomowo;
- komenda korzysta z jednego walidatora;
- zabronić aktywnego kontraktu, jeśli wymagane zamówienie jest cancelled/expired;
- każda zmiana statusu ma jawny transition, aktora, timestamp i reason;
- retry tej samej komendy jest idempotentny.

Przykładowa macierz przejść:

| Encja | Z | Do | Warunek |
|---|---|---|---|
| Contract | draft | active | komplet danych, aktywny klient, zgodny job/order |
| Contract | active | ended | data zakończenia lub jawna terminacja |
| Contract | active | suspended | powód i uprawnienie |
| ClientOrder | draft | active | zgodny kontrakt/framework, okres i waluta |
| ClientOrder | active | cancelled | powód; kontrakt nie może pozostać bez pokrycia |
| ClientOrder | active | expired | data końca i worker |

### M1-LIFE-02 — idempotencja, konkurencja i duplikaty

**Ryzyka w kodzie**

- hired hook wykonuje „SELECT, a potem INSERT”; dwa równoległe wywołania mogą utworzyć duplikat;
- numer referencyjny stanowiska oparty o <code>max + 1</code> ma race condition;
- ustawienie primary/head zespołu klienta demotuje i ustawia rekordy bez blokady klienta;
- wysyłki Autenti/framework mogą być powtórzone;
- alert końca umowy ma równoległe źródła prawdy i możliwą kolizję deduplikacji.

**Rekomendacja**

- unique <code>source_hired_stage_id</code> albo osobny klucz idempotencji dla package creation;
- tabela/sequence/counter dla numerów stanowisk;
- <code>SELECT ... FOR UPDATE</code> na rekordzie klienta przy zmianie primary/head;
- idempotentne PUT „set primary”, nie sekwencja demote + create;
- idempotency key i unikalny external envelope id dla wysyłek;
- jedno źródło daty końca zamówienia;
- jeden worker dla jednego rodzaju alertu;
- indeks deduplikacyjny obejmujący typ encji, id encji i typ powiadomienia;
- advisory lock albo persisted watermark dla cyklicznego workera.

**Kryteria akceptacji**

- 20 równoległych retry „hired” tworzy dokładnie jeden contract package;
- 20 równoległych create Job ma unikalne referencje;
- dla klienta istnieje najwyżej jeden primary DL i jeden head TAC zgodnie z regułami;
- ponowna wysyłka z tym samym idempotency key zwraca ten sam rezultat;
- worker można uruchomić równolegle bez podwójnych alertów.

---

## 7.6. Poprawność finansowa

### M1-FIN-01 — LTV, MRR i liczby zamówień nie mają jednego kontraktu

**Potwierdzone na produkcji**

Profil aktywnego klienta pokazywał m.in. aktywną marżę MRR, ale LTV równe 0. Widok mieszał też polskie i angielskie etykiety.

**Dowód w kodzie**

- profil klienta pobiera ograniczoną liczbę historycznych kontraktów, a następnie liczy część statystyk z tej listy;
- <code>active_mrr</code> jest sumą miesięcznych marż bez pełnego kontraktu walutowego;
- czas trwania opiera się na przybliżeniu <code>days // 30</code>;
- wartości Decimal bywają rzutowane do int;
- schema profilu typuje część pieniędzy jako int;
- dashboard grupuje po statusie i walucie, a potem może liczyć grupy jak ordery lub sumować wartości z różnych walut;
- <code>rate_client or contract.rate_client</code> traktuje legalne zero jak brak wartości;
- Moich klientów ma niepoprawny warunek „wygasa wkrótce”.

**Rekomendacja**

Najpierw ustalić słownik:

- bookings — zakontraktowana wartość zamówień;
- revenue — zrealizowany przychód w okresie;
- gross margin — przychód minus koszt konsultanta;
- monthly run-rate — przeliczenie aktywnych stawek na miesiąc;
- LTV — historyczna zrealizowana lub zakontraktowana marża; wybrać jedną i nazwać jawnie;
- placements — liczba unikalnych zatrudnień, nie rekordów kontraktu/orderu.

Następnie:

- liczyć SQL-em niezależnym od listy i paginacji;
- zwracać Money jako <code>{amount: "1234.56", currency: "PLN"}</code>;
- nigdy nie sumować walut bez jawnej konwersji i kursu z datą;
- pokazywać osobne kwoty per waluta, dopóki nie ma zaufanego FX;
- użyć <code>Decimal</code> end-to-end;
- wybrać efektywną stawkę obowiązującą w danym okresie;
- testować częściowe miesiące, leap year, zero rate, zmianę stawki i wiele walut.

**Kryteria akceptacji**

- agregat nie zmienia się po zmianie <code>page_size</code>;
- 101. historyczny kontrakt jest uwzględniony;
- PLN i EUR są prezentowane osobno;
- zero nie uruchamia fallbacku;
- API nie rzutuje części dziesiętnej;
- definicja każdej metryki jest dostępna w tooltipie i dokumentacji;
- test fixture ma ręcznie policzony expected result.

---

## 7.7. Pliki i dokumenty

### M1-FILE-01 — niebezpieczna walidacja oraz brak atomowości

**Dowód w kodzie**

- one-pager akceptuje plik, gdy zgadza się rozszerzenie **lub** deklarowany MIME;
- limit rozmiaru jest sprawdzany po pełnym zapisie na dysk;
- required documents nie mają spójnej walidacji MIME/extension;
- create order potrafi zapisać plik pod tymczasowym <code>order_id=0</code> przed utworzeniem encji;
- w części ścieżek stary plik jest kasowany przed zatwierdzeniem nowego rekordu.

**Ryzyko**

- spoofing typu pliku;
- zużycie dysku dużym uploadem;
- osierocone pliki po rollbacku DB;
- rekord DB wskazujący plik skasowany przed nieudaną transakcją;
- kolizje tymczasowej ścieżki;
- trudny audit i cleanup.

**Rekomendowany pipeline**

1. Odczyt strumieniowy z twardym limitem bajtów.
2. Allowlista rozszerzenia **i** magic bytes; MIME klienta tylko pomocniczo.
3. Zapis do unikalnego obiektu tymczasowego.
4. Skan/normalizacja, jeśli infrastruktura to obsługuje.
5. Utworzenie encji DB i finalnej immutable ścieżki.
6. Commit DB.
7. Dopiero po commicie usunięcie starego obiektu.
8. Cleanup temp przy każdym wyjątku.
9. Download przez autoryzowany endpoint z:
   - <code>Content-Disposition: attachment</code>;
   - <code>X-Content-Type-Options: nosniff</code>;
   - bez ujawniania fizycznej ścieżki.

Dodać:

- checksum;
- rozmiar;
- detected content type;
- uploaded_by;
- created_at;
- version/ETag dla replace;
- audit create/replace/delete/download w zakresie wymaganym przez politykę.

**Kryteria akceptacji**

- plik <code>.pdf</code> z HTML zostaje odrzucony;
- przekroczenie limitu przerywa strumień przed pełnym zapisem;
- nie istnieje ścieżka współdzielona <code>order_id=0</code>;
- błąd DB nie zostawia nowego finalnego obiektu;
- błąd storage nie usuwa starego działającego pliku;
- dwa równoległe replace dają 409 dla przegranej wersji;
- każdy download przechodzi RBAC klienta.

---

## 7.8. Wydajność, UX i testy

### M1-PERF-01 — brak paginacji i N+1

**Ustalenia**

- kontakty, wiedza, Moich klientów i Moje relacje nie mają spójnego modelu paginacji;
- admin widzi na stronie Moich klientów cały zbiór;
- serializacja orderów i liczenie frameworków wykonują dodatkowe zapytania per rekord;
- sortowanie hit ratio w <code>ClientsListV2.tsx</code> odbywa się tylko na aktualnie pobranej stronie, choć wygląda jak globalne.

**Rekomendacja**

Wspólny kontrakt list:

~~~json
{
  "items": [],
  "page": 1,
  "page_size": 25,
  "total": 157,
  "sort": "display_name",
  "direction": "asc"
}
~~~

- backendowe sortowanie wszystkich widocznych kolumn;
- eager loading albo batched aggregate zamiast N+1;
- maksymalny page size;
- indeksy dla faktycznych filtrów;
- query count tests dla list krytycznych;
- tekst wyszukiwania zgodny z polami przeszukiwanymi przez backend.

### M1-UX-01 — URL nie odtwarza zakładki

Widok Moich klientów linkuje do <code>/clients/{id}?tab=analityka</code>, ale strona klienta trzyma aktywną zakładkę wyłącznie w lokalnym state. Bezpośredni link otwiera Profil.

**Rekomendacja**

- <code>useSearchParams</code> jako źródło inicjalnego stanu;
- zmiana taba aktualizuje URL przez router;
- nieznany tab wraca do profilu;
- back/forward przywraca zakładkę;
- użyć semantyki ARIA tablist/tab/tabpanel;
- test komponentowy i Playwright dla deep linku.

### M1-UX-02 — silent lookup failure

W produkcyjnym formularzu edycji Job wszystkie lookup-backed selecty pokazywały tylko placeholdery:

- klient;
- użytkownicy;
- TAC;
- DL;
- hiring manager;
- template;
- competence category.

Jednocześnie strona szczegółów pokazywała nazwę klienta. To potwierdza objaw, ale bez logów nie przesądza, czy przyczyną był 403, błąd jednego Promise, schema mismatch czy filtr hidden.

**Rekomendacja**

Każdy lookup ma jawne stany:

- loading;
- ready with data;
- ready empty;
- forbidden;
- failed with retry.

Jeśli aktualnie wybrana encja stała się hidden/archived, select nadal pokazuje ją jako „aktualna — nie można wybrać ponownie”, ale nie udaje pustej wartości.

Nie łączyć wielu niezależnych lookupów jednym <code>Promise.all</code>, w którym jeden błąd zeruje cały formularz. Używać niezależnych wyników albo <code>allSettled</code> z telemetrią per źródło.

### M1-UX-03 — spójność i dostępność

**Potwierdzone**

- surowe statusy <code>active/inactive/prospect</code>;
- mieszane polskie i angielskie etykiety;
- formularz klienta nie obejmuje legal name/NIP/REGON;
- modal nie ma pełnej semantyki dialogu, label associations i dostępnej nazwy close;
- hardcoded colors;
- instrukcja Moich relacji opisuje inną kolejność niż faktyczne zakładki;
- copy Moich klientów mówi o klientach przypisanych do DL, choć admin widzi wszystkich.

**Rekomendacja**

- token-first design;
- reużycie <code>PageHeader</code>, <code>DataTable</code>, <code>AppModal</code>, <code>TabbedNav</code>, <code>EmptyState</code>;
- pełne polskie etykiety statusów i wspólny słownik;
- dialog focus trap, Escape, restore focus, aria-labelledby;
- label htmlFor/id, opisy błędów przez aria-describedby;
- role-aware copy;
- formularz create client z danymi prawnymi i podpowiedzią duplikatu;
- filtry, wyszukiwarka i paginacja w portalach personalnych;
- poprawny breadcrumb i ikony z tekstem lub accessible name.

### M1-TEST-01 — krytyczne testy nie są wymaganym gate’em

Repozytorium ma m.in.:

- <code>backend/tests/test_client_profile.py</code>;
- <code>backend/tests/test_clients_team.py</code>;
- <code>backend/tests/test_client_materials.py</code>;
- <code>backend/tests/test_reports_clients.py</code>;
- <code>backend/tests/test_contract_finance_rbac.py</code>;
- testy kontraktów, jobów i pipeline’u.

Selektywna lista w <code>.github/workflows/ci.yml</code> nie obejmuje jednak całego krytycznego zestawu modułu, a bezpośrednich testów contact/knowledge i głównych flow frontendowych jest mało lub brak.

**Rekomendacja**

Utworzyć stabilny marker/suite <code>module_client_demand</code> albo jawną listę plików, która jest obowiązkowym jobem CI. Nie uruchamiać całego historycznego suite’u w ciemno, jeśli repo ma live tests; dodać konkretny, deterministyczny kontrakt modułu.

Minimalny gate:

- RBAC matrix;
- client identity/list/merge;
- same-client constraints;
- demand transitions i idempotency;
- job readiness gates;
- hired package idempotency;
- file upload/replace;
- financial fixtures;
- frontend component tests;
- Playwright smoke dla głównego happy path.

---

## 8. Docelowa architektura modułu

### 8.1. Warstwy

1. **API / schemas**  
   Waliduje format, mapuje błędy domenowe na HTTP, nie zawiera rozproszonej logiki biznesowej.

2. **Commands / services**  
   Wykonuje create/update/promote/activate/merge i kontroluje transakcję.

3. **Policies**  
   <code>ClientAccess</code>, projekcje danych i decyzje per operacja.

4. **Domain validators**  
   <code>ClientRelationValidator</code>, <code>DemandReadinessService</code>, <code>JobReadinessService</code>, <code>ContractPackageValidator</code>.

5. **Persistence**  
   Modele, constraints, version columns, repozytoria zapytań list/agregacji.

6. **Effects**  
   Powiadomienia, AI, embeddingi, storage i integracje uruchamiane po poprawnym przejściu stanu, z idempotencją.

Frontend nie powinien odtwarzać reguł gotowości. Ma renderować kody blockerów i ewentualnie mapować je na kontrolki.

### 8.2. Proponowane nowe pliki backendu

Nazwy są rekomendacją; Claude powinien dopasować je do aktualnego układu repo bez tworzenia zbędnych abstrakcji.

- <code>backend/app/models/client_demand.py</code>;
- <code>backend/app/schemas/client_demand.py</code>;
- <code>backend/app/api/client_demands.py</code>;
- <code>backend/app/services/client_access.py</code>;
- <code>backend/app/services/client_identity.py</code>;
- <code>backend/app/services/client_relation_validator.py</code>;
- <code>backend/app/services/client_demand_service.py</code>;
- <code>backend/app/services/job_readiness.py</code>;
- <code>backend/app/services/contract_package_service.py</code>;
- <code>backend/app/services/client_financials.py</code>;
- <code>backend/app/services/safe_upload.py</code>.

### 8.3. Proponowane nowe testy

- <code>backend/tests/test_client_access_matrix.py</code>;
- <code>backend/tests/test_client_identity.py</code>;
- <code>backend/tests/test_client_merge.py</code>;
- <code>backend/tests/test_client_same_client_constraints.py</code>;
- <code>backend/tests/test_client_demands.py</code>;
- <code>backend/tests/test_client_demand_idempotency.py</code>;
- <code>backend/tests/test_job_readiness.py</code>;
- <code>backend/tests/test_contract_package_lifecycle.py</code>;
- <code>backend/tests/test_contract_package_concurrency.py</code>;
- <code>backend/tests/test_client_file_safety.py</code>;
- <code>backend/tests/test_client_financials_v2.py</code>.

### 8.4. Proponowane frontend surfaces

- <code>frontend/src/app/client-demands/page.tsx</code>;
- <code>frontend/src/app/client-demands/[id]/page.tsx</code>;
- <code>frontend/src/components/client-demand/DemandForm.tsx</code>;
- <code>frontend/src/components/client-demand/ReadinessPanel.tsx</code>;
- <code>frontend/src/components/jobs/JobReadinessPanel.tsx</code>;
- wspólny <code>LookupSelect</code> z jawnym loading/error/empty;
- wspólny formatter statusów i Money.

---

## 9. Docelowa macierz uprawnień

To jest rekomendowany punkt startowy. Przed implementacją właściciel produktu powinien potwierdzić nazwy ról, ale backend ma pozostać fail-closed.

| Operacja | Admin / HoR | Przypisany DL/TAC | Recruiter/Sourcer na Job | Właściciel relacji | Viewer/User |
|---|---:|---:|---:|---:|---:|
| Bezpieczny profil klienta | tak | tak | tak, w swoim kontekście | tak | tylko jawny grant |
| Dane prawne | tak | wg polityki | nie | nie | nie |
| Finanse klienta | tak | DL wg polityki | nie | nie | nie |
| Lista kontaktów | tak | tak | ograniczona | swoje/klienta wg polityki | nie |
| Prywatne notatki relacyjne | tak | wg polityki | nie | swoje | nie |
| Edycja kontaktu | tak | tak | nie | dozwolone pola swojego | nie |
| Zmiana ownera relacji | tak | wg polityki | nie | nie | nie |
| Wiedza operacyjna | tak | tak | read na przypisanym Job | read wg polityki | nie |
| Tworzenie Demand | tak | tak | wg jawnego procesu | nie | nie |
| Promote Demand → Job | tak | tak | jeśli przypisany i gotowe | nie | nie |
| Publish Job | tak | tak | właściciel Job | nie | nie |
| Merge/archive klienta | tak | nie | nie | nie | nie |
| Pliki prawne/framework | tak | wg polityki | nie | nie | nie |

Każde „wg polityki” ma zostać skonfigurowane w jednym resolverze, a nie przez lokalne warunki w routerach.

---

## 10. Inwarianty, których system ma zawsze pilnować

1. Każdy biznesowy klient używany w nowych procesach jest kanoniczny, widoczny i nie jest rekordem systemowym.
2. Kontakt wybrany jako hiring manager należy do tego samego klienta co demand/job.
3. Job, Contract, ClientOrder i Framework połączone w jednym package mają ten sam <code>client_id</code>.
4. Zwykły PATCH nie przenosi encji pomiędzy klientami.
5. Jeden Demand tworzy najwyżej jeden Job w pierwszej wersji.
6. Niekompletny Job nie przyjmuje kandydatów i nie jest publikowany.
7. Retry nie tworzy drugiego kontraktu/orderu/envelope/powiadomienia.
8. ClientOrder jest PO dla kontraktu, a nie intake briefem.
9. Standardowy delete klienta jest archiwizacją, nie fizycznym kasowaniem.
10. Pieniądze zachowują Decimal i walutę.
11. Agregaty nie zależą od paginacji.
12. Plik jest dostępny tylko przez autoryzowany download.
13. Zapis nowego pliku i zmiana referencji nie mogą pozostawić częściowego stanu.
14. Użytkownik bez prawa nie dostaje chronionego pola w API.
15. Każda krytyczna zmiana stanu ma actor, timestamp, reason i request/idempotency id.

---

## 11. Plan implementacji — maksymalnie 7 PR-ów

## PR 1/7 — Containment RBAC i bezpieczne projekcje

### Cel

Natychmiast zamknąć najbardziej ryzykowne ścieżki zapisu i odczytu bez zmiany całego modelu domenowego.

### Zakres backend

1. Dodać <code>ClientAccess</code> i dependency pobierającą klienta wraz z decyzją dostępu.
2. Zastąpić sam <code>CurrentUser</code> w:
   - <code>backend/app/api/contacts.py</code>;
   - <code>backend/app/api/client_knowledge.py</code>;
   - <code>backend/app/api/client_materials.py</code>;
   - <code>backend/app/api/client_framework_contracts.py</code>;
   - odpowiednich odczytach w <code>clients.py</code>, <code>my_clients.py</code> i <code>my_relationships.py</code>.
3. Wykorzystać istniejący <code>financial_access.py</code>, nie duplikować zasad.
4. Zastąpić bezpośrednie porównania roli przez multi-role helper.
5. Ograniczyć reassign ownera i delete kontaktu.
6. Rozdzielić safe/legal/financial/relationship response schemas.
7. Dodać audit eventy dla contact/knowledge/owner/file actions.
8. Ustalić privacy klasyfikację pól <code>relationship_notes</code>.

### Zakres DB

Jeśli istniejący audit log nie wystarcza:

- dodać tabelę <code>client_audit_events</code> albo rozszerzyć istniejącą;
- nie tworzyć równoległego systemu audytu, jeśli repo ma już wspólny mechanizm;
- każdą nową tabelę/kolumnę odtworzyć idempotentnie w <code>backend/entrypoint.sh</code>.

### Testy

- tabelaryczna macierz pięciu profili użytkownika;
- testy read/write/delete/reassign;
- test braku pól finansowych/prawnych w bezpiecznej projekcji;
- test użytkownika z wieloma rolami;
- test 404 vs 403 zgodny z przyjętą polityką ujawniania istnienia rekordu;
- test audit event.

### Kryteria akceptacji

- P0 z sekcji 7.1 są zamknięte;
- istniejące autoryzowane flow admin/DL nadal działa;
- nie ma tylko frontendowego zabezpieczenia;
- odpowiedzi 403 mają stabilny kod błędu;
- wymagany job CI zawiera nowy suite.

### Rollout

- deploy bez flagi dla naprawy zapisu; bezpieczeństwo ma działać od razu;
- przed merge porównać listę routów z router registry, aby żadna mutacja nie została pominięta;
- monitorować 403 per route/role, bez logowania treści prywatnych pól.

### Rollback

- rollback kodu jest możliwy, ale migracja auditowa ma być backward compatible;
- nie cofać zapisanych audit events;
- jeśli pojawi się brak legalnego dostępu, poprawić policy mapping, nie przywracać globalnego <code>CurrentUser</code>.

### Poza PR

- bez ClientDemand;
- bez redesignu frontend;
- bez merge duplikatów.

---

## PR 2/7 — Kanoniczny klient i integralność same-client

### Cel

Ujednolicić tożsamość klienta i uniemożliwić tworzenie relacji pomiędzy encjami różnych klientów.

### Zakres backend

1. Dodać wspólny <code>ClientQueryService</code>.
2. Wszystkie listy/lookupy:
   - wykluczają hidden/system;
   - używają display label;
   - mają deterministyczne sortowanie;
   - wspierają server-side pagination/search/sort.
3. Create/update klienta:
   - trim + NFC;
   - normalizacja nazwy;
   - walidacja danych prawnych;
   - candidates-for-duplicate.
4. Dodać admin dry-run oraz command merge.
5. Zastąpić hard delete przez archive.
6. Dodać <code>ClientRelationValidator</code>.
7. Zablokować zwykłą zmianę klienta dla Job z zależnościami.
8. Sprawdzić same-client w create/update contract/order/framework/hiring manager.

### Zakres DB

1. Preflight wszystkich niespójności.
2. Dodać:
   - <code>clients.normalized_name</code>;
   - <code>clients.is_system</code>;
   - <code>clients.merged_into_client_id</code>;
   - <code>clients.archived_at</code>;
   - <code>clients.archived_by</code>.
3. Oznaczyć technicznego klienta importowego jako systemowy.
4. Dodać unikalne pary <code>(id, client_id)</code>.
5. Dodać kompozytowe FK opisane w sekcji 7.3.
6. Stosować etapowe constraints po cleanupie.
7. Uzupełnić <code>backend/entrypoint.sh</code>.

### Ważna zasada migracji

Nie łączyć fuzzy duplikatów automatycznie. Najpierw wygenerować raport:

- exact NIP/external id;
- exact normalized name;
- potencjalne podobne nazwy;
- liczba jobs, contacts, contracts, orders, files, knowledge per rekord;
- konflikty danych prawnych.

Claude ma przedstawić dry-run do zatwierdzenia. Sam PR może dostarczyć mechanizm i oznaczyć wyłącznie techniczny rekord; masowy merge danych produkcyjnych jest osobnym kontrolowanym krokiem operacyjnym.

### Testy

- spójność wszystkich list i lookupów;
- hidden/system nie pojawia się biznesowo;
- aktualnie wybrany archived klient jest widoczny tylko jako historyczny;
- normalizacja Unicode i whitespace;
- exact duplicate candidates;
- transactional merge i rollback;
- kompozytowe FK;
- próba cross-client w każdym commandzie;
- blokada transferu Job z zależnościami.

### Kryteria akceptacji

- jedna funkcja definiuje nazwę klienta;
- sortowanie hit ratio jest naprawdę server-side;
- żaden nowy cross-client record nie powstaje;
- archive i merge zostawiają audit;
- constraints są zwalidowane;
- deploy nie kończy się zielony przy brakującej kolumnie.

### Rollout

- najpierw <code>CLIENT_CANONICAL_VIEW_ENABLED</code> na adminach;
- porównać liczebności starej i nowej listy;
- dopiero potem użyć nowego query we wszystkich lookupach;
- constraints po oczyszczeniu danych, nie przed.

### Rollback

- nowe kolumny nullable/backward compatible;
- przełączenie flagi przywraca stary odczyt;
- merged rekordów nie „odmergowywać” automatem — użyć audit/dry-run i jawnej procedury.

---

## PR 3/7 — ClientDemand: intake, doprecyzowanie i lineage

### Cel

Dodać właściwą encję zapotrzebowania, nie naruszając roli ClientOrder.

### Zakres backend

1. Model i schema <code>ClientDemand</code>.
2. Enum statusów i źródeł.
3. CRUD z optimistic version.
4. <code>DemandReadinessService</code>.
5. Endpointy readiness/mark-ready/cancel.
6. Idempotentny create przez <code>Idempotency-Key</code> i <code>external_key</code>.
7. Audit każdej zmiany statusu i kluczowych pól.
8. Uprawnienia przez <code>ClientAccess</code>.
9. Read-only listę z paginacją, filtrem klient/status/owner/source/deadline.
10. Bez integracji Traffit w pierwszym PR, ale z przygotowanym stabilnym <code>source/external_key</code>.

### Zakres DB

- tabela <code>client_demands</code>;
- status/source jako istniejący repo pattern: enum DB albo constrained string;
- indeksy:
  - client/status;
  - owner/status;
  - response_deadline;
  - updated_at;
- częściowy unique <code>(source, external_key)</code> where external_key is not null;
- version integer;
- audit/transition linkage;
- idempotentny mirror w <code>backend/entrypoint.sh</code>.

### Minimalny frontend w PR

Może ograniczyć się do strony pod feature flagą dostępnej admin/DL:

- lista;
- create/edit;
- readiness blockers;
- cancel.

Jeżeli PR staje się zbyt duży, frontend można ograniczyć do wewnętrznego preview, a pełny UX zostawić PR 6. API i testy muszą być kompletne.

### Testy

- przejścia statusów;
- walidacja ready;
- same-client hiring manager;
- optimistic locking;
- idempotentny create;
- duplicate external key;
- RBAC;
- audit;
- pagination/filter/sort;
- cancelled nie może być promoted.

### Kryteria akceptacji

- brief może być zapisany jako niekompletny intake;
- status ready nie jest możliwy z blockerami;
- retry nie dubluje rekordu;
- ClientOrder pozostaje nietknięty semantycznie;
- lineage i actor są dostępne w API admina;
- feature flag <code>CLIENT_DEMAND_ENABLED</code> domyślnie false na produkcji do pełnego UI.

### Rollout

- deploy schema + API z flagą off;
- smoke test admin na staging/preview;
- włączyć dla małej grupy;
- przez pierwszy okres zbierać demand równolegle do starego ręcznego create Job;
- nie robić automatycznego backfillu starych Jobs jako sztucznych demandów.

### Rollback

- wyłączyć flagę;
- zachować zebrane demandy;
- migracja addytywna, bez usuwania tabel istniejących.

---

## PR 4/7 — Promote Demand, Job readiness i spójny lifecycle package

### Cel

Połączyć ClientDemand z Job oraz wymusić gotowość przed operacjami biznesowymi. Ujednolicić tworzenie/aktywację Contract + ClientOrder.

### Zakres backend

1. Dodać <code>client_demand_id</code> do Job lub bezpieczną tabelę lineage.
2. Zaimplementować idempotentne <code>promote</code>:
   - lock demand;
   - sprawdzenie ready;
   - utworzenie Job w tej samej transakcji;
   - zapis snapshotu briefu;
   - <code>converted_job_id</code>;
   - zwrot istniejącego Job przy retry.
3. Dodać <code>JobReadinessService</code>.
4. Użyć go w:
   - publish;
   - add candidate;
   - pipeline move;
   - matching/marketplace/similar notifications;
   - odpowiednich efektach AI.
5. Przenieść efekty uboczne create Job za przejście gotowości albo jawny preview.
6. Stworzyć jeden <code>ContractPackageService</code>.
7. Wszystkie ścieżki tworzą draft package.
8. Jedna komenda aktywacji waliduje i zmienia oba stany.
9. Dodać idempotency/unique dla hired hook.
10. Naprawić numerację Job, primary team i alert worker concurrency.
11. Usunąć podwójne źródło daty końca lub ustalić jedno kanoniczne z migracją.

### Zakres DB

- unique lineage Demand → Job;
- idempotency key table albo zgodny istniejący mechanizm;
- unique source hired stage;
- counter/sequence dla Job reference;
- status transition/audit fields;
- poprawiony notification dedup index;
- version fields, jeśli ich brakuje;
- mirror w <code>backend/entrypoint.sh</code>.

### Testy

- promote success;
- promote z blockerami;
- 20 równoległych promote/retry;
- wszystkie Job gates;
- preview bez powiadomień;
- publish po usunięciu blockera;
- 20 równoległych hired hooks;
- atomic activation package;
- cancelled order vs active contract;
- alert worker concurrency;
- unique Job references;
- primary DL/TAC concurrency.

### Kryteria akceptacji

- produkcyjnie nie da się dodać kandydata do niegotowego Job;
- UI i backend używają tego samego readiness result;
- promote tworzy dokładnie jeden Job;
- hired tworzy dokładnie jeden draft package;
- aktywacja nie omija wspólnego walidatora;
- żaden skutek zewnętrzny nie powstaje przed commitem i readiness;
- <code>JOB_READINESS_ENFORCED</code> ma tryb shadow i enforce.

### Rollout

1. Shadow mode: obliczaj blockery, ale nie blokuj; zapisuj metryki bez danych wrażliwych.
2. Raport istniejących aktywnych Jobs z blockerami.
3. Napraw dane i właścicieli.
4. Enforce dla nowych Jobs.
5. Enforce dla edytowanych Jobs.
6. Enforce dla wszystkich operacji.

### Rollback

- flaga wraca z enforce do shadow;
- nie cofać lineage ani idempotency records;
- lifecycle package pozostaje draft-first; nie przywracać ścieżki tworzącej active bez walidacji.

---

## PR 5/7 — Bezpieczne pliki i odporność na retry

### Cel

Ujednolicić upload/download/replace/delete dla materiałów, wymaganych dokumentów, frameworków i orderów.

### Zakres backend

1. Wspólny <code>SafeUploadService</code>.
2. Streaming size limit.
3. Magic-byte detection i allowlista.
4. Unikalne temp object keys.
5. Finalizacja po utworzeniu realnej encji.
6. Cleanup temp przy błędzie.
7. Old object delete dopiero po commit.
8. Optimistic version dla replace/delete.
9. Autoryzowany download i bezpieczne nagłówki.
10. Jednolity audit metadata.
11. Background cleanup osieroconych tempów starszych niż określony TTL.

### Zakres DB

W istniejących tabelach plików, jeśli brakuje:

- checksum;
- size_bytes;
- detected_content_type;
- storage_key;
- version;
- uploaded_by;
- created_at/updated_at.

Nie przechowywać ścieżek zależnych od nieistniejącego <code>order_id=0</code>.

### Testy

- magic bytes mismatch;
- MIME spoof;
- limit + 1 byte;
- disconnect podczas uploadu;
- rollback DB;
- awaria storage podczas finalizacji;
- dwa równoległe replace;
- download RBAC;
- traversal/path injection;
- cleanup TTL nie usuwa aktywnego temp;
- stare API pozostaje kompatybilne w okresie migracji.

### Kryteria akceptacji

- brak nowych osieroconych finalnych plików w fault-injection tests;
- rekord DB nigdy nie wskazuje usuniętego starego pliku po rollbacku;
- plik klienta nie jest publiczny;
- logi nie zawierają treści dokumentu ani tokenu download;
- <code>CLIENT_FILE_PIPELINE_V2</code> można włączać per typ dokumentu.

### Rollout

- zacząć od one-pagera;
- potem required documents;
- potem framework;
- na końcu ClientOrder;
- dashboard liczy temp/orphan/finalization failure;
- jednorazowy read-only inventory starych obiektów przed cleanupem.

### Rollback

- read path obsługuje stare i nowe storage keys;
- wyłączenie flagi blokuje nowe write V2, ale nie odbiera dostępu do poprawnie zapisanych plików;
- cleanup nigdy nie działa bez dry-run na pierwszym uruchomieniu.

---

## PR 6/7 — Spójny frontend klient → demand → gotowy Job

### Cel

Zbudować jeden czytelny przepływ użytkownika, oparty na backendowych policy/readiness i istniejącym design systemie.

### Zakres

#### Lista klientów

- kanoniczne nazwy;
- brak hidden/system;
- server-side search/sort/pagination;
- wyszukiwanie zgodne z placeholderem;
- lokalizowane statusy;
- hit ratio sortowane globalnie;
- create client z legal name/NIP/REGON i duplicate suggestions.

#### Profil klienta

Zakładki:

- Przegląd;
- Zapotrzebowania;
- Stanowiska;
- Zespół;
- Kontakty;
- Relacje;
- Wiedza;
- Materiały;
- Umowy i zamówienia;
- Analityka.

Nie każda rola widzi każdą zakładkę. Lista powstaje z permissions zwróconych przez backend, ale backend nadal zabezpiecza dane.

#### Demand

- lista z filtrami status/owner/deadline;
- formularz krokowy albo sekcyjny;
- autosave draft z version conflict handling;
- readiness panel;
- akcja „Oznacz jako gotowe”;
- akcja „Utwórz stanowisko”;
- czytelny lineage do powstałego Job;
- cancel z powodem.

#### Job

- Job readiness panel;
- blocker linkuje do konkretnego pola;
- brak aktywnych akcji pipeline przy blockerach;
- niezależne stany lookupów;
- wyświetlenie aktualnie wybranego archived/hidden klienta jako historycznego;
- pełny error/retry.

#### Portale osobiste

- Moich klientów: role-aware copy, filtry, paginacja;
- Moje relacje: poprawna instrukcja, filtry, prywatność notatek;
- deep links do zakładek działają;
- query tab synchronizowane z routerem.

#### Design i a11y

- przeczytać <code>frontend/docs/ds/ADDING-BLOCKS.md</code>;
- używać komponentów DS;
- tylko semantic tokens;
- pełna semantyka dialogów i tabów;
- keyboard navigation;
- responsywność;
- polski słownik statusów;
- zero wywołań <code>npx shadcn add</code>.

### Testy

- Vitest/RTL dla permissions i readiness;
- lookup loading/empty/error/forbidden;
- tab deep link/back-forward;
- conflict 409;
- duplicate client suggestion;
- Playwright:
  1. utwórz intake;
  2. zobacz blockery;
  3. uzupełnij;
  4. mark ready;
  5. promote;
  6. otwórz Job;
  7. publish;
- a11y smoke dla dialogu i tabów;
- screenshoty desktop/mobile/dark.

### Kryteria akceptacji

- użytkownik rozumie, czy zapisuje brief, stanowisko, kontrakt czy PO;
- żaden błąd lookupu nie wygląda jak pusta poprawna lista;
- URL odtwarza dokładną zakładkę;
- readiness z UI jest zgodne z odpowiedzią backendu;
- role nie widzą pustych zakładek bez prawa;
- wszystkie kolory pochodzą z tokenów;
- produkcyjny Chrome flow przechodzi po deployu.

### Rollout

- nowy nav i Demand pod <code>CLIENT_DEMAND_ENABLED</code>;
- grupa pilotażowa admin + wybrany DL;
- obserwować completion time, blocker distribution i abandon rate;
- po stabilizacji włączyć wszystkim uprawnionym;
- stary create Job może pozostać chwilowo jako „Utwórz szkic bez briefu”, ale także podlega readiness.

### Rollback

- wyłączyć nowy nav/flow;
- linki do utworzonych Job i Demand pozostają dostępne adminowi;
- API i dane nie są usuwane.

---

## PR 7/7 — Finanse V2, wydajność, obserwowalność i obowiązkowy CI gate

### Cel

Naprawić wskaźniki klienta, usunąć problemy skalowania i ustanowić mierzalny kontrakt jakości modułu.

### Zakres finansowy

1. Spisać definicje metryk jako ADR/docstring/API docs.
2. SQL aggregates niezależne od listy.
3. Money Decimal + currency.
4. Brak cross-currency sum bez FX.
5. Efektywne stawki per okres.
6. Poprawić expiring soon.
7. Zastąpić <code>or</code> jawnym <code>is not None</code>.
8. Wersjonowany endpoint <code>financials-v2</code> albo kompatybilna migracja kontraktu.

### Zakres wydajności

1. Paginacja contacts/knowledge/my-clients/my-relationships.
2. Usunięcie N+1 order/framework.
3. Indeksy na rzeczywistych filtrach.
4. Query-count regression tests.
5. Limit page size.
6. Cache tylko tam, gdzie invalidacja jest jednoznaczna; nie cache’ować prywatnych projekcji między użytkownikami.

### Zakres obserwowalności

Metryki bez PII:

- liczba demandów per status;
- średni czas intake → ready;
- średni czas ready → converted;
- rozkład readiness blockers;
- liczba blocked publish/add-candidate;
- liczba idempotent retries;
- liczba cross-client attempts;
- liczba canonical/hidden/system klientów;
- liczba merge candidates;
- liczba lifecycle inconsistencies;
- upload failures/temp orphan count;
- 403 per endpoint/rola;
- query latency p50/p95/p99;
- finance aggregate mismatch podczas shadow comparison.

Dodać modułowy admin snapshot bez treści kontaktów, notatek i dokumentów.

### Zakres CI

1. Dodać jawny required job <code>client-demand-module</code>.
2. Włączyć testy z PR 1–7.
3. Dodać test migracji przez <code>alembic upgrade heads</code>.
4. Sprawdzać mirror <code>backend/entrypoint.sh</code>.
5. Frontend lint/type-check/test/build bez równoległego dev.
6. Playwright smoke jako osobny stabilny gate lub post-deploy verification zgodnie z repo.

### Kryteria akceptacji

- metryki finansowe przechodzą golden fixtures;
- API list nie wykonują zapytania per rekord;
- p95 mieści się w ustalonym budżecie na danych zbliżonych do produkcji;
- snapshot pokazuje wszystkie inwarianty bez PII;
- wymagany CI nie pozwala zmergować regresji modułu;
- po merge produkcyjny <code>/api/health.version</code> zaczyna się od oczekiwanego short SHA;
- wszystkie smoke curle używają <code>User-Agent: dynaminds-smoke-test/1.0</code>.

### Rollout

- finance V2 działa w shadow i porównuje stare/nowe wyniki per klient/waluta;
- różnice powyżej progu trafiają do raportu, nie do automatycznej korekty danych;
- UI przełącza się dopiero po akceptacji golden set;
- optymalizacje mierzyć przed/po.

### Rollback

- zachować stary endpoint do krótkiego okresu kompatybilności;
- flaga <code>CLIENT_FINANCE_V2</code>;
- nowe indeksy i snapshoty addytywne;
- nie usuwać historycznych pól przed potwierdzeniem braku konsumentów.

---

## 12. Zależności między PR-ami

~~~mermaid
flowchart LR
    P1["PR1 RBAC"] --> P2["PR2 Identity + integrity"]
    P2 --> P3["PR3 ClientDemand"]
    P3 --> P4["PR4 Promote + readiness + lifecycle"]
    P1 --> P5["PR5 Safe files"]
    P2 --> P6["PR6 Frontend"]
    P3 --> P6
    P4 --> P6
    P5 --> P6
    P6 --> P7["PR7 Finance + perf + obs + CI"]
    P4 --> P7
~~~

Możliwe równoległe wykonanie:

- PR 5 może powstawać równolegle do PR 3/4 po ustabilizowaniu PR 1;
- część golden fixtures finansowych z PR 7 można przygotować wcześniej, ale nie należy mieszać ich w PR-y bezpieczeństwa.

Nie wolno:

- zaczynać od redesignu bez RBAC;
- włączać enforce readiness bez shadow reportu;
- dodawać kompozytowych constraints przed preflight i cleanup;
- automatycznie scalać fuzzy duplikatów;
- przenazywać ClientOrder na Demand;
- budować jednego PR zmieniającego cały moduł.

---

## 13. Preflight danych przed migracjami

Poniższe zapytania są wzorami read-only. Claude ma dopasować dokładne nazwy kolumn do aktualnych modeli/migracji i uruchomić je wyłącznie przez zatwierdzoną powierzchnię administracyjną.

### 13.1. Duplikaty klientów

~~~sql
SELECT
  lower(regexp_replace(trim(coalesce(display_name, legal_name, name)), '\s+', ' ', 'g')) AS normalized_name,
  count(*) AS clients_count,
  array_agg(id ORDER BY id) AS client_ids
FROM clients
GROUP BY 1
HAVING count(*) > 1
ORDER BY clients_count DESC, normalized_name;
~~~

### 13.2. Techniczne i ukryte rekordy używane biznesowo

~~~sql
SELECT
  c.id,
  c.name,
  c.hidden,
  count(DISTINCT j.id) AS jobs,
  count(DISTINCT co.id) AS orders,
  count(DISTINCT ct.id) AS contracts
FROM clients c
LEFT JOIN jobs j ON j.client_id = c.id
LEFT JOIN client_orders co ON co.client_id = c.id
LEFT JOIN contracts ct ON ct.client_id = c.id
WHERE c.hidden = true OR c.name LIKE '\_\_%'
GROUP BY c.id, c.name, c.hidden;
~~~

### 13.3. Order kontra Contract

~~~sql
SELECT
  o.id AS order_id,
  o.client_id AS order_client_id,
  c.id AS contract_id,
  c.client_id AS contract_client_id
FROM client_orders o
JOIN contracts c ON c.id = o.contract_id
WHERE o.client_id <> c.client_id;
~~~

### 13.4. Order kontra Job

~~~sql
SELECT
  o.id AS order_id,
  o.client_id AS order_client_id,
  j.id AS job_id,
  j.client_id AS job_client_id
FROM client_orders o
JOIN jobs j ON j.id = o.job_id
WHERE o.client_id <> j.client_id;
~~~

### 13.5. Job kontra hiring manager

~~~sql
SELECT
  j.id AS job_id,
  j.client_id AS job_client_id,
  c.id AS contact_id,
  c.client_id AS contact_client_id
FROM jobs j
JOIN contacts c ON c.id = j.hiring_manager_contact_id
WHERE j.client_id <> c.client_id;
~~~

### 13.6. Sprzeczne statusy Contract/Order

~~~sql
SELECT
  c.id AS contract_id,
  c.status AS contract_status,
  o.id AS order_id,
  o.status AS order_status
FROM contracts c
LEFT JOIN client_orders o ON o.contract_id = c.id
WHERE c.status = 'active'
  AND (o.id IS NULL OR o.status IN ('cancelled', 'expired'));
~~~

### 13.7. Jobs używane mimo braku gotowości

Należy policzyć co najmniej:

- draft z kandydatami;
- active/published bez ownera;
- active/published bez client;
- job bez must-have/description/work mode;
- job z hiring managerem innego klienta;
- job z kontraktem/orderem i zmienionym client_id.

### 13.8. Duplikaty package po hired

Policzyć:

- wiele kontraktów dla tego samego hired stage/candidate/job;
- wiele orderów dla tego samego contract;
- duplikaty notification type + entity + date;
- duplikaty primary DL/head TAC.

### 13.9. Pliki

Inventory:

- rekord bez storage object;
- storage object bez rekordu;
- key z <code>order_id=0</code>;
- duplicate storage key;
- brak checksum/type/size;
- temp starszy niż TTL.

Pierwsze uruchomienie cleanup zawsze jako dry-run.

---

## 14. Strategia migracji i kompatybilności

Każdy PR ze zmianą schematu musi:

1. sprawdzić aktualne Alembic heads;
2. bazować na właściwych heads albo dodać merge migration, jeśli to konieczne;
3. używać <code>alembic upgrade heads</code>;
4. mieć downgrade bez destrukcji danych, o ile jest bezpieczny;
5. odzwierciedlić nowe kolumny/tabele idempotentnie w <code>backend/entrypoint.sh</code>;
6. przejść test na pustej bazie i bazie z danymi fixture;
7. nie dodawać od razu NOT NULL bez backfillu;
8. nie walidować constraint przed raportem niespójności;
9. pozostawić stary odczyt kompatybilny na czas rollout flagi;
10. opisać kolejność deploy → backfill → validate → enable.

Rekomendowany schemat expand/contract:

- expand schema;
- dual read lub backward-compatible read;
- backfill;
- shadow metrics;
- enable nowy write;
- validate constraints;
- enable nowy read/UI;
- po pełnej obserwacji usunąć stare ścieżki w osobnym PR.

---

## 15. Test plan

### 15.1. Backend — testy jednostkowe

- access policy dla każdej operacji;
- normalizacja nazw;
- duplicate classification;
- demand readiness;
- job readiness;
- money arithmetic;
- transition validators;
- file type detection;
- idempotency result mapping.

### 15.2. Backend — testy integracyjne

- endpoint + DB + RBAC;
- constraints same-client;
- transakcja promote;
- concurrency hired/promote/reference/primary;
- contract package activation;
- rollback przy awarii storage/effect;
- query pagination/sort/filter;
- finance aggregate na >100 kontraktach;
- audit event completeness.

### 15.3. Frontend

- permissions projection;
- query tab;
- lookup states;
- readiness blocker → field;
- optimistic conflict;
- Money/status format;
- form validation zgodna z backendem;
- modal keyboard/focus.

### 15.4. E2E

Happy path:

1. DL otwiera kanonicznego klienta.
2. Dodaje kontakt hiring managera.
3. Tworzy niekompletny Demand.
4. Widzi blockery.
5. Uzupełnia wymagania, warunki i ownera.
6. Oznacza Demand jako ready.
7. Promuje do Job.
8. Próbuje publikacji.
9. Publikuje po braku blockerów.
10. Dodaje kandydata.
11. Przenosi do hired.
12. System tworzy dokładnie jeden draft Contract + ClientOrder.

Negative paths:

- viewer próbuje edycji kontaktu;
- recruiter otwiera finanse;
- hiring manager innego klienta;
- duplikat create/promote przy retry;
- cross-client order;
- cancelled demand;
- MIME spoof;
- równoległy replace;
- ukryty klient w lookup;
- lookup 500/403;
- active contract bez aktywnego orderu.

### 15.5. Produkcyjna weryfikacja po każdym PR

- CI green;
- squash merge;
- deploy workflow zakończony;
- <code>/api/health</code> z wymaganym User-Agent;
- version zaczyna się od siedmioznakowego SHA merge;
- backend change: curl i parsowany JSON;
- frontend change: realna interakcja w Chrome i screenshot;
- brak nowych Sentry errors;
- metryki modułu bez skoku 403/5xx/latency.

---

## 16. Obserwowalność i alerty

### 16.1. Metryki

Nazwy przykładowe:

- <code>nexus_client_access_denied_total{route,operation,role_group}</code>;
- <code>nexus_client_demand_total{status,source}</code>;
- <code>nexus_client_demand_transition_total{from,to}</code>;
- <code>nexus_client_demand_age_seconds{status}</code>;
- <code>nexus_job_readiness_blocker_total{code}</code>;
- <code>nexus_job_action_blocked_total{action,code}</code>;
- <code>nexus_client_cross_relation_rejected_total{relation}</code>;
- <code>nexus_idempotency_replay_total{command}</code>;
- <code>nexus_client_file_operation_total{type,result}</code>;
- <code>nexus_client_file_temp_orphans</code>;
- <code>nexus_client_query_seconds{endpoint}</code>;
- <code>nexus_client_finance_shadow_difference{metric,currency}</code>.

Nie dodawać do label:

- client id przy dużej kardynalności;
- nazwy klienta;
- emaila;
- treści notatki;
- nazwy dokumentu zawierającej PII.

### 16.2. Alerty

- wzrost 5xx na client/job/demand;
- ponadprogowy 403 po rollout policy;
- cross-client inconsistency > 0;
- active contract with invalid order > 0;
- orphan/temp files rosną;
- p95 list przekracza budżet;
- readiness calculation failure;
- finance shadow mismatch powyżej ustalonego progu;
- worker idempotency conflict powyżej normalnego poziomu.

### 16.3. Admin snapshot modułu

Snapshot powinien zwracać tylko agregaty:

- klientów visible/hidden/system/merged;
- exact duplicate groups;
- cross-client inconsistency counts;
- demand per status;
- job blocker counts;
- lifecycle inconsistency counts;
- orphan file counts;
- ostatni poprawny worker watermark;
- p95 API;
- wersję readiness rules.

---

## 17. Definition of Done całego modułu

Moduł 1 jest ukończony dopiero, gdy:

- P0 RBAC jest zamknięte;
- listy używają jednej kanonicznej tożsamości klienta;
- techniczne i hidden rekordy nie są wybieralne biznesowo;
- istnieje ClientDemand z pełnym lineage;
- Demand → Job jest idempotentne;
- Job readiness blokuje publikację/pipeline/efekty;
- same-client jest wymuszane przez aplikację i bazę;
- Contract + ClientOrder mają jeden lifecycle command;
- retry/concurrency nie tworzy duplikatów;
- pliki przechodzą bezpieczny, atomowy pipeline;
- finanse są per waluta, Decimal i niezależne od paginacji;
- portal klienta, Moich klientów i Moje relacje mają spójny UX;
- deep linki działają;
- lookup failure jest jawny;
- a11y i token-first są spełnione;
- wymagany CI gate modułu jest zielony;
- merge SHA jest wdrożone;
- produkcyjne API i Chrome flow są zweryfikowane;
- snapshot nie pokazuje nowych niespójności;
- dokumentacja opisuje nowe statusy, role, metryki i runbook rollbacku.

---

## 18. Instrukcja startowa dla Claude Code

Poniższy prompt można przekazać Claude razem z tym dokumentem.

> Pracujesz w repozytorium NEXUS. Przeczytaj najpierw AGENTS.md oraz cały plik:
> /Users/arturtwardowski/NEXUS/docs/client-demand-module-audit-and-claude-implementation-plan-2026-07-16.md
>
> Realizuj plan sekwencyjnie, zaczynając wyłącznie od PR 1/7. Nie implementuj kolejnych PR-ów w tym samym branchu.
>
> Zasady:
>
> 1. Pobierz aktualny origin/main i utwórz czysty branch z prefiksem fix/ albo feat/. Obecny lokalny rescue branch zawiera niezwiązane WIP — nie resetuj, nie stashuj, nie commituj i nie mieszaj tych zmian.
> 2. Przed kodowaniem potwierdź, czy problem nadal istnieje na aktualnym origin/main.
> 3. Zachowaj zakres danego PR. Nie rób sąsiednich refactorów.
> 4. Nigdy nie używaj lokalnego Dockera.
> 5. Każdą regułę bezpieczeństwa egzekwuj w backendzie.
> 6. Dla zmian DB sprawdź wszystkie Alembic heads, użyj upgrade heads i uzupełnij idempotentny fallback w backend/entrypoint.sh.
> 7. Nie scalaj fuzzy duplikatów automatycznie i nie wykonuj destrukcyjnego cleanupu produkcji.
> 8. Nowe flow włączaj feature flagą; poprawki P0 RBAC mają być fail-closed.
> 9. Dodaj testy wymienione dla PR-u oraz włącz je do wymaganego CI.
> 10. Uruchom najmniejszy sensowny zestaw host-native testów, lint i type-check. Pełne buildy/integrację pozostaw CI zgodnie z AGENTS.md.
> 11. Przejrzyj dokładny diff. Commit ma być conventional i zawierać tylko dany PR.
> 12. Push, otwórz PR, czekaj na CI, napraw konkretne błędy, zmerge’uj po green.
> 13. Poczekaj na deploy i potwierdź exact SHA przez /api/health z User-Agent dynaminds-smoke-test/1.0.
> 14. Dla UI wykonaj realny Chrome flow i screenshot; dla backendu curl + parsowany JSON.
> 15. W handoffie podaj branch, commit, PR, testy, CI, merge SHA, deployed SHA, smoke result, flag state, migrację, rollout i rollback.
>
> Dla PR 1 zacznij od inventory wszystkich endpointów klienta/kontaktów/wiedzy/materiałów/frameworków/orderów. Zbuduj macierz obecna dependency → wymagana permission. Następnie wdroż ClientAccess, bezpieczne projekcje, multi-role helper, audit i tabelaryczne testy. Nie dodawaj jeszcze ClientDemand ani redesignu.
>
> Jeśli dokładna decyzja produktowa o roli DL/TAC jest nieznana, nie rozszerzaj dostępu. Zaimplementuj fail-closed policy, wskaż jedną krótką decyzję wymagającą zatwierdzenia i kontynuuj wszystkie elementy niezależne od niej.

---

## 19. Decyzje produktowe do potwierdzenia przed PR 3/4

Implementacja może zacząć się od PR 1 i PR 2 bez czekania. Przed finalizacją ClientDemand należy potwierdzić:

1. Czy jeden Demand zawsze tworzy jeden Job, czy headcount ma kiedyś tworzyć kilka Jobs?  
   **Rekomendacja V1:** jeden Demand → jeden Job z headcount.

2. Kto może oznaczyć Demand jako ready?  
   **Rekomendacja:** admin/HoR, przypisany DL lub TAC; recruiter tylko jeśli jest ownerem i polityka to jawnie dopuszcza.

3. Czy stawka jest obowiązkowa przed ready?  
   **Rekomendacja:** tak dla modeli wymagających budżetu; wyjątek jako jawny waiver z aktorem i powodem, nie puste pole.

4. Czy prywatne relationship notes są widoczne dla DL klienta czy tylko ownera relacji i admina?  
   **Rekomendacja:** domyślnie owner + admin; współdzielenie jawnie per notatka lub kategoria.

5. Co oznacza LTV: zrealizowana marża czy zakontraktowana marża?  
   **Rekomendacja:** prezentować obie jako osobne, jednoznacznie nazwane metryki.

6. Czy aktywny kontrakt zawsze wymaga aktywnego ClientOrder?  
   **Rekomendacja:** tak, chyba że istnieje jawny typ „bez PO”, zatwierdzony i audytowany.

7. Jaki jest okres retencji dokumentów po archiwizacji klienta?  
   **Rekomendacja:** zgodnie z polityką prawną/RODO; nie implementować hard purge bez tej decyzji.

---

## 20. Ostateczna rekomendacja

Modułu nie należy naprawiać przez dodanie kolejnej zakładki do istniejącego profilu albo przez przemianowanie ClientOrder. Problem jest głównie kontraktowy:

- kto może zobaczyć i zmienić dane;
- który rekord jest kanonicznym klientem;
- jak zapotrzebowanie przechodzi do gotowego stanowiska;
- jakie inwarianty łączą klienta, kontakt, Job, Contract i ClientOrder;
- kiedy wolno uruchomić efekty biznesowe;
- jak wynik jest mierzony i audytowany.

Najbezpieczniejsza kolejność to:

1. containment RBAC;
2. kanoniczna tożsamość i integralność;
3. osobny ClientDemand;
4. readiness i lifecycle;
5. bezpieczne pliki;
6. spójny frontend;
7. finanse, wydajność, obserwowalność i CI.

Ta kolejność minimalizuje ryzyko, pozwala wdrażać małymi PR-ami i daje Claude jednoznaczne kryteria ukończenia każdego etapu.
