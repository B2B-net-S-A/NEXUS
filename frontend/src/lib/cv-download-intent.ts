/**
 * Pobranie pliku CV a jego podgląd idą tą samą trasą — serwer zapisuje wpis
 * `cv_file_downloaded` tylko dla pobrania (decyzja Artura 12.10.2026: mierzymy,
 * jak często CV wychodzi z NEXUSA do Worda). Przycisk „Pobierz” dokleja
 * intencję i miejsce w aplikacji; podglądy nie doklejają niczego.
 */

export type CvDownloadSurface = "editor" | "card" | "preview" | "cpro" | "result" | "files";

export function withDownloadIntent(path: string, surface: CvDownloadSurface): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}intent=download&surface=${surface}`;
}
