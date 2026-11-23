/**
 * Publiczne API strony kontraktora (`/api/public/b2b-sign/{token}`): zwykły
 * `fetch`, nigdy instancja axios z logowaniem (kontraktor nie ma konta).
 */

import { parseDispositionFilename } from "@/lib/cv-generator";

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

export function base(token: string): string {
  return `${apiBase()}/api/public/b2b-sign/${encodeURIComponent(token)}`;
}

export async function errorText(
  res: Response,
  fallback = "Nie udało się przyjąć pliku. Spróbuj ponownie za chwilę.",
): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // treść nie jest JSON-em
  }
  return fallback;
}

/** Pobierz PDF z trasy publicznej; nazwę pliku układa serwer. Zwraca błąd albo null. */
export async function savePdf(url: string, fallbackName: string): Promise<string | null> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) return errorText(res);
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = parseDispositionFilename(res.headers.get("content-disposition") ?? "", fallbackName);
  a.click();
  URL.revokeObjectURL(href);
  return null;
}
