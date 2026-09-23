import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  candidatesApi: {
    setRecruitmentExpectedRate: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
}));

import { useAuthStore } from "@/store/auth";
import { RecruitmentRateRow } from "../RecruitmentsTab";

const clientRate = { value: 190, unit: "hourly", currency: "PLN" };
const expectedRate = { value: 150, unit: "hourly", currency: "PLN" };

function renderAs(roles: string[]) {
  useAuthStore.setState({
    user: {
      id: 1,
      email: "osoba@example.com",
      name: "Osoba",
      role: roles[0],
      roles,
    } as never,
    hydrated: true,
  });
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RecruitmentRateRow
        candidateId={1}
        jobId={2}
        clientRate={clientRate}
        expectedRate={expectedRate}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => useAuthStore.setState({ user: null, hydrated: true }));

// Decyzja 23.09.2026: rekruter, sourcer i TAC nie widzą stawki do klienta,
// HoR, TCM i Finanse widzą, zapisuje wyłącznie DL albo admin.
describe("RecruitmentRateRow — stawka do klienta wg roli", () => {
  it.each(["recruiter", "sourcer", "tac"])(
    "%s widzi tylko stawkę kandydata, bez marży",
    (role) => {
      renderAs([role]);
      expect(screen.getByText("Stawka kandydata")).toBeInTheDocument();
      expect(screen.queryByText("Stawka do klienta")).not.toBeInTheDocument();
      expect(screen.queryByText(/Marża/)).not.toBeInTheDocument();
    },
  );

  it.each(["head_of_recruitment", "talent_community_manager", "finance"])(
    "%s widzi stawkę do klienta bez przycisku edycji",
    (role) => {
      renderAs([role]);
      expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
      expect(screen.getByText(/Marża/)).toBeInTheDocument();
      expect(screen.queryByTestId("client-rate-edit")).not.toBeInTheDocument();
    },
  );

  it("Delivery Lead widzi i edytuje stawkę do klienta", () => {
    renderAs(["delivery_lead"]);
    expect(screen.getByTestId("client-rate-edit")).toBeInTheDocument();
  });

  it("rekruter z dodatkową rolą DL widzi stawkę do klienta", () => {
    renderAs(["recruiter", "delivery_lead"]);
    expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
  });
});
