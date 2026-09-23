/**
 * Ekran, na którym jest użytkownik → kontekst dla Jarvisa.
 *
 * Dzięki temu „ten kandydat” / „ta rekrutacja” działa bez podawania nazwiska.
 * Czysta funkcja (testowalna bez routera). Rozpoznaje wyłącznie ścieżki
 * rekordów o liczbowym ID — reszta idzie jako sama ścieżka.
 */

import { screenKeyFor } from "@/lib/help/screen-key";
import type { JarvisScreen, ScreenGuide } from "./types";

const ENTITY_ROUTES: ReadonlyArray<[RegExp, NonNullable<JarvisScreen["entity"]>["type"]]> = [
  [/^\/candidates\/(\d+)(?:\/|$)/, "candidate"],
  [/^\/jobs\/(\d+)(?:\/|$)/, "job"],
  [/^\/clients\/(\d+)(?:\/|$)/, "client"],
  [/^\/my-clients\/(\d+)(?:\/|$)/, "client"],
  [/^\/contracts\/(\d+)(?:\/|$)/, "contract"],
];

export function screenFromLocation(pathname: string | null | undefined, search?: string | null): JarvisScreen {
  const path = (pathname || "/").slice(0, 200);
  const query = search ? (search.startsWith("?") ? search : `?${search}`) : "";
  const full = `${path}${query}`.slice(0, 300);
  const key = refineScreenKey(screenKeyFor(path, query));
  for (const [pattern, type] of ENTITY_ROUTES) {
    const match = pattern.exec(path);
    if (match) {
      const id = Number(match[1]);
      if (Number.isSafeInteger(id) && id > 0) return { path: full, entity: { type, id }, key };
    }
  }
  return { path: full, entity: null, key };
}

/**
 * Dok osoby na Tablicy nie stoi w adresie (strona zdejmuje `?candidate=`),
 * więc rozpoznajemy go po otwartym panelu — to ten ekran widzi użytkownik.
 */
function refineScreenKey(key: string | null): string | null {
  if (key !== "jobs.board" || typeof document === "undefined") return key;
  return document.querySelector('[data-help="jobs.person.dock"]') ? "jobs.person" : key;
}

/** Podpowiedzi pod polem wiadomości — zależne od ekranu, bez wywołania modelu. */
export function suggestionsFor(screen: JarvisScreen, guide?: ScreenGuide | null): string[] {
  if (guide && guide.tasks.length > 0) return guide.tasks.slice(0, 3).map((t) => t.q);
  switch (screen.entity?.type) {
    case "candidate":
      return [
        "Podsumuj tego kandydata",
        "W jakich rekrutacjach jest ten kandydat?",
        "Dodaj notatkę do tego kandydata",
      ];
    case "job":
      return [
        "Kogo z moich ludzi przepiąć na tę rekrutację?",
        "Kto stoi najdłużej na tablicy tej rekrutacji?",
        "Znajdź w bazie kandydatów pasujących do tej rekrutacji",
      ];
    case "client":
      return [
        "Komu u tego klienta kończy się zamówienie?",
        "Jakie są zasady współpracy z tym klientem?",
        "Jakie rekrutacje są otwarte u tego klienta?",
      ];
    case "contract":
      return ["Streść ten kontrakt", "Jak zakończyć współpracę na tym kontrakcie?"];
    default:
      return [
        "Co mam dziś do zrobienia?",
        "Kto z moich ludzi czeka najdłużej na nowy projekt?",
        "Jak dodać zamówienie z PDF-a?",
      ];
  }
}
