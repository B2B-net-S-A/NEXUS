/**
 * Ekran, na którym jest użytkownik → kontekst dla Jarvisa.
 *
 * Dzięki temu „ten kandydat” / „ta rekrutacja” działa bez podawania nazwiska.
 * Czysta funkcja (testowalna bez routera). Rozpoznaje wyłącznie ścieżki
 * rekordów o liczbowym ID — reszta idzie jako sama ścieżka.
 */

import type { JarvisScreen } from "./types";

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
  for (const [pattern, type] of ENTITY_ROUTES) {
    const match = pattern.exec(path);
    if (match) {
      const id = Number(match[1]);
      if (Number.isSafeInteger(id) && id > 0) return { path: full, entity: { type, id } };
    }
  }
  return { path: full, entity: null };
}

/** Podpowiedzi pod polem wiadomości — zależne od ekranu, bez wywołania modelu. */
export function suggestionsFor(screen: JarvisScreen): string[] {
  switch (screen.entity?.type) {
    case "candidate":
      return [
        "Podsumuj tego kandydata",
        "W jakich rekrutacjach jest ten kandydat?",
        "Dodaj notatkę do tego kandydata",
      ];
    case "job":
      return [
        "Kto stoi najdłużej na tablicy tej rekrutacji?",
        "Czego brakuje tej rekrutacji do searchu?",
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
        "Jakie mam dziś spotkania?",
        "Jak dodać zamówienie z PDF-a?",
      ];
  }
}
