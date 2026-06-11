# Raport ukończenia — Podgląd CV/plików otwiera się in-app (nie pobiera)

**Data:** 2026-06-11
**Zgłoszenie:** „Klikam «Podgląd» i CV kandydata **pobiera mi się**. Ma być: klikam «Podgląd» i CV **otwiera mi się**." (kandydat `/candidates/17896`, zakładka Pliki)

## Root cause

Przeglądarka **nie renderuje DOCX inline** — `window.open(blobUrl)` na blobie DOCX wymusza pobranie pliku. PDF działał (Chrome ma natywny viewer), ale CV w formacie `.docx` (24% wszystkich dokumentów: 16 630 / ~70 000; PDF 76%) zawsze się pobierały zamiast pokazywać.

## Rozwiązanie

Nowy **`FilePreviewModal`** (in-app podgląd) w `frontend/src/components/v2/pages/CandidateDetailV2.tsx`:

| Typ pliku | Render |
|---|---|
| PDF | `<iframe>` (natywny Chrome PDF viewer) |
| DOCX | `docx-preview` (lazy `import()`, osobny chunk ~168 KB) |
| obraz | `<img>` |
| reszta (legacy `.doc`, xlsx, odt, pages…) | komunikat + przycisk „Pobierz" |

Wpięty w **2 powierzchnie** (obie miały ten sam bug):
1. Zakładka **Pliki** → przycisk „Podgląd" (`PlikiTab`).
2. Zakładka **Profil** → sekcja CV → przycisk „Otwórz" (`ProfilTab.openCv`, dawniej `window.open` na `/cv-download`).

Wspólne helpery `fetchDocumentBlob` / `downloadDocumentBlob` (DRY: modal + PlikiTab + ProfilTab). Fetch = natywny `fetch` na `${NEXT_PUBLIC_API_URL}/api/candidates/{cid}/documents/{did}/content?disposition=inline` (same-origin nie istnieje — Next.js nie ma rewrite `/api/*`).

## Napotkane problemy (i fixy)

- **Kids-mode rozjeżdżał modale:** `[data-kids="true"] .bg-card:hover { transform: translateY(-3px) scale(1.006) }` w `globals.css` nadpisywał `translate(-50%,-50%)` (centrowanie Radix Dialog, który ma klasę `bg-card`) → modal skakał poza środek przy najechaniu kursorem. Fix: wykluczone `[role="dialog"]`/`[role="alertdialog"]` z reguły bounce (dotyczyło **wszystkich** dialogów w kids mode).
- **Transient chunk-load po deployu:** webpack cachuje odrzucony promise dynamic-importu na cały session strony — pojedynczy fail `import("docx-preview")` (okno deploy-swap) psuł podgląd DOCX aż do reloadu. Fallback „Pobierz" łagodzi; reload naprawia.

## Zmienione pliki

- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — `FilePreviewModal`, `previewKind`, helpery, wpięcie w `PlikiTab` + `ProfilTab`.
- `frontend/src/app/globals.css` — wykluczenie dialogów z kids-mode hover-bounce.
- `frontend/package.json` + `package-lock.json` — `docx-preview ^0.3.7`, `jszip ^3.10.1`.

## Commity (na `main`, zdeployowane)

- `3c15a4b` — feat: modal podglądu + deps.
- `df7d6ac` — fix: kids-mode CSS (centrowanie modali).
- `bfd96c4` — fix: Profil „Otwórz" → modal + wspólne helpery (DRY).

## Weryfikacja (Chrome MCP, prod)

- ✅ Pliki → „Podgląd" DOCX (`cv2025pl.docx`) → renderuje treść CV (nie pobiera).
- ✅ Pliki → „Podgląd" PDF (`Daniel_Klimczak…pdf`) → natywny viewer, 3 strony.
- ✅ Profil → CV „Otwórz" (DOCX primary) → ten sam modal, renderuje.
- ✅ Modal wycentrowany również przy najechaniu kursorem (po fixie kids-mode).
- ✅ `/api/health` healthy, deploye zielone (smoke-test version-match).

## Znane ograniczenia

- Legacy `.doc` (binarny, 356 plików), xlsx/odt/pages → brak inline podglądu, oferowane pobranie.
- Transient chunk-load (rzadkie, okno deploy) → error state z fallbackiem „Pobierz" do reloadu.
- Opcja na przyszłość: skonfigurować CORS na buckecie Hetzner → presigned URL flow odciążyłby backend proxy.
