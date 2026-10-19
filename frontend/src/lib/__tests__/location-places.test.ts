import { describe, expect, it } from "vitest";
import {
  MAX_LOCATION_PLACES,
  addLocationPlace,
  describeLocationPlaces,
  encodeLocationPlaces,
  locationPlacesParam,
  locationPlacesPatch,
  parseLocationPlaces,
  removeLocationPlace,
  setLocationPlaceRadius,
  shownLocationPlaces,
  withPreferredCities,
  type LocationPlace,
} from "@/lib/location-places";
import {
  DEFAULT_FILTERS,
  decodeFilters,
  encodeFilters,
  filtersToApiParams,
} from "@/lib/url-filters";

const W30: LocationPlace = { city: "Warszawa", radiusKm: 30 };
const LODZ: LocationPlace = { city: "Łódź", radiusKm: null };
const K50: LocationPlace = { city: "Kraków", radiusKm: 50 };

describe("adres `locs` (D6, 19.10.2026)", () => {
  it("lista w obie strony", () => {
    expect(encodeLocationPlaces([W30, LODZ, K50])).toBe("Warszawa:30|Łódź|Kraków:50");
    expect(parseLocationPlaces("Warszawa:30|Łódź|Kraków:50")).toEqual([W30, LODZ, K50]);
  });

  it("puste, powtórki i zły promień z ręcznie zmienionego adresu", () => {
    expect(parseLocationPlaces(null)).toEqual([]);
    expect(parseLocationPlaces("|Łódź||lodz|Warszawa:|Kraków:999")).toEqual([
      LODZ,
      { city: "Warszawa", radiusKm: null },
      { city: "Kraków", radiusKm: null },
    ]);
  });

  it("najwyżej 10 miast z adresu", () => {
    const raw = Array.from({ length: 12 }, (_, i) => `M${i}`).join("|");
    expect(parseLocationPlaces(raw)).toHaveLength(MAX_LOCATION_PLACES);
  });

  it("API dostaje powtarzane `location_places`", () => {
    expect(locationPlacesParam([W30, LODZ])).toEqual(["Warszawa:30", "Łódź"]);
    const params = filtersToApiParams({ ...DEFAULT_FILTERS, locationPlaces: [W30, LODZ] }, 1);
    expect(params.location_places).toEqual(["Warszawa:30", "Łódź"]);
    expect(params.location).toBeUndefined();
    expect(filtersToApiParams(DEFAULT_FILTERS, 1).location_places).toBeUndefined();
  });

  it("stare `loc`/`radius`/`woj` czytają się jak dotąd i okienko widzi jedno miasto", () => {
    const old = decodeFilters(new URLSearchParams("loc=Kraków&radius=25&woj=małopolskie"));
    expect(old.location).toBe("Kraków");
    expect(old.locationRadiusKm).toBe(25);
    expect(old.locationPlaces).toEqual([]);
    expect(shownLocationPlaces(old)).toEqual([{ city: "Kraków", radiusKm: 25 }]);
    // Stary kształt idzie do API po staremu (koniunkcja z województwem).
    const params = filtersToApiParams(old, 1);
    expect(params).toMatchObject({
      location: "Kraków",
      location_radius_km: 25,
      voivodeship: ["małopolskie"],
    });
    expect(params.location_places).toBeUndefined();
  });
});

describe("okienko lokalizacji: zapis i edycja listy", () => {
  it("jedno miasto bez województw = dawny kształt, reszta = lista", () => {
    expect(locationPlacesPatch([W30], [])).toEqual({
      location: "Warszawa",
      locationRadiusKm: 30,
      locationPlaces: [],
      voivodeships: [],
    });
    expect(locationPlacesPatch([W30], ["pomorskie"])).toEqual({
      location: "",
      locationRadiusKm: null,
      locationPlaces: [W30],
      voivodeships: ["pomorskie"],
    });
    expect(locationPlacesPatch([W30, LODZ], [])).toMatchObject({
      location: "",
      locationPlaces: [W30, LODZ],
    });
    expect(locationPlacesPatch([], ["pomorskie"])).toMatchObject({
      location: "",
      locationPlaces: [],
      voivodeships: ["pomorskie"],
    });
  });

  it("dodaj, to samo miasto zmienia promień, usuń, zmień promień", () => {
    let places = addLocationPlace([], W30).places;
    places = addLocationPlace(places, LODZ).places;
    expect(places).toEqual([W30, LODZ]);
    places = addLocationPlace(places, { city: "warszawa", radiusKm: 50 }).places;
    expect(places).toEqual([{ city: "Warszawa", radiusKm: 50 }, LODZ]);
    expect(addLocationPlace(places, { city: "  ", radiusKm: null }).places).toEqual(places);
    expect(setLocationPlaceRadius(places, 1, 25)).toEqual([
      { city: "Warszawa", radiusKm: 50 },
      { city: "Łódź", radiusKm: 25 },
    ]);
    expect(removeLocationPlace(places, 0)).toEqual([LODZ]);
  });

  it("jedenaste miasto nie wchodzi i mówi dlaczego", () => {
    const ten = Array.from({ length: 10 }, (_, i) => ({ city: `M${i}`, radiusKm: null }));
    const result = addLocationPlace(ten, { city: "Gdańsk", radiusKm: null });
    expect(result.places).toHaveLength(10);
    expect(result.note).toMatch(/Najwyżej 10 miast/);
  });

  it("„Wstaw miasta rekrutacji” dokłada brakujące do limitu", () => {
    const nine = Array.from({ length: 9 }, (_, i) => ({ city: `M${i}`, radiusKm: null }));
    const { places, skipped } = withPreferredCities(nine, ["M1", "Gdańsk", "Sopot"]);
    expect(places.map((p) => p.city).slice(-1)).toEqual(["Gdańsk"]);
    expect(skipped).toEqual(["Sopot"]);
  });

  it("opis: „Warszawa +30 km, Łódź, Kraków +50 km”", () => {
    expect(describeLocationPlaces([W30, LODZ, K50])).toBe("Warszawa +30 km, Łódź, Kraków +50 km");
  });
});

describe("D5: wybór „ukryj” dla stawki i miasta w adresie i API", () => {
  it("`hur`/`hul` w obie strony, globalne `hu` bez zmian", () => {
    const filters = { ...DEFAULT_FILTERS, hideUnknownRate: true, hideUnknownLocation: true };
    const encoded = encodeFilters(filters);
    expect(encoded.get("hur")).toBe("1");
    expect(encoded.get("hul")).toBe("1");
    expect(encoded.has("hu")).toBe(false);
    expect(decodeFilters(encoded)).toEqual(filters);
    expect(filtersToApiParams(filters, 1)).toMatchObject({
      hide_unknown_rate: true,
      hide_unknown_location: true,
    });
    expect(filtersToApiParams(filters, 1).hide_unknown).toBeUndefined();
    const none = filtersToApiParams(DEFAULT_FILTERS, 1);
    expect(none.hide_unknown_rate).toBeUndefined();
    expect(none.hide_unknown_location).toBeUndefined();
  });
});
