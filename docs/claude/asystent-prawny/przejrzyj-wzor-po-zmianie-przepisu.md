# Asystent prawny w Przepisach: karta źródeł i zadanie „Przejrzyj wzór” (część H, 25.11.2026)
<!-- indeks: Przepisy, Źródła i boty, Źródła asystenta prawnego, LegalSourcesCard, GET /api/legal/sources, documents, template_review, Przejrzyj wzór, template_review.py, legal_template_review, corpus.changes_since, law_changes, law_change_tasks, law_radar_items gate_reason legal_corpus, LEX Gofin tylko link -->

Plan: `docs/asystent-prawny-plan.md` (część H). Asystent działa w tle
istniejących ekranów (decyzja Artura 25.11.2026); w Przepisach ma dwa wpięcia.

## Karta „Źródła asystenta prawnego”

- Przepisy → „Źródła i boty”, pełna szerokość nad „Boty dziś”
  (`components/compliance/LegalSourcesCard.tsx`, model
  `legal-sources-model.ts`). Dane wyłącznie z `GET /api/legal/sources`:
  korpus (`corpus.sources_status`), a od części H także `documents`
  (orzeczenia, wzory z repo, klienci z klauzulami, zatwierdzone wzory własne,
  odczytane umowy ramowe i aneksy — `services/legal/sources.py`) oraz
  `template_review` (otwarte zmiany „Przejrzyj wzory”, ostatnie założenie).
  Same liczby, bez nazw klientów, osób i wzorów. Nowej trasy nie ma.
- **Bramka trasy się nie zmienia** (Generator umów B2B za sekcją Sourcing).
  Przepisy widzą też Płace, Kadry i Finanse bez Generatora — oni dostają 403
  i karta mówi „widzi osoba z dostępem do Generatora umów B2B”, nie pustą kartę.
- Stany: ładowanie, błąd (`apiErrorMessage` + „Spróbuj ponownie”), pusty
  korpus (komunikat w grupie przepisów; reszta karty zostaje).
- **LEX i Gofin to stały wiersz „tylko link — nie do modelu”** (licencje,
  decyzja Artura 25.11.2026). CBOSA, EUREKA i `sn.pl` też tylko link
  (`orzecznictwo-i-interpretacje.md`). Nie zamieniaj tych wierszy na liczniki.

## „Przejrzyj wzór” po nowym tekście aktu

- `services/legal/template_review.py`: `corpus.changes_since` (nowa wersja
  z poprzednią w korpusie, oznaczenia dodane / usunięte / zmienione) ×
  cytaty z `citations.extract` we wzorach: `templates/contract/*.html`,
  bieżące rewizje `templates/documents/*.html` z rejestru typów (stare
  rewizje zostają w repo tylko dla wydanych dokumentów i nie wchodzą),
  klauzule klientów (`clause_override_content.CLIENT_OVERRIDES`, PL)
  i zatwierdzone, niewycofane wzory własne.
- **Dopasowanie:** zmieniła się jednostka cytowana albo jej podjednostka
  („art. 32” ← nowy „art. 32 ust. 5”); „§” i „ust.” to ta sama jednostka.
  Zmiana samego artykułu nadrzędnego nie liczy się dla cytatu z § 1 — tekst
  artykułu obejmuje wszystkie paragrafy, więc zmienia się przy każdej zmianie
  § 2. Odwołanie bez rozpoznanego aktu odpada.
- **Jedna zmiana na wersję aktu** w `law_changes` (rola `contracts`, etap
  `in_force`, pilność `soon`, tytuł „Przejrzyj wzory — nowy tekst KC
  (DU/…)”) z zadaniami „Przejrzyj wzór „X” — zmienił się art. Y KC”
  (`source = 'user'`, `created_by` puste = założył NEXUS; ikona bota znaczy
  Analityka). Dziennik: „Zmiana założona przez NEXUS”.
- **Bez duplikatów, bez migracji:** zmiana ma pozycję `law_radar_items`
  z adresem urzędowego tekstu (`official`, `verified`, `gate_reason =
  'legal_corpus'`, odcisk `sha256("legal_corpus:<id wersji>")`). Pozycja ma
  `analyzed_at`, więc nie idzie do Analityka, a licznik „potwierdzone źródło”
  na karcie zmiany jest prawdziwy. Drugi przebieg dokłada do **otwartej**
  zmiany tylko brakujące zadania (bez wielkości liter); zmiany zrobionej albo
  „Nie dotyczy” nie rusza (decyzja człowieka). Pętla i skrypt naraz:
  `pg_advisory_xact_lock`.
- Analityk widzi tę zmianę na liście otwartych (tytuł i `legal_ref` — dane
  publiczne; nazwy wzorów są tylko w zadaniach, które do bota nie idą) i może
  zaktualizować jej treść, nie zadania ani status.
- **Bez maili i bez powiadomień** (jak cały radar, decyzja 15.11.2026).
- **Kiedy biegnie:** pętla `legal_corpus` (worker) po każdym ticku, co
  godzinę, z oknem `LOOKBACK` = 3 dni (powtórka po awarii; awaria przeglądu nie
  zatrzymuje pętli). Na stagingu pętla stoi — po `scripts.legal_corpus_seed`
  ręcznie `python -m scripts.legal_template_review [--since RRRR-MM-DD]
  [--dry-run]` (z `backend/`; wypisuje same liczby i oznaczenia przepisów).
  Pierwsze zasilenie korpusu nie zakłada niczego (wersja bez poprzedniej).
- Zmiany zapisują się także przy wyłączonym `LAW_RADAR_ENABLED`; ekran zmian
  pokaże je dopiero po włączeniu radaru, a liczbę otwartych widać w nagłówku
  karty źródeł.
