# Mapa wiedzy IT: powiązania haseł słownika (0660, 07.11.2026)
<!-- indeks: wynika z / część spełniają wymaganie wszędzie; zamiennik i typowe dają pytanie; nocny bieg zatwierdza sam; generator nie dopisuje -->

Decyzje Artura z 07.11.2026 (artefakt „Mapa wiedzy IT”). Słownik znał nazwy, ale
nie związki: „Java” u osoby z samym Spring Boot była brakiem, a QC blokowało CV
z GitHubem przy wymaganiu „Git”. Wyszukiwarka i przegląd DL uznawały „SQL” przy
PostgreSQL (`IMPLIED_BY`), a QC tę samą osobę blokowało.

## Cztery rodzaje (`skill_relations`)

- **„wynika z”** (`implies`, Spring Boot ⇒ Java) i **„część”** (`part_of`,
  GitHub ⇒ Git): spełniają wymaganie w całości wszędzie. Działają przez
  `skill_normalize.implied_forms`: wyszukiwanie, bramka krytycznych, punktacja,
  przegląd DL, QC (`dz_review._patterns`) i strażnik generatora
  (`_loosely_present(dictionary=True)`). Kierunek jest jeden: Java nie daje
  Spring Boot.
- **„zamiennik”** (`alternative`, Flask ~ FastAPI): nie spełnia wymagania.
  Krytycznego brakuje, ale osoba z zamiennikiem nie znika z wyników
  (`dealbreaker_filters._kept_by_alternatives`). Karta pokazuje „fastapi? zna
  flask”, a QC podaje gotowe pytanie.
- **„typowe”** (`typical`, Java → Maven): nie spełnia wymagania; QC i ściąga
  podpowiadają pytanie do rozmowy.

## Skąd się biorą i kto zatwierdza

- Nocny bieg (`tasks/skill_proposals.py`, po propozycjach haseł) liczy pary
  z umiejętności profili (≥ 300 profili, ≥ 50% wpisuje oba), podpowiedzi
  słowniczka „po ludzku” (`cv_hints`) i zamienniki per kategoria. Rodzaj
  ocenia model F45 (`skill_dictionary_proposals`).
- **Zatwierdza nocny bieg, bez człowieka.** Decyzja Artura z 07.11.2026:
  „wszystko zatwierdź sam, nie pytaj”. Tak samo zatwierdzane są „pewne”
  propozycje haseł. HoR+ widzi powiązania w zakładce „Powiązania” i może
  je wycofać; wycofane nie wracają w nocy.
- **Bezpieczniki zamiast przeglądu** (`skill_relations.apply_guards`):
  - role nie mają powiązań;
  - „wynika z” i „część” potrzebują drugiego świadka: ≥ 90% profili albo słowniczka; inaczej para spada do „typowe”;
  - para wymyślona przez samego model nigdy nie jest twarda;
  - „typowe” musi potwierdzić co najmniej połowa profili;
  - dwa zapisy tego samego hasła odpadają.
- Prompt odrzuca:
  - narzędzie AI → umiejętność budowania (ChatGPT → LLM);
  - usługę → całą platformę (Azure DevOps → Azure, Power Query → Power BI);
  - dystrybucję → system i protokół → format (Ubuntu → Linux, SOAP → XML) jako twarde. Pomiar pokazał, że te dwie pary obniżały ranking.

## Generator i QC

- Generator **nie dopisuje** technologii, która wynika z innej, tylko jej nie
  usuwa (decyzja Artura). „Typowe” i zamiennik trafiają do CV dopiero po
  potwierdzeniu w rozmowie, a wtedy źródłem jest odpowiedź kandydata.
- `QC_VERSION = "qc-truth-6"`, `MUST_GATE_POLICY_VERSION = "critical-v13"`.
- Pamięć wzorców dowodu z tekstu (`must_text_evidence._patterns`) czyści się przy
  każdym przeładowaniu słownika; wcześniej nowe aliasy działały w tekście
  dopiero po restarcie.

## Pomiar (staging, 60 rekrutacji, `eval_matching`, 07.11.2026)

| Scorer | P@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|
| Legacy, bez powiązań | 0,117 | 0,093 | 0,278 | 0,110 |
| Legacy, z powiązaniami (bez SOAP ⇒ XML i Ubuntu ⇒ Linux) | 0,123 | 0,102 | 0,292 | 0,112 |
| Canonical, bez powiązań | 0,110 | 0,083 | 0,235 | 0,089 |
| Canonical, z powiązaniami (bez SOAP ⇒ XML i Ubuntu ⇒ Linux) | 0,113 | 0,084 | 0,244 | 0,089 |

Sprawdzone i odrzucone: połowa punktów za trafienie tylko przez powiązanie
obniżała MRR (0,278 → 0,272). Dlatego powiązanie liczy się w punktacji w całości.
