/**
 * Wariant umowy B2B dla spółki (ticket 8, 28.09.2026) — reguły formularza.
 *
 * Komparycja spółki mówi „z siedzibą w Warszawie … reprezentowaną przez Pana
 * Jana Kowalskiego – Prezesa Zarządu”. KRS podaje miejscowość i funkcję
 * w mianowniku, a imion i nazwisk zarządu publiczne API nie podaje wcale
 * (maskuje je gwiazdkami) — więc biernik i miejscownik liczymy tu jako
 * podpowiedź, a pola zostają edytowalne, jak narzędnik w umowie JDG.
 */
import type { B2BCompanyRepresentative } from "@/lib/api";

export type RepresentativeGender = "m" | "k";

function titleCase(w: string): string {
  return w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w;
}

function titleCaseCompound(w: string): string {
  return w
    .split("-")
    .map((part) => titleCase(part))
    .join("-");
}

function accusativeToken(raw: string, gender: RepresentativeGender): string {
  const w = titleCaseCompound(raw);
  const lw = w.toLowerCase();
  const cut = (n: number, suf: string) => w.slice(0, w.length - n) + suf;
  if (gender === "k") {
    if (lw.endsWith("ska") || lw.endsWith("cka") || lw.endsWith("dzka"))
      return cut(1, "ą");
    if (lw.endsWith("owa")) return cut(1, "ą");
    if (lw.endsWith("a")) return cut(1, "ę");
    return w; // nazwisko żeńskie zakończone spółgłoską — nieodmienne
  }
  if (lw.endsWith("ski") || lw.endsWith("cki") || lw.endsWith("dzki"))
    return cut(1, "iego");
  if (lw.endsWith("y")) return cut(1, "ego");
  if (lw.endsWith("ek")) return cut(2, "ka");
  if (lw.endsWith("eł")) return cut(2, "ła");
  if (lw.endsWith("a")) return cut(1, "ę");
  if (
    lw.endsWith("i") ||
    lw.endsWith("o") ||
    lw.endsWith("e") ||
    lw.endsWith("u")
  )
    return w; // nieoczywiste zakończenie — zostaw, człowiek poprawi
  return w + "a"; // spółgłoska twarda: Jan → Jana, Nowak → Nowaka
}

/** „Jan Kowalski” → „Jana Kowalskiego”; „Anna Nowak” → „Annę Nowak”. */
export function accusativeNamePl(
  fullName: string,
  gender: RepresentativeGender,
): string {
  const tokens = (fullName || "").trim().split(/\s+/).filter(Boolean);
  return tokens.map((t) => accusativeToken(t, gender)).join(" ");
}

const FUNCTION_ACCUSATIVE: Record<string, { m: string; k: string }> = {
  "prezes zarządu": { m: "Prezesa Zarządu", k: "Prezes Zarządu" },
  "wiceprezes zarządu": { m: "Wiceprezesa Zarządu", k: "Wiceprezes Zarządu" },
  "członek zarządu": { m: "Członka Zarządu", k: "Członka Zarządu" },
  prokurent: { m: "Prokurenta", k: "Prokurent" },
  komplementariusz: { m: "Komplementariusza", k: "Komplementariusza" },
};

/** Funkcja w organie po „–” w komparycji („Prezes Zarządu” → „Prezesa Zarządu”). */
export function functionAccusativePl(
  fn: string,
  gender: RepresentativeGender,
): string {
  const key = (fn || "").trim().replace(/\s+/g, " ").toLowerCase();
  const known = FUNCTION_ACCUSATIVE[key];
  return known ? known[gender] : (fn || "").trim();
}

/** Fraza po „reprezentowaną przez” — „Pana Jana Kowalskiego – Prezesa Zarządu”. */
export function representationPl(
  name: string,
  fn: string,
  gender: RepresentativeGender,
): string {
  const person = accusativeNamePl(name, gender);
  if (!person) return "";
  const title = gender === "k" ? "Panią" : "Pana";
  const role = functionAccusativePl(fn, gender);
  return role ? `${title} ${person} – ${role}` : `${title} ${person}`;
}

const SEAT_LOCATIVE: Record<string, string> = {
  warszawa: "w Warszawie",
  kraków: "w Krakowie",
  wrocław: "we Wrocławiu",
  poznań: "w Poznaniu",
  gdańsk: "w Gdańsku",
  gdynia: "w Gdyni",
  sopot: "w Sopocie",
  łódź: "w Łodzi",
  katowice: "w Katowicach",
  lublin: "w Lublinie",
  szczecin: "w Szczecinie",
  bydgoszcz: "w Bydgoszczy",
  białystok: "w Białymstoku",
  rzeszów: "w Rzeszowie",
  olsztyn: "w Olsztynie",
  toruń: "w Toruniu",
  kielce: "w Kielcach",
  opole: "w Opolu",
  gliwice: "w Gliwicach",
  zabrze: "w Zabrzu",
  sosnowiec: "w Sosnowcu",
  częstochowa: "w Częstochowie",
  radom: "w Radomiu",
  "zielona góra": "w Zielonej Górze",
  "bielsko-biała": "w Bielsku-Białej",
  "gorzów wielkopolski": "w Gorzowie Wielkopolskim",
  piaseczno: "w Piasecznie",
  pruszków: "w Pruszkowie",
  legionowo: "w Legionowie",
  wieliczka: "w Wieliczce",
};

/**
 * Miejscowość siedziby → fraza po „z siedzibą”. `known = false` znaczy, że
 * odmiany nie znamy i zwracamy „w <Miejscowość>” do sprawdzenia ręcznie.
 */
export function seatLocativePl(city: string): {
  phrase: string;
  known: boolean;
} {
  const clean = (city || "").trim().replace(/\s+/g, " ");
  if (!clean) return { phrase: "", known: true };
  const known = SEAT_LOCATIVE[clean.toLowerCase()];
  if (known) return { phrase: known, known: true };
  return { phrase: `w ${clean}`, known: false };
}

/** „Prezes Zarządu, Członek Zarządu ×2” — skład organu z odpisu KRS. */
export function boardSummary(people: B2BCompanyRepresentative[]): string {
  const counts = new Map<string, number>();
  for (const p of people) {
    const label =
      (p.name ? `${p.name} (${p.function ?? "—"})` : p.function) ?? "";
    if (!label) continue;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, n]) => (n > 1 ? `${label} ×${n}` : label))
    .join(", ");
}

/** Funkcje z KRS do szybkiego wyboru (bez powtórzeń, w kolejności odpisu). */
export function boardFunctions(people: B2BCompanyRepresentative[]): string[] {
  const seen: string[] = [];
  for (const p of people) {
    const fn = (p.function ?? "").trim();
    if (fn && !seen.includes(fn)) seen.push(fn);
  }
  return seen;
}

export interface CompanyVariantFields {
  krs: string;
  seatLocative: string;
  registryCourt: string;
  shareCapital: string;
  representativeName: string;
  representativeFunction: string;
  representation: string;
}

/** Braki wymagane w wariancie spółki — etykiety pól formularza. */
export function companyVariantMissing(f: CompanyVariantFields): string[] {
  const missing: string[] = [];
  if (!f.krs.trim()) missing.push("KRS");
  if (!f.seatLocative.trim()) missing.push("Siedziba spółki");
  if (!f.registryCourt.trim()) missing.push("Sąd rejestrowy i wydział");
  if (!f.shareCapital.trim()) missing.push("Kapitał zakładowy");
  if (!f.representativeName.trim()) missing.push("Osoba reprezentująca spółkę");
  if (!f.representativeFunction.trim())
    missing.push("Funkcja osoby reprezentującej");
  if (!f.representation.trim()) missing.push("Reprezentacja w komparycji");
  return missing;
}
