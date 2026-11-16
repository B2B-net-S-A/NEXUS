# Aneks z własną nazwą („Aneks — inna zmiana”) w Generatorze aneksów
<!-- indeks: typ annex_custom, lista zmian w paragrafach, gotowa klauzula zwolnienia z zakazu konkurencji, bez skutku w polach kontraktu, wpis custom_change -->

Zgłoszenie Finansów z 16.11.2026: aneks o zdjęciu zakazu konkurencji nie
pasował do żadnego z pięciu typów. Artur wybrał wariant C z makiet na
stagingu (lista zmian + gotowe klauzule). Migracja 0721 (CHECK typów
dokumentu i wartość `custom_change` w `contractamendmenttype`).

- **Typ `annex_custom`** (`registry.py`) — rodzina `annex`, `allows_external`,
  więc działa jak pozostałe aneksy generatora: umowa z rejestru, umowa spoza
  Nexusa, „Bez kontraktu” (czeka na powiązanie przed podpisem). Człowiek
  pisze tylko nazwę (`annex_title`, do tytułu „w sprawie: …”, rejestru
  aneksów i nazwy pliku) i § 1. Komparycja, § 2 i podpisy są te same co
  w pozostałych aneksach (`scripts/build_b2b_annex_templates.py`, klucz
  `annex_custom_pl`; builder przyjmuje klucze w argumentach, żeby nowy wzór
  nie przepisywał bajtów pozostałych DOCX).
- **Lista zmian (`annex_changes`)**: wiersz = `op` (`replace` „otrzymuje
  brzmienie”, `add` „dodaje się ust.”, `delete` „skreśla się”, `free` własny
  punkt), `paragraph`, `section`, `text`. Formułki składa serwer
  (`context.annex_change_points`), nie człowiek — żeby każdy aneks mówił tak
  samo. Front pokazuje formułkę pod wierszem (`lib/annex-changes.ts`, lustro
  zdań odmowy z `registry.annex_changes_problems`).
- **Gotowe klauzule** to dane typu (`DocumentType.clauses`, idą w
  `GET /document-types`), nie kod formularza. Placeholdery `{klucz}`
  podstawia front z prefillu (`ref_defaults`, klient umowy); brak danych
  zostaje jako `[uzupełnij]` i blokuje aneks po obu stronach. Klauzula
  dopisuje wiersze (puste ustępują, wpisane zostają) i nazwę aneksu tylko
  wtedy, gdy pole jest puste.
- **Zwolnienie z zakazu konkurencji** używa zdania z porozumienia
  o rozwiązaniu umowy (`termination_agreement_pl`) z paragrafem z wersji
  wzoru (`contract_versions.non_compete_paragraph`), nie z nowego tekstu
  prawnego. Nowa klauzula = nowa treść prawna: przed dodaniem akceptuje ją
  Artur.
- **Podpis nie zmienia pól kontraktu.** NEXUS nie wie, co znaczy dowolna
  treść, więc skutkiem jest wyłącznie wpis `custom_change` w zakładce
  „Aneksy” (`new_values.annex_title`, skan po podpisie). Okno podpisu mówi
  wprost, że stawkę albo daty z takiego aneksu trzeba poprawić w kontrakcie
  ręcznie. Nie dokładaj tu zgadywania skutków z treści — do zmian, które
  NEXUS ma przełożyć na kontrakt, służą typy dedykowane.
- Testy: `test_b2b_annex_custom.py`, `test_b2b_document_templates.py`
  (render obu wariantów Partnera), `annex-changes.test.ts`,
  `AnnexChangesField.test.tsx`.
