# Archiwum eBI24: przyrost przed wyłączeniem i kopia na dysku firmy (18.11.2026)

Archiwum eBI24 weszło do NEXUSA 16.11.2026: 49 728 dokumentów, eksport z 16.11
(zasady E5: `docs/claude/zamowienia/archiwum-ebi24-w-finansach.md`). eBI24 działa
dalej aż do wyłączenia, więc dokumenty, które trafią do jego archiwum po 16.11,
trzeba dociągnąć osobno. Rozliczenia (18.11) chcą też mieć dane na dyskach firmy,
nie tylko w NEXUSIE. Artur wybrał 18.11 „przenieść dane na nasze dyski”.

## Decyzje Artura z 18.11.2026

- **Kopia** leży w OneDrive firmowym Artura, w folderze `Archiwum eBI24`. Folder jest
  prywatny, a Finansom Artur udostępnia go sam. Zawiera foldery po latach
  z oryginałami, `manifest.csv` (spis dla Excela), `SHA256SUMS` i `CZYTAJ.txt`.
  Do biblioteki B2B_ALL kopii nie wrzucamy, bo widzą ją wszyscy.
- **Termin wyłączenia eBI24** nie jest jeszcze znany. Przyrost robimy tuż przed
  wyłączeniem, na polecenie Artura w czacie („dociągnij przyrost eBI24”). Nie
  planujemy go z góry ani nie odpalamy w rutynie.

## Dlaczego przyrost liczymy po id, a nie po dacie

eBI24 przenosi dokument do archiwum z obiegu, a obieg miał 13.11 ok. 1 600
dokumentów, także starszych. Dokument z wcześniejszym `_bucketNumber`
i `documentDate` może więc pojawić się w archiwum po 16.11. Filtr „nowsze niż
06.11” albo „bucket > ostatni” by go zgubił. Dlatego bierzemy pełną listę
metadanych (50 żądań po 1 000 wierszy) i porównujemy ją z `source_id` z bazy.

Import pomija id, które już są w NEXUSIE (`archive.import_package`), więc
**zmiany metadanych starych dokumentów po 16.11 (np. `paid`) nie wchodzą**.
Archiwum to stan z dnia eksportu. Zapłaty NEXUS bierze z wyciągów.

## Procedura przyrostu (bieg tuż przed wyłączeniem, za zgodą Artura)

Okno: pn–pt 18:00–08:00 albo weekend (import pisze na produkcję). Podręcznik
eBI24 dopuszcza duże pobrania w godzinach 20:00–7:00.

1. **Obieg eBI24.** Dokumenty, które Finanse chcą zachować, a które nadal są
   w obiegu, Finanse przenoszą w eBI24 do archiwum przed eksportem. Eksport
   czyta tylko `archive/index`.
2. **Lista id w NEXUSIE** (laptop, tylko odczyt):
   ```bash
   echo "SELECT source_id FROM finance_archive_documents WHERE source='ebi24' ORDER BY 1" \
     | ~/.claude/nexus-rutyny/bin/prod_readonly.py sql --csv > <scratchpad>/w-nexusie.txt
   ```
3. **Narzędzia** leżą obok eksportu, poza repo: `~/NEXUS-ebi24-export/narzedzia/`
   (`odbiornik.py`, `1-metadane.js`, `2-dokumenty.js`, `kopia_onedrive.py`).
   Odbiornik słucha tylko na `127.0.0.1:8799`, przyjmuje POST wyłącznie
   z `https://ebi24.pl` i zapisuje do `~/NEXUS-ebi24-export/<ścieżka>`. Uruchom go
   w tle (`python3 -I odbiornik.py`). Chrome przy pierwszym żądaniu pyta o dostęp
   eBI24 do sieci lokalnej, zgodę daje Artur.
4. **Metadane** w karcie eBI24 (konto Finansów w Chrome, tylko odczyt).
   Zapis idzie do osobnego katalogu `przyrost-RRRRMMDD/`, żeby paczki nie
   objęły eksportu z 16.11. Skrypt `1-metadane.js` to pętla z 16.11, różni się tylko katalogiem:
   `POST /system/archive/index?isc_dataFormat=json`,
   `{"dataSource":"ArchiveDataSource","operationType":"fetch","operationId":"read",
   "startRow":s,"endRow":s+1000,"sortBy":["-_bucketNumber"],"textMatchStyle":"exact",
   "componentId":"ArchiveLayout_ListGrid","data":{"operator":"and","_constructor":"AdvancedCriteria","criteria":[]}}`.
   Każdą stronę zapisz jako `przyrost-RRRRMMDD/archiwum/metadane-<s:06d>.json`.
   Bez `operationId:"read"` lista zwraca błąd, a `totalRows` rośnie stopniowo,
   więc kończ na stronie krótszej niż 1 000.
5. **Nowe id** (z `backend/`):
   ```bash
   python -m scripts.pack_ebi24_archive --src ~/NEXUS-ebi24-export/przyrost-RRRRMMDD \
     --known <scratchpad>/w-nexusie.txt --print-new-ids > <scratchpad>/nowe-id.json
   ```
   Sprawdź, czy liczba jest rozsądna (ok. 1 100 miesięcznie). `[]` = nic do dociągnięcia.
6. **Treść tylko nowych** w karcie eBI24 (`2-dokumenty.js`, wklej `nowe-id.json`): dla każdego id
   `POST /system/archive/getDocument?isc_dataFormat=json` z `operationId:"getDocument"`
   i `data:{_id}`. JSON (faktura z eBI24) zapisz bez `header.companyLogo`, PDF/XML/obraz
   jako blob, do `przyrost-RRRRMMDD/archiwum/dokumenty/<rok documentDate>/<bucket:06d>-<id>.<rozszerzenie>`.
   Po 4 równolegle, 3 próby, lista nieudanych na koniec.
7. **Paczki** ≤25 MB:
   ```bash
   python -m scripts.pack_ebi24_archive --src ~/NEXUS-ebi24-export/przyrost-RRRRMMDD \
     --known <scratchpad>/w-nexusie.txt --out <scratchpad>/paczki-przyrost
   ```
   Wynik musi mieć `bez pliku: 0`. Inaczej wróć do kroku 6 dla brakujących.
8. **Import na produkcji** (SSH do workera, jak 16.11, osobna zgoda Artura na ten krok):
   paczki `docker cp` do `/tmp/ebi24-paczki` w workerze (`chown 10001`), potem
   `docker exec -u 10001 -w /app <worker> python -m scripts.import_ebi24_archive /tmp/ebi24-paczki <id admina>`.
   Wynik ma być `RAZEM nowe=<liczba z kroku 5> bledy=0`. Paczki potem usuń
   z kontenera i z hosta.
9. **Sprawdzenie:** `SELECT count(*), count(DISTINCT source_id)` = 49 728 + nowe,
   próbka 30 plików `sha256sum -c` w workerze zgodna z `file_sha256`.
10. **Kopia na OneDrive:** dograj nowe pliki do `Archiwum eBI24/dokumenty/<rok>/`
    i przepisz `manifest.csv` oraz `SHA256SUMS`. Robi to `kopia_onedrive.py <eksport> <spis z bazy> <folder>`
    dla eksportu z 16.11 i dla katalogu przyrostu, a pliki już skopiowane pomija. Spis daje
    SELECT kolumn `source_id … file_sha256` z `finance_archive_documents`.
    Liczba w manifeście ma być równa liczbie w bazie, a skrypt kończy się kodem 0.

## Kopia na OneDrive (stan 18.11.2026)

- Źródło: eksport z 16.11 na laptopie (`~/NEXUS-ebi24-export/archiwum/dokumenty`).
  Przed kopią porównany z bazą: 49 728 = 49 728 `source_id`, 0 rozjazdów SHA-256
  i rozmiaru. Pliki na produkcji to te same bajty.
- Manifest powstaje z SHA-256 pliku już zapisanego w folderze OneDrive, porównanego
  z `file_sha256` w bazie. Rozjazd przerywa zapis manifestu.
- Folder po latach `documentDate` z eBI24 (2 dokumenty mają w NEXUSIE inny rok,
  bo NEXUS bierze datę wystawienia). Rok w NEXUSIE jest w kolumnie „data wystawienia”.
- JSON to faktury wystawione w eBI24 (dane, nie wydruk). Czytelny podgląd daje
  NEXUS: Finanse → Archiwum eBI24.
- Sprawdzenie kopii na Macu: `cd "Archiwum eBI24" && shasum -a 256 -c SHA256SUMS`.
- Nie wynika z tego kopia off-site wolumenu `uploads` na produkcji. Ta nadal nie
  istnieje: backup hosta obejmuje pg, qdrant i coolify.
