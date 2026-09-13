# M10 — Insights, Cortex, dashboardy, DynaReporter

| Pole | Wartość |
|---|---|
| Tryb | **R** |
| Persony | recruiter, delivery_lead, head_of_recruitment, finance, sourcer (podgląd); admin |
| Zależności | Fala 0; decyzja o DynaReporterze (README → decyzje) |
| Czas | ~2,5 h (+1 h jeśli DR w zakresie) |
| Głębokość | przegląd + pełna dla spójności liczb (karta B) |
| Akcje AI | Cortex — odczyt gotowych wniosków; **nie uruchamiaj „Odśwież analizę”** |

## Zakres

- `/insights` — 3 zakładki: **Rekrutacja** (`?tab=rekrutacja`: Podsumowanie · Lejek · Zespół ·
  Liga i wyścigi · Trendy roczne · Placementy · Power Calling · LinkedIn · Ścieżka rozwoju · Źródła),
  **Delivery Lead** (`?tab=delivery-lead`: Ranking DL · Placementy wg klientów · Hit ratio per klient · Hiring managerowie),
  **Rada Nadzorcza** (`?tab=rada`: KPI i finanse · Rok do roku · Klienci (MRR)).
  Aliasy: `?tab=klienci` → delivery-lead, `?tab=zarzad` → rada. Pasek okresu (Tydzień/Miesiąc/Kwartał/Rok/Wszystko + offset).
- `/cortex` — Cortex (wnioski, kuratela admin-only).
- Dashboardy ról — M00 S12–S15.
- `/dynareporter/*` (jeśli w zakresie): rekrutacja, delivery-lead-dashboard, board-dashboard, admin-dashboard, mindy, profile, admin/upload.

## NIE KLIKAJ

„Nadaj plakietkę”/„Wygaś plakietkę”, CRUD kampanii, „Zamroź ranking” (`POST /freeze`), Cortex „Odśwież”/kuratela,
DynaReporter → upload, admin, MINDY (płatne).

## Scenariusze — Insights

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | recruiter | `/insights` | ląduje na Rekrutacji; domyślny okres = POPRZEDNI pełny miesiąc (`offset=-1`) | P1 |
| S02 | recruiter | `?tab=klienci`, `?tab=zarzad` (stare) | przekierowane na Delivery Lead / Rada (aliasy), nie na Rekrutację | P1 |
| S03 | recruiter | Delivery Lead: domyślny okres | ROK (nie miesiąc) | P2 |
| S04 | recruiter | Rada: domyślny okres | KWARTAŁ | P2 |
| S05 | recruiter | pasek sekcji (spis treści) w każdej zakładce | klik → scroll do sekcji; nagłówek NIE chowa się pod paskiem aplikacji (`scroll-mt`); każda sekcja z tablicy istnieje na stronie | P2 |
| S06 | recruiter | Rekrutacja → Lejek | etapy z dwiema flagami (`in_milestones`, `mapped_from_traffit`); konwersja > 100 % NIE jest przycinana; zero mianownika = „—” (nie `0,0 %`) | P1 |
| S07 | recruiter | Rekrutacja → Liga i wyścigi | Hall of Fame (D2: pierwsze `hired` per para); byli pracownicy z chipem, nie ukryci; `scope` (ile w rankingu / poza) | P1 |
| S08 | recruiter | Rekrutacja → Placementy → porównaj liczby z Hall of Fame | te same liczby dla tych samych osób i okresu (kod definicji `first_hired_per_candidate_job`) | P1 |
| S09 | recruiter | Rekrutacja → Power Calling · LinkedIn | gdy brak danych o dniach roboczych z Compass → `not_assessable` („nie da się ocenić”), NIE lista „poniżej progu” | P1 |
| S10 | recruiter | Rekrutacja → Ścieżka rozwoju | poziomy z progami (LUB), zegar eksperta od awansu na seniora; poziom nie spada | P2 |
| S11 | recruiter | baner kampanii | brak kampanii → NIC (nie ramka „0/0”); aktywna → postęp i dni do końca | P2 |
| S12 | recruiter | Rada → Rok do roku | 12 miesięcy × 3 lata; przyszłe miesiące `—`; bieżący oznaczony „(trwa)” bez delty; wiersz Suma: `sum` dla przepływów, `avg` dla wskaźników (procenty NIE sumują się do 874 %) | P1 |
| S13 | recruiter | Rada → Rok do roku → ostrzeżenie przy grupach `basis: contracts` | WIDOCZNE („ewidencja kontraktów młodsza niż firma”); brak ostrzeżenia przy grupach `pipeline` | P1 |
| S14 | recruiter | Rada → Klienci (MRR) | ranking; suma MRR = suma wierszy; MRR klienta D1 (po P2/P3) zgodny z profilem klienta (karta B) | P1 |
| S15 | recruiter | zmiana okresu → wszystkie sekcje | liczby zmieniają się; brak 500; spinner < 10 s | P2 |
| S16 | recruiter | eksport CSV zakładki | plik; Rok do roku NIE w eksporcie (inny zakres) | P3 |
| S17 | recruiter | awaria (symuluj offline w DevTools → odśwież sekcję) | stan błędu z „Ponów”, NIE pusty stan | P1 |
| S18 | sourcer / finance / head_of_recruitment | `/insights` wszystkie 3 zakładki | dostęp dla KAŻDEJ roli (D7); te same liczby | P1 |
| S19 | admin | plakietki (`user_performance_flags`) — kontrolka | widoczna adminowi TAKŻE przy zerze plakietek; **nie klikaj** | P2 |

## Scenariusze — Cortex

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S20 | recruiter | `/cortex` | wnioski/insighty; data ostatniej analizy; brak 500 | P2 |
| S21 | admin | kuratela (akceptuj/odrzuć) — widoczność | widoczna adminowi; finance → brak (kuratela admin-only) | P1 |
| S22 | recruiter | `/cortex` w roli `user` (jeśli istnieje) | odmowa (CORTEX_ROLES bez `user`) | P3 |

## Scenariusze — DynaReporter (tylko jeśli w zakresie)

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S30 | recruiter | `/dynareporter/rekrutacja`, `/dynareporter/delivery-lead-dashboard` | ładują się; dane zamrożone na tygodniu 21/2026 — UI to komunikuje? zapisz | P2 |
| S31 | delivery_lead / head_of_recruitment | `/dynareporter/board-dashboard` | dostępne; recruiter → odmowa | P2 |
| S32 | admin | `/dynareporter/admin-dashboard` | dokładnie 10 kart modułów (regresja); `/dynareporter/admin` przekierowuje | P2 |
| S33 | recruiter | `/dynareporter/liga` | 404 aplikacji (slug niespójny — znany) | P3 |
| S34 | finance | `/dynareporter/admin-dashboard` → sekcja `admin` | wyłączona dla finance | P1 |
| S35 | recruiter | `/dynareporter/mindy` | widoczne; **nie zadawaj pytań** (płatne, wymaga `allowed_sections`) | P3 |

## Kontrole API

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const yoy = await fetch('https://api.nexus.dynaminds.pl/api/insights/board/yoy?end_year=2026&years=3',{headers:h}).then(r=>r.json());
console.log(Object.keys(yoy), yoy.coverage?.contracts_by_year);
console.table(yoy.metrics?.map(m=>({key:m.key, aggregate:m.aggregate, lower_is_better:m.lower_is_better, basis:m.basis})));
const hof = await fetch('https://api.nexus.dynaminds.pl/api/competitions/hall-of-fame',{headers:h}).then(r=>r.json());
console.log('HoF scope:', hof.scope, 'definition:', hof.definition_code); // first_hired_per_candidate_job
```

## Znane pułapki

- Rok do roku patrzy na pełne lata kalendarzowe — brak paska okresu w tej sekcji jest zamierzony.
- Rezygnacje = podzbiór zejść; `poached_by_client` poza — nie zgłaszaj „liczby się nie sumują”.
- Hall of Fame liczy INACZEJ niż wyścigi płacące nagrody (verifier-anchored) — różnica między
  „Liga” (wyścig miesiąca) a Hall of Fame jest zamierzona.

## Do raportu

Zrzuty 3 zakładek; tabela S08 (HoF vs Placementy) i S14 (MRR Rada vs profil klienta); wynik S09.
