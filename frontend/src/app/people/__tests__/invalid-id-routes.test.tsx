import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const params: { current: Record<string, string> } = { current: {} };
const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("next/navigation", () => ({
  useParams: () => params.current,
  notFound: () => notFound(),
}));
vi.mock("@/components/hr/HrConfigGate", () => ({
  HrConfigGate: () => <div data-testid="gate" />,
}));
vi.mock("@/components/hr/people/PersonProfile", () => ({ PersonProfile: () => null }));
vi.mock("@/components/hr/lifecycle/OffboardingScreen", () => ({ OffboardingScreen: () => null }));
vi.mock("@/components/hr/lifecycle/OnboardingCaseView", () => ({ OnboardingCaseView: () => null }));
vi.mock("@/components/admin-cases/CaseDetailView", () => ({ CaseDetailView: () => null }));

import PeopleCasePage from "../cases/[id]/page";
import OnboardingCasePage from "../new/[caseId]/page";
import OffboardingPage from "../[userId]/offboarding/page";
import PersonPage from "../[userId]/page";

const ROUTES = [
  { name: "kartoteka", Page: PersonPage, key: "userId" },
  { name: "odejście", Page: OffboardingPage, key: "userId" },
  { name: "sprawa wejścia", Page: OnboardingCasePage, key: "caseId" },
  { name: "sprawa administracja@", Page: PeopleCasePage, key: "id" },
] as const;

describe("dynamiczne trasy „Ludzie” — zły identyfikator to 404, nie wieczne wczytywanie", () => {
  beforeEach(() => {
    notFound.mockClear();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  for (const { name, Page, key } of ROUTES) {
    it.each(["offboarding", "0", "-3", "1.5"])(`${name}: „%s” → notFound()`, (value) => {
      params.current = { [key]: value };
      expect(() => render(<Page />)).toThrow("NEXT_NOT_FOUND");
      // React ponawia render po błędzie — liczy się samo wywołanie.
      expect(notFound).toHaveBeenCalled();
    });

    it(`${name}: liczba dodatnia renderuje ekran`, () => {
      params.current = { [key]: "12" };
      const { getByTestId } = render(<Page />);
      expect(getByTestId("gate")).toBeTruthy();
      expect(notFound).not.toHaveBeenCalled();
    });
  }
});
