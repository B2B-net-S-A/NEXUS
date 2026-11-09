import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import type { EmploymentMarker } from "@/lib/employment-marker";
import { useAuthStore } from "@/store/auth";
import {
  EmployedPeopleNotice,
  EmploymentNotice,
  EmploymentPopoverPill,
} from "../EmploymentNotice";

const WORKING: EmploymentMarker = {
  phase: "working",
  source: "contract",
  elsewhere: null,
  clients: [
    {
      client_id: 100,
      client_name: "Bank Przykładowy",
      contract_id: 10,
      phase: "working",
      order_end_date: "2026-12-31",
      delivery_lead_name: "Karol Wzorcowy",
    },
  ],
};

const STARTING: EmploymentMarker = {
  phase: "starting",
  source: "contract",
  elsewhere: null,
  clients: [
    {
      client_id: 200,
      client_name: "Telekom Przykładowy",
      contract_id: 20,
      phase: "starting",
      starts_on: "2026-11-01",
    },
  ],
};

function signIn(role: "admin" | "recruiter") {
  useAuthStore.setState({
    user: { id: 1, email: "test@example.com", name: "Test", role, roles: [role] } as never,
    hydrated: true,
  });
}

afterEach(() => {
  useAuthStore.setState({ user: null, hydrated: true });
});

describe("EmploymentPill", () => {
  it("trwające zamówienie: czerwony zakaz z ikoną telefonu, bez daty", () => {
    render(<EmploymentPill marker={WORKING} />);

    const pill = screen.getByText("Aktywne zamówienie · nie dzwoń").parentElement!;
    expect(pill).toHaveAttribute("data-employment-phase", "working");
    expect(pill.className).toContain("text-destructive");
    expect(pill.querySelector("svg")).not.toBeNull();
    expect(pill.textContent).not.toContain("31.12");
  });

  it("skrócona treść zostawia pełną w dymku", () => {
    render(<EmploymentPill marker={WORKING} label={{ short: true }} />);

    const pill = screen.getByText("Nie dzwoń").parentElement!;
    expect(pill).toHaveAttribute("title", "Aktywne zamówienie · nie dzwoń");
  });

  it("ławka: neutralna kropka zamiast telefonu", () => {
    render(<EmploymentPill marker={{ ...WORKING, no_current_order: true }} />);

    const pill = screen.getByText("Bez aktywnego zamówienia").parentElement!;
    expect(pill.className).not.toContain("text-destructive");
    expect(pill.querySelector("svg")).toBeNull();
  });

  it("wariant tekstowy nie ma tła plakietki", () => {
    render(<EmploymentPill marker={STARTING} appearance="text" />);

    const text = screen.getByText("Zaczyna u nas · nie dzwoń").parentElement!;
    expect(text.className).toContain("text-destructive");
    expect(text.className).not.toContain("bg-destructive");
  });
});

describe("EmploymentNotice", () => {
  it("rekruter: u kogo i kto jest Delivery Leadem, bez daty", () => {
    signIn("recruiter");
    render(<EmploymentNotice marker={WORKING} personName="Anna Przykładowa" />);

    const notice = screen.getByRole("note");
    expect(
      within(notice).getByText("Anna Przykładowa: aktywne zamówienie · nie dzwoń · Bank Przykładowy"),
    ).toBeInTheDocument();
    expect(within(notice).getByText("Delivery Lead: Karol Wzorcowy")).toBeInTheDocument();
    expect(notice.textContent).not.toContain("31.12");
    expect(within(notice).getByText("Przed wysłaniem profilu zapytaj Delivery.")).toBeInTheDocument();
  });

  it("dostęp do Delivery: data zamówienia zostaje", () => {
    signIn("admin");
    render(<EmploymentNotice marker={WORKING} />);

    expect(
      screen.getByText("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy"),
    ).toBeInTheDocument();
  });

  it("link do kontraktu tylko z dostępem do Delivery", () => {
    signIn("recruiter");
    const { unmount } = render(<EmploymentNotice marker={WORKING} />);
    expect(screen.queryByRole("link", { name: "Kontrakt ›" })).toBeNull();
    unmount();

    signIn("admin");
    render(<EmploymentNotice marker={WORKING} />);
    expect(screen.getByRole("link", { name: "Kontrakt ›" })).toHaveAttribute(
      "href",
      "/contracts/10?from=candidate",
    );
  });

  it("bez wskazówki, gdy ekran ma własną", () => {
    render(<EmploymentNotice marker={WORKING} hint={null} />);

    expect(screen.queryByText("Przed wysłaniem profilu zapytaj Delivery.")).toBeNull();
  });
});

describe("EmployedPeopleNotice", () => {
  const anna = { id: 1, name: "Anna Przykładowa", marker: WORKING };
  const piotr = { id: 2, name: "Piotr Fikcyjny", marker: STARTING };

  it("nie rysuje nic, gdy nikt z wyboru u nas nie pracuje", () => {
    const { container } = render(<EmployedPeopleNotice people={[]} total={3} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("jedna osoba: pełne szczegóły", () => {
    render(<EmployedPeopleNotice people={[anna]} total={2} />);

    expect(screen.getByText("Anna Przykładowa: aktywne zamówienie · nie dzwoń · Bank Przykładowy")).toBeInTheDocument();
  });

  it("kilka osób: liczba, lista i akcja", () => {
    render(
      <EmployedPeopleNotice
        people={[anna, piotr]}
        total={4}
        action={<button type="button">Dodaj bez tych 2 osób</button>}
      />,
    );

    const notice = screen.getByRole("note");
    expect(within(notice).getByText("2 z 4 osób pracują u nas")).toBeInTheDocument();
    expect(notice).toHaveTextContent("Anna Przykładowa — aktywne zamówienie · nie dzwoń");
    expect(notice).toHaveTextContent("Piotr Fikcyjny — zaczyna u nas · nie dzwoń");
    expect(within(notice).getByRole("button", { name: "Dodaj bez tych 2 osób" })).toBeInTheDocument();
  });

  it("długa lista kończy się licznikiem reszty", () => {
    const many = [1, 2, 3, 4, 5].map((id) => ({ id, name: `Osoba ${id}`, marker: WORKING }));

    render(<EmployedPeopleNotice people={many} total={9} />);

    expect(screen.getByText("i jeszcze 2")).toBeInTheDocument();
    expect(screen.queryByText("Osoba 4")).toBeNull();
  });
});

describe("EmploymentPopoverPill", () => {
  it("krótka pigułka otwiera ramkę ze szczegółami", async () => {
    render(<EmploymentPopoverPill marker={WORKING} />);

    expect(screen.queryByRole("note")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Aktywne zamówienie · nie dzwoń" }));

    expect(
      within(screen.getByRole("note")).getByText("Aktywne zamówienie · nie dzwoń · Bank Przykładowy"),
    ).toBeInTheDocument();
  });
});
