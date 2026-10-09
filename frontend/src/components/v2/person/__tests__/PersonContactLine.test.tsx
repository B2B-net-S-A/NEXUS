/**
 * Linia kontaktu pod nazwiskiem w panelu osoby (09.10.2026). Dane fikcyjne.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { PersonContactLine } from "@/components/v2/person/PersonContactLine";

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PersonContactLine", () => {
  it("numer jest linkiem tel: bez spacji, adres zwykłym tekstem", () => {
    render(<PersonContactLine phone="+48 600 100 200" email="jan@example.com" personName="Jan Przykładowy" />);
    expect(screen.getByRole("link", { name: "+48 600 100 200" })).toHaveAttribute("href", "tel:+48600100200");
    expect(screen.getByText("jan@example.com")).toBeInTheDocument();
  });

  it("pokazuje tylko to, co profil ma; bez obu pól nie renderuje nic", () => {
    const { rerender, container } = render(
      <PersonContactLine phone="  " email="jan@example.com" personName="Jan Przykładowy" />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("button", { name: "Kopiuj adres e-mail: Jan Przykładowy" })).toBeInTheDocument();
    rerender(<PersonContactLine phone={null} email={undefined} personName="Jan Przykładowy" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("kopiowanie mówi, czy się udało", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(<PersonContactLine phone="600 100 200" email={null} personName="Jan Przykładowy" />);
    await user.click(screen.getByRole("button", { name: "Kopiuj numer: Jan Przykładowy" }));
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Skopiowano numer telefonu"));
    expect(writeText).toHaveBeenCalledWith("600 100 200");

    stubClipboard(vi.fn().mockRejectedValue(new Error("odmowa")));
    await user.click(screen.getByRole("button", { name: "Kopiuj numer: Jan Przykładowy" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Nie udało się skopiować numeru — zaznacz go ręcznie."),
    );
  });
});
