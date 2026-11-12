import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCompanyDecisionMap, type CompanyDecisionMap as CompanyDecisionMapData } from "@/lib/api/sales-bot-people";

const useMap = vi.fn();
const start = vi.fn();
const useStart = vi.fn();

vi.mock("@/lib/api/sales-bot-people", () => ({
  useCompanyDecisionMap: (companyId: number, enabled: boolean) => useMap(companyId, enabled),
  useStartBotPeople: (source: string) => useStart(source),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));

import { CompanyDecisionMap } from "../bot-people/CompanyDecisionMap";

const map: CompanyDecisionMapData = {
  enabled: true,
  company_id: 7,
  can_start: true,
  running: false,
  people: [{
    full_name: "Ewa Testowa",
    title: "Dyrektor IT",
    active: true,
    source: "cognism",
    source_url: "https://app.cognism.com/search/prospects/persons/example",
    observed_at: "2026-11-12",
    email: "ewa.testowa@firma.example",
    email_observed_at: "2026-11-10",
    phone: "+48 000 000 000",
    phone_type: "mobile",
    phone_observed_at: "2026-11-11",
    verified_mobile: true,
  }],
};

function Subject() {
  const query = useCompanyDecisionMap(7, true);
  return <CompanyDecisionMap companyId={7} query={query} />;
}

beforeEach(() => {
  vi.clearAllMocks();
  useMap.mockReturnValue({ isLoading: false, isSuccess: true, error: null, data: map });
  useStart.mockReturnValue({ isPending: false, mutate: start });
});

describe("mapa decydentów na karcie firmy", () => {
  it("pokazuje zapisaną osobę, źródło, datę i służbowe dane kontaktowe", () => {
    render(<Subject />);
    expect(screen.getByRole("list", { name: "Mapa decydentów" })).toHaveTextContent("Ewa Testowa");
    expect(screen.getByText("Dyrektor IT")).toBeInTheDocument();
    expect(screen.getByText("Aktywna rola")).toBeInTheDocument();
    expect(screen.getByText("ewa.testowa@firma.example").closest("a")).toBeNull();
    expect(screen.getByText("+48 000 000 000").closest("a")).toBeNull();
    expect(screen.getByText("Komórkowy · zweryfikowany")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cognism" })).toHaveAttribute("href", map.people[0].source_url);
    const role = screen.getByText("Stanowisko sprawdzone").parentElement!;
    const email = screen.getByText("E-mail służbowy").parentElement!;
    const phone = screen.getByText("Telefon służbowy").parentElement!;
    expect(within(role).getByText("12.11.2026")).toHaveAttribute("datetime", "2026-11-12");
    expect(within(email).getByText("10.11.2026")).toHaveAttribute("datetime", "2026-11-10");
    expect(within(phone).getByText("11.11.2026")).toHaveAttribute("datetime", "2026-11-11");
  });

  it("rozróżnia ładowanie, pustą mapę i odmowę dostępu", () => {
    useMap.mockReturnValue({ isLoading: true, isSuccess: false });
    const { rerender } = render(<Subject />);
    expect(screen.getByRole("status")).toHaveTextContent("Wczytywanie mapy decydentów");

    useMap.mockReturnValue({ isLoading: false, isSuccess: true, data: { ...map, people: [] } });
    rerender(<Subject />);
    expect(screen.getByText("Na mapie tej firmy nie ma jeszcze decydentów.")).toBeInTheDocument();

    useMap.mockReturnValue({ isLoading: false, isSuccess: false, error: { response: { status: 403 } }, data: map });
    rerender(<Subject />);
    expect(screen.getByRole("status")).toHaveTextContent("Brak uprawnień");
    expect(screen.queryByText("Ewa Testowa")).not.toBeInTheDocument();
  });

  it("zleca Cognism tylko po kliknięciu i blokuje przycisk na czas biegu", () => {
    const { rerender } = render(<Subject />);
    expect(useStart).toHaveBeenCalledWith("cognism");
    expect(start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij z Cognism" }));
    expect(start).toHaveBeenCalledWith(7, expect.any(Object));

    useMap.mockReturnValue({ isLoading: false, isSuccess: true, data: { ...map, running: true } });
    rerender(<Subject />);
    expect(screen.getByRole("button", { name: "Uzupełnij z Cognism" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Trwa bieg Cognism. Kolejny można zlecić po jego zakończeniu.");
  });
});
