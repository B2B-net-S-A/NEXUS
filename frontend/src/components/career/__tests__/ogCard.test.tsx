import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OgCard, ogJobTiles, ogTitleSize, ogTitleWords } from "@/components/career/ogCard";

describe("grafika OG w barwach marki", () => {
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

  it("czerwone tylko ostatnie słowo z liter, nie kod ani numer", () => {
    expect(ogTitleWords("Senior Java Developer").map((w) => w.red)).toEqual([false, false, true]);
    expect(ogTitleWords("Java Developer (ZOB-3003)").some((w) => w.red)).toBe(false);
    expect(ogTitleWords("DevOps").some((w) => w.red)).toBe(false);
  });

  it("dłuższy tytuł = mniejszy krój, ale nie poniżej 56 px (miniatura LinkedIna)", () => {
    expect(ogTitleSize("Java Developer")).toBe(100);
    expect(ogTitleSize("Network SME – Data & Management Traffic Segregation PL")).toBe(64);
    expect(ogTitleSize("x".repeat(120))).toBe(56);
  });

  it("bez śladów terminala, z adresem i wezwaniem", () => {
    const { container } = render(
      <OgCard
        theme="jasny"
        status={{ label: "Rekrutacja otwarta" }}
        kicker="Rekrutacja IT"
        title="Starszy Analityk Biznesowy"
        facts={[{ label: "Umowa", value: "B2B" }]}
        foot="Aplikuj w 2 minuty →"
        host="kariera.b2bnetwork.pl"
      />,
    );
    expect(container.textContent).toContain("Rekrutacja otwarta");
    expect(container.textContent).toContain("kariera.b2bnetwork.pl");
    expect(container.textContent).not.toMatch(/\$ |cat \/|~\//);
  });
});
