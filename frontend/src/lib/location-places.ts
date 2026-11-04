/**
 * Lokalizacja kandydata: kilka miast, każde z własnym promieniem (D6,
 * 19.10.2026). Lustro `candidate_search_predicates.parse_location_places`
 * i `location_places_clause` po stronie serwera.
 *
 * - Adres: `locs=Warszawa:30|Łódź|Kraków:50` (do 10 miast). API: powtarzany
 *   `location_places` (`"Warszawa:30"`, `"Łódź"`).
 * - Nowy kształt (lista) = SUMA: miasto, promień któregokolwiek środka albo
 *   województwo. Stary kształt (jedno `loc` + `radius` + `woj`) serwer łączy
 *   dalej koniunkcją, więc stare adresy i zapisy pokazują to co dotąd.
 * - Okienko pokazuje oba kształty jako jedną listę (`shownLocationPlaces`),
 *   a zapisuje przez `locationPlacesPatch`: jedno miasto bez województw idzie
 *   starym kształtem (to samo znaczenie), wszystko inne — listą.
 */
import type { CandidateFilters } from "@/lib/url-filters";

export interface LocationPlace {
  city: string;
  /** Promień w km; `null` = samo miasto (dopasowanie nazwy). */
  radiusKm: number | null;
}

export const MAX_LOCATION_PLACES = 10;
const MAX_RADIUS_KM = 300;

/** Klucz nazwy jak na serwerze (`pl_places.place_key`): bez polskich znaków,
 *  małe litery, myślnik = spacja, tylko człon przed przecinkiem. */
export function placeKey(value: string): string {
  return value
    .split(",")[0]
    .replace(/[łŁ]/g, "l")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[\s-]+/g, " ")
    .trim();
}

function parseEntry(raw: string): LocationPlace | null {
  const text = raw.trim();
  if (!text) return null;
  const at = text.lastIndexOf(":");
  if (at > 0) {
    const city = text.slice(0, at).trim();
    const tail = text.slice(at + 1).trim();
    if (city && /^\d+$/.test(tail)) {
      const km = Number.parseInt(tail, 10);
      // Zły promień z adresu = samo miasto (serwer odpowiedziałby 422).
      return { city, radiusKm: km >= 1 && km <= MAX_RADIUS_KM ? km : null };
    }
    if (city && !tail) return { city, radiusKm: null };
  }
  return { city: text, radiusKm: null };
}

function samePlace(a: LocationPlace, b: LocationPlace): boolean {
  return placeKey(a.city) === placeKey(b.city) && a.radiusKm === b.radiusKm;
}

/** `Warszawa:30|Łódź` → lista; puste i powtórki odpadają, najwyżej 10. */
export function parseLocationPlaces(raw: string | null): LocationPlace[] {
  const out: LocationPlace[] = [];
  for (const part of (raw ?? "").split("|")) {
    const place = parseEntry(part);
    if (!place || out.some((p) => samePlace(p, place))) continue;
    out.push(place);
    if (out.length >= MAX_LOCATION_PLACES) break;
  }
  return out;
}

function entry(place: LocationPlace): string {
  return place.radiusKm ? `${place.city}:${place.radiusKm}` : place.city;
}

/** Lista → `Warszawa:30|Łódź` (adres). */
export function encodeLocationPlaces(places: readonly LocationPlace[]): string {
  return places.map(entry).join("|");
}

/** Lista → wartości powtarzanego `location_places` (API). */
export function locationPlacesParam(places: readonly LocationPlace[]): string[] {
  return places.map(entry);
}

type LocationShape = Pick<
  CandidateFilters,
  "location" | "locationRadiusKm" | "locationPlaces" | "voivodeships"
>;

/** Miasta w okienku: lista z nowego kształtu albo jedno miasto ze starego. */
export function shownLocationPlaces(
  filters: Pick<CandidateFilters, "location" | "locationRadiusKm" | "locationPlaces">,
): LocationPlace[] {
  const list = [...filters.locationPlaces];
  const city = filters.location.trim();
  if (city && !list.some((p) => placeKey(p.city) === placeKey(city))) {
    list.unshift({ city, radiusKm: filters.locationRadiusKm });
  }
  return list;
}

/** Łatka filtrów po zmianie w okienku lokalizacji. */
export function locationPlacesPatch(
  places: readonly LocationPlace[],
  voivodeships: readonly string[],
): LocationShape {
  if (places.length === 1 && voivodeships.length === 0) {
    return {
      location: places[0].city,
      locationRadiusKm: places[0].radiusKm,
      locationPlaces: [],
      voivodeships: [],
    };
  }
  return {
    location: "",
    locationRadiusKm: null,
    locationPlaces: [...places],
    voivodeships: [...voivodeships],
  };
}

export type AddPlaceResult =
  | { places: LocationPlace[]; note: null }
  | { places: LocationPlace[]; note: string };

/** Dopisuje miasto (to samo miasto = nowy promień zamiast drugiego wiersza). */
export function addLocationPlace(
  places: readonly LocationPlace[],
  place: LocationPlace,
): AddPlaceResult {
  const city = place.city.trim();
  if (!city) return { places: [...places], note: null };
  const at = places.findIndex((p) => placeKey(p.city) === placeKey(city));
  if (at >= 0) {
    const next = [...places];
    next[at] = { city: next[at].city, radiusKm: place.radiusKm };
    return { places: next, note: null };
  }
  if (places.length >= MAX_LOCATION_PLACES) {
    return {
      places: [...places],
      note: `Najwyżej ${MAX_LOCATION_PLACES} miast — usuń któreś, żeby dodać „${city}”.`,
    };
  }
  return { places: [...places, { city, radiusKm: place.radiusKm }], note: null };
}

export function removeLocationPlace(
  places: readonly LocationPlace[],
  index: number,
): LocationPlace[] {
  return places.filter((_, i) => i !== index);
}

export function setLocationPlaceRadius(
  places: readonly LocationPlace[],
  index: number,
  radiusKm: number | null,
): LocationPlace[] {
  return places.map((p, i) => (i === index ? { ...p, radiusKm } : p));
}

/** „Warszawa +30 km, Łódź, Kraków +50 km”. */
export function describeLocationPlaces(places: readonly LocationPlace[]): string {
  return places
    .map((p) => (p.radiusKm ? `${p.city} +${p.radiusKm} km` : p.city))
    .join(", ");
}

/** „Wstaw miasta rekrutacji”: „Mile widziane” → twarda lista (do limitu). */
export function withPreferredCities(
  places: readonly LocationPlace[],
  preferred: readonly string[],
): { places: LocationPlace[]; skipped: string[] } {
  let next = [...places];
  const skipped: string[] = [];
  for (const city of preferred) {
    if (next.some((p) => placeKey(p.city) === placeKey(city))) continue;
    const result = addLocationPlace(next, { city, radiusKm: null });
    if (result.note) skipped.push(city);
    next = result.places;
  }
  return { places: next, skipped };
}
