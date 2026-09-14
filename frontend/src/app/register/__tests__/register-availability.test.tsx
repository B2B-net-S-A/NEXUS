import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), register: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.get },
  authApi: { register: mocks.register, resendVerification: vi.fn() },
}));
vi.mock("@/components/blocks/AuthShell", () => ({
  AuthShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import RegisterPage from "@/app/register/page";

describe("/register — wyłączona rejestracja (UAT M12-B06)", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.register.mockReset();
  });

  it("przy self_registration=false od razu mówi o wyłączeniu, bez formularza", async () => {
    mocks.get.mockResolvedValue({ data: { password: false, microsoft: true, self_registration: false } });
    render(<RegisterPage />);

    expect(await screen.findByText("Rejestracja jest obecnie wyłączona")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Email służbowy/)).toBeNull();
    expect(mocks.get).toHaveBeenCalledWith("/api/auth/methods");
  });

  it("przy włączonej rejestracji pokazuje formularz", async () => {
    mocks.get.mockResolvedValue({ data: { self_registration: true } });
    render(<RegisterPage />);

    expect(await screen.findByLabelText(/Email służbowy/)).toBeInTheDocument();
  });

  it("503 po wysłaniu zamienia formularz na komunikat o wyłączeniu", async () => {
    mocks.get.mockResolvedValue({ data: { self_registration: true } });
    mocks.register.mockRejectedValue({ response: { status: 503, data: { detail: "x" } } });
    const { container } = render(<RegisterPage />);

    fireEvent.change(await screen.findByLabelText(/Imię i nazwisko/), { target: { value: "Jan Test" } });
    fireEvent.change(screen.getByLabelText(/Email służbowy/), { target: { value: "jan@example.com" } });
    const passwords = container.querySelectorAll('input[type="password"]');
    passwords.forEach((input) => fireEvent.change(input, { target: { value: "haslo-testowe-1" } }));
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() =>
      expect(screen.getByText("Rejestracja jest obecnie wyłączona")).toBeInTheDocument(),
    );
    expect(container.querySelector("form")).toBeNull();
  });
});
