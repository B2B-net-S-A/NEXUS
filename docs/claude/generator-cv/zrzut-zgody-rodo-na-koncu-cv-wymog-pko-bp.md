# Zrzut zgody RODO na końcu CV (wymóg PKO BP)

PKO BP wymaga, żeby pod treścią CV był widoczny **zrzut ekranu maila**, w którym
kandydat zgadza się na przetwarzanie danych przez bank. Do 09.2026 generator
tylko OSTRZEGAŁ rekrutera, żeby wkleił go ręcznie przed wysyłką — nie miał skąd
wziąć obrazu. Teraz rekruter wgrywa go przy generacji, a renderer wkleja sam.

- **Sterowane regułą klienta, nie nazwą.** `ClientCvRule.requires_rodo_consent_block`
  (dziś wyłącznie PKO BP) — ten sam przełącznik, który wcześniej włączał samo
  ostrzeżenie. Reguła musi być **zatwierdzona**: `resolve_client_rule` pomija
  propozycje z seeda, a front sprawdza `is_active`. Rozjazd tych dwóch warunków
  dałby przycisk zablokowany regułą, której serwer nie stosuje.
- **W `render_payload` ląduje SAM KLUCZ z magazynu, nie obraz.** DOCX jest
  re-renderowany przy KAŻDYM pobraniu (`rerender_docx_from_payload`), więc zrzut
  musi być trwały — ale zrzut maila waży setki kilobajtów i w JSONB puchłby przy
  każdym odczycie wiersza. Bajty doczytuje `hydrate_consent_screenshot`, na
  KOPII payloadu: zapisany wiersz nie może utyć o obraz.
- **Renderer zostaje czystą funkcją** — nie sięga do magazynu. Bajty wstrzykuje
  wołający pod `consent_screenshot._bytes`. Dzięki temu testy i ponowny render
  działają bez sieci.
- **Osobny endpoint uploadu** (`POST /api/cv-generator/consent-screenshot`),
  a nie pole w `/generate`: tamta ścieżka przyjmuje JSON, więc obraz w base64
  puchnie o jedną trzecią i ląduje w logach requestów. Przy okazji obie ścieżki
  generacji (JSON `/generate` i multipart `/generate-upload`) mają JEDEN
  mechanizm zamiast dwóch, które by się rozjechały.
- **Odmowa jest twarda (422) i pada PRZED naliczeniem kwoty AI.** Dla PKO BP CV
  bez zrzutu jest dokumentem, którego i tak nie da się wysłać — ostrzeżenie
  znaczyłoby „wygenerowaliśmy Ci plik do wyrzucenia", a generacja to najdroższe
  wywołanie modelu w produkcie. Kolejności pilnuje test czytający źródło
  (sprawdzony mutacją).
- **Wstawianie obrazu jest fail-soft.** Nieczytelny plik albo padnięty magazyn
  dają CV BEZ zrzutu, nie wywaloną generację — wyjątek zabrałby też to, za co
  już zapłacono. Dlatego ostrzeżenie „sprawdź, czy zrzut jest widoczny"
  ZOSTAJE w `client_rules`, choć nie mówi już „wklej ręcznie".
- **W normalnym przepływie, nie jako pływak.** Klauzula RODO niżej jest
  kotwiczona do dolnej krawędzi ostatniej strony z oblewaniem „góra i dół",
  więc treść pod nią przechodzi na kolejną stronę zamiast się nakładać. Obraz
  jako drugi pływak nie miałby tej gwarancji i mógłby przykryć klauzulę.
- **Poza zakresem świadomie:** publiczny link do CV (`/cv/i/{token}`) i eksport
  HTML nie niosą zrzutu. Wymóg dotyczy dokumentu wysyłanego do banku, a obraz
  niesie adres e-mail kandydata — inny kanał to osobna decyzja.
- **Pod centralnymi regułami zgoda blokuje POBRANIE, nie generację** (decyzja
  Artura 23.09.2026). `services/cv_consent_gate.py` (`consent_required` =
  `central_policy.requires_rodo_consent_block`, `consent_missing`) odpowiada
  409 `{code:"consent_required"}` na każdej trasie oddającej plik (DOCX, HTML,
  wersje zatwierdzone, podgląd DOCX/PDF szkicu — generatora i etapu, tworzenie
  linku). Wyłącznik awaryjny `CV_CONSENT_DOWNLOAD_GATE_ENABLED` (domyślnie ON).
  Do 23.09 CV dla PKO bez zgody dawało się pobrać i wysłać mailem, bo blokowała
  tylko „gotowość pakietu”, której nikt nie używał.
  Druk / PDF przy wymogu zgody jest zablokowany ZAWSZE (409 `consent_required`,
  ten sam wyłącznik; wydruk nie niesie zrzutu — decyzja właściciela 26.09.2026),
  a kopia etapu jest sprawdzana po WŁASNYM obrazie i zamrożonym w metadanych
  wymogu (`consent_required`), więc usunięcie wygenerowanego CV blokady nie zdejmuje.
- **Zrzut dołącza się i WYMIENIA po generacji** (`/consent-screenshot` z
  `generated_id` → `POST /generated/{id}/consent`): serwer renderuje DOCX
  ponownie i przepina kopię zgody w szkicach; wersja już zatwierdzona dostaje
  nową wersję bez wywołania AI (treść bez zmian). Blokada dotyczy pliku, nie
  ruchu karty — „Kanban bez bramek” obowiązuje.
