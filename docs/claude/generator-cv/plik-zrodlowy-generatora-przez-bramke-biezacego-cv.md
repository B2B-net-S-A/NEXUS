# Plik źródłowy generatora i automatu CV przez bramkę bieżącego CV

Decyzja Artura z 25.11.2026 („filtr wszędzie”).

Lista plików generatora (`list_candidate_cv_sources`, trasa
`/api/cv-generator/candidates/{id}/cv-sources`, API integracji) i plik wskazany
jawnie (`load_candidate_generation_source` z `cv_document_id`) idą przez
`chosen_cv_filters_for` z `app/services/cv_source.py`. Z listy znika plik:

- nieaktualny (`outdated_at`),
- z kwarantanny tożsamości (CV innej osoby bez zwolnienia przez admina/HoR)
  i każda jego kopia z tymi samymi bajtami.

Rodzaju pliku ta bramka nie sprawdza: certyfikat i list motywacyjny zostają na
liście i można je wskazać, bo wybór jest świadomy, a pliki bywają źle
sklasyfikowane (runda 9 audytu, R9-N7-11). Wybór domyślny bez wskazania
(`current_cv_filters_for`) dalej je pomija.

Jawny wybór takiego pliku kończy się błędem „Wybrane CV nie jest dostępne”,
nigdy cichym wzięciem innego pliku. Rekruter nie wybiera świadomie pliku
nieaktualnego: oznaczenie „nieaktualny” zdejmuje się w profilu kandydata.

Dlaczego: automat CV (`cv_auto_generate.py`) bierze pierwszy plik listy, a front
zaznacza go domyślnie i wysyła jako jawne id. Kwarantanna zdejmuje z pliku tylko
`is_primary`, więc najnowszy plik innej osoby wygrywał w `current_cv_ordering`.
Pomiar na kopii produkcji 25.11.2026: na 1014 z 1851 CV z 60 dni, które da się
dopasować po skrócie pliku (`editorial_provenance.cv_sha256`), 3 ręczne powstały
z pliku w kwarantannie, 0 z nieaktualnego. U 136 osób pierwszy plik listy był
w kwarantannie; 42 z nich nie mają innego pliku, więc automat pomija je teraz
z powodem `no_cv_document`. Plików nieaktualnych było 11 u 9 osób.

Nowa ścieżka, która wybiera plik CV jednej osoby, bierze `current_cv_filters_for`
(wybór domyślny) albo `chosen_cv_filters_for` (lista do wyboru), a nie sam
`_supported_cv_doc_filter` (ten pilnuje tylko rozszerzenia PDF/DOCX i usunięcia
z profilu).
