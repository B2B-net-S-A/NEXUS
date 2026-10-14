/**
 * Pobranie pliku CV a jego podgląd idą tą samą trasą — serwer zapisuje wpis
 * `cv_file_downloaded` tylko dla pobrania (decyzja Artura 12.10.2026: mierzymy,
 * jak często CV wychodzi z NEXUSA do Worda). Przycisk „Pobierz” dokleja
 * intencję i miejsce w aplikacji; podglądy nie doklejają niczego.
 */

// `dock` — „Pobierz Word / PDF” w sekcji „CV” panelu osoby (14.10.2026, D1).
export type CvDownloadSurface = "editor" | "card" | "dock" | "preview" | "cpro" | "result" | "files";

export function withDownloadIntent(path: string, surface: CvDownloadSurface): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}intent=download&surface=${surface}`;
}
