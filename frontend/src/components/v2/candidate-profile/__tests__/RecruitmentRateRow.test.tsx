import { describe, expect, it, vi } from "vitest";
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

import { RecruitmentRateRow } from "../RecruitmentsTab";

const clientRate = { value: 190, unit: "hourly", currency: "PLN" };
const expectedRate = { value: 150, unit: "hourly", currency: "PLN" };

function renderRow(props: { clientRateVisible?: boolean; clientRateWritable?: boolean }) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RecruitmentRateRow
        candidateId={1}
        jobId={2}
        clientRate={props.clientRateVisible ? clientRate : null}
        expectedRate={expectedRate}
        {...props}
      />
    </QueryClientProvider>,
  );
}

// Decyzja 23.09.2026: rekruter, sourcer i TAC nie widzą stawki do klienta,
// zapisuje ją wyłącznie DL albo admin. O obu flagach decyduje serwer (/history).
describe("RecruitmentRateRow — stawka do klienta wg roli", () => {
  it("bez prawa odczytu pokazuje tylko stawkę kandydata, bez marży", () => {
    renderRow({ clientRateVisible: false });
    expect(screen.getByText("Stawka kandydata")).toBeInTheDocument();
    expect(screen.queryByText("Stawka do klienta")).not.toBeInTheDocument();
    expect(screen.queryByText(/Marża/)).not.toBeInTheDocument();
    expect(screen.getByTestId("expected-rate-edit")).toBeInTheDocument();
  });

  it("z odczytem bez zapisu pokazuje stawkę do klienta bez przycisku edycji", () => {
    renderRow({ clientRateVisible: true, clientRateWritable: false });
    expect(screen.getByText("Stawka do klienta")).toBeInTheDocument();
    expect(screen.getByText(/Marża/)).toBeInTheDocument();
    expect(screen.queryByTestId("client-rate-edit")).not.toBeInTheDocument();
  });

  it("z zapisem pokazuje przycisk edycji stawki do klienta", () => {
    renderRow({ clientRateVisible: true, clientRateWritable: true });
    expect(screen.getByTestId("client-rate-edit")).toBeInTheDocument();
  });
});
