# Pogrubianie wymagań przez słownik umiejętności (G2, 07.11.2026)
<!-- indeks: narzędzia, standardy i AI z must/nice się pogrubiają; inny zapis ze słownika; nazwy w wymaganiu-zdaniu; „Kafka Streams”; „Pogrub wymagania” = generator -->

Decyzja Artura z 07.11.2026: wdrożyć rekomendacje pomiaru „co rekruterzy
zmieniają w CV z generatora” (raport: https://claude.ai/artifact/5Qd2t5rbuM6kpv12txwruc).
Ten plik dotyczy G2: generator nie pogrubiał części wymagań, które rekruter
potem pogrubiał ręcznie.

## Co pokazał pomiar (staging, kopia produkcji z 06.11)

- Punkt startowy edytora odtworzony co do bajtu (skrót HTML) w 326 CV
  zatwierdzonych od 12.10. Odtwarzanie trzeba robić **z wczytanym słownikiem
  i bez niego** — część CV powstała przy innym stanie słownika. Pomiar bez
  słownika dawał „Selenium 120, Playwright 84, JUnit 59, PySpark 34”, a to
  były technologie, które generator pogrubia; artefakt pomiaru, nie błąd.
- Rekruter dopisał pogrubienia na niezmienionym tekście w 120 z 326 CV.
  Pogrubień generatora prawie nie zdejmuje (17 z 7 199).
- Przy wymaganiach must/nice było 192 ręcznych pogrubień w 51 CV. Reszta
  (ok. 1 050 w 111 CV) to rzeczy spoza wymagań: słownictwo AML przy must
  „AML” (KYC, CDD, EDD, PEP), własny stos kandydata (JUnit, Mockito, Terraform),
  początki punktów podsumowania (to sesja G1) i całe zdania. Generator ich nie
  pogrubia i nie powinien — pogrubia wymagania klienta.

## Reguła

- **Pogrubia się technologia, narzędzie, standard i AI ze słownika**
  (`GATE_TECH_CATEGORIES`, te same kategorie co bramka krytycznych):
  `docx_renderer._is_technology` / `_is_tech_word`. Do 07.11 tylko
  `TECH_CATEGORIES`, więc „Pega”, „Bamboo”, „Appium”, „VMware” z must/nice
  zostawały bez pogrubienia. Metodyka, praktyka, dziedzina i rola dalej się nie
  pogrubiają (audyt 13.07.2026).
- **Inny zapis tej samej rzeczy** (`skill_normalize.bold_alias_forms`):
  technologia z wszystkimi wariantami jak dotąd, narzędzie/standard/AI
  z wariantami liczącymi się w tekście (`TEXT_ALIASES`) — „SailPoint IIQ”
  pogrubia „SailPoint IdentityIQ”.
- **Nazwa ze słownika w wymaganiu-zdaniu** (`_dictionary_tech_grams`):
  „Doświadczenie w testowaniu z wykorzystaniem Espresso, JUnit oraz MockK”
  pogrubia „JUnit”, nie słowa zdania. Tylko zapis z wielką literą
  i tylko hasło albo wariant liczący się w tekście
  (`skill_normalize.is_bold_technology_mention`). „Access”, „Project”,
  „Word”, „Teams”, „Office”, „Apache”, „Outlook”, „Visio” w zdaniu się nie
  liczą (`_AMBIGUOUS_MENTIONS`): w pierwszej wersji „access” z „Access
  Management” pogrubiło się 42 razy.
- **Nazwa produktu za technologią** (`_tech_product_name`): „Kafka Streams”,
  „Kafka Connect” pogrubiają się w całości. Słowo roli albo stopnia
  („Developer”, „Senior”) i słowo ze słownika spoza technologii („Scrum”) to
  nie nazwa produktu. Sama marka z takiej nazwy się nie pogrubia („Apache”
  z „Apache Iceberg”).
- **„A / B” ze spacjami to dwie nazwy**, gdy obie mają co najmniej 4 znaki
  („Cloud Composer / Apache Airflow”); „CI / CD” zostaje jedną.
- **„Pogrub wymagania” w edytorze liczy tak jak generator**: `cv_qc.bold_all`
  i `_has_unbolded` biorą `cv_qc._bold_patterns` (czyli
  `compile_keyword_patterns`) i scalanie zakresów `highlight_spans`. Wcześniej
  poprawka brała nazwę każdego wymagania i pogrubiała też „Scrum”
  i „bankowość”, których licznik QC nie liczył. „Usuń termin” zostaje przy
  `dz._tech_patterns`.

## Wynik na tych samych 326 CV

- Generator robi sam 64 z 192 ręcznych pogrubień przy wymaganiach (13 CV):
  Apache Airflow 10, Kafka Streams/Connect 17, Kotlin 8, Android 7,
  SailPoint IdentityIQ 6, Appium 3, VMware, Bamboo, Pega.
- Nowych pogrubień, których rekruter w tym miejscu nie dopisał: 53 w 21 CV —
  wszystkie to narzędzia i AI z must/nice (Excel, LLM, Robot Framework, Jira,
  Pega). QC pokaże je w edytorze jako „pogrubione nie wszędzie” w CV
  wygenerowanych przed zmianą; poprawka jest jednym kliknięciem.
- Zostaje bez pogrubienia: nazwy spoza słownika (Cisco, Talend, Informatica,
  Arista, Cloud Composer, Espresso, Google Play) — trafią do słownika przez
  nocne propozycje albo „Słownik umiejętności”; świadomie bez pogrubienia —
  metodyki i pojęcia (Agile, governance, user stories, UX).

Testy: `tests/test_cv_bold_requirements_dictionary.py`.
