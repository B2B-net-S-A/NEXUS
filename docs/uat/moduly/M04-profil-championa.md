# M04 — Profil Championa

| Pole | Wartość |
|---|---|
| Tryb | **R** (zapis profilu → P1; tu tylko odczyt, import DOCX w trybie podglądu formularza) |
| Persony | delivery_lead, recruiter (podgląd); admin |
| Zależności | Fala 0 (D3 z Championem D10, `champion-D3.docx` w fixtures) |
| Czas | ~90 min |
| Głębokość | pełna (Champion zasila scoring, radar, generator CV) |
| Akcje AI | tak — parser dokumentu (`/api/champion/preview`) i szkic AI. Jedno wywołanie parsera = jedna kwota. Limit: 2 importy. |

## Zakres

- `/jobs/[id]` → sekcja/zakładka „Profil Championa”: edytor **6 sekcji** (1. Podstawowe
  informacje · 2. Co wpisać (search) · 3. Stack technologiczny · 4. O projekcie ·
  5. Pytania screeningowe · 6. O kliencie), import z Worda (`ChampionIntake`), uzgodnienie
  profilu z polami rekrutacji, walidacja (doradcza — `CHAMPION_INTAKE_GATE_ENABLED=false`).
- `/share/champion-card/[token]` — publiczna karta (patrz M12; tutaj tylko tworzenie linku jest zakazane).
- Wzór Word: link do SharePointu w Pomocy.

## NIE KLIKAJ

„Zapisz profil” na PRAWDZIWEJ rekrutacji, „Utwórz link do karty”, „Zaakceptuj szkic AI”,
„Wyślij do DL” (handoff), „Przekaż do searchu” (to P1).

## Scenariusze

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | recruiter | `/jobs/{{D3}}` → Champion | 6 sekcji o nazwach jak w Zakresie; kolejność 1→6; brak sekcji „Standardy klienta”/„Dokumenty” (przeniesione do karty klienta) | P1 |
| S02 | recruiter | sekcja 1: pola | „Lokalizacja biura” (nie „kandydata”); „Język pracy” edytowalny; „Język CV” **tylko do odczytu** z podpisem, że pochodzi z reguły CV klienta (D12: PL) | P1 |
| S03 | recruiter | sekcja 3: stack | must `Python, PostgreSQL, Docker`, nice `Kubernetes` — zgodne z `Job.must_skills`/`nice_skills` (sprawdź w API) | P1 |
| S04 | recruiter | sekcja 1: stawka | „Maksymalna stawka PLN/h” = 160 (z „do 160 zł/h netto” w DOCX); notatka doradcza o zakresie, jeśli był zakres | P1 |
| S05 | recruiter | sekcja 5: pytania screeningowe | lista pytań z DOCX; ta sama lista w docku kandydata → „Screening” (M03 S13) | P2 |
| S06 | recruiter | sekcja 6: O kliencie | treść zależna od roli (co przekona kandydata, insight, historyczne pytania); wariant compact karty klienta D11 (SLA 5 dni…) + link „Pełna karta klienta →” do `/help?tab=clients&client={{D1}}` | P2 |
| S07 | recruiter | „Uzgodnij profil i pola rekrutacji” (podgląd okna, **bez zapisu**) | okno pokazuje różnice profil ↔ kolumny rekrutacji; stawka NIE jest oznaczona jako do zmiany, gdy liczba jest równa | P1 |
| S08 | recruiter | walidacja profilu (panel ostrzeżeń) | brak błędów blokujących; ostrzeżenia (jeśli są) po polsku; **żadne** „Profil Championa wymaga poprawy przed użyciem” (bramka OFF) | P1 |
| S09 | recruiter | import DOCX: wgraj `champion-D3.docx` w oknie importu (podgląd wyniku, **Anuluj** na końcu) | podgląd parsera: 6 sekcji rozpoznane po NAZWACH nagłówków; stawka 160; stack z tabeli; brak 422 „nie można odczytać pliku” | P1 |
| S10 | recruiter | import DOCX starego wzoru (7 sekcji, nagłówek „Pytania od Delivery Leada”) — jeśli fixtures ma taki plik | rozpoznany; stare nagłówki zmapowane; brak utraty sekcji | P2 |
| S11 | recruiter | import pliku > 14 000 znaków w sekcji tekstowej | preflight: prawdziwy powód odmowy (limit znaków), nie „nie można odczytać pliku DOCX” | P2 |
| S12 | recruiter | awaria podglądu AI (symuluj: wgraj poprawny DOCX przy wyczerpanej kwocie — tylko jeśli kwota faktycznie wyczerpana; inaczej SKIP) | plik przypięty PRZED podglądem; notka informacyjna (`championPreviewNotice`), nie błąd blokujący; generacja CV nadal możliwa | P1 |
| S13 | delivery_lead | S01–S06 | identyczny odczyt; przycisk „Zapisz” widoczny (zapis → 403 w podglądzie) | P2 |
| S14 | recruiter | prawdziwa rekrutacja ze STARYM profilem (sprzed 09.2026; wybierz z listy, zapisz tylko ID) | migracja leniwa: 6 sekcji wypełnione ze starych kluczy; „about/responsibilities/selling_points” w sekcji 4/6; brak pustego ekranu | P1 |
| S15 | recruiter | prawdziwa rekrutacja z profilem z importu 08.2026 (stawka tekstowa „140 zł netto/h”) | stawka liczbowa 140 widoczna; **nie zapisuj** | P1 |
| S16 | admin | Pomoc → materiały → link do wzoru Word | link do SharePointu (jeden wzór ogólny); 14 wzorów per klient NIE są opublikowane | P3 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const cp = await fetch('https://api.nexus.dynaminds.pl/api/jobs/{{D3}}/champion-profile',{headers:h}).then(r=>r.json());
console.log(Object.keys(cp));                       // 7 kluczy JSONB (basics, sourcing, stack, project, screening, client, documents lub podobne)
console.log(cp.stack?.must, cp.basics?.rate_value); // ['Python','PostgreSQL','Docker'], 160
const j = await fetch('https://api.nexus.dynaminds.pl/api/jobs/{{D3}}',{headers:h}).then(r=>r.json());
console.log(j.must_skills, j.rate_budget_hourly);   // zsynchronizowane ze stackiem i stawką
```

## Znane pułapki

- Klucze JSONB są historyczne (`candidate_location_pref` = lokalizacja BIURA) — etykieta w UI
  jest źródłem prawdy, nie nazwa klucza.
- `embedding_parts` dla starego profilu celowo węższe — nie zgłaszaj, że „radar nie widzi
  pytań screeningowych” starych profili.
- Parser rozpoznaje sekcje po NAZWIE nagłówka; przenumerowanie jest OK, przemianowanie nie.

## Do raportu

Zrzut 6 sekcji D3, wynik podglądu importu (S09) jako JSON, porównanie S03 (UI vs API).
