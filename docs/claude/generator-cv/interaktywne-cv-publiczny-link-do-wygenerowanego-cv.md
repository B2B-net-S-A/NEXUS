# Interaktywne CV (publiczny link do wygenerowanego CV)

Generator CV B2B ma ścieżkę do klienta: rekruter tworzy token-link
(`/cv/i/{token}`), hiring manager przełącza widok **classic** (HTML 1:1 z
`render_payload`) ↔ **interaktywny** (kafelki must/nice-have z
dowodami-cytatami + chat AI). Migracja `0217_cv_interactive_share` (+ lustro
w entrypoint.sh). Pełny opis: `docs/cv-interactive-share-completion-report.md`.

- **Jedno źródło prawdy client-safe**: `cv_generator_b2b/public_view.py::build_public_payload`
  (bez `warnings`, blind maskowany lustrem renderera DOCX). Ten sam payload
  renderuje widok classic, jest WEJŚCIEM generacji mapy wymagań i CAŁYM
  kontekstem chatu — model fizycznie nie widzi notatek/stawek/transkryptów.
- **WYŁĄCZONE od 21.09.2026 (decyzja Artura): `CV_INTERACTIVE_ENABLED=false`**
  (backend, sprawdzane w `interactive_client_enabled`, `ensure_requirement_map`
  i `execute_map`) + `CV_INTERACTIVE_UI_ENABLED=false` (`lib/cv-generator.ts`).
  Brak dodatkowego wywołania AI mapy wymagań (~28% kosztu generacji przy
  2 linkach użytych w historii), link `/cv/i/` i plik HTML pokazują widok
  klasyczny, czat zwraca 404, pola Must/Nice i checkbox klienta ukryte. Pola
  Must/Nice zasilały WYŁĄCZNIE kafelki, a serwer liczył je jako „jest
  Champion” — tryb dopasowany przechodził bez Championa w prompcie. Powrót =
  obie flagi na `true`; reszta opisu poniżej dotyczy stanu włączonego.
- **Kafelki = precompute**: 1 dodatkowy call Claude na końcu background-joba
  generacji. Źródło wymagań: mode="new" → Job (must/nice, fallback
  champion/JD); mode="upload" → ręczne pola `must_requirements`/
  `nice_requirements` (Form, przecinki/nowe linie) albo sekcje MUST/NICE
  wgranego pliku championa — bez żadnego źródła upload zostaje classic-only.
  Walidator odrzuca cytaty niebędące substringiem payloadu; „met" bez dowodów
  degraduje do „partial". Fail-open — kwota/błąd LLM nie psuje generacji CV.
  Publiczny endpoint serwuje wyłącznie cache. Uwaga: upload nie zna klienta,
  więc flaga `cv_interactive_enabled` go nie ogranicza (ta sama klasa luki co
  sufit content_mode w upload — świadoma).
- **Jeden plik HTML** (doprecyzowanie Artura — wersja do wysyłki mailem jak
  DOCX): `GET /api/cv-generator/generated/{id}/html` → samodzielny plik
  (style/dane/JS inline, offline) z układem szablonu firmowego + kafelkami +
  przełącznikiem; druk = czyste klasyczne CV. Renderer:
  `cv_generator_b2b/html_export.py` (wejście = ten sam client-safe payload;
  wszystko przez html.escape). DOCX nie wykonuje logiki, PDF z JS działa
  tylko w Acrobacie — stąd HTML. Chat NIE działa w pliku (wymaga serwera).
- **Chat**: `POST /api/public/cv-i/{token}/chat` — dzienny limit per link
  (`CV_INTERACTIVE_CHAT_DAILY_LIMIT`=30 → 429) + kwota
  `AIFeatureKey.cv_interactive_chat` (→ 503) + rate limit 5/min; injection →
  odmowa bez wywołania AI; historia server-side. Model default Haiku
  (`CV_INTERACTIVE_CHAT_MODEL`). Pytania logowane w `cv_share_chat_messages`.
- **Tokeny v2-only** (`cv_generated_share_tokens`): sekret raz, w DB tylko
  SHA-256, PK = revoke-key `v2$<hex>`, bez gałęzi legacy. Veto HM przy
  tworzeniu linku (jak w brandowanym CV).
- **Flaga per klient** `Client.cv_interactive_enabled` (default ON, checkbox w
  EditClientModal) — gasi kafelki+chat, link zostaje classic. Świadomie
  NIEZALEŻNA od `cv_content_mode_cap`.
- Dwa nowe klucze AI w Ustawieniach → AI: `cv_requirement_map`,
  `cv_interactive_chat` (0217 seeduje `ai_features`).
