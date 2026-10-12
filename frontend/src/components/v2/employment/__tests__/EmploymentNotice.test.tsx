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
  it("pokazuje pełną treść i zieloną kropkę, gdy osoba pracuje", () => {
    render(<EmploymentPill marker={WORKING} />);

    const pill = screen.getByText("Pracuje u nas · Bank Przykładowy · do 31.12.2026").parentElement!;
    expect(pill).toHaveAttribute("data-employment-phase", "working");
    expect(pill.className).toContain("bg-success-muted");
    expect(pill.querySelector("[aria-hidden]")).toHaveClass("bg-success");
  });

  it("skrócona treść zostawia pełną w dymku", () => {
    render(<EmploymentPill marker={WORKING} label={{ clients: "none", date: "short" }} />);

    const pill = screen.getByText("Pracuje u nas · do 31.12").parentElement!;
    expect(pill).toHaveAttribute("title", "Pracuje u nas · Bank Przykładowy · do 31.12.2026");
  });

  it("klient tej rekrutacji: bursztyn i ikona zamiast kropki", () => {
    render(<EmploymentPill marker={{ ...WORKING, elsewhere: false }} />);

    const pill = screen.getByText("Pracuje u tego klienta · do 31.12.2026").parentElement!;
    expect(pill.className).toContain("bg-warning-muted");
    expect(pill.querySelector("svg")).not.toBeNull();
  });

  it("wariant tekstowy nie ma tła plakietki", () => {
    render(<EmploymentPill marker={STARTING} appearance="text" />);

    const text = screen.getByText("Zaczyna u nas 01.11.2026 · Telekom Przykładowy").parentElement!;
    expect(text.className).toContain("text-info-muted-foreground");
    expect(text.className).not.toContain("bg-info-muted");
  });
});

describe("EmploymentNotice", () => {
  it("mówi, u kogo, do kiedy i kto jest Delivery Leadem", () => {
    render(<EmploymentNotice marker={WORKING} personName="Anna Przykładowa" />);

    const notice = screen.getByRole("note");
    expect(within(notice).getByText("Anna Przykładowa pracuje u nas · Bank Przykładowy")).toBeInTheDocument();
    expect(
      within(notice).getByText("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy"),
    ).toBeInTheDocument();
    expect(within(notice).getByText("Przed wysłaniem profilu zapytaj Delivery.")).toBeInTheDocument();
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

    expect(screen.getByText("Anna Przykładowa pracuje u nas · Bank Przykładowy")).toBeInTheDocument();
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
    expect(notice).toHaveTextContent("Anna Przykładowa — pracuje u nas · Bank Przykładowy · do 31.12.2026");
    expect(notice).toHaveTextContent("Piotr Fikcyjny — zaczyna u nas 01.11.2026 · Telekom Przykładowy");
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
    await userEvent.click(screen.getByRole("button", { name: "Pracuje u nas · do 31.12" }));

    expect(
      within(screen.getByRole("note")).getByText("Pracuje u nas · Bank Przykładowy"),
    ).toBeInTheDocument();
  });
});
