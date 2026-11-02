"use client";

/**
 * Panel klienta pod linkiem z CV (`/k/{token}`): lista kandydatów rekrutacji,
 * dowody z CV, warunki, pliki, pytania i prośba o rozmowę. Bez konta i bez
 * powłoki aplikacji. Dostęp daje sam link, więc ekran pokazuje wyłącznie to, co
 * oddał serwer: gdy `show_rate=false`, stawki nie ma nigdzie.
 *
 * Awaria zapytania i link nieaktualny to osobne ekrany, nigdy pusta lista.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";

import {
  httpPanelTransport,
  panelKey,
  type PanelTransport,
  type PanelView,
} from "@/lib/api/clientPanel";

import { CandidatesList } from "./CandidatesList";
import { CandidateView } from "./CandidateView";
import { CompareView } from "./CompareView";
import { RequirementsChangeDialog } from "./PanelDialogs";
import { formatPanelDate } from "./panel-logic";
import { PanelContextProvider } from "./panel-context";

export interface ClientPanelAppProps {
  token: string;
  /** `?c=<public_id>` z linku: ta osoba otwiera się od razu. */
  initialPublicId?: string | null;
  /** Harness i testy: dane fikcyjne, zero zapytań. */
  transport?: PanelTransport;
}

export type PanelFailureKind = "gone" | "expired" | "failed";

export function panelFailureKind(error: unknown): PanelFailureKind {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  if (status === 410) return "expired";
  if (status === 404) return "gone";
  return "failed";
}

const STALE_HEADING = "Ten link jest nieaktualny, napisz do opiekuna procesu";
const FAILURE_COPY: Record<PanelFailureKind, { heading: string; body: string }> = {
  gone: {
    heading: STALE_HEADING,
    body: "Opiekun procesu to osoba z B2B Network, która przesłała Ci CV. Prześle aktualny link.",
  },
  expired: {
    heading: STALE_HEADING,
    body: "Minął termin ważności linku. Opiekun procesu, czyli osoba z B2B Network, która przesłała Ci CV, może go przedłużyć.",
  },
  failed: {
    heading: "Nie udało się otworzyć panelu",
    body: "To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.",
  },
};

function PanelFailure({ kind, onRetry }: { kind: PanelFailureKind; onRetry: () => void }) {
  const copy = FAILURE_COPY[kind];
  return (
    <main className="mx-auto w-full max-w-xl p-4 pt-12 sm:p-6 sm:pt-16">
      <div
        role="alert"
        className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-center sm:p-6"
      >
        <AlertCircle className="mx-auto mb-3 h-8 w-8 text-destructive" />
        <h1 className="mb-1 font-display text-lg font-semibold">{copy.heading}</h1>
        <p className="text-sm text-muted-foreground">{copy.body}</p>
        {kind === "failed" ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Ponów
          </button>
        ) : null}
      </div>
    </main>
  );
}

function PanelTopBar({ view }: { view: PanelView }) {
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-border bg-card px-4 py-2">
      <span
        aria-hidden
        className="grid h-7 w-7 place-items-center rounded-md bg-primary font-display text-[11px] font-bold text-primary-foreground"
      >
        B2B
      </span>
      <span className="text-sm font-semibold">B2B Network</span>
      {view.job.client_name ? (
        <span className="text-sm text-muted-foreground">kandydaci dla {view.job.client_name}</span>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground sm:ml-auto">
        {view.panel.expires_at ? (
          <span>Link z CV, ważny do {formatPanelDate(view.panel.expires_at)}</span>
        ) : null}
        {view.owner?.name ? <span>Opiekun: {view.owner.name}</span> : null}
      </div>
    </header>
  );
}

function readUrlCandidate(): string | null {
  return new URLSearchParams(window.location.search).get("c");
}

export function ClientPanelApp({
  token,
  initialPublicId = null,
  transport,
}: ClientPanelAppProps) {
  const client = useMemo(() => transport ?? httpPanelTransport(token), [transport, token]);
  // Osoba z wejścia decyduje o liście, gdy „inni kandydaci” są wyłączeni, więc
  // nie zmienia się przy chodzeniu po panelu.
  const [entryId] = useState(initialPublicId);
  const [openId, setOpenId] = useState<string | null>(initialPublicId);
  const [comparing, setComparing] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [changingRequirements, setChangingRequirements] = useState(false);

  const query = useQuery({
    queryKey: panelKey(token, entryId),
    queryFn: () => client.fetchPanel(entryId),
    staleTime: 30_000,
  });

  // Przycisk „wstecz” przeglądarki wraca z osoby na listę.
  useEffect(() => {
    const onPop = () => {
      setOpenId(readUrlCandidate());
      setComparing(false);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = useCallback((publicId: string | null) => {
    setOpenId(publicId);
    setComparing(false);
    const url = new URL(window.location.href);
    if (publicId) url.searchParams.set("c", publicId);
    else url.searchParams.delete("c");
    window.history.pushState(null, "", url.toString());
  }, []);

  const contextValue = useMemo(
    () => ({ token, transport: client, view: query.data ?? null }),
    [token, client, query.data],
  );

  if (query.isPending) {
    return (
      <div className="grid h-dvh place-items-center text-sm text-muted-foreground" role="status">
        Wczytuję panel…
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <PanelFailure kind={panelFailureKind(query.error)} onRetry={() => void query.refetch()} />
    );
  }

  const view = query.data;
  const current = view.candidates.find((item) => item.public_id === openId) ?? null;
  const comparedCandidates = compareIds
    .map((id) => view.candidates.find((item) => item.public_id === id))
    .filter((item) => item != null);

  return (
    <PanelContextProvider value={contextValue}>
      <div className="flex h-dvh flex-col bg-background text-foreground" data-testid="client-panel">
        <PanelTopBar view={view} />
        {current ? (
          <CandidateView
            key={current.public_id}
            view={view}
            candidate={current}
            onBack={() => open(null)}
            onOpen={open}
          />
        ) : comparing && comparedCandidates.length >= 2 ? (
          <CompareView
            view={view}
            candidates={comparedCandidates}
            onBack={() => setComparing(false)}
            onOpen={open}
          />
        ) : (
          <CandidatesList
            view={view}
            selected={compareIds}
            onSelectedChange={setCompareIds}
            onCompare={() => setComparing(true)}
            onOpen={open}
            onChangeRequirements={() => setChangingRequirements(true)}
          />
        )}
        {changingRequirements ? (
          <RequirementsChangeDialog
            ownerName={view.owner?.name ?? null}
            onClose={() => setChangingRequirements(false)}
          />
        ) : null}
      </div>
    </PanelContextProvider>
  );
}
