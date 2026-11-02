import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvFileNameRow } from "@/components/v2/recruitment/CvFileNameRow";
import { candidateStageCvApi } from "@/lib/api";

const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess, showError }) }));
vi.mock("@/lib/api", () => ({ candidateStageCvApi: { branded: { rename: vi.fn() } } }));

const rename = vi.mocked(candidateStageCvApi.branded.rename);

describe("CvFileNameRow", () => {
  beforeEach(() => vi.clearAllMocks());

  it("zapisuje nazwę bez końcówki i pokazuje nową", async () => {
    rename.mockResolvedValue({ data: { filename: "Nowa_nazwa.docx", pattern_filename: "Wzor.docx" } } as never);
    render(<CvFileNameRow stageId={7} filename="Wzor.docx" />);
    await userEvent.click(screen.getByRole("button", { name: "Zmień nazwę" }));
    const input = screen.getByLabelText("Nazwa pliku");
    expect(input).toHaveValue("Wzor");
    await userEvent.clear(input);
    await userEvent.type(input, "Nowa_nazwa");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz nazwę" }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith(7, "Nowa_nazwa.docx"));
    expect(await screen.findByText("Nowa_nazwa.docx")).toBeTruthy();
    expect(showSuccess).toHaveBeenCalled();
  });

  it("wraca do wzoru klienta po ręcznej zmianie", async () => {
    render(<CvFileNameRow stageId={7} filename="Nowa.docx" patternFilename="Wzor.docx" />);
    await userEvent.click(screen.getByRole("button", { name: "Zmień nazwę" }));
    await userEvent.click(screen.getByRole("button", { name: "Wróć do wzoru" }));
    expect(screen.getByLabelText("Nazwa pliku")).toHaveValue("Wzor");
  });

  it("bez nazwy nie zapisuje, a błąd serwera zostawia okno otwarte", async () => {
    rename.mockRejectedValue(new Error("nope"));
    render(<CvFileNameRow stageId={7} filename="Wzor.docx" />);
    await userEvent.click(screen.getByRole("button", { name: "Zmień nazwę" }));
    const input = screen.getByLabelText("Nazwa pliku");
    await userEvent.clear(input);
    expect(screen.getByRole("button", { name: "Zapisz nazwę" })).toBeDisabled();
    await userEvent.type(input, "X");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz nazwę" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("w trybie tylko do odczytu nie daje zmiany", () => {
    render(<CvFileNameRow stageId={7} filename="Wzor.docx" readOnly />);
    expect(screen.queryByRole("button", { name: "Zmień nazwę" })).toBeNull();
  });
});
