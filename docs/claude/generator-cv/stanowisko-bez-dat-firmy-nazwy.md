# Stanowisko bez dat, bez firmy albo bez nazwy (25.11.2026)

<!-- indeks: `role_title`, `dates`, `role_employer`, `dz._kept`, pusta linia stanowiska, `position` puste -->

Pętla jakości „Nowego CV” z 25.11.2026 znalazła w `render_payload` role
z pustym `dates`, `company` albo `position`. W Nowym CV taka rola nie trafia na
oś kariery, w Wordzie ma puste pole. Artur zdecydował (AskUserQuestion 25.11):
zbadać przyczynę i poprawić, a w QC dopiąć istniejące uwagi zamiast dokładać
drugą o tym samym; żadna z nich nie blokuje wysyłki.

## Pomiar (kopia produkcji `nexus_staging_nightly_20261125`, tylko odczyt)

1843 CV z generatora z 60 dni, 10 820 ról. Oryginał dopasowany do CV po
`editorial_provenance.cv_sha256` (136 z 139 CV z brakami; 3 bez pliku).

| brak pola | ról / CV | oryginał też nie podaje | rola spoza tekstu CV¹ | plik to nie CV² | zgubione przez generator |
|---|---|---|---|---|---|
| `dates` | 192 / 67 | 171 | 7 | 5 | **0** |
| `company` | 97 / 60 | 81 | 10 | 0 | **6 (1 CV)** |
| `position` | 57 / 25 | 48 | 9 | 0 | 0 |

¹ z notatek albo nazwa przetłumaczona; ² umowa przedwstępna, NDA wgrane jako CV.
W `dates` dodatkowo 9 ról z 3 CV bez pliku oryginału. „Oryginał też nie podaje” to: sama długość
(„Allianz | B2B Contract | 3 years”), rola w podsumowaniu („Earlier career
2001–2016”, „Wcześniej: …, 2018”), urlop, przerwa, korepetycje, własna
działalność, CV bez nazw firm („Senior Project Manager | 09.2023 – current”).
Każdą z 26 ról, przy których w pobliżu stała data, przejrzano ręcznie: to daty
studiów, narracja („Since 2012…”) albo okres innej roli.

Jedyny ubytek: CV z 20.10 (prompt 9, model sprzed GPT-6.1 Sol) zgubił firmę
w 6 rolach z linii „Firma – Stanowisko”. Obecny generator (prompt 14,
`gpt-6.1-sol` z rejestru) na tym samym oryginale zachował wszystkie 6 firm
w 3 z 3 przebiegów, więc promptu i `legacy_v7` nie zmieniamy. Kod nie czyści
`company` ani `dates` (`_normalize_candidate_data` tylko przycina).

## QC (`cv_qc.py`)

Na 1040 szkicach CV etapu (stan po edycji): 104 role bez dat w 44 CV
(`dates` oznaczało 94), 39 bez firmy w 32 CV (`role_employer` 13, reszta to
urlopy i praca na swoim — celowo bez uwagi), 15 ról bez nazwy w 6 CV i 8 pustych
linii stanowiska w 6 CV (żadna uwaga ich nie widziała).

- **Pusta linia stanowiska to stanowisko** (`dz_review._kept`): parser bloków
  zostawia pusty akapit `data-cv-section="role"` (inne puste akapity dalej
  znikają). Do 25.11 ginął: firma i obowiązki wchodziły do poprzedniej roli,
  `dates` jej nie liczyło, a `role_index` dalszych ról wskazywał w edytorze
  sąsiednie stanowisko, bo `cvOutline` liczy pusty akapit jako rolę.
  `_EditableParser` (poprawki `qc/transform`) używa tego samego warunku, więc
  indeksy bloków są wspólne.
- **`role_title` „Każde stanowisko ma nazwę”** (uwaga, po `role_employer`):
  nazwa to pogrubiona część linii stanowiska, a bez pogrubienia cała linia, po
  zdjęciu dat i „obecnie / currently”. Same daty (także pogrubione) = brak
  nazwy. Pozycja: „Stanowisko w {firma} ({daty}) nie ma nazwy.” albo „…nie ma
  nazwy ani dat.” z `role_index` (przycisk „Pokaż w CV” wskazuje linię
  stanowiska). CV bez znaczników stanowisk → „nie dotyczy”.
- `dates` i `role_employer` bez zmian w regułach; po poprawce parsera widzą
  też stanowisko z pustą linią. `QC_VERSION` bez zmian (nowa uwaga nie blokuje).

Harness: `/preview/cv-editor?state=lata` (rola „2012 – 2013” w Hurtowni
Przykładowej). Testy: `test_cv_qc.py` (pusta linia, `role_title`, zgodność
`EditableCv`), `CvEditorIssues.test.tsx` („stanowisko bez nazwy”).
