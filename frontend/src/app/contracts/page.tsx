"use client";

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";
import {
  ContractsClientPicker,
  type ClientRef,
} from "@/components/contracts/ContractsClientPicker";
import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

type ViewMode = "operations" | "register";

/**
 * /contracts is one workspace with two modes:
 *  - "register"   — the full contract register (global list or per-client),
 *                   financial-gated. Default; visible to everyone who can open
 *                   /contracts today.
 *  - "operations" — the contractor roster (drafty do uzupełnienia / aktywni /
 *                   kończący się). Role-gated to the same roles the former
 *                   standalone "Kontraktorzy" nav item used. The backend
 *                   enforces access independently (403 for viewers), so the
 *                   toggle is UX, not the security boundary.
 *
 * The former /contractors route now redirects here with ?view=operations.
 *
 * Workspace state lives in the URL via the History API
 * (?view=&client=&clientName=) so deep-links + back/forward work. We read it
 * after mount and avoid useSearchParams to skip the Next 15 streaming-SSR
 * Suspense boundary (same reason as the mounted gate below).
 */

const OPERATIONS_ROLES = [
  "admin",
  "delivery_lead",
  "tac",
  "head_of_recruitment",
] as const;

export default function ContractsPage() {
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<ViewMode>("register");
  const [client, setClient] = useState<ClientRef | null>(null);
  const { user } = useAuthStore();
  const canSeeOperations = hasRole(user, ...OPERATIONS_ROLES);

  useEffect(() => {
    setMounted(true);
    const params = new URLSearchParams(window.location.search);
    if (params.get("view") === "operations") setView("operations");
    const id = params.get("client");
    const name = params.get("clientName");
    if (id) setClient({ id: Number(id), name: name ?? `#${id}` });
  }, []);

  // Guard: a non-operational role that deep-links ?view=operations falls back
  // to the register (and the backend would 403 the roster fetch anyway).
  const showOperations = view === "operations" && canSeeOperations;

  const changeView = (next: ViewMode) => {
    setView(next);
    const params = new URLSearchParams(window.location.search);
    if (next === "operations") {
      params.set("view", "operations");
      // Client scope is a register-only concept.
      params.delete("client");
      params.delete("clientName");
      setClient(null);
    } else {
      params.delete("view");
    }
    const qs = params.toString();
    window.history.replaceState(null, "", `/contracts${qs ? `?${qs}` : ""}`);
  };

  const handleClientChange = (next: ClientRef | null) => {
    setClient(next);
    const params = new URLSearchParams(window.location.search);
    if (next) {
      params.set("client", String(next.id));
      params.set("clientName", next.name);
    } else {
      params.delete("client");
      params.delete("clientName");
    }
    const qs = params.toString();
    window.history.replaceState(null, "", `/contracts${qs ? `?${qs}` : ""}`);
  };

  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie kontraktów…</div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      {canSeeOperations && (
        <div
          role="tablist"
          aria-label="Tryb modułu Kontrakty"
          className="inline-flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-muted/40 p-1"
        >
          <ModeButton active={showOperations} onClick={() => changeView("operations")}>
            Obsługa kontraktorów
          </ModeButton>
          <ModeButton active={!showOperations} onClick={() => changeView("register")}>
            Rejestr kontraktów
          </ModeButton>
        </div>
      )}

      {showOperations ? (
        <Suspense
          fallback={
            <div className="p-8 text-sm text-muted-foreground">
              Ładowanie kontraktorów…
            </div>
          }
        >
          <ContractorsListV2 />
        </Suspense>
      ) : (
        <>
          <ContractsClientPicker value={client} onChange={handleClientChange} />
          {client ? (
            <ClientContractRegister clientId={client.id} clientName={client.name} />
          ) : (
            <ContractsListV2 />
          )}
        </>
      )}
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
        active
          ? "bg-background text-foreground shadow-xs"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}
