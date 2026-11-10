import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
const startDuty = vi.fn();
vi.mock("@/lib/duty-search-api", () => ({
  dutySearchApi: { start: (...args: unknown[]) => startDuty(...args) },
}));

let user: Record<string, unknown> | null = null;
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: unknown) => unknown) => select({ user }),
}));
vi.mock("@/components/talent-radar/TalentRadarClientPicker", () => ({
  TalentRadarClientPicker: ({ onChange }: { onChange: (c: { id: number; name: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 5, name: "Bank SA" })}>
      Wybierz klienta
    </button>
  ),
}));
vi.mock("@/components/v2/recruitment/JobPicker", () => ({
  JobPicker: ({ onChange }: { onChange: (j: { id: number; title: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 9, title: "Java Developer" })}>
      Wybierz rekrutację
    </button>
  ),
}));

import { RequestSearchDialog } from "@/components/v2/candidates/RequestSearchDialog";

const LONG_TEXT = "Szukamy Senior Java Developera, Spring Boot, Kafka, praca hybrydowa w Warszawie.";

function renderDialog(props: Partial<Parameters<typeof RequestSearchDialog>[0]> = {}) {
  const onSubmit = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
      <RequestSearchDialog open onOpenChange={onOpenChange} onSubmit={onSubmit} {...props} />
    </QueryClientProvider>,
  );
  return { onSubmit, onOpenChange, dialog: screen.getByRole("dialog") };
}

describe("RequestSearchDialog", () => {
  beforeEach(() => {
    user = { id: 1, role: "recruiter", effective_section_access: { pipeline: "read" } };
  });

  it("trzy źródła wymagań; bez odczytu rekrutacji zostają dwa", () => {
    const { dialog } = renderDialog();
    expect(within(dialog).getByText("Skąd bierzemy wymagania?")).toBeTruthy();
    expect(within(dialog).getAllByRole("radio").map((r) => r.textContent)).toEqual([
      expect.stringContaining("Wklej tekst"),
      expect.stringContaining("Wgraj plik Championa"),
      expect.stringContaining("Rekrutacja z NEXUSA"),
    ]);
  });

  it("bez odczytu pipeline'u nie ma kafla rekrutacji", () => {
    user = { id: 1, role: "user", effective_section_access: { pipeline: "none" } };
    const { dialog } = renderDialog();
    expect(within(dialog).getAllByRole("radio")).toHaveLength(2);
  });

  it("klient jest wymagany, a dane idą dalej jednym obiektem", () => {
    const { dialog, onSubmit, onOpenChange } = renderDialog({ initialText: LONG_TEXT });
    expect(within(dialog).getByLabelText("Treść requestu")).toHaveValue(LONG_TEXT);
    fireEvent.click(within(dialog).getByRole("button", { name: "Dalej: sprawdź wymagania" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz klienta.");

    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));
    fireEvent.change(within(dialog).getByLabelText("Budżet (zł/h)"), { target: { value: "180" } });
    fireEvent.change(within(dialog).getByLabelText("Dni w biurze"), { target: { value: "2" } });
    fireEvent.change(within(dialog).getByLabelText("Miasto biura"), { target: { value: "Warszawa" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Dalej: sprawdź wymagania" }));
    expect(onSubmit).toHaveBeenCalledWith({
      source: "text",
      text: LONG_TEXT,
      file: null,
      job: null,
      client: { id: 5, name: "Bank SA" },
      budget: "180",
      officeDays: "2",
      officeCity: "Warszawa",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("miasto biura pojawia się dopiero przy dniach w biurze > 0", () => {
    const { dialog } = renderDialog();
    expect(within(dialog).queryByLabelText("Miasto biura")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Dni w biurze"), { target: { value: "0" } });
    expect(within(dialog).queryByLabelText("Miasto biura")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Dni w biurze"), { target: { value: "3" } });
    expect(within(dialog).getByLabelText("Miasto biura")).toBeTruthy();
  });

  it("rekrutacja z NEXUSA nie pyta o klienta ani budżet", () => {
    const { dialog, onSubmit } = renderDialog();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Rekrutacja z NEXUSA/ }));
    expect(within(dialog).queryByLabelText("Budżet (zł/h)")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz rekrutację" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Dalej: sprawdź wymagania" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        source: "job",
        job: { id: 9, title: "Java Developer", client_name: null },
        client: null,
      }),
    );
  });

  it("plik jest wymagany dla źródła „plik Championa”", () => {
    const { dialog, onSubmit } = renderDialog();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Wgraj plik Championa/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Dalej: sprawdź wymagania" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz plik profilu Championa.");
    const file = new File(["x"], "profil.docx");
    fireEvent.change(within(dialog).getByLabelText("Plik profilu Championa"), {
      target: { files: [file] },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Dalej: sprawdź wymagania" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ source: "file", file }));
  });

  it("„Cel projektu” startuje „Kto już to robił” z klientem i przechodzi do wyniku", async () => {
    startDuty.mockResolvedValue({ run_id: "abc-1", state: "queued", usage: { used_today: 1, daily_limit: 10 } });
    const { dialog, onSubmit, onOpenChange } = renderDialog();
    fireEvent.click(within(dialog).getByRole("tab", { name: /Cel projektu/ }));
    expect(within(dialog).queryByText("Skąd bierzemy wymagania?")).toBeNull();
    expect(within(dialog).queryByLabelText("Budżet (zł/h)")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Szukaj, kto już to robił" }));
    expect(within(dialog).getByRole("alert").textContent).toContain("Opisz, co osoba ma zrobić");
    fireEvent.change(within(dialog).getByLabelText("Co osoba ma zrobić?"), {
      target: { value: "Przenieść 40 aplikacji z serwerowni VMware do AWS i wygasić data center." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Szukaj, kto już to robił" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/candidates?mode=goal&run=abc-1"));
    expect(startDuty).toHaveBeenCalledWith({
      client_id: 5,
      goal: "Przenieść 40 aplikacji z serwerowni VMware do AWS i wygasić data center.",
    });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
