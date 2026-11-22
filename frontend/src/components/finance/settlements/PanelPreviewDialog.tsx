"use client";

// „Zobacz panel jak konsultant” z karty osoby w Rozliczeniach (tryb „Tylko zespół”,
// decyzja Artura 16.11.2026). Te same ekrany co panel konsultanta, wypełnione danymi
// z trasy podglądu Finansów: osobny QueryClient z gotowymi danymi pod kluczami panelu,
// więc ekrany niczego nie pobierają same (sesji konsultanta tu nie ma). Treść jest
// `inert`: podgląd niczego nie wysyła i niczego nie zmienia.
import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds";
import { AppModal } from "@/components/ds/AppModal";
import {
  InvoicesScreen,
  SettlementScreen,
  StartScreen,
} from "@/components/consultant-portal/PanelScreens";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  usePanelPreview,
  type PanelPreview,
} from "@/lib/api/client-settlements";
import { portalKeys } from "@/lib/api/consultant-portal";

type Screen = "start" | "settlement" | "invoices";

const SCREENS: readonly { value: Screen; label: string }[] = [
  { value: "start", label: "Start" },
  { value: "settlement", label: "Rozliczenia" },
  { value: "invoices", label: "Faktury" },
];

export function previewClient(data: PanelPreview): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
    },
  });
  client.setQueryData(portalKeys.me, data.me);
  client.setQueryData(portalKeys.todo, data.todo);
  client.setQueryData(portalKeys.settlement, data.settlement);
  client.setQueryData(portalKeys.finance, data.finance);
  client.setQueryData(portalKeys.meetings, { items: [], note: "" });
  return client;
}

function PreviewScreens({ data }: { data: PanelPreview }) {
  const [screen, setScreen] = useState<Screen>("start");
  const client = useMemo(() => previewClient(data), [data]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedRadio
          label="Ekran panelu"
          size="sm"
          value={screen}
          options={SCREENS}
          onChange={setScreen}
        />
        <p className="text-xs text-muted-foreground">
          {data.activated
            ? "Panel tej osoby jest aktywowany."
            : "Panel tej osoby nie jest aktywowany: konsultant tego nie widzi."}
        </p>
      </div>
      <p className="rounded-lg bg-warning-muted px-3 py-2 text-[13px] text-warning-muted-foreground">
        Podgląd: tak zobaczy to konsultant. Przyciski nie działają i nic nie
        zostanie wysłane.
      </p>
      <div inert className="rounded-xl border bg-background p-4">
        <QueryClientProvider client={client}>
          {screen === "start" ? <StartScreen me={data.me} /> : null}
          {screen === "settlement" ? <SettlementScreen me={data.me} /> : null}
          {screen === "invoices" ? <InvoicesScreen /> : null}
        </QueryClientProvider>
      </div>
    </div>
  );
}

export function PanelPreviewDialog({
  contractId,
  person,
  onClose,
}: {
  contractId: number;
  person: string;
  onClose: () => void;
}) {
  const preview = usePanelPreview(contractId);
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title={`Panel oczami konsultanta: ${person}`}
      size="2xl"
    >
      {preview.isError ? (
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(
            preview.error,
            "Nie udało się wczytać podglądu panelu.",
          )}
          onRetry={() => preview.refetch()}
        />
      ) : preview.isSuccess ? (
        <PreviewScreens data={preview.data} />
      ) : (
        <div className="py-10 text-center text-sm text-muted-foreground">
          Ładowanie…
        </div>
      )}
    </AppModal>
  );
}
