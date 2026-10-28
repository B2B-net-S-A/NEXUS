import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HOLDER_KIND_LABELS } from "@/components/equipment/equipment-format";
import { HolderPicker } from "@/components/equipment/HolderPicker";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));

const PARTICIPANT = {
  kind: "academy",
  id: 501,
  name: "Ola Przykładowa",
  email: "ola@example.com",
  detail: "Uczestnik Akademii · Akademia Rekrutera · edycja 11.2026",
};
const WORKER = {
  kind: "user",
  id: 12,
  name: "Olga Testowa",
  email: "olga@example.com",
  detail: "Konto NEXUSA",
};

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockImplementation(async (_url: string, config: { params: Record<string, string> }) => ({
    data: { items: config.params.kind === "academy" ? [PARTICIPANT] : [WORKER] },
  }));
});

describe("HolderPicker", () => {
  it("labels the academy holder kind", () => {
    expect(HOLDER_KIND_LABELS.academy).toBe("Uczestnik Akademii");
    expect(HOLDER_KIND_LABELS.contract).toBe("Kontraktor");
  });

  it("without academy mode offers only the register and people outside NEXUS", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    wrap(<HolderPicker value={null} onChange={onChange} />);
    expect(screen.queryByRole("button", { name: "Uczestnik Akademii" })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "Ol");
    await user.click(await screen.findByRole("button", { name: /Olga Testowa/ }));
    expect(onChange).toHaveBeenCalledWith(WORKER);
    expect(mocks.get).toHaveBeenCalledWith("/api/equipment/holders", { params: { q: "Ol" } });
  });

  it("finds an academy participant and hands it to the issue wizard", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    wrap(<HolderPicker academy value={null} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Uczestnik Akademii" }));
    expect(screen.queryByRole("button", { name: /Osoba spoza NEXUSA/ })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Szukaj uczestnika Akademii" }), "Ola");
    await user.click(await screen.findByRole("button", { name: /Ola Przykładowa/ }));
    expect(onChange).toHaveBeenCalledWith(PARTICIPANT);
    expect(mocks.get).toHaveBeenCalledWith("/api/equipment/holders", {
      params: { q: "Ola", kind: "academy" },
    });
  });

  it("a register-only picker never emits an academy participant", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mocks.get.mockResolvedValue({ data: { items: [PARTICIPANT] } });
    wrap(<HolderPicker value={null} onChange={onChange} />);
    await user.type(screen.getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "Ola");
    await user.click(await screen.findByRole("button", { name: /Ola Przykładowa/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the chosen academy participant with its description", () => {
    wrap(<HolderPicker academy value={{ ...PARTICIPANT, kind: "academy" }} onChange={vi.fn()} />);
    expect(screen.getByText("Ola Przykładowa")).toBeInTheDocument();
    expect(screen.getByText(/Uczestnik Akademii · Akademia Rekrutera/)).toBeInTheDocument();
  });

  it("labels the register mode for employees, consultants and people outside", () => {
    wrap(<HolderPicker academy value={null} onChange={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "Pracownik, konsultant, osoba spoza" }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Imię i nazwisko albo e-mail…")).toBeInTheDocument();
  });

  it("explains where it searched and what to do with a newcomer without an account", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({ data: { items: [] } });
    wrap(<HolderPicker academy value={null} onChange={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "sylwesiuk");
    expect(await screen.findByText("Nikt nie pasuje do „sylwesiuk”.")).toBeInTheDocument();
    expect(
      screen.getByText(/aktywnych kont NEXUSA, kontraktów konsultantów \(od szkicu do zakończenia\)/),
    ).toBeInTheDocument();
    expect(screen.getByText("Nowa osoba w firmie?")).toBeInTheDocument();
    expect(screen.getByText(/przepiszesz go jednym kliknięciem/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Osoba spoza NEXUSA/ })).toBeInTheDocument();
  });

  it("academy mode keeps its short no-match sentence", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue({ data: { items: [] } });
    wrap(<HolderPicker academy value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Uczestnik Akademii" }));
    await user.type(screen.getByRole("textbox", { name: "Szukaj uczestnika Akademii" }), "Zuza");
    expect(await screen.findByText("Nikt nie pasuje do „Zuza”.")).toBeInTheDocument();
    expect(screen.queryByText("Nowa osoba w firmie?")).toBeNull();
    expect(screen.getByPlaceholderText("Imię i nazwisko uczestnika Akademii…")).toBeInTheDocument();
  });

  it("accounts-only picker lists NEXUS accounts and cannot add a person outside", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const EXTERNAL = { kind: "external", id: 7, name: "Olga Spoza", email: null, detail: "Osoba spoza NEXUSA" };
    mocks.get.mockResolvedValue({ data: { items: [WORKER, EXTERNAL] } });
    wrap(<HolderPicker accountsOnly value={null} onChange={onChange} />);
    expect(screen.queryByRole("button", { name: /Osoba spoza NEXUSA/ })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Szukaj konta NEXUSA" }), "Ol");
    expect(await screen.findByRole("button", { name: /Olga Testowa/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Olga Spoza/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Olga Testowa/ }));
    expect(onChange).toHaveBeenCalledWith(WORKER);
  });
});
