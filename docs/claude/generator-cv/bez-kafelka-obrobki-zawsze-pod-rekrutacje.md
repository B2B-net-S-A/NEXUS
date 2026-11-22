# Generator CV bez kafelka „Obróbka” — każde CV pod rekrutację (22.11.2026)

<!-- indeks: kafle „Redakcja / Pod rekrutację” zdjęte, `GENERATE_CONTENT_MODE`, `ContentModeNote`, brak Championa = serwer robi Redakcję z uwagą, wiersz „Tryb” w regułach -->

Decyzja Artura z 22.11.2026: generator działa tylko w rekrutacji
(`generator-cv-tylko-w-rekrutacji.md`), więc każde CV robimy pod rekrutację.
Kafle „Redakcja / Pod rekrutację” zniknęły z panelu „Z czego zrobić CV?”
w karcie „CV do klienta” i z okna generatora.

## Co mówiły dane

Kopia produkcji z 19.11.2026, CV z generatora od 13.10 (od przeniesienia
generatora do rekrutacji): 1309 CV, z tego 39 w trybie Redakcja.

- 17 automatycznych i 9 ręcznych: rekrutacja bez kompletnego Profilu
  Championa, więc Redakcja przyszła sama (serwer albo domyślny kafel).
- 13 ręcznych przy gotowym Championie, czyli świadomy wybór. To około 1% CV
  generowanych ręcznie, a od tygodnia 16.11 nie było żadnego.
- Żaden klient nie ma sufitu trybu (`clients.cv_content_mode_cap`) ani trybu
  w regule CV (`client_cv_rules.content_mode`).

## Co jest w kodzie

- **Formularz zawsze prosi o „Pod rekrutację”:** `GENERATE_CONTENT_MODE`
  w `cv-generator-form.ts`, bez stanu i bez przełącznika w `useCvGenerator`.
  Sufit klienta „Przepisanie” dalej wysyła `basic`.
- **Bez Championa decyduje serwer**, jak dotąd przy automatach:
  `central_policies.resolve_mode` zamienia `tailored` na `polished`
  i dopisuje uwagę `MISSING_CHAMPION_NOTICE`. Nie blokujemy „Generuj” (wybór
  Artura: CV bez dopasowania zamiast blokady do uzupełnienia Championa).
  Po uzupełnieniu Championa rekruter klika „Dopasuj pod rekrutację” w edytorze.
- **Zamiast kafli jest jedna linia** `ContentModeNote` („Treść: Pod rekrutację /
  Bez dopasowania / Przepisanie” i zdanie, co to znaczy). Zwinięte podsumowanie
  panelu bez Championa mówi „bez dopasowania”, nie „Pod rekrutację”.
- **Wiersz „Tryb” w regułach klienta** (`CvHandoffWorkbench`) pokazuje
  „Pod rekrutację”, a tryb z reguły tylko wtedy, gdy reguła go blokuje.
- **Serwer bez zmian:** API dalej przyjmuje `basic | polished | tailored`
  (automaty, integracje, sufit klienta). Ustawienia trybu w regułach CV
  klienta (`/settings/cv-rules`) zostają.

## Czego nie cofać

- Nie przywracaj przełącznika „Redakcja” w formularzu bez nowej decyzji Artura.
- Nie zmieniaj domyślnego trybu formularza na `polished` przy braku Championa:
  wtedy CV powstaje bez uwagi o brakującym Championie.
