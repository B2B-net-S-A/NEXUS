# Droga rekrutera do DL (D1–D7, 14.10.2026)

Mniej kliknięć od dodania osoby do przekazania CV Delivery Leadowi. Analiza i makiety: https://claude.ai/artifact/89gzGUHT22CXbGkTBtC4pw (13.10.2026).
Artur 14.10.2026: „tak na wszystkie D1–D7, wdrażaj”. Przykład z makiet (osoba
z „Propozycji z bazy”, 5 pytań, 3 uwagi QC): 24 → 15 kliknięć, bez czekania
na CV i poprawki AI bez sygnału. Szczegóły każdego kawałka są w regułach
obszarów; tu całość i to, czego nie wolno cofnąć „przy okazji”.

- **D1 — okno „Kandydaci do dodania”.** Wynik dopasowania liczy się sam dla
  widocznych wierszy (osadzenie zapytania + odczyt wektorów, bez modelu), bez
  przycisku „Policz dopasowanie”. Wiersz ma „+ Dodaj” (jedno kliknięcie) i do
  trzech plakietek wymagań („✓ / ✕ / ? zapytaj”); po dodaniu zostaje
  „Dodano do Nowych · rezerwacja 12 h · Cofnij”. „Cofnij” w ciągu 15 minut
  przywraca też propozycję. „Szukaj ręcznie” to zakładka tego samego okna.
  → `prostszy-ekran-rekrutacji-fakty-kafle-kandydaci-do.md`
- **D2 — stawka raz.** Okno stawki przy ruchu na „Zweryfikowany” pokazuje się
  tylko, gdy para nie ma stawki etapu (`expected_rate_value`). Pole stawki
  w formularzu wypełnia się z dosłownego cytatu (notatka, karta) albo „Stawka
  od” i mówi skąd. Bramka serwera (arkusz + stawka) bez zmian.
  → `kanban-bez-bramek.md`, `../screening-notatki/jeden-formularz-screeningu.md`
- **D3 — jedna notatka.** „Zapisz notatkę i wypełnij formularz” w polu notatki
  doku: notatka zapisuje się raz, formularz dostaje jej numer
  (`note_import.note_id`), serwer nie zakłada drugiej notatki.
- **Formularz od razu.** Bez kroku „Zacznij screening”; fakty sprzed telefonu
  w zwijanym bloku nad formularzem. Rezerwacja 12 h zakłada się przy pierwszym
  zapisie formularza (rezerwacji innej osoby nie przejmuje).
- **Po „Zapisz i przekaż dalej”** panel przechodzi na „CV” (`onForwarded`) i
  pokazuje postęp: CV (generuje się / gotowe / źródło gotowego CV / powód
  pominięcia) → QC. „Następna w Screeningu” jest przyciskiem — panel nie skacze
  sam (`nastepna-osoba-po-odrzuceniu.md`).
- **D4/D5 — CV gotowe samo.** Po podpięciu CV z automatu serwer liczy QC
  (od #2197) i pobiera propozycje poprawek AI, a osoba, która przesunęła
  kartę, dostaje dzwonek `cv_ready` („CV gotowe do sprawdzenia” albo „Automat
  nie zrobił CV” z powodem). Edytor ładuje propozycje AI sam, bez „Zaproponuj
  poprawki (AI)”. Dzwonek tylko po automacie — CV wybrane albo wgrane rekruter
  ma przed sobą. → `../generator-cv/automaty-rekrutacji-v3.md`
- **D6 — przekazanie z edytora.** Gdy karta stoi na „Zweryfikowany”, stopka
  edytora ma „Uwaga dla Delivery Leada”, „Zapisz i przekaż do DL” (ruch na
  „QC CV” przez `usePipelineMoveCore`) i „Przekaż mimo uwag…” (obejście QC
  z powodem). Uwaga jedzie jako `recruiter_remark` i stoi na górze przeglądu
  DL. → `../generator-cv/edytor-cv-pelny-ekran.md`, `przeglad-delivery-leada-v2.md`
- **D7 — strzałka bez okna.** Strzałka na karcie bez braków przesuwa od razu,
  z „Cofnij” przez 10 s. Ruch jest odroczony (wysyłka po 10 s albo przy
  zamknięciu Tablicy), bo cofnięcie wstecz zostawiłoby dzwonek DL, auto-CV
  i zaliczoną weryfikację. Z „Zweryfikowany” brak CV firmowego (`company_cv`)
  to brak — strzałka i przeciągnięcie otwierają okno.
- **W „QC CV”** zamiast martwego „Przekaż Delivery Leadowi” jest „Czeka
  u Delivery Leada od …”; gdy QC w tej kolumnie padnie, rekruter dostaje
  dzwonek-zadanie „QC CV do poprawy”.
- **Gotowe CV i upload zostają** (pytanie Artura 14.10): wybór CV z profilu
  (`StageCvPicker`, „Użyj innego CV”), wgranie CV firmowego z dysku i „Wgraj
  nowe CV” działają jak wcześniej; QC (i poprawki AI od „Zweryfikowany”) liczą
  się dla każdego źródła CV, a automat dalej pomija parę z CV (`pair_cv_exists`).
