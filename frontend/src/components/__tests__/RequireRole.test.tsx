import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { RequireRole } from "@/components/RequireRole";
import { useAuthStore } from "@/store/auth";

/**
 * „Nie wiem jeszcze" ≠ „nie wolno".
 *
 * Regresja z produkcji: admin wchodzący na `/finance` widział przez kilka
 * sekund „Brak uprawnień. Moduł Finanse wymaga uprawnień finansowych. Poproś
 * administratora o dostęp." — komunikat fałszywy i wskazujący winnego, którym
 * był sam adresat. Przyczyna: `RequireRole` czytał tylko `user`, a ten jest
 * `null` do czasu `hydrate()` (tożsamość leży w localStorage, SSR jej nie zna).
 * Dla wywołań z domyślnym `fallback={null}` okno było niewidoczne; wystarczyło
 * podać własny komunikat, żeby zaczęło kłamać.
 */

function setAuthState(partial: Record<string, unknown>) {
  useAuthStore.setState(partial as never);
}

describe("RequireRole — stan przed hydracją", () => {
  beforeEach(() => {
    setAuthState({ user: null, token: null, realUser: null, hydrated: false });
  });

  it("NIE renderuje fallbacku, dopóki tożsamość nie jest znana", () => {
    render(
      <RequireRole roles={["admin"]} fallback={<p>Brak uprawnień</p>}>
        <p>tajne</p>
      </RequireRole>,
    );

    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
    expect(screen.queryByText("tajne")).not.toBeInTheDocument();
  });

  it("renderuje `pending`, jeśli podano — zamiast odmowy", () => {
    render(
      <RequireRole
        roles={["admin"]}
        fallback={<p>Brak uprawnień</p>}
        pending={<p>Ładowanie…</p>}
      >
        <p>tajne</p>
      </RequireRole>,
    );

    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
  });

  it("NIE przepuszcza dzieci przed hydracją (bramka nie jest osłabiona)", () => {
    // Kluczowe: poprawka nie może zamienić „nie wiem" w „wpuść".
    setAuthState({ user: { role: "admin", roles: ["admin"] }, hydrated: false });
    render(
      <RequireRole roles={["admin"]}>
        <p>tajne</p>
      </RequireRole>,
    );
    expect(screen.queryByText("tajne")).not.toBeInTheDocument();
  });
});

describe("RequireRole — po hydracji", () => {
  it("admin widzi moduł bramkowany na admin+finance", () => {
    setAuthState({
      user: { role: "admin", roles: ["admin"] },
      hydrated: true,
    });
    render(
      <RequireRole
        roles={["admin", "finance"]}
        fallback={<p>Brak uprawnień</p>}
      >
        <p>Finanse</p>
      </RequireRole>,
    );
    expect(screen.getByText("Finanse")).toBeInTheDocument();
    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
  });

  it("rola bez dostępu dostaje fallback — dopiero TERAZ odmowa jest prawdziwa", () => {
    setAuthState({
      user: { role: "recruiter", roles: ["recruiter"] },
      hydrated: true,
    });
    render(
      <RequireRole
        roles={["admin", "finance"]}
        fallback={<p>Brak uprawnień</p>}
      >
        <p>Finanse</p>
      </RequireRole>,
    );
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Finanse")).not.toBeInTheDocument();
  });

  it("rola `finance` też widzi moduł (dwie rozłączne publiczności)", () => {
    setAuthState({
      user: { role: "finance", roles: ["finance"] },
      hydrated: true,
    });
    render(
      <RequireRole roles={["admin", "finance"]}>
        <p>Finanse</p>
      </RequireRole>,
    );
    expect(screen.getByText("Finanse")).toBeInTheDocument();
  });
});
