/**
 * Historia wersji i powrót pliku Word w harnessie — bez sieci, dane fikcyjne.
 *
 * Odpowiada jak trasy `…/cv/branded/versions`, `…/versions/{n}` i
 * `…/import-preview`: dwie zatwierdzone wersje (2 — bieżąca, 1 — starsza)
 * i treść „z pliku Word”. Obie treści powstają z zasiewu edytora kilkoma
 * podmianami, żeby dało się przeklikać każdy rodzaj różnicy.
 */

import type {
  CvEditorHistoryApi,
  CvImportPreview,
  CvVersionContent,
  CvVersionsResponse,
} from "@/lib/api/cvEditorHistory";

const VERSIONS: CvVersionsResponse = {
  versions: [
    {
      version: 2,
      approved_at: "2026-10-10T09:00:00Z",
      approved_by_name: "Marta Testowa",
      language: "pl",
      docx_available: true,
      is_current: true,
    },
    {
      version: 1,
      approved_at: "2026-10-06T14:20:00Z",
      approved_by_name: "Marta Testowa",
      language: "pl",
      docx_available: false,
      is_current: false,
    },
  ],
};

/** Plik o tej nazwie serwer „odrzuca” — widać komunikat błędu w panelu. */
export const BROKEN_WORD_FILE = "uszkodzony.docx";

/** Wersja 1: jeden punkt brzmiał inaczej, jednego jeszcze nie było, jeden później usunięto. */
function versionOne(seed: string): string {
  return seed
    .replace("Optymalizacja zapytań w PostgreSQL.", "Strojenie zapytań i indeksów w PostgreSQL.")
    .replace("<li><p>Projektowała mikroserwisy płatności w <strong>Spring Boot</strong>.</p></li>", "")
    .replace(
      "<li><p>Testy jednostkowe i integracyjne (JUnit, Testcontainers).</p></li>",
      "<li><p>Testy jednostkowe i integracyjne (JUnit, Testcontainers).</p></li>" +
        "<li><p>Dyżury wsparcia produkcyjnego raz w miesiącu.</p></li>",
    );
}

/**
 * Treść „z pliku Word”: opakowanie dokumentu, punkty bez akapitu i klauzula
 * w brzmieniu innym niż w edytorze — tak wygląda HTML po odczycie pliku.
 */
function wordContent(seed: string): string {
  const body = seed
    .replace(/<p data-cv-section="rodo"[^>]*>[\s\S]*?<\/p>/, "")
    .replace(/<li><p>([\s\S]*?)<\/p><\/li>/g, "<li>$1</li>")
    .replace(
      "Przeglądy kodu i wdrażanie młodszych programistów.",
      "Przeglądy kodu oraz wdrażanie i mentoring młodszych programistów.",
    )
    .replace("<li>Integracje z systemami zewnętrznymi przez kolejki komunikatów.</li>", "")
    .replace(
      "<li>Ponad 7 lat doświadczenia",
      "<li>Prowadziła warsztaty z testów kontraktowych dla zespołu.</li><li>Ponad 7 lat doświadczenia",
    );
  const clause =
    '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych przez Software House Przykład ' +
    "sp. z o.o. dla potrzeb przyszłych rekrutacji.</p>";
  return `<article class="cv">${body}${clause}</article>`;
}

function rejected(status: number, detail: string): Error {
  // Kształt błędu axiosa — panel czyta `response.data.detail`.
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  });
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** `seed` — treść, z którą harness otwiera edytor (wersja 2 to właśnie ona). */
export function memoryHistoryApi(seed: string): CvEditorHistoryApi {
  return {
    versions: async () => VERSIONS,
    version: async (_stageId, version): Promise<CvVersionContent> => {
      // Chwila zwłoki — widać stan wczytywania na przycisku „Porównaj”.
      await pause(250);
      const summary = VERSIONS.versions.find((item) => item.version === version);
      if (!summary) throw rejected(404, "Nie ma takiej wersji CV.");
      return {
        version,
        content_html: version === 1 ? versionOne(seed) : seed,
        language: summary.language,
        approved_at: summary.approved_at,
      };
    },
    importPreview: async (_stageId, file): Promise<CvImportPreview> => {
      await pause(250);
      if (file.name === BROKEN_WORD_FILE) {
        throw rejected(422, "Nie udało się odczytać pliku Word — jest uszkodzony albo zabezpieczony hasłem.");
      }
      return { content_html: wordContent(seed), filename: file.name };
    },
  };
}
