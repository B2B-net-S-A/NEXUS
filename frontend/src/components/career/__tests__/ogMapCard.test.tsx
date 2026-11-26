import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OgListCard, OgOfferCard, ogOfferTitleSize } from "@/components/career/ogMapCard";
import { cityColumnsSvg, offerFocusSvg, remoteSvg } from "@/lib/career/mapSvg";
import { buildCityMap } from "@/lib/career/polandMap";

const FACETS = [
  { id: "warszawa", label: "Warszawa", count: 77 },
  { id: "gdansk", label: "Gdańsk", count: 42 },
  { id: "gdynia", label: "Gdynia", count: 33 },
  { id: "lodz", label: "Łódź", count: 20 },
  { id: "sopot", label: "Sopot", count: 5 },
];

describe("grafika OG w języku A", () => {
  it("lista: hasło, liczba, linia miast, etykiety czterech największych miast, bez przycisku", () => {
    const map = buildCityMap(FACETS, { phone: true });
    const { container } = render(
      <OgListCard
        openLabel="101 otwartych rekrutacji IT"
        cityLine="Zdalnie, hybrydowo i w biurze w ośmiu miastach"
        map={cityColumnsSvg(map)}
        labels={map.labels}
        host="kariera.b2bnetwork.pl"
      />,
    );
    expect(screen.getByText("Dołącz do projektów, które muszą działać.")).toBeTruthy();
    expect(screen.getByText("101 otwartych rekrutacji IT")).toBeTruthy();
    expect(screen.getByText("77")).toBeTruthy();
    expect(screen.getByText("Łódź")).toBeTruthy();
    expect(screen.queryByText("Sopot")).toBeNull();
    expect(container.textContent).not.toMatch(/→/);
    expect(container.querySelector("img")?.getAttribute("src")).toMatch(/^data:image\/svg\+xml;base64,/);
  });

  it("oferta w mieście: technologie, tytuł, linia, podpis miasta na mapie", () => {
    const focus = offerFocusSvg(FACETS, ["Warszawa"]);
    const { container } = render(
      <OgOfferCard
        tags={["LLM", "Document AI"]}
        title="AI Engineer"
        line="Warszawa · hybryda · B2B"
        sub="Czas projektu: 12+ miesięcy · prowadzi Marek"
        map={{ kind: "focus", map: focus, lit: focus.lit, cities: "Warszawa", note: "biuro 1 dzień w tygodniu" }}
        host="kariera.b2bnetwork.pl"
      />,
    );
    for (const t of ["LLM", "Document AI", "AI Engineer", "Warszawa · hybryda · B2B", "Warszawa", "biuro 1 dzień w tygodniu"]) {
      expect(screen.getByText(t)).toBeTruthy();
    }
    expect(container.textContent).not.toMatch(/Wyślij CV|→/);
  });

  it("oferta zdalna i zamknięta: plakietka zamiast technologii", () => {
    render(
      <OgOfferCard tags={["Oracle"]} status="Rekrutacja zamknięta" title="Team Leasing – Oracle" line={null} sub={null} map={{ kind: "remote", map: remoteSvg() }} host="h" />,
    );
    expect(screen.getByText("Rekrutacja zamknięta")).toBeTruthy();
    expect(screen.queryByText("Oracle")).toBeNull();
  });

  it("tytuł dobiera rozmiar do miejsca: tytuł nie schodzi na adres w stopce", () => {
    expect(ogOfferTitleSize("AI Engineer")).toBe(96);
    // „Power Platform” przy 80 px nie mieści się w 590 px — wychodziły trzy linie na adres.
    expect(ogOfferTitleSize("Power Platform Developer")).toBe(64);
    expect(ogOfferTitleSize("Starszy Analityk Biznesowo-Systemowy")).toBeLessThanOrEqual(64);
    expect(ogOfferTitleSize("Senior Fullstack Developer Java Angular Spring Boot w sektorze bankowym")).toBeLessThanOrEqual(54);
  });
});
