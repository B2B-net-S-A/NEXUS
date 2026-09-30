# Wyszukiwanie kandydatów — audyt całej maszyny, symulacje i rekomendacje (30.09.2026)

- **Pytanie Artura:** jak powinno działać wyszukiwanie kandydatów (od profilu Championa, przez
  wyszukiwanie w bazie, po podobne rekrutacje i przepięcia), skąd biorą się dane i co poprawić.
  Osobno: pomysł **„umiejętności krytycznych”** w profilu Championa — bez nich kandydat nie
  wychodzi w wyszukiwaniu, a must have i nice to have tylko dodają punkty. Rekomendacje mają stać
  na symulacjach na prawdziwych danych.
- **Baza:** produkcja `a155550a2` (= `origin/main` 30.09 rano). W trakcie badania wdrożenia innych
  sesji dwa razy zrestartowały Qdranta — dotknięte biegi powtórzone.
- **Tryb:** wyłącznie odczyt. Skrypty w jednorazowym kontenerze z obrazem backendu, połączenia z bazą
  wymuszone na `default_transaction_read_only` (`ro_boot.py`). Kod reguł = kod produkcji (import
  z `/app`), więc symulacja liczy dokładnie tak jak ekrany. Skrypty obok:
  `docs/audits/2026-09-30/wyszukiwanie-kandydatow/`.
- **Uzupełnia (nie powtarza):** `docs/audits/2026-09-26/tworzenie-rekrutacji-a-wyszukiwanie.md`
  (bramka must v7/v8, formularz, miasta) i `docs/audits/2026-09-26/wyszukiwanie-reczne.md`
  (lista i „Szukaj ręcznie”). Tamte badania liczyły bramkę must na **liście umiejętności**; od 27.09
  produkcja (v8) liczy dowód także z CV i notatek — tu wszystko jest policzone na v8.

## Najważniejsze w 7 zdaniach

1. **Obecna bramka must (każde must obowiązkowe) ukrywa 41,5% osób, które zespół wysłał do klienta**
   (cała historia, 18 137 par) i w 40% rekrutacji chowa ponad połowę wysłanych.
2. **„Umiejętności krytyczne” działają — pod warunkiem, że są krótkie i dobrze wybrane.** Reguła
   „krytyczna = technologia, którą ≥90% wysłanych w podobnych rekrutacjach ma w profilu/CV” ukrywa
   1,9–2,6% wysłanych zamiast 41,5%; w symulacji listy rekrutera zwiększa trafienia w pierwszej
   dwudziestce o 64% względem dziś (22,4% → 36,8%). To odwraca werdykt H4 z 26.09 („krytyczne obalone”) —
   tamten pomiar liczył dowód z samej listy umiejętności i wybór z etykiet-śmieci.
3. **Dodatkowe punkty za must/nice nie poprawiają kolejności** (±1 pp), a większa waga umiejętności
   ją psuje. Pomaga co innego: warstwa umiejętności liczona z tego samego dowodu co bramka (CV,
   profil, notatki) zamiast z samej listy — MRR +4,7 pp, top 100 +4,6 pp (oba istotne). Kolejność
   i tak robi wektor (≈67% oceny).
4. **Reguła „które must bramkują” ma błędy**: nazwy ról i kategorii ze słownika („software developer”,
   „qa”, „it analysis”, „test engineering”) i frazy typu „dostępność asap / maksymalnie 1 miesiąc”
   bramkują; przykłady w nawiasie po zdaniu stają się wymogiem („Doświadczenie z integracją systemów
   (on-premise, hybrid, cloud)” → kandydat musi mieć „on-premise” albo „hybrid”).
5. **Po must największy „zjadacz” trafnych to budżet:** w rekrutacjach od marca 2026 bramka budżetu
   ukrywa 32% wysłanych (mediana ich stawki: +29% ponad budżet), a dni w biurze — 8%. Zatrudnieni
   mają umowę w budżecie w 85% przypadków — stawka z profilu nie nadaje się na twardy filtr. Ta sama
   stawka w ocenie (16,7 pkt) spycha trafnych w dół: neutralna stawka daje top 100 +7,6 pp.
6. **Podobne rekrutacje:** obecny wzór (Jaccard technologii + tytuł, próg 55) wskazuje prawdziwe źródło
   przepięcia w pierwszej piątce dla 40% rekrutacji; wektor rekrutacji — dla 60%, przy tej samej
   precyzji propozycji (7–9%). 86% rekrutacji, z których zespół naprawdę przepinał ludzi, ma dziś wynik
   poniżej progu 55.
7. **Algorytm to dziś mniejszy problem niż użycie:** z 57 nocnych propozycji „z bazy” nikt nie dodał
   ani nie odrzucił żadnej; z 44 propozycji przepięcia dodano 1; import JJIT dorzuca kandydatów do
   średnio 3,9 rekrutacji każdego (1 819 wpisów, 2 poszły dalej). Bez pętli zwrotnej (dodał/odrzucił
   i dlaczego) każde strojenie jest na ślepo.

## 1. Jak działa maszyna dziś (mapa)

```
Mail klienta ─► /jobs/new (Luna: JOB_REQUEST_INTAKE v7) ─► Champion (stack.must / nice, basics, experience,
                                                              search.requirements, insights)
     PUT champion-profile ─► jobs.must_skills / nice_skills (sync), budżet, dni, miasto (tylko puste)

Tekst zapytania (_build_job_text_v1: tytuł, opis, Champion, must/nice) ─► Voyage voyage-3 ─► wektor zapytania
                                                                                   │
Kandydat: profil + skills + doświadczenie + CV[:3000] ─► wektor kandydata (Qdrant) ┘
                                                                                   ▼
Ocena canonical_fit (base fit): semantyka 66,7 · umiejętności 11,1 (must 7,4 / nice 3,7) · stawka 16,7 · lokalizacja 5,6
                                ─► kara stażu (×0,68–1) · brak danych = 0,65 × max warstwy
Bramki (dealbreaker_filters.apply_dealbreakers, kolejność): tylko etat → budżet → must (v8: lista/profil/CV/notatki;
       brak danych = no_data) → dni w biurze → miasto (tylko ≥4 dni) → tylko zdalnie
```

Powierzchnie (`scoring_service.py:111-127`, `request_matching_context.py:53-66`, `config.py`):

| powierzchnia | pula | bramki | próg / rozmiar |
|---|---|---|---|
| Pełny przegląd bazy (ręczny i nocny) | cała baza (~64 tys.) | wszystkie | nocny: ≥70 pkt, top 60, **najwyżej 5 rekrutacji na noc**, tylko po zdarzeniu (publikacja/zmiana) |
| `/ai-matches`, Talent Radar (canonical) | top 1 000 z Qdranta | wszystkie | lista do 200 |
| Auto-dopasowanie nowego CV | opublikowane rekrutacje (top 300) | wszystkie + ≥1 must | ≥70 pkt, starszy scoring (z `champion_fit`) |
| Auto-dopasowanie po publikacji rekrutacji | **tylko CV odczytane nowym parserem** (`_profile_schema=2`, 5,2% bazy) | jw. | jw. |
| Moi ludzie | lista rekrutera, top 200/60 | wszystkie | ≥70 pkt, najwyżej 10 |
| Lista / „Szukaj ręcznie” | filtry listy | bez bramek dopasowania | pierwsze 200 przeliczone pełnym „Dop.” |
| Podobne rekrutacje / przepięcia | wszystkie rekrutacje z klientem | brak | `0,55·Jaccard(technologie) + 0,30·Jaccard(tytuł) + 0,15·(ta sama kategoria lub klient)`, próg 55, top 5 |

Czego w modelu nie ma: pojęcia „krytyczne” (poziomy to `must|nice|excluded|uncertain`,
`schemas/matching_requirements.py:11`). Wiersze „Wymagania do wyszukiwania w bazie”
(`search.requirements`) czyta tylko „Szukaj ręcznie” i bramka handoffu. Sekcja „Doświadczenie poza
stackiem” (dziedziny, lata) daje wyłącznie plakietki. Warstwa umiejętności w ocenie czyta **samą listę
umiejętności** — dowód z CV i notatek zna tylko bramka.

## 2. Skąd są dane i jakie są dziury

Kandydaci (63 837). „Wysłani 12 mies.” = 3 356 osób wysłanych do klienta w ostatnim roku.

| pole | cała baza | reszta bazy | wysłani 12 mies. | kto czyta |
|---|---:|---:|---:|---|
| tekst CV (>200 znaków) | 94,8% | 94,5% | 99,3% | wektor (pierwsze 3 000 znaków), bramka must, słowa kluczowe |
| lista umiejętności | 96,2% | 96,0% | 99,7% | ocena (warstwa umiejętności), bramka |
| technologie z Traffita | 69,8% | 70,3% | 62,1% | profil, bramka |
| notatki z rozmów (call/meeting/general/interview) | 29,6% | 25,7% | **98,9%** | bramka must, fakty z notatek |
| fakty z notatek (`_notes_insights`) | 27,5% | 23,7% | 96,2% | tryb pracy, stawka, „tylko zdalnie” |
| miasto / lokalizacja | 81,7% | 81,1% | 92,1% | warstwa lokalizacji, bramka miasta |
| stawka PLN/h | 16,0% | **11,5%** | **95,8%** | warstwa stawki, **bramka budżetu** |
| lata doświadczenia | 84,5% | 83,8% | 97,4% | kara za staż, wektor |
| limit dni w biurze | 4,4% | 2,5% | 38,2% | bramka dni w biurze |
| poziom języka (A1–C2) | 5,0% | 5,1% | 2,5% | nic |
| data dostępności | 4,0% | 3,1% | 20,9% | nic (w ocenie waga 0) |
| profil z nowego parsera CV (v7) | 5,2% | 5,3% | 3,8% | auto-dopasowanie po publikacji, oś technologii |
| wektor w Qdrancie | 99,96% | — | — | wszystko |

Wnioski o danych:
- **Asymetria „znani vs nieznani”.** Stawkę, limit dni i notatki ma prawie tylko ten, kto już był
  w procesie. Bramki działające na tych polach (budżet, dni w biurze) karzą ludzi, których zespół zna,
  a przepuszczają nieznanych („brak danych przechodzi”). Dokładnie ci ludzie wypadają z list (B3).
- **Nie znamy wieku CV.** 81 075 z 87 707 dokumentów CV nie ma daty wgrania (`uploaded_at`), 57 787 z nich
  pokazuje dzień importu z maja 2026. Naprawa dat plików z Traffita
  (`POST /api/admin/traffit/file-dates-repair`) istnieje, ale nie była uruchomiona (brak paragonu
  `traffit_file_dates_repair_2026_09`). Bez tego system nie odróżni CV z 2019 od CV z zeszłego miesiąca.
- **Poziom języka i dostępność praktycznie nie istnieją** (5% / 4%) — filtr po nich nie ma sensu (zgodne
  z B8 z 26.09).
- Po stronie rekrutacji: otwartych jest dziś 18 (po archiwizacji Traffita). Nowe rekrutacje z maila mają
  4–10 pozycji must (przed #1881: zwykle 10), historyczne rekrutacje z Traffita — mediana 1 pozycji,
  często etykieta kategorii („Software Developer”, „Manual Testing”).

## 3. Jak jest używane (produkcja 22–29.09.2026)

| co | ile | co z tego wyszło |
|---|---:|---|
| Nowe rekrutacje w NEXUSIE (od 25.09) | 31 (18 opublikowanych) | ręcznie dodanych do nich osób: 14, z propozycji: 5 |
| Nocne przeglądy bazy | 5 (28–29.09) | propozycje: 9, 0, 1, 2, 24 |
| Propozycje „z bazy” (`full_base`) | 57 w 8 rekrutacjach | **0 dodanych, 0 odrzuconych** |
| Propozycje z nowego CV (`new_cv`) | 65 w 26 rekrutacjach | 6 dodanych |
| Propozycje przepięcia (`reassign`) | 44 w 4 rekrutacjach | 1 dodana |
| Ręczne połączenia „podobne rekrutacje” | 8 (6 rekrutacji) | — |
| „Moi ludzie” — dopasowania | 1 635 (18 rekrutacji, 32 osoby) | 29 osób (1,8%) trafiło potem do tej rekrutacji |
| Import JJIT → auto-dopasowanie | 1 819 wpisów, 471 kandydatów, 160 rekrutacji (**3,9 rekrutacji na osobę**) | 2 poszły dalej niż „Nowi” |

Zespół nadal pracuje głównie w Traffit (10 611 procesów z importu od 16.09). Liczby użycia są za małe,
żeby z nich stroić algorytm — stąd symulacje na historii (B1–B7).

## 4. Badania

Miara trafności jak 26.09: trafni = osoby, które zespół **wysłał do klienta** (`cv_sent` i dalej), mocno
trafni = rozmowa u klienta / akceptacja / zatrudnienie. Symulacja listy: trafni + 3 000 losowych
kandydatów (≈4,7% bazy), ocena produkcyjna `canonical_fit`, bramki produkcyjne. **Notatki liczone tylko
sprzed otwarcia rekrutacji** (inaczej notatka z tego samego procesu „dowodzi” must u osób wysłanych).
Oszacowania „w pierwszych 60 na pełnej bazie” przeskalowują pozycję wśród losowych ×21,3.

### B1. Umiejętności krytyczne — lista rekrutera (`critical_study.py`, 200 rekrutacji od 07.2024)

Rekrutacje z ≥3 wysłanymi i ≥1 bramkującym must (średnio 2,4 etykiety). Warianty różnią się
**wyłącznie tym, które must ukrywają**; reszta bramek bez zmian.

| wariant (co ukrywa) | wysłani widoczni | mocno trafni widoczni | top 20 | top 100 | P@10 | MRR | lista (% bazy) | puste listy | wysłani w top 60 pełnej bazy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| brak bramki must | **81,4%** | 79,4% | **37,7%** | 58,2% | 0,198 | 0,468 | 95,6% | 0% | 21,3% |
| **krytyczne: reguła historyczna ≥90%** | **78,5%** | 75,9% | **36,8%** | 57,3% | 0,193 | 0,464 | 73,2% | 0% | 20,5% |
| krytyczne: reguła historyczna ≥80% | 76,3% | 73,5% | 36,5% | 55,8% | 0,188 | 0,465 | 64,8% | 0% | 19,8% |
| krytyczne: wybór Luny (1–3 z listy) | 69,2% | 66,9% | 36,5% | 54,7% | 0,184 | 0,446 | 41,3% | 1,5% | 19,7% |
| krytyczne: technologie z tytułu | 65,7% | 64,0% | 36,8% | 54,5% | 0,189 | 0,470 | 31,7% | 3% | 20,0% |
| krytyczne: najlepsza 1 pozycja „z wiedzą po fakcie” | 65,9% | 65,2% | 36,2% | 54,7% | 0,181 | 0,469 | 15,3% | 0,5% | 20,2% |
| krytyczne: pierwsza pozycja listy | 61,0% | 57,4% | 32,8% | 50,3% | 0,163 | 0,424 | 14,1% | 3% | 17,8% |
| krytyczne: dwie pierwsze pozycje | 53,5% | 48,5% | 29,2% | 44,0% | 0,143 | 0,403 | 10,1% | 8,5% | 16,1% |
| **dziś (v8): wszystkie must** | **45,9%** | 42,6% | **22,4%** | 36,5% | 0,099 | 0,305 | 9,1% | **19%** | 10,8% |
| v8 bez notatek | 44,6% | 41,1% | 21,7% | 35,2% | 0,097 | 0,303 | 9,1% | 19% | 10,6% |
| wszystkie must, sama lista umiejętności (jak do 27.09) | 19,2% | 15,6% | 10,2% | 16,1% | 0,051 | 0,156 | 2,6% | 35,5% | 4,0% |

Skąd u wysłanych pochodzi dowód must: lista umiejętności 46,8%, profil/CV 18,1%, notatki sprzed
otwarcia 1,3%, **brak nigdzie 33,8%**. Luna zostawiła listę krytycznych pustą w 36% rekrutacji
(średnio 0,66 pozycji); 69 tys. / 2,8 tys. tokenów na 200 rekrutacji.

Wnioski:
- Każda bramka kosztuje trafnych, ale **krótka bramka krytycznych kosztuje 3–12 pp, obecna — 36 pp.**
- Pierwsza dwudziestka jest prawie taka sama dla brak/krytyczne (36–38%): kolejność robi wektor, bramka
  działa na ogon listy. Obecna bramka psuje też początek listy (22%), bo wycina trafnych z góry.
- Nawet „najlepsza pojedyncza pozycja z wiedzą po fakcie” gubi 15,5 pp — w wielu rekrutacjach **nie ma**
  pozycji, którą mają wszyscy wysłani. Dlatego krytyczne muszą być opcjonalne (0–2), a nie „zawsze 1”.

### B2. Które must bramkują — na całej historii (`gate_labels_study.py`, `gate_rule_variants.py`)

2 428 rekrutacji z ≥3 wysłanymi i bramkującym must, 18 137 par, tło 600 losowych kandydatów.

| reguła wyboru ukrywających must | wysłani ukryci | rekrutacji tracących >50% wysłanych | lista (% bazy) | średnio etykiet | rekrutacji z bramką |
|---|---:|---:|---:|---:|---:|
| **dziś (v8): wszystkie** | **41,5%** | **40,2%** | 10,1% | 2,18 | 100% |
| tylko technologie ze słownika (wszystkie opcje `is_taxonomy_technology`) | 6,0% | 4,0% | 77,1% | 0,56 | 27% |
| historyczne ≥90% | 2,6% | 1,4% | 78,5% | 0,38 | 27% |
| historyczne ≥85% | 6,0% | 3,3% | 63,4% | 0,66 | 45% |
| historyczne ≥80% | 8,6% | 4,7% | 52,9% | 0,85 | 58% |
| **historyczne ≥90% i technologia** | **1,9%** | **0,9%** | 84,3% | 0,30 | 20% |
| pierwsza technologia z listy | 2,3% | 1,6% | 78,7% | 0,27 | 27% |
| najlepsza 1 pozycja „po fakcie” | 17,1% | 13,6% | 16,4% | 1 | 100% |

Odsetek wysłanych, którzy mają daną etykietę (dowód v8, historia; etykiety z ≥8 rekrutacji):

| grupa | przykłady (odsetek wysłanych z dowodem) |
|---|---|
| ≥90% — naturalnie „krytyczne” | Spring 100%, React 96,8%, UML 98,1%, Scrum Master 97,2%, Apache Spark 97,5%, Scala 95,9%, Java 95,6%, Spring Boot 95,6%, SQL 95,3%, .NET 94,7%, Power BI 94,6%, Docker 94,4%, Python 93,8%, Terraform 93,5%, TypeScript 93,3%, C# 93,1%, Selenium 92,2%, REST API 91,9%, BPMN 91,8%, Hibernate 91,8%, Figma 91,4%, Angular 90,1%, Microservices 90,3%, MS SQL Server 90,6% |
| 70–90% — must jako punkty | Kubernetes 88,6%, Agile 88,6%, Postman 88,5%, ETL 88,5%, AWS 86,1%, Git 86,0%, Linux 85,2%, Jira 84,9%, Azure 84,6%, PostgreSQL 84,5%, Kafka 83,2%, Ansible 82,0%, Jenkins 78,0%, CI/CD 77,2%, Oracle DB 75,7%, Maven 75,4%, Robot Framework 73,3%, Confluence 71,9%, Scrum 70,3% |
| <50% — nie powinny bramkować nigdy | QA 0,3%, IT analysis 3,1%, Test engineering 0%, Quality assurance 24,6%, Backend developer 24,1%, Data engineering 31,8%, IT consulting 32,5%, IT operations 36,7%, System administration 45,5%, GCP 49,4%, Risk management 49,7% |

Błędy w regule `must_gate_terms` (potwierdzone na taksonomii produkcji, `labels_check.py`):

1. **Nazwa ze słownika omija sprawdzenie roli i kategorii** — `must_gate_terms.py:352`
   (`if text.lower() in ALIAS_MAP: return text, None`) zwraca etykietę jako technologię, zanim
   `_option_reason` sprawdzi rolę/kategorię. Bramkują: „software developer”, „qa”, „backend developer”,
   „frontend developer”, „fullstack developer”, „project management”, „business analysis”,
   „systems analysis”, „it analysis”, „data engineering”, „devops engineering”, „test automation”,
   „it consulting”, „enterprise architecture”, „ai”. Jak pokazać: `gate_requirement("qa")` zwraca
   wymaganie; rekrutacja z must „QA” ukrywa 99,7% osób, które zespół do niej wysłał.
2. **Przykłady z nawiasu po zdaniu stają się wymogiem** — gałąź `_EXAMPLES/_PAREN_LIST`
   (`must_gate_terms.py:388-409`): głowa „Doświadczenie z integracją systemów” nie jest technologią,
   ale opcje z nawiasu tak („on-premise”, „hybrid”; „cloud” odpada jako kategoria) → bramka
   „on-premise lub hybrid”. Tak samo „Umiejętność pracy w dynamicznym środowisku IT (DevOps /
   Application Operations)” → „devops lub application operations”, „Wykształcenie wyższe kierunkowe
   (informatyka, matematyka)” → 19,4% wysłanych ma dowód. Etykiety tego typu dotyczyły 449 użyć;
   wysłani mają je w 52%.
3. **Zwroty miękkie i warunki bramkują jako „technologie”**: „team player” (3,7%), „flexibility” (0%),
   „szybkie przyswajanie wiedzy” (0%), „dostępność asap / maksymalnie 1 miesiąc” (5,3%), „customer
   service”, „root cause analysis”. Przechodzą regułę składniową (≤3 słowa, bez słów-śmieci).

Skala dziś (15 opublikowanych rekrutacji z NEXUSA, B7): nietechnologiczne etykiety bramkują w 7 z nich —
„user stories”, „inżynieria oprogramowania” (#689424), „hook-oriented programming” (#689433),
„performance analysis”, „profiling”, „optimization” (#689438), „data modelling” (#689439),
„data quality”, „reporting” (#689441), „release manager” (#706639), „ai”, „defining structured
governance” (#706640). Każda taka etykieta ukrywa prawie wszystkich, bo nikt nie ma jej w CV
dosłownie.

### B3. Inne bramki: budżet i dni w biurze (`other_gates_ceiling.py`)

Wysłani do klienta, bramka must wyłączona, reszta bramek produkcyjnych:

| co ukrywa wysłanych | cała historia (21 800 par) | rekrutacje od 03.2026 (4 353 pary) |
|---|---:|---:|
| budżet (stawka w profilu > budżet) | 11,4% | **31,9%** |
| dni w biurze (deklarowany limit < wymagane) | 2,4% | **8,0%** |
| „tylko zdalnie” z notatek | 0,2% | 0,3% |
| miasto biura (≥4 dni) | 0,1% | 0,1% |

Ukryci „za budżet” mają stawkę ×1,14 / ×1,29 / ×1,36 budżetu (kwartyle, rekrutacje od 03.2026);
tylko 22% mieści się w +10%. Progi (3 567 par w rekrutacjach z budżetem od 03.2026): stawka ponad
budżet 39,8%, ponad +20% 26,2%, ponad +30% 19,0%, ponad +40% 6,8%, ponad +50% 3,5%. Kontrola na zatrudnionych (230 par z budżetem): 39% ma dziś w profilu
stawkę powyżej budżetu, a z tych, którzy mają umowę w NEXUSIE, 85% (69/81) ma stawkę umowy w
budżecie (mediana 0,97 budżetu). Stawka w profilu to oczekiwanie, często sprzed negocjacji albo
późniejsze — nie twardy fakt. Stawki z etapu procesu (w chwili wysłania) praktycznie nie ma
(26 wierszy w całej bazie), więc tej hipotezy nie da się sprawdzić dokładniej.

### B4. Punkty za must/nice i warstwy oceny (`critical_study.py`, `ablation_study.py`)

Punkty doliczane do obecnej oceny, dowód v8 (lista/profil/CV/notatki), bez bramki must:

| wariant | top 20 | top 100 | P@10 | MRR |
|---|---:|---:|---:|---:|
| ocena produkcyjna | 37,7% | 58,2% | 0,198 | 0,468 |
| + 10 pkt × odsetek spełnionych must | 38,6% | 59,9% | 0,184 | 0,459 |
| + 20 pkt × must | 36,6% | 56,7% | 0,169 | 0,453 |
| + 10 pkt × nice | 37,2% | 57,2% | 0,185 | 0,458 |
| + 10 must + 5 nice | 38,1% | 59,9% | 0,181 | 0,463 |
| + 20 must + 10 nice | 35,6% | 56,8% | 0,168 | 0,450 |

Dodatkowe punkty za must/nice **nie poprawiają** kolejności: +0,9 pp w top 20 przy −1,4 pp P@10
(10 pkt), a większe wagi szkodzą. Zgodne z B6/B9 z 26.09.

Ablacja warstw (`ablation_study.py`; ta sama próbka 200 rekrutacji, **bez żadnych bramek**, więc
wartości bazowe wyższe niż w B1). Warianty przeliczają ocenę z punktów warstw:

| wariant oceny | top 20 | top 100 | P@10 | MRR |
|---|---:|---:|---:|---:|
| produkcja (semantyka 66,7 · umiejętności 11,1 · stawka 16,7 · lokalizacja 5,6) | 42,2% | 63,5% | 0,213 | 0,496 |
| sama semantyka (wektor) | 42,7% | 72,7% | 0,194 | 0,496 |
| bez warstwy stawki / stawka neutralna u wszystkich | 43,3% | 71,0% | 0,209 | 0,523 |
| bez warstwy lokalizacji | 40,5% | 62,1% | 0,208 | 0,495 |
| umiejętności ×2 / ×3 | 41,0% / 40,2% | 63,2% / 62,9% | 0,209 / 0,204 | 0,485 / 0,470 |
| **umiejętności z dowodem „gdziekolwiek”** (must/nice z listy, profilu, CV, notatek — jak bramka) | 43,3% | 68,0% | 0,223 | 0,543 |
| umiejętności „gdziekolwiek” ×2 | 41,7% | 68,6% | 0,215 | 0,539 |
| **stawka neutralna + umiejętności „gdziekolwiek”** | **45,0%** | **74,2%** | 0,218 | **0,541** |

Różnica względem produkcji, średnia i 95% przedział (bootstrap po rekrutacjach, 2 000 losowań),
w punktach procentowych (MRR ×100). **Pogrubione** = przedział nie obejmuje zera.

| wariant | top 20 | top 100 | P@10 | MRR |
|---|---|---|---|---|
| stawka neutralna | +1,0 (−2,2…+4,2) | **+7,6 (+4,6…+10,6)** | −0,4 (−2,3…+1,3) | +2,7 (−1,1…+6,8) |
| umiejętności „gdziekolwiek” | +1,0 (−0,9…+2,8) | **+4,6 (+2,5…+6,6)** | +1,1 (−0,2…+2,2) | **+4,7 (+1,1…+8,3)** |
| stawka neutralna + umiejętności „gdziekolwiek” | +2,8 (−0,5…+6,2) | **+10,7 (+7,4…+14,2)** | +0,6 (−1,4…+2,5) | +4,5 (−0,9…+9,8) |
| sama semantyka | +0,5 (−3,1…+4,3) | **+9,3 (+6,0…+12,8)** | −1,9 (−4,0…+0,3) | 0,0 (−4,6…+5,1) |
| bez lokalizacji | **−1,8 (−3,1…−0,6)** | **−1,4 (−2,3…−0,5)** | −0,5 (−1,3…+0,4) | −0,1 (−2,4…+2,2) |
| umiejętności ×2 | **−1,3 (−2,3…−0,4)** | −0,2 (−1,3…+0,8) | −0,4 (−0,9…+0,2) | −1,1 (−3,5…+1,2) |
| umiejętności ×3 | **−2,0 (−3,4…−0,8)** | −0,5 (−1,8…+0,7) | **−0,9 (−1,6…−0,3)** | −2,6 (−5,4…+0,1) |

Czytanie: zmiany pewne w głębi listy (top 100) i w MRR; w pierwszej dwudziestce kierunek dodatni,
ale w granicach szumu na 200 rekrutacjach.

Wnioski:
- **Warstwa stawki szkodzi** (16,7 pkt): spycha w dół ludzi, których zespół wysyła (często z oczekiwaniem
  ponad budżet — B3). Neutralna stawka daje +7,6 pp w top 100 (istotne); MRR +2,7 pp (w granicach szumu).
- **Warstwa umiejętności liczona z samej listy jest za słaba**; z dowodem z CV/notatek (ta sama reguła,
  której od 27.09 używa bramka) istotnie poprawia MRR i top 100, a pozostałe miary idą w tę samą
  stronę — to jest właściwe miejsce, w którym must/nice mają „dodawać punkty”, bez podnoszenia wagi.
- Lokalizacja pomaga (bez niej gorzej). Sama semantyka jest mocna — wektor robi większość pracy.

### B5. Sufit puli wektorowej (`other_gates_ceiling.py`, 250 rekrutacji od 07.2024)

Odsetek wysłanych wśród K najbliższych wektorowo w całej bazie (ten sam wektor zapytania co ocena):

| K | 60 | 200 | 300 | **1 000** (`/ai-matches`) | 3 000 |
|---|---:|---:|---:|---:|---:|
| wysłani w puli | 19,4% | 33,2% | 39,6% | **61,7%** | 80,8% |

`/ai-matches` i Talent Radar (canonical) z pulą 1 000 nie widzą 38% trafnych, zanim zadziała ocena.
Pełny przegląd bazy tego sufitu nie ma, ale nocą robi najwyżej 5 rekrutacji i tylko po zdarzeniu.

### B6. Podobne rekrutacje i przepięcia (`similar_study.py`)

Zdarzenie przepięcia z historii: osoba wysłana do klienta w A (nie zatrudniona w A) trafiła później
w B co najmniej do „zweryfikowany” (≤365 dni). 1 620 rekrutacji B otwartych od 01.2025, 2 157 osób.
Dla każdej B porządkujemy wszystkie wcześniejsze rekrutacje z wysłanymi osobami.

| miara podobieństwa | źródło w top 5 | przepiętych osób z top 5 | propozycji na rekrutację | precyzja propozycji |
|---|---:|---:|---:|---:|
| **dziś: wzór + próg 55** (to widzi panel) | **39,7%** | 21,7% | 16,3 | 8,5% |
| wzór bez progu (top 5) | 49,2% | 27,2% | 21,1 | 5,9% |
| **wektor rekrutacji (Qdrant `nexus_jobs`)** | **60,1%** | **36,0%** | 22,3 | 7,1% |
| wektor + premia za tego samego klienta | 60,6% | 36,3% | 22,1 | 7,3% |
| wzór + wektor | 58,8% | 34,7% | 22,0 | 7,0% |
| ten sam klient, najnowsze | 16,8% | 7,8% | 10,3 | 2,0% |

Prawdziwe źródła przepięć mają dziś wynik: kwartyle 29 / 35 / 45 — **86% jest poniżej progu 55**.
45% źródeł to ten sam klient. Precyzja 7–9% znaczy ok. 1,2–1,6 osoby przepiętej na rekrutację
z ~16–22 propozycji — tyle zespół historycznie wziął (bez podpowiedzi systemu).

### B7. Nowe rekrutacje z NEXUSA na pełnej bazie (`critical_full.py`)

15 opublikowanych rekrutacji założonych w NEXUSIE od 25.09 (filtr tytułów bez słowa „test” pominął
3 prawdziwe rekrutacje testerskie). Cała baza (~64 tys.), ocena i bramki produkcyjne, próg nocnych
propozycji ≥70 i top 60. W komórce: **osób na liście / propozycji nocnych**.

| rekrutacja | must bramkujące | dziś (v8) | krytyczne — reguła (≤2, historia ≥90%, nazwy kanoniczne) | krytyczne — Luna | bez bramki must |
|---|---:|---:|---|---|---:|
| #689424 Starszy Analityk Biznesowo-Systemowy | 4 | 5 / 2 | — (brak): 59 397 / 60 | uml: 3 090 / 60 | 59 397 / 60 |
| #689429 Full Stack Java Developer | 10 | 19 / 12 | java, spring boot: 4 478 / 60 | java: 14 556 / 60 | 60 395 / 60 |
| #689430 Senior Java Developer | 9 | 201 / 60 | java, spring boot: 4 452 / 60 | java: 14 423 / 60 | 59 975 / 60 |
| #689431 Senior Java Developer | 7 | 326 / 60 | java 8+, spring: 5 961 / 60 | java 8+: 14 557 / 60 | 60 395 / 60 |
| #689432 Senior/Expert Java Developer | 6 | 18 / 14 | java, spring: 5 961 / 60 | java: 14 556 / 60 | 60 395 / 60 |
| #689433 Senior Frontend Developer | 7 | 0 / 0 | react.js 18+, typescript: 6 361 / 60 | react.js 18+: 9 355 / 60 | 58 806 / 60 |
| #689436 Pega Lead System Architect (LSA) | 1 | 184 / 7 | — (brak): 61 417 / 23 | pega: 184 / 7 | 61 417 / 23 |
| #689438 Senior Java Developer | 9 | 1 / 1 | java, spring boot: 4 478 / 60 | java: 14 556 / 60 | 60 395 / 60 |
| #689439 MS Power Platform Expert | 4 | 0 / 0 | sql: 28 174 / 60 | power platform: 1 357 / 43 | 58 806 / 60 |
| #689440 Windows Expert | 10 | 7 / 5 | — (brak): 60 395 / 60 | powershell: 3 062 / 60 | 60 395 / 60 |
| #689441 Application Manager/SME for DORA Regis | 4 | 144 / 10 | power bi: 6 464 / 60 | snowflake: 1 022 / 24 | 58 040 / 60 |
| #689443 Senior FullStack Developer | 10 | 105 / 35 | java 7/8, spring: 5 615 / 60 | java 7/8: 13 781 / 60 | 58 474 / 60 |
| #706639 Change/Release Manager | 1 | 5 130 / 10 | — (brak): 59 677 / 13 | release manager: 5 130 / 10 | 59 677 / 13 |
| #706640 Project Manager – AI-driven applicatio | 2 | 0 / 0 | — (brak): 59 305 / 14 | ai: 1 101 / 3 | 59 305 / 14 |
| #706641 Starszy Programista Frontend (Angular) | 8 | 1 / 1 | docker, typescript: 5 020 / 60 | angular: 5 490 / 60 | 56 724 / 60 |

- Dziś 8 z 15 rekrutacji ma mniej niż 10 propozycji nocnych, a 3 mają **pustą listę** (0 osób:
  React, Power Platform, Project Manager AI). Lista 4–10 must zamienia bramkę w filtr „ma wszystko”.
- Reguła z limitem 2 i nazwami kanonicznymi daje w każdej z 15 rekrutacji listę i propozycje
  (dziś: 3 puste listy, 8 rekrutacji z <10 propozycjami). W 5 rekrutacjach
  nie podpowiada nic (np. UML/BPMN, PEGA, Release Manager — nie są w słowniku „technologią” albo nie mają
  historii ≥90%); tam decyduje DL albo nie ma bramki must.
- Żywe przykłady błędu reguły etykiet (B2): #706639 bramkuje rolą „release manager”, #706640 słowem
  „ai” i zwrotem „defining structured governance” (0 osób na liście), #689441 zwrotami „data quality”
  i „reporting”.
- **Krytyczne muszą być opcjonalne.** W jedynej nowej rekrutacji z wieloma osobami dodanymi przez
  zespół (#706641, Angular, 9 osób dodanych przez DL 28.09) 8 z 9 nie ma Angulara ani w CV, ani
  w profilu. Krytyczne „Angular” by je ukryło (widoczna 1 z 9; bez bramki must 5 z 9 — resztę ukrywa
  budżet 95 zł/h przy oczekiwaniach 100–187 zł/h). Nie wiemy, czy to świadomy wybór DL (np. przekwalifikowanie
  z Reacta) — dlatego DL zatwierdza krytyczne, system tylko podpowiada.
- Luna jako „krytyczne” wybiera czasem etykietę z wersją („java 8+”, „react.js 18+”), którą bramka i tak
  normalizuje, ale też rzeczy niebędące rdzeniem („snowflake” dla roli Application Manager, „ai” dla PM).


## 5. Rekomendacje

Priorytety: **P0** = błąd albo reguła, która dziś ukrywa trafnych; **P1** = duży zysk jakości;
**P2** = porządek i pomiar. Przy każdej: dowód, oczekiwany efekt z symulacji, ryzyko.

### Jak to powinno działać (docelowo)

1. **Rekrutacja z maila → Champion.** Luna przepisuje must / nice klienta (jak dziś, bez limitu 10),
   lata doświadczenia i listę miast biura. DL oznacza **0–2 pozycje krytyczne** — system podpowiada
   je z historii (technologie, które ma ≥90% osób wysyłanych do podobnych ról).
2. **Pełny przegląd bazy** zaraz po publikacji i po każdej zmianie wymagań, a do tego raz w tygodniu
   dla każdej rekrutacji w pracy. Wynik: top 60 z oceną ≥70 jako propozycje z decyzją
   „Dodaj / Nie pasuje (powód)”.
3. **Ukrywa wyłącznie:** brak technologii krytycznej (dowód: lista, profil, CV, notatki), czarna lista,
   „tylko umowa o pracę”, inne miasto przy ≥4 dniach w biurze. **Budżet, dni w biurze, wymiar pracy,
   brak must/nice — plakietki**, nie ukrycie.
4. **Kolejność:** wektor (pełny tekst rekrutacji i kandydata) + umiejętności must/nice z dowodem
   „gdziekolwiek” + lokalizacja + kara za staż. Stawka nie obniża pozycji — widać ją na plakietce.
5. **Podobne rekrutacje** po wektorze rekrutacji (+ ten sam klient) → osoby wysłane tam do klienta →
   propozycje przepięcia w „Do przejrzenia”.
6. **Pomiar:** tygodniowy raport propozycji (dodane / odrzucone z powodem / bez decyzji) i
   `eval_matching.py` przed każdą zmianą wag lub bramek.

### Docelowy model „krytyczne / must / nice” (odpowiedź na pomysł Artura)

| poziom w Championie | co robi w wyszukiwaniu | kto ustala |
|---|---|---|
| **Krytyczne** (0–2 pozycje, tylko technologie) | **ukrywa** kandydata bez dowodu (lista, profil, CV, notatki — reguła v8) | DL; system **podpowiada** z historii |
| **Must have** | punkty w warstwie umiejętności (z dowodem „gdziekolwiek”) + plakietka ✓/✗ | DL / Luna z maila (jak dziś) |
| **Nice to have** | punkty (1/3 warstwy) + plakietka | jak dziś |

### P0

1. **Wprowadzić „Krytyczne” i przenieść na nie bramkę must** (zamiast „każde must ukrywa”).
   - Champion: znacznik `critical` na pozycji `stack.must` (bez nowej listy — pozycja zostaje must
     i dalej punktuje). Najwyżej 2. Brak zaznaczenia = brak bramki must.
   - Podpowiedź systemu: pozycje must będące technologią ze słownika, które ≥90% osób wysłanych
     w historycznych rekrutacjach ma w profilu/CV (tabela w B2; porównanie po nazwie kanonicznej,
     odświeżane z historii, bez modelu). **Najpierw technologie z tytułu roli, potem wg historii** —
     sama historia wybrała dla roli „Frontend (Angular)” Docker i TypeScript zamiast Angulara (B7).
     Słownik trzeba poszerzyć o standardy analityków (UML, BPMN — historycznie 98% i 92%), dziś nie są
     „technologią” i nie da się ich podpowiedzieć.
     Luna jako podpowiedź przegrywa (B1: 69% widocznych wysłanych, pusto w 36% rekrutacji) — nie ona.
   - `search_dealbreaker_inputs` bierze do bramki tylko krytyczne; `MUST_GATE_POLICY_VERSION` → v9.
   - Efekt (B1, B2): wysłani widoczni 45,9% → 78,5% (lista rekrutera) i 58,5% → 97–98% (cała historia,
     tylko bramka must); trafni w top 20 22,4% → 36,8%; puste listy 19% → 0%; lista 9% → 73% bazy.
     Nowe rekrutacje na pełnej bazie — B7.
   - Ryzyko: dłuższe listy (to zamierzone — kolejność robi wektor, początek listy zostaje ten sam).
     Decyzja Artura z 27.09 („brak must = nie pasuje”) zostaje zachowana dla pozycji, które DL oznaczy
     jako krytyczne.
2. **Naprawić regułę „które must bramkują”** (`must_gate_terms.py`), niezależnie od punktu 1 — ta sama
   reguła zdecyduje, które pozycje wolno oznaczyć jako krytyczne:
   - pozycja bramkuje tylko, gdy **każda opcja jest technologią ze słownika**
     (`skill_normalize.is_taxonomy_technology`), a nie „dowolną nazwą ze słownika” (`:352`);
   - przykłady z nawiasu/„np.” liczą się tylko, gdy głowa jest technologią albo kategorią
     („bazy danych (Oracle, PostgreSQL)”), nie zdaniem („Doświadczenie z…”, „Umiejętność…”) (`:388-409`);
   - efekt na historii (B2, „tylko technologie ze słownika”): wysłani ukryci przez must 41,5% → 6,0%.
   - Test regresji na etykietach z B2 („qa”, „software developer”, „dostępność asap / maksymalnie
     1 miesiąc”, „Doświadczenie z integracją systemów (on-premise, hybrid, cloud)”).
3. **Budżet: z bramki na plakietkę** (decyzja Artura). Dziś ukrywa 32% wysłanych w rekrutacjach od
   03.2026, a 85% zatrudnionych ma umowę w budżecie mimo wyższego oczekiwania w profilu (B3).
   Propozycja: nie ukrywać; plakietka „oczekuje +X% ponad budżet”; opcjonalnie ukrywać dopiero
   powyżej +50% (w rekrutacjach z budżetem od 03.2026: ponad budżet jest 39,8% wysłanych, ponad
   +40% — 6,8%, ponad +50% — 3,5%).
   To samo dla „dni w biurze” (8% wysłanych): plakietka zamiast ukrycia, bo limit dni mają głównie
   osoby znane zespołowi (2,5% bazy vs 38% wysłanych).

### P1

4. **Ocena: warstwa umiejętności z dowodem „gdziekolwiek”, stawka neutralna** (B4). Warstwa
   umiejętności ma czytać tę samą regułę dowodu co bramka (lista + profil + CV + notatki); warstwa
   stawki — zostać plakietką albo mieć dużo łagodniejszy spadek. Efekt w symulacji: top 100
   63,5% → 74,2% (+10,7 pp, przedział +7,4…+14,2), MRR 0,496 → 0,541; sama warstwa umiejętności
   „gdziekolwiek” daje istotny zysk MRR (+4,7 pp). Zmiana wag = bump `scoring_algorithm_version()` i pomiar
   `scripts/eval_matching.py` przed/po (reguła repo).
5. **Podobne rekrutacje: wektor rekrutacji jako główna miara** (B6). Pozycje panelu „Podobne
   rekrutacje” porządkować po kosinusie wektorów z kolekcji `nexus_jobs` (są dla 4 372 z 4 373
   rekrutacji), z drobną premią za tego samego klienta; próg 55 obecnego wzoru zdjąć albo zastąpić
   progiem kosinusa. Efekt: źródło przepięcia w top 5 z 39,7% do 60,6%, osoby do przepięcia
   z 21,7% do 36,3%, przy podobnej precyzji propozycji (7,3% vs 8,5%).
6. **Pokrycie przeglądów bazy.** Otwartych rekrutacji jest 18 — nocny przegląd powinien objąć każdą
   opublikowaną rekrutację w pracy co najmniej raz na tydzień i po każdej zmianie wymagań
   (dziś: najwyżej 5 na noc i tylko po zdarzeniu — w 5 nocy powstało 5 przeglądów). `/ai-matches`
   i Talent Radar: pula 3 000 zamiast 1 000 (sufit 61,7% → 80,8%, B5) albo korzystanie z ostatniego
   pełnego przeglądu.
7. **Import JJIT nie wrzuca kandydatów do „Nowych” wielu rekrutacji.** Dziś każdy kandydat trafia
   średnio do 3,9 rekrutacji, 2 z 1 819 wpisów poszły dalej. Dopasowanie do INNYCH rekrutacji niż ta,
   na którą aplikował, powinno iść do propozycji (`new_cv`), nie do tablicy.

### P2

8. **Pętla zwrotna propozycji.** 0 z 57 nocnych propozycji ma decyzję. Przycisk „Nie pasuje”
   z powodem (brak krytycznej technologii / stawka / miasto / seniority / inne) i tygodniowy raport
   „dodane / odrzucone / bez decyzji” per źródło. Bez tego nie wiemy, czy propozycje są złe, czy
   niewidziane.
9. **Naprawa dat CV** (`file-dates-repair` — próba na sucho, potem zapis): wiek CV jako plakietka
   i przyszły sygnał w ocenie (świeżość). Dziś nie da się go policzyć.
10. **Stawka i dni w biurze z rozmów** — praktykant i screening już je zbierają; dopóki pokrycie bazy
    to 11–16%, te pola nie mogą ukrywać (punkt 3).
11. **„Wymagania do wyszukiwania w bazie” (wiersze)** zostają narzędziem „Szukaj ręcznie” — nie łączyć
    ich z krytycznymi: wiersze zawierają też branże i słowa („bankow*”), a krytyczne mają być tylko
    technologiami.

## 6. Czego nie robić (sprawdzone)

- **Każde must jako twarda bramka** (dziś) — gubi 41,5% wysłanych (B2).
- **Krytyczne wybierane przez model bez historii** — Luna gubi ok. 4× więcej trafnych niż reguła
  historyczna i zostawia pustą listę w 36% rekrutacji (B1). Model może pomóc w czytaniu maila, nie
  w decyzji, co ukrywa.
- **„Zawsze pierwsza pozycja listy jako krytyczna”** — 61% widocznych wysłanych (B1).
- **Dodatkowe punkty za must/nice ponad obecną ocenę** i podnoszenie wagi umiejętności (×2, ×3) — nie
  poprawiają albo pogarszają (B4).
- **Ranking podobnych rekrutacji po samym kliencie** — 16,8% trafień (B6).
- **Filtr po języku i dostępności** — dane są u 4–5% bazy (sekcja 2).

## 7. Ograniczenia i niepotwierdzone

- **Trafni = wysłani do klienta.** Zespół szukał ich w Traffit, więc to „znalezieni”, nie „wszyscy
  dobrzy”. Dane kandydata są dzisiejsze (CV, profil, stawka), a nie z dnia wysyłki — tylko notatki
  obcięte do daty otwarcia rekrutacji.
- **Asymetria danych** (sekcja 2) działa w obie strony: osoby wysłane mają pełniejsze profile, więc
  część przewagi „dowodu gdziekolwiek” i część szkody warstwy stawki może być artefaktem historii.
  Kierunek wszystkich wyników jest zgodny z badaniami z 26.09 i z danymi zatrudnionych (B3).
- **Symulacja listy na tle 3 000 losowych** (≈4,7% bazy) — liczby względne (porównanie wariantów).
  Pełna baza liczona tylko dla nowych rekrutacji (B7).
- **Reguła historyczna** potrzebuje historii etykiety (≥5 rekrutacji). Nowa technologia bez historii
  nie dostanie podpowiedzi — DL oznacza ją sam.
- **Podobne rekrutacje:** ground truth to przepięcia, które zespół zrobił bez podpowiedzi systemu
  (w Traffit); precyzja propozycji 7–9% to dolna granica.
- **Niepotwierdzone:** czy propozycje nocne są dobre w oczach DL (brak decyzji w danych — punkt 8);
  jak zmiana budżetu na plakietkę wpłynie na pracę zespołu (decyzja produktowa).

## Sprawdzone i czyste

- Reguła dowodu v8 (lista/profil/CV/notatki) działa zgodnie z opisem; notatki sprzed otwarcia
  rekrutacji dają tylko 1,3% dowodów — v8 nie jest „zawyżona” notatkami z tego samego procesu.
- Miasto biura po poprawce z 27.09 ukrywa 0,1% wysłanych (było 2,6% w v7).
- Wektory: 63 813 z 63 837 kandydatów ma `embedding_id`; 4 372 z 4 373 rekrutacji z klientem ma punkt w Qdrancie.
- Lokalizacja w ocenie pomaga (ablacja B4).

## Jak powtórzyć

Skrypty (`wyszukiwanie-kandydatow/`) kopiujesz na serwer produkcji do `/root/nexus-search-research/s30/`
i uruchamiasz `./run.sh /research/<skrypt>.py` (jednorazowy kontener z obrazem backendu, 3 CPU / 6 GB,
baza tylko do odczytu przez `ro_boot.py`, argumenty przez `RESEARCH_ARGS`). Jeden kontener naraz.

| skrypt | co liczy | czas | zależy od |
|---|---|---|---|
| `critical_study.py` | B1 (+ punkty must/nice w B4); woła Lunę (~70 tys. tokenów) | ~15 min | — |
| `gate_labels_study.py` | B2: etykiety, skala błędów reguły | ~2 min | — |
| `gate_rule_variants.py` | B2: reguły wyboru, odsetek wysłanych z dowodem per etykieta | ~10 min | — |
| `labels_check.py` | B2: które etykiety bramkują na taksonomii produkcji | <1 min | — |
| `other_gates_ceiling.py` | B3, B5 | ~3 min | — |
| `ablation_study.py` | B4 (ablacja + przedziały bootstrap) | ~15 min | — |
| `similar_study.py` | B6 | ~3 min | — |
| `critical_full.py` | B7 (pełna baza; wznawialny, `out_critical_full.jsonl`) | ~2–3 min / rekrutację | `out_critical.json` |
| `critical_full2.py` | B7: reguła ≤2 / nazwy kanoniczne | ~1–2 min / rekrutację | `out_gate_rules.json` |

Wdrożenia innych sesji restartują bazę i Qdranta (w badaniu 4 razy w 3 godziny) — bieg kończy się
błędem połączenia albo `Temporary failure in name resolution`. Długie biegi puszczaj w pętli
wznawiającej (jak `loop_full.sh`: `./run.sh …; sleep 90` do skutku). `data.py` zapisuje w `cache/`
identyfikatory kandydatów — katalog `cache/` usunięty z serwera po badaniu.

## Wdrożenie (30.09.2026, gałąź `claude/search-critical-skills`)

Rekomendacje wdrożone jednym PR-em wg decyzji Artura z 30.09.2026 (plan w opisie PR). Kod gałęzi
zmierzony na produkcji tylko do odczytu (`run_branch.sh` montuje `branch_app/app` nad `/app/app`).

**Bramka v9 (umiejętności krytyczne)** — `verify_critical_branch.py`, 1 199 rekrutacji, 9 362 pary
wysłane do klienta:

| | v8 (produkcja) | v9 (gałąź) |
|---|---|---|
| wysłani, których bramka ukryłaby | 41,5% | **2,9%** |
| rekrutacje tracące > 50% wysłanych | — | 1,4% |
| rekrutacje z podpowiedzią krytycznych | — | 45,5% (śr. 0,61 technologii) |
| wysłani bez żadnych danych (`no_data`) | — | 0,3% |

Przeliczenie statystyk historii (`compute_stats`) trwa 14,8 s (1 048 etykiet, 2 749 rekrutacji).
Liczone bez leave-one-out — rekrutacja widzi własną historię, więc 2,9% jest lekko optymistyczne.
Pomiar znalazł też praktyki spoza słownika technologii, które przechodziły regułę składniową
(„QA”, „IT analysis”, „Data engineering”) — poprawione przed merge.

**Ocena** — ablacja B4 na tej samej, dzisiejszej próbce (200 rekrutacji, pula 3 000 + wysłani;
`ablation_study.py` na kodzie produkcji i `ablation_branch.py` na kodzie gałęzi, ta sama losowość —
warstwa semantyczna: R@100 69,8% vs 69,4%):

| | R@20 | R@100 | P@10 | MRR |
|---|---|---|---|---|
| produkcja | 40,4% | 60,8% | 20,3% | 0,483 |
| **gałąź** | **43,3%** | **68,4%** | 20,5% | 0,485 |
| wariant z badania (stawka neutralna + umiejętności gdziekolwiek) | 42,9% | 70,7% | 20,9% | 0,513 |

Gałąź: top 20 +2,9 pp, top 100 +7,6 pp, MRR bez zmian. Do wariantu z badania brakuje 2,3 pp
w top 100 i 0,03 MRR. Różnica to waga umiejętności: wariant z badania przy rekrutacji bez
„nice” (≈90% ofert) liczy must za 2/3 wagi warstwy, gałąź — za pełną. Na tej samej próbce
wariant ponad gałąź daje R@100 +1,2 pp (95%: −0,1…+2,6) i MRR +0,012 (−0,010…+0,035) —
nieistotne, więc wag nie dopasowujemy pod jeden pomiar. Wczorajsze liczby B4 (63,5% → 74,2%)
pochodzą z innej próbki (baza urosła, losowa pula tła się zmieniła) i nie są porównywalne
z dzisiejszymi.

**Podobne rekrutacje** — `similar_calibration.py`, 1 620 rekrutacji z przepięciami: prawdziwe źródło
w top 5 60,6% (wektor + klient) wobec 39,7% (dawny wzór z progiem 55). Próg plakietki „≈” na
liście = 0,65 (mediana wyniku prawdziwych źródeł).

Kroki na produkcji po merge (każdy za zgodą Artura): przeniesienie kart z portali do propozycji
(próba → lista → zapis), naprawa dat CV z Traffita (próba → raport → zapis), `MATCH_POOL_SIZE=3000`.
