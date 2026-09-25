/**
 * Hiring manager rekrutacji: osoba z listy kontaktów klienta albo wpisana
 * ręcznie (25.09.2026). Zapis idzie JEDNĄ trasą `PUT /api/jobs/{id}/hiring-manager`,
 * która nową osobę zakłada jako kontakt klienta — po dopasowaniu do istniejących,
 * bo weto hiring managera działa po id kontaktu.
 */
import api from "@/lib/api";
import { foldText } from "@/lib/contract-client-filter";

export interface HiringManagerOption {
  id: number;
  name: string;
  position?: string | null;
}

export type HiringManagerChoice =
  | { kind: "contact"; id: number; name: string }
  | { kind: "new"; name: string; position?: string | null; email?: string | null };

export const hiringManagerOptionsKey = (clientId: number | null) =>
  ["hiring-manager-options", clientId] as const;

export function fetchHiringManagerOptions(
  clientId: number,
): Promise<HiringManagerOption[]> {
  return api
    .get<HiringManagerOption[]>("/api/jobs/hiring-manager-options", {
      params: { client_id: clientId },
    })
    .then((r) => (Array.isArray(r.data) ? r.data : []));
}

/**
 * Klucz osoby: słowa bez wielkości liter, polskich znaków i interpunkcji,
 * w dowolnej kolejności — lustro `name_key` z `services/job_hiring_manager.py`.
 */
export function personNameKey(name: string | null | undefined): string {
  return (name ?? "")
    .split(/[\s,;]+/)
    .map((word) => foldText(word).replace(/[^\p{L}\p{N}]+/gu, ""))
    .filter(Boolean)
    .sort()
    .join(" ");
}

/** Imię i nazwisko = co najmniej dwa słowa (lustro walidacji serwera). */
export function looksLikePersonName(name: string): boolean {
  return personNameKey(name).split(" ").filter(Boolean).length >= 2;
}

/** Kontakt, który jest tą samą osobą co wpisany tekst (albo null). */
export function sameContact(
  options: HiringManagerOption[],
  name: string,
): HiringManagerOption | null {
  const key = personNameKey(name);
  if (!key.includes(" ")) return null;
  return options.find((o) => personNameKey(o.name) === key) ?? null;
}

/** Filtr listy po każdym słowie wpisu (prefiks), bez polskich znaków. */
export function filterHiringManagerOptions(
  options: HiringManagerOption[],
  query: string,
): HiringManagerOption[] {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return options;
  return options.filter((o) => {
    const haystack = foldText(`${o.name} ${o.position ?? ""}`).split(/[^\p{L}\p{N}]+/u);
    return words.every((w) => haystack.some((h) => h.startsWith(w)));
  });
}

export function hiringManagerLabel(choice: HiringManagerChoice | null): string | null {
  if (!choice) return null;
  return choice.name;
}

export function sameChoice(
  a: HiringManagerChoice | null,
  b: HiringManagerChoice | null,
): boolean {
  if (a === null || b === null) return a === b;
  if (a.kind === "contact" && b.kind === "contact") return a.id === b.id;
  if (a.kind === "new" && b.kind === "new") {
    return (
      personNameKey(a.name) === personNameKey(b.name) &&
      (a.position ?? "") === (b.position ?? "") &&
      (a.email ?? "") === (b.email ?? "")
    );
  }
  return false;
}

export function hiringManagerRequestBody(choice: HiringManagerChoice | null) {
  if (choice === null) return { clear: true };
  if (choice.kind === "contact") return { contact_id: choice.id };
  return {
    new_person: {
      name: choice.name.trim(),
      position: choice.position?.trim() || null,
      email: choice.email?.trim() || null,
    },
  };
}

export function saveHiringManager(jobId: number, choice: HiringManagerChoice | null) {
  return api.put(`/api/jobs/${jobId}/hiring-manager`, hiringManagerRequestBody(choice));
}
