/**
 * Telefon i e-mail w nagłówku panelu rozmowy (20.10.2026): numer dzwoni
 * (`tel:` bez spacji), e-mail otwiera pocztę, „Kopiuj” bierze to, co jest,
 * a bez obu linii nie ma — rola bez odczytu kandydatów nie widzi pustej ramki.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
  copy: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...a: unknown[]) => mocks.copy(...a),
}));

import { CandidateContactLine } from "@/components/calendar/cycle/CandidateContactLine";

beforeEach(() => {
  mocks.toast.showError.mockReset();
  mocks.toast.showSuccess.mockReset();
  mocks.copy.mockReset();
});

describe("CandidateContactLine", () => {
  it("pokazuje numer jako tel: i e-mail jako mailto:", () => {
    render(<CandidateContactLine phone="+48 601 234 567" email="anna@example.com" />);
    expect(screen.getByRole("link", { name: "+48 601 234 567" })).toHaveAttribute(
      "href",
      "tel:+48601234567",
    );
    expect(screen.getByRole("link", { name: "anna@example.com" })).toHaveAttribute(
      "href",
      "mailto:anna@example.com",
    );
  });

  it("„Kopiuj oba” kopiuje telefon i e-mail razem", async () => {
    mocks.copy.mockResolvedValue(true);
    render(<CandidateContactLine phone="+48 601 234 567" email="anna@example.com" />);
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj oba" }));
    await waitFor(() => expect(mocks.toast.showSuccess).toHaveBeenCalledWith("Skopiowano telefon i e-mail"));
    expect(mocks.copy).toHaveBeenCalledWith("+48 601 234 567 · anna@example.com");
  });

  it("bez numeru zostaje e-mail i zwykłe „Kopiuj”", async () => {
    mocks.copy.mockResolvedValue(true);
    render(<CandidateContactLine phone={undefined} email="anna@example.com" />);
    expect(screen.queryByRole("link", { name: /\+48/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj" }));
    await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith("anna@example.com"));
  });

  it("nieudane kopiowanie mówi, co zrobić", async () => {
    mocks.copy.mockResolvedValue(false);
    render(<CandidateContactLine phone="601234567" email={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj" }));
    await waitFor(() =>
      expect(mocks.toast.showError).toHaveBeenCalledWith("Nie udało się skopiować — zaznacz tekst ręcznie."),
    );
  });

  it("bez telefonu i e-maila nic nie rysuje", () => {
    const { container } = render(<CandidateContactLine phone="  " email={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
