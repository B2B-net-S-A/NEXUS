import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ForbiddenPage from "@/app/403/page";
import { useAuthStore } from "@/store/auth";

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null } as never);
});

// O dostępie decyduje uprawnienie konta, nie sama rola — strona odmowy mówi,
// kto i gdzie może je nadać, i nie obiecuje konkretnego uprawnienia (nie wie,
// którego zabrakło).
describe("strona 403", () => {
  it("mówi o brakującym uprawnieniu i wskazuje administratora oraz panel „Osoby i role”", () => {
    useAuthStore.setState({
      user: { id: 1, role: "recruiter", roles: ["recruiter"] },
    } as never);
    render(<ForbiddenPage />);

    // Nagłówek czyta test e2e `rbac-deny.spec.ts` — zostaje bez zmian.
    expect(
      screen.getByRole("heading", { name: "403 — Brak uprawnień" }),
    ).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Nie masz uprawnienia do tej części aplikacji.");
    expect(text).toContain("poproś administratora o dostęp");
    expect(text).toContain("Ustawienia → Zespół i dostęp → Osoby i role");
    expect(text).not.toMatch(/zastrzeżona dla innych ról/);
  });

  it("nie nazywa konkretnego uprawnienia — strona nie wie, którego zabrakło", () => {
    render(<ForbiddenPage />);

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/Brakuje Ci uprawnienia „/);
    expect(text).not.toMatch(/Moduł Finanse|Stawki i kwoty|Klienci, kontrakty i zamówienia/);
  });

  it("zostawia drogę wyjścia: stronę główną i profil", () => {
    render(<ForbiddenPage />);

    expect(screen.getByRole("link", { name: "Wróć na stronę główną" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Mój profil" })).toHaveAttribute(
      "href",
      "/profile",
    );
  });
});
