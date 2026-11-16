import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildUsersByEmail,
  hasEveryoneMention,
  renderWithMentions,
} from "@/lib/renderMentions";

const users = buildUsersByEmail([
  { id: 2, name: "Łukasz Żak", email: "lzak@example.com", role: "delivery_lead" },
]);

describe("@wszyscy w treści (13.11.2026)", () => {
  it("rozpoznaje znacznik jak serwer, a nie adres", () => {
    expect(hasEveryoneMention("@wszyscy proszę")).toBe(true);
    expect(hasEveryoneMention("Hej @Wszyscy, sync")).toBe(true);
    expect(hasEveryoneMention("(@WSZYSCY)")).toBe(true);
    expect(hasEveryoneMention("biuro@wszyscy.pl")).toBe(false);
    expect(hasEveryoneMention("@wszyscy@firma.pl")).toBe(false);
    expect(hasEveryoneMention("@wszyscyX")).toBe(false);
  });

  it("odznaka z liczbą i nazwiskami tych, których serwer oznaczył", () => {
    render(
      <p>{renderWithMentions("@wszyscy i @lzak@example.com — statusy", users, { names: ["Łukasz Żak", "Jan Kowalski"] })}</p>,
    );
    const badge = screen.getByText("@Wszyscy (2)");
    expect(badge).toHaveAttribute("title", "Oznaczeni: Łukasz Żak, Jan Kowalski");
    expect(screen.getByText("@Łukasz Żak")).toBeInTheDocument();
  });

  it("bez listy (notatka) — sama odznaka, adres z „wszyscy” w domenie zostaje adresem", () => {
    render(<p>{renderWithMentions("@wszyscy uwaga, pisać na @biuro@wszyscy.pl", users)}</p>);
    expect(screen.getByText("@Wszyscy")).toHaveAttribute("title", "Wszyscy przypisani do rekrutacji");
    expect(screen.getByText("@biuro@wszyscy.pl")).toBeInTheDocument();
  });
});
