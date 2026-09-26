import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/v2/pages/CandidateProfileFactsBar", () => ({
  CandidateProfileFactsBar: () => null,
}));
vi.mock("@/components/v2/CandidateNav", () => ({ CandidateNav: () => null }));
vi.mock("@/components/v2/presence/ActiveViewers", () => ({ ActiveViewers: () => null }));
vi.mock("@/components/v2/CompetenceCategoryBadge", () => ({
  CompetenceCategoryBadge: () => null,
}));
vi.mock("@/components/v2/PinButton", () => ({ PinButton: () => null }));
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
};

function renderHeader(candidate: Record<string, unknown>) {
  return render(
    <ProfileHeader
      candidate={{ id: 5, name: "Anna", lastname: "Nowak", status: "active", ...candidate }}
      candidateId={5}
      canWrite={false}
      canCall={false}
      showContactStatus={false}
      viewers={[]}
      editingIdentity={false}
      onCloseIdentityEditor={noop}
      actions={actions}
    />,
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
