import { describe, expect, it } from "vitest";

import type { CareerJobParams } from "../api";
import { cityColumnsSvg, closedSvg, offerFocusSvg, remoteSvg, svgDataUri } from "../mapSvg";
import {
  LIST_DESCRIPTION,
  OG_SITE_NAME,
  listOgTitle,
  offerOgDescription,
  offerOgLine,
  offerOgSub,
  offerOgTitle,
  openRecruitmentsIT,
} from "../ogText";
import { buildCityMap } from "../polandMap";

const P = (over: Partial<CareerJobParams> = {}): CareerJobParams => ({
  city: "Warszawa",
  remote_policy: "hybrid",
  onsite_days_per_week: 1,
  seniority: null,
  contract: "B2B",
  start: null,
  duration: "12+ miesięcy",
  ...over,
});

describe("teksty podglądu linku (OG-w-portalach)", () => {
  it("lista: liczba otwartych w tytule, marka, opis bez obietnic", () => {
    expect(listOgTitle(101)).toBe("101 otwartych rekrutacji IT · B2Bnetwork");
    expect(listOgTitle(3)).toBe("3 otwarte rekrutacje IT · B2Bnetwork");
    expect(listOgTitle(1)).toBe("1 otwarta rekrutacja IT · B2Bnetwork");
    expect(listOgTitle(null)).toBe("Otwarte rekrutacje IT · B2Bnetwork");
    expect(listOgTitle(0)).toBe("Otwarte rekrutacje IT · B2Bnetwork");
    expect(LIST_DESCRIPTION).toBe("Projekty w bankowości, AI, danych i testach. Zdalnie, hybrydowo i w biurze.");
    expect(OG_SITE_NAME).toBe("B2Bnetwork · Kariera");
    expect(openRecruitmentsIT(22)).toBe("22 otwarte rekrutacje IT");
    expect(openRecruitmentsIT(12)).toBe("12 otwartych rekrutacji IT");
  });

  it("oferta w mieście: stanowisko · miasto, tryb; opis = zdanie o projekcie + B2B, czas", () => {
    const job = { title: "AI Engineer", subtitle: "rozwój platformy analizy dokumentów", params: P() };
    expect(offerOgTitle(job)).toBe("AI Engineer · Warszawa, hybryda · B2Bnetwork");
    expect(offerOgDescription(job)).toBe("Rozwój platformy analizy dokumentów. B2B, 12+ miesięcy.");
    expect(offerOgLine(job.params)).toBe("Warszawa · hybryda · B2B");
    expect(offerOgSub(job.params, "Marek")).toBe("Czas projektu: 12+ miesięcy · prowadzi Marek");
  });

  it("oferta zdalna: „zdalnie” w tytule, „Zdalnie z całej Polski” w opisie i na grafice", () => {
    const job = { title: "Team Leasing – Oracle", subtitle: "Specjalista Oracle w modelu Team Leasing.", params: P({ remote_policy: "remote", city: "Warszawa", duration: null }) };
    expect(offerOgTitle(job)).toBe("Team Leasing – Oracle · zdalnie · B2Bnetwork");
    expect(offerOgDescription(job)).toBe("Specjalista Oracle w modelu Team Leasing. Zdalnie z całej Polski.");
    expect(offerOgLine(job.params)).toBe("Zdalnie z całej Polski · B2B");
    expect(offerOgSub(job.params, "Michał")).toBe("Prowadzi Michał");
  });

  it("opis pola miasta i Trójmiasto: rozpoznane miasta, najwyżej dwa", () => {
    expect(offerOgTitle({ title: "QA", params: P({ city: "Priorytet Gdańsk" }) })).toBe("QA · Gdańsk, hybryda · B2Bnetwork");
    expect(offerOgLine(P({ city: "Trójmiasto" }))).toBe("Gdańsk, Gdynia +1 · hybryda · B2B");
    // Opis zamiast miasta (dłuższy niż 30 znaków) nie trafia do tytułu.
    expect(offerOgTitle({ title: "QA", params: P({ city: "Sporadycznie, 1-2 dni w miesiącu, możliwa 100% praca zdalna" }) })).toBe(
      "QA · hybryda · B2Bnetwork",
    );
  });

  it("bez parametrów (ukryte przełącznikiem) — sam tytuł, opis z podtytułu albo nic", () => {
    expect(offerOgTitle({ title: "Analityk", params: null })).toBe("Analityk · B2Bnetwork");
    expect(offerOgDescription({ subtitle: null, params: null })).toBeNull();
    expect(offerOgLine(null)).toBeNull();
    expect(offerOgSub(null, "")).toBeNull();
  });

  it("długi czas projektu nie trafia na grafikę", () => {
    expect(offerOgSub(P({ duration: "12 miesięcy z możliwością przedłużenia, Wymiar: 250 MD" }), "Ola")).toBe("Prowadzi Ola");
  });
});

describe("mapa OG jako SVG (bez napisów)", () => {
  const facets = [
    { id: "warszawa", label: "Warszawa", count: 77 },
    { id: "gdansk", label: "Gdańsk", count: 42 },
  ];

  it("lista: kolumny z danych, bez <text>, poprawny data URI", () => {
    const { svg, view } = cityColumnsSvg(buildCityMap(facets, { phone: true }));
    expect(view).toEqual([0, 60, 600, 540]);
    expect(svg).toContain("378.0,432.6 400.0,432.6 400.0,155.4 378.0,155.4");
    expect(svg).not.toContain("<text");
    expect(svgDataUri(svg)).toMatch(/^data:image\/svg\+xml;base64,/);
    expect(atob(svgDataUri(svg).split(",")[1])).toContain("<svg");
  });

  it("oferta: podświetlone miasto ma co najmniej 200 jednostek, nieznane miasto dostaje kolumnę z rzutu", () => {
    const f = offerFocusSvg(facets, ["Warszawa"]);
    expect(f.lit).toEqual([{ x: 378, base: 432.6, height: 277.2 }]);
    expect(offerFocusSvg([], ["Kraków"]).lit[0].height).toBe(200);
  });

  it("zdalna i zamknięta bez kolumn", () => {
    expect(remoteSvg().svg).toContain('fill="#C42329"');
    expect(closedSvg().svg).toContain("stroke-dasharray");
  });
});
