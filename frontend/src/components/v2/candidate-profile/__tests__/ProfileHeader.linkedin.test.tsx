import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/v2/pages/CandidateProfileFactsBar", () => ({
  CandidateProfileFactsBar: () => null,
}));
vi.mock("@/components/v2/CandidateNav", () => ({ CandidateNav: () => null }));
vi.mock("@/components/v2/presence/ActiveViewers", () => ({ ActiveViewers: () => null }));
vi.mock("@/components/v2/CompetenceCategoryBadge", () => ({
  CompetenceCategoryBadge: () => null,
}));
vi.mock("../CandidateTagsEditor", () => ({ CandidateTagsEditor: () => null }));

import { ProfileHeader } from "../ProfileHeader";
import { linkedinHref } from "../profile-helpers";

const noop = () => {};
const actions = {
  onAssign: noop,
  onAddNote: noop,
  onEmail: noop,
  onScheduleInterview: noop,
  onPrepInvite: noop,
  onGenerateCv: noop,
  onEdit: noop,
  onMarketplace: noop,
  onTagsPools: noop,
  onConflicts: noop,
};

function renderHeader(candidate: Record<string, unknown>, canWrite = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProfileHeader
        candidate={{ id: 5, name: "Anna", lastname: "Nowak", status: "active", ...candidate }}
        candidateId={5}
        canWrite={canWrite}
        canCall={false}
        showContactStatus={false}
        viewers={[]}
        editingIdentity={false}
        onCloseIdentityEditor={noop}
        actions={actions}
      />
    </QueryClientProvider>,
  );
}

// Runda 8 (R8-N14-3): `GET /api/candidates/{id}` zwraca pole `linkedin`,
// a nagłówek czytał `linkedin_url` — link nie pokazywał się nigdy.
describe("ProfileHeader — link do LinkedIna", () => {
  it("czyta pole `linkedin` z odpowiedzi kandydata", () => {
    renderHeader({ linkedin: "https://www.linkedin.com/in/przyklad" });
    const link = screen.getByRole("link", { name: /LinkedIn/ });
    expect(link.getAttribute("href")).toBe("https://www.linkedin.com/in/przyklad");
  });

  it("adres bez schematu dostaje https, niebezpieczny schemat — brak linku", () => {
    expect(linkedinHref("linkedin.com/in/przyklad")).toBe("https://linkedin.com/in/przyklad");
    expect(linkedinHref("javascript:alert(1)")).toBeNull();
    expect(linkedinHref("  ")).toBeNull();
    renderHeader({ linkedin: "javascript:alert(1)" });
    expect(screen.queryByRole("link", { name: /LinkedIn/ })).toBeNull();
  });
});

// Przegląd kodu 04.10.2026: tagi, pule, konflikty i weta zeszły z widoku do
// menu „⋯” — rola bez zapisu nie może ich stracić z oczu.
describe("ProfileHeader — menu „⋯” bez prawa zapisu", () => {
  it("pokazuje okna do odczytu, chowa akcje zapisu", () => {
    renderHeader({}, false);
    expect(screen.queryByRole("button", { name: /Przypisz do rekrutacji/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Dodaj notatkę/ })).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: /Tagi i pule/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Konflikty i weta/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Edytuj dane/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Napisz maila/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Wrzuć na targ/ })).toBeNull();
  });

  it("z prawem zapisu ma „Przypisz” i pełne menu", () => {
    renderHeader({}, true);
    expect(screen.getByRole("button", { name: /Przypisz do rekrutacji/ })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: /Edytuj dane/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Tagi i pule/ })).toBeTruthy();
  });
});
