# Ogłoszenie na portale — treść do wklejenia w Pracuj.pl i JustJoin.IT (0430, 12.10.2026)

<!-- indeks: okno „Ogłoszenie na portale”, jedna treść w dwóch formatach, kontrola przed skopiowaniem, stałe części firmy, awaria modelu nie nadpisuje treści, relacja do publikacji przez API -->

Decyzje Artura 12.10.2026 (makiety https://claude.ai/artifact/NK7tLYnrh1mNgH7MQ8MhtX).
Pomiar naszych publicznych ogłoszeń tego dnia (50 na JustJoin.IT, 15 na
Pracuj.pl): „co oferujemy” miały 4 z 50 i 5 z 15, etapów procesu żadne z 50,
pięć było wklejonym wewnętrznym formularzem requestu („Stawka kandydata: …”),
jedno miało inne widełki w nagłówku i w treści, a tytuły sześć różnych
dopisków. Rekruterzy układali treść w ChatGPT. Stary „Szkic ogłoszenia”
(`ai_writer`) był szablonem bez modelu, który dopisywał „Klient: …”.

Kod: `services/job_ad/` (`material`, `generate`, `render`, `lint`,
`fixed_blocks`), `api/job_ads.py`, tabela `job_ads` (jedno ogłoszenie na
rekrutację); front `components/v2/job-ad/`, `lib/api/jobAd.ts`, karta
`components/settings/JobAdFixedBlocksCard.tsx`. Harness `/preview/job-ad`
(`?state=ready|findings|template|empty`, `?tab=jjit`).

- **Jedna treść, dwa formaty.** `job_ads.content` + `tech` zapisuje się raz,
  a `render.render_ad` składa z nich pola formularza Pracuj.pl i opis
  JustJoin.IT. Nie dokładaj osobnej treści per portal — rozjazd między
  portalami to dokładnie błąd z pomiaru.
- **Do schowka idą WYŁĄCZNIE teksty `rendered` z odpowiedzi serwera** —
  policzone dla zapisanego stanu, po kontroli. Front nie formatuje treści
  sam, podgląd rysuje jako zwykły tekst (HTML z odpowiedzi nigdy nie trafia
  do `dangerouslySetInnerHTML`), a kopiowanie jest wyłączone, gdy pole jest
  w edycji, trwa zapis albo `can_copy` jest fałszem.
- **Materiał = to, co wolno powiedzieć** (`material.build_material`): opis
  projektu, obowiązki, wymagania, notatki „Można powiedzieć kandydatowi” —
  przez `job_public_profile.draft_material`, tę samą funkcję co szkic strony
  kariery. Nigdy klient, stawka, sekcja `client` ani notatki „Tylko zespół”.
  Z `basics` Championa czytane jest tylko `language` (sekcja niesie stawkę).
  Opis rekrutacji traci linie `Klient: …` i znaczniki `##` zostawione przez
  stary szkic.
- **Model redaguje, kod dokleja.** Model (klucz `job_description_generator`,
  rejestr `ai_models`) oddaje wstęp, opis projektu, obowiązki, wymagania, mile
  widziane i punkty z „co wolno powiedzieć”. Tytuł, tryb pracy, miasto, start,
  długość, „co oferujemy” firmy i etapy procesu składa `render` z pól
  rekrutacji i stałych bloków — tam model nie ma czego zmyślać. W wersji
  angielskiej model dodatkowo TŁUMACZY start, długość i język pracy; wartości,
  której rekrutacja nie ma, nie wolno mu dopisać (`generate.with_terms`).
- **Awaria modelu nie zastępuje zapisanej treści.** Złożenie z pól rekrutacji
  (`source="template"`, baner w oknie) powstaje tylko jako PIERWSZA wersja
  ogłoszenia i tylko po polsku. „Przygotuj ponownie” przy niedostępnym modelu
  = 503 bez zapisu — rekruter mógł już poprawić treść. Poprzedni generator
  oddawał w takiej sytuacji szablon ze zmyślonymi widełkami, nie do
  odróżnienia od wyniku AI.
- **Kontrola (`lint.lint_ad`) czyta wszystko, co idzie do schowka:** pola
  ogłoszenia, miasto z rekrutacji (`terms`), stałe bloki (`fixed`) i na końcu
  komplet napisów z `render.rendered_texts`. Nowe wejście renderu = nowy
  przypadek w teście z wartownikiem (`test_job_ad_lint.py`).
  **Blokują:** nazwa klienta (także nazwa wyświetlana i prawna —
  `job_public_profile.client_lint_names`), dane kontaktowe, nazwisko oraz
  kwota z walutą albo stawką za jednostkę czasu. **Doradzają:** liczba przy
  słowie „stawka”/„rate” bez waluty („rate limiting … Java 17”), nagłówki
  wewnętrznego formularza, liczby MD, numer zlecenia, wymaganie w jednym–dwóch
  słowach, brak startu, długości albo sekcji.
- **Nazwa klienta jest dopasowywana po całych słowach**, jak na stronie
  kariery: odmienioną formę („w Kwarcowym Banku”) łapie dopiero alias klienta.
- **Widełki wpisuje człowiek w formularzu portalu** (decyzja z 25.09.2026
  bez zmian): okno ich nie podpowiada, a w treści ogłoszenia kwot nie ma.
- **Stałe części firmy** (`app_settings['job_ad_fixed_blocks']`, Ustawienia →
  Rekrutacja → „Stałe części ogłoszenia”, admin i Head of Recruitment):
  dopisek do tytułu, „co oferujemy”, etapy procesu i zdanie o firmie, osobno
  po polsku i po angielsku. Zapis odmawia kwot i danych kontaktowych — blok
  trafia do każdego ogłoszenia, a rekruter go nie poprawi. Wartości startowe
  to punkty z publicznych profili firmy na portalach.
- **Lista technologii bierze tylko krótkie pozycje** (do 3 słów i 40 znaków,
  zamienniki „X lub Y” osobno). Zdanie klienta zostaje w wymaganiach. Poziom
  JustJoin.IT: krytyczne (wyłącznie z decyzji Delivery Leada) → Advanced,
  wymagane → Regular, mile widziane → Nice to have; okno mówi, ile
  technologii nie zmieściło się w limicie 10.
- **`material_hash` liczy się z jawnej, wersjonowanej listy pól**
  (`material._HASH_FIELDS`). Nowe pole `AdMaterial` dopisane do odcisku bez
  zmiany wersji oznaczy wszystkie zapisane ogłoszenia jako „rekrutacja się
  zmieniła”.
- **Zapis poprawki niesie `expected_updated_at`**; inna wersja w bazie = 409
  `job_ad_changed`, okno wczytuje ogłoszenie ponownie, a niezapisany tekst
  zostaje w polu.
- **To nie jest publikacja przez API.** Sekcja „Portale ogłoszeniowe”
  (`JobPortalsSection`, tabela `job_postings`, treść z zatwierdzonego opisu
  publicznego) zostaje osobno i za flagami. Ręcznie wklejonego ogłoszenia nie
  zapisuj w `job_postings`: to kolejka workera, więc taki wiersz dostałby
  zlecenie wysyłki przez API, a przy Pracuj.pl trwale blokował usunięcie
  rekrutacji. Połączenie obu treści to osobny etap.
- **Strona kariery nie zmieniła kontroli.** Szersza lista nazw klienta działa
  tylko w ogłoszeniu na portale; na stronie kariery obróciłaby adresy
  `/r/<slug>` rozesłanych już linków i zaczęła odmawiać zatwierdzonym opisom —
  to osobna decyzja.
