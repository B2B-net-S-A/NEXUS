import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { JarvisSources, isNexusPath } from "../JarvisSources";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("JarvisSources", () => {
  it("dokumenty NEXUSA i internet to dwie osobne grupy", () => {
    render(
      <JarvisSources
        items={[
          {
            url: "/contracts/7?tab=documents",
            title: "umowa nr 12/2025 § 8 ust. 2",
            origin: "nexus",
            kind: "contract_document",
          },
          {
            url: "/clients/3?tab=umowy-ramowe",
            title: "Umowa ramowa — Aneks nr 1",
            origin: "nexus",
            kind: "framework_contract",
          },
          { url: "https://example.org/kc", title: "Kodeks cywilny" },
        ]}
      />,
    );
    const nexus = screen.getByTestId("jarvis-sources-nexus");
    expect(within(nexus).getByText("Źródła z NEXUSA")).toBeInTheDocument();
    const nexusLinks = within(nexus).getAllByRole("link");
    expect(nexusLinks.map((a) => a.getAttribute("href"))).toEqual([
      "/contracts/7?tab=documents",
      "/clients/3?tab=umowy-ramowe",
    ]);
    // Dokument NEXUSA otwiera się w tej samej karcie.
    expect(nexusLinks[0]).not.toHaveAttribute("target");
    expect(within(nexus).getByText("Dokumenty kontraktu")).toBeInTheDocument();

    const web = screen.getByTestId("jarvis-sources-web");
    const webLinks = within(web).getAllByRole("link");
    expect(webLinks).toHaveLength(1);
    expect(webLinks[0]).toHaveAttribute("target", "_blank");
  });

  it("źródło NEXUSA z adresem spoza aplikacji nie trafia na ekran", () => {
    render(
      <JarvisSources
        items={[
          { url: "//evil.example/x", title: "a", origin: "nexus" },
          { url: "https://evil.example/x", title: "b", origin: "nexus" },
          { url: "javascript:alert(1)", title: "c", origin: "nexus" },
          { url: "/\\evil.example", title: "d", origin: "nexus" },
        ]}
      />,
    );
    expect(screen.queryByTestId("jarvis-sources")).toBeNull();
  });

  it("ścieżka z internetu nie udaje dokumentu NEXUSA", () => {
    // Bez origin to wynik wyszukiwarki — ścieżka bez hosta odpada.
    render(<JarvisSources items={[{ url: "/contracts/7", title: "x" }]} />);
    expect(screen.queryByTestId("jarvis-sources")).toBeNull();
  });

  it("kliknięcie dokumentu NEXUSA zamyka panel (onNavigate)", () => {
    const onNavigate = vi.fn();
    render(
      <JarvisSources
        items={[{ url: "/contracts/7?tab=documents", title: "umowa § 12", origin: "nexus" }]}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.click(screen.getByRole("link", { name: /umowa § 12/ }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("isNexusPath", () => {
    expect(isNexusPath("/contracts/1?tab=documents")).toBe(true);
    expect(isNexusPath("//host/x")).toBe(false);
    expect(isNexusPath("https://host/x")).toBe(false);
    expect(isNexusPath("contracts/1")).toBe(false);
  });
});
