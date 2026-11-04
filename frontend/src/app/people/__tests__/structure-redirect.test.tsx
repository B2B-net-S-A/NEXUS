/**
 * `/people/structure` (dawna zakładka „Struktura”) prowadzi od 22.10.2026 do
 * widoku „Schemat” katalogu — z resztą adresu.
 */
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import PeopleStructurePage from "../structure/page";

describe("/people/structure → /people?view=schemat", () => {
  beforeEach(() => router.replace.mockClear());

  it("goły adres", async () => {
    window.history.replaceState(null, "", "/people/structure");
    render(<PeopleStructurePage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/people?view=schemat"));
  });

  it("zachowuje inne parametry", async () => {
    window.history.replaceState(null, "", "/people/structure?q=Ola&view=lista");
    render(<PeopleStructurePage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/people?q=Ola&view=schemat"));
  });
});
