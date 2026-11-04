/**
 * Widok Firma (22.10.2026) — teksty z kokpitu, ruchu konsultantów i „w drodze”.
 * Czyste funkcje; widok tylko je rysuje.
 */

import { countPl } from "@/lib/plural-pl";

/** „+13”, „−9” (minus typograficzny), „0”. */
export function signedCount(n: number): string {
  if (n > 0) return `+${n}`;
  if (n < 0) return `−${Math.abs(n)}`;
  return "0";
}

export interface FirmaFacts {
  /** Gotowy tekst kwoty marży („612 tys. zł”) albo `null`, gdy niepoliczona. */
  margin: string | null;
  marginChangePct: number | null;
  net: number | null;
  endingWithoutContinuation: number | null;
  /** „ok. 29–30” albo `null`, gdy szacunku nie ma. */
  periodForecast: string | null;
}

/**
 * Jedno zdanie na górze widoku: pieniądze, ruch konsultantów i co jeszcze
 * może wpaść. Części bez danych odpadają — nie piszemy „marża —”.
 */
export function firmaSentence(f: FirmaFacts): string | null {
  const parts: string[] = [];
  if (f.margin) {
    const change =
      f.marginChangePct === null
        ? ""
        : ` (${f.marginChangePct >= 0 ? "+" : "−"}${Math.abs(Math.round(f.marginChangePct))}%)`;
    parts.push(`Marża miesięczna ${f.margin}${change}.`);
  }
  if (f.net !== null) {
    const ending =
      f.endingWithoutContinuation && f.endingWithoutContinuation > 0
        ? `, a ${countPl(f.endingWithoutContinuation, "kontrakt kończy", "kontrakty kończą", "kontraktów kończy")} się w 30 dni bez kontynuacji`
        : "";
    parts.push(`Konsultantów netto: ${signedCount(f.net)}${ending}.`);
  }
  if (f.periodForecast) {
    parts.push(`Z akceptacjami okres może skończyć się na ${f.periodForecast} placementach.`);
  }
  return parts.length ? parts.join(" ") : null;
}
