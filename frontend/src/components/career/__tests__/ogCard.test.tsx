import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OgCard, ogJobTiles, ogTitleSize, ogWordSize } from "@/components/career/ogCard";

describe("grafika OG w wyglądzie nowej strony kariery", () => {
  it("kafle: miasto, tryb i umowa w jednej linii; zdalnie bez miasta", () => {
    expect(
      ogJobTiles({ city: "Warszawa, Łódź, Gdynia, Gdańsk", remote_policy: "hybrid", contract: "B2B" }),
    ).toEqual([
      { label: "Lokalizacja", value: "Warszawa +3" },
      { label: "Tryb pracy", value: "Hybryda" },
      { label: "Umowa", value: "B2B" },
    ]);
    expect(ogJobTiles({ city: "Kraków", remote_policy: "remote", contract: null })).toEqual([
      { label: "Tryb pracy", value: "Zdalnie" },
    ]);
    expect(ogJobTiles(null)).toEqual([]);
  });

  it("dłuższy tytuł = mniejszy krój; z wielkim słowem tytuł jest drugim napisem", () => {
    expect(ogTitleSize("Java Developer")).toBe(96);
    expect(ogTitleSize("Network SME – Data & Management Traffic Segregation PL")).toBe(64);
    expect(ogTitleSize("x".repeat(120))).toBe(54);
    expect(ogTitleSize("Java Developer", true)).toBe(52);
    expect(ogWordSize("SQL")).toBeGreaterThan(ogWordSize("Power Platform"));
  });

  it("bez śladów terminala, z adresem i wezwaniem", () => {
    const { container } = render(
      <OgCard
        word="Python"
        status={{ label: "Rekrutacja otwarta" }}
        kicker="Rekrutacja IT"
        title="Starszy Analityk Biznesowy"
        facts={[{ label: "Umowa", value: "B2B" }]}
        foot="Wyślij CV →"
        host="kariera.b2bnetwork.pl"
      />,
    );
    expect(container.textContent).toContain("Rekrutacja otwarta");
    expect(container.textContent).toContain("kariera.b2bnetwork.pl");
    expect(container.textContent).toContain("Python");
    expect(container.textContent).not.toMatch(/\$ |cat \/|~\//);
  });
});
