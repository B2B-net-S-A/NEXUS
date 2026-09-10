"use client";

// Jednorazowe czyszczenie zakładki „Nieaktywni klienci".
//
// Przepływ: podgląd (serwer tylko czyta) → administrator zaznacza, że rozumie,
// co zostanie usunięte → wykonanie → raport z dwiema listami. Serwer usuwa
// WYŁĄCZNIE klientów z listy pokazanej w tym podglądzie, którzy w chwili
// wykonania nadal się kwalifikują — ktoś, kto zakwalifikował się później,
// trafia na listę wstrzymanych, bo nikt go tu nie widział.
//
// Bez `window.confirm`: natywny dialog zamraża automatyzację przeglądarki,
// a potwierdzenie w treści okna i tak mówi więcej (liczba + nazwy).

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, PauseCircle, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  inactiveClientsCleanupApi,
  type InactiveCleanupClient,
  type InactiveCleanupDeletedClient,
  type InactiveCleanupPreview,
  type InactiveCleanupReport,
} from "@/lib/api";
import { httpStatusFromError } from "@/lib/view-state";

export const INACTIVE_CLEANUP_STATUS_KEY = ["inactive-clients-cleanup", "status"];
const PREVIEW_KEY = ["inactive-clients-cleanup", "preview"];

function errorDetail(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Liczebnik w dopełniaczu („sprawdzono 3 klientów", „1 klienta"). */
function clientCountLabel(count: number): string {
  return count === 1 ? "1 klienta" : `${count} klientów`;
}

function sourceSystemLabel(
  source: string | null | undefined,
  externalId: string | null | undefined,
): string | null {
  if (!source || source === "manual") return null;
  const name = source === "traffit" ? "Traffit" : source;
  return externalId ? `${name} #${externalId}` : name;
}

function ClientIdentity({
  client,
}: {
  client: Pick<
    InactiveCleanupClient,
    "name" | "nip" | "legal_name" | "external_source" | "external_id"
  >;
}) {
  const origin = sourceSystemLabel(client.external_source, client.external_id);
  const meta = [
    client.legal_name && client.legal_name !== client.name
      ? client.legal_name
      : null,
    client.nip ? `NIP ${client.nip}` : null,
    origin,
  ].filter(Boolean);
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-medium text-foreground">
        {client.name}
      </p>
      {meta.length ? (
        <p className="truncate text-xs text-muted-foreground">
          {meta.join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

function ListSection({
  icon,
  title,
  description,
  count,
  children,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  count: number;
  children: React.ReactNode;
  tone: "destructive" | "warning" | "neutral";
}) {
  const toneClass =
    tone === "destructive"
      ? "border-destructive/30"
      : tone === "warning"
        ? "border-warning/40"
        : "border-border";
  return (
    <section className={`rounded-lg border ${toneClass} bg-card`}>
      <header className="flex items-start gap-3 border-b border-border px-4 py-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-foreground">
            {title}{" "}
            <span className="font-normal tabular-nums text-muted-foreground">
              ({count})
            </span>
          </h3>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </header>
      {count === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">Brak.</p>
      ) : (
        <ul className="max-h-72 divide-y divide-border overflow-y-auto">
          {children}
        </ul>
      )}
    </section>
  );
}

function DeletedRow({ client }: { client: InactiveCleanupDeletedClient }) {
  return (
    <li className="px-4 py-2">
      <ClientIdentity client={client} />
    </li>
  );
}

function HeldRow({ client }: { client: InactiveCleanupClient }) {
  return (
    <li className="space-y-1.5 px-4 py-2.5">
      <ClientIdentity client={client} />
      <ul className="space-y-1">
        {client.reasons.map((reason, index) => (
          <li
            key={`${reason.code}-${reason.table ?? ""}-${index}`}
            className="text-xs text-foreground"
          >
            <span className="font-medium">{reason.label}</span>
            {reason.count > 1 ? (
              <span className="tabular-nums text-muted-foreground">
                {" "}
                ({reason.count})
              </span>
            ) : null}
            {reason.details && reason.details.length ? (
              <span className="text-muted-foreground">
                {" "}
                — {reason.details.join(", ")}
              </span>
            ) : null}
            {reason.effect ? (
              <span className="text-muted-foreground"> · {reason.effect}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </li>
  );
}

function KeptSummary({
  preview,
}: {
  preview: Pick<InactiveCleanupPreview, "kept" | "kept_by_source" | "source_labels">;
}) {
  const rows = Object.entries(preview.kept_by_source).filter(
    ([, count]) => count > 0,
  );
  return (
    <details className="rounded-lg border border-border bg-card">
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-foreground">
        <CheckCircle2
          className="mr-2 inline h-4 w-4 text-success"
          aria-hidden="true"
        />
        Zostają bez zmian — mają ślad współpracy{" "}
        <span className="font-normal tabular-nums text-muted-foreground">
          ({preview.kept.length})
        </span>
      </summary>
      <div className="space-y-3 border-t border-border px-4 py-3">
        {rows.length ? (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            {rows.map(([code, count]) => (
              <div key={code} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">
                  {preview.source_labels[code] ?? code}
                </dt>
                <dd className="tabular-nums text-foreground">{count}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <ul className="max-h-56 divide-y divide-border overflow-y-auto">
          {preview.kept.map((client) => (
            <li
              key={client.client_id}
              className="flex items-start justify-between gap-3 py-1.5"
            >
              <ClientIdentity client={client} />
              <span className="shrink-0 text-right text-xs text-muted-foreground">
                {client.sources.map((source) => source.label).join(", ")}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export function InactiveCleanupReportView({
  report,
}: {
  report: InactiveCleanupReport;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-foreground">
        <p>
          Czyszczenie wykonano {formatDateTime(report.executed_at)}
          {report.executed_by_name ? ` (${report.executed_by_name})` : ""}.
        </p>
        <p className="mt-1 text-muted-foreground">
          Sprawdzono {clientCountLabel(report.candidates_count)}: usunięto{" "}
          <span className="font-medium text-foreground tabular-nums">
            {report.deleted_count}
          </span>
          , wstrzymano{" "}
          <span className="font-medium text-foreground tabular-nums">
            {report.held_count}
          </span>
          , bez zmian{" "}
          <span className="font-medium text-foreground tabular-nums">
            {report.kept_count}
          </span>
          . Operacja była jednorazowa — nie uruchomi się ponownie.
        </p>
      </div>
      <ListSection
        tone="destructive"
        icon={<Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />}
        title="Lista A — klienci trwale usunięci"
        description="Bez żadnego śladu współpracy i bez innych powiązanych danych."
        count={report.deleted.length}
      >
        {report.deleted.map((client) => (
          <DeletedRow key={client.client_id} client={client} />
        ))}
      </ListSection>
      <ListSection
        tone="warning"
        icon={
          <PauseCircle className="h-4 w-4 text-warning" aria-hidden="true" />
        }
        title="Lista B — wstrzymani, do decyzji ręcznej"
        description="Bez śladu współpracy, ale z innymi danymi, które usunięcie by skasowało. Pozostają w zakładce „Nieaktywni klienci”."
        count={report.held.length}
      >
        {report.held.map((client) => (
          <HeldRow key={client.client_id} client={client} />
        ))}
      </ListSection>
    </div>
  );
}

export function InactiveCleanupPreviewView({
  preview,
}: {
  preview: InactiveCleanupPreview;
}) {
  const sources = Object.values(preview.source_labels).join(", ");
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-foreground">
        <p>
          Sprawdzono {clientCountLabel(preview.candidates_count)} z zakładki
          „Nieaktywni klienci”. Klient zostaje bez zmian, jeśli ma którykolwiek
          ślad współpracy: {sources}.
        </p>
        <p className="mt-1 text-muted-foreground">
          Klient bez śladu współpracy, ale z innymi powiązanymi danymi, nie
          zostanie usunięty — trafi na listę do decyzji ręcznej. Pozostali
          zostaną usunięci trwale. Nic nie zostało jeszcze zmienione.
        </p>
      </div>
      <ListSection
        tone="destructive"
        icon={<Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />}
        title="Do trwałego usunięcia"
        description="Brak śladu współpracy i brak innych powiązanych danych."
        count={preview.to_delete.length}
      >
        {preview.to_delete.map((client) => (
          <li key={client.client_id} className="px-4 py-2">
            <ClientIdentity client={client} />
          </li>
        ))}
      </ListSection>
      <ListSection
        tone="warning"
        icon={
          <PauseCircle className="h-4 w-4 text-warning" aria-hidden="true" />
        }
        title="Wstrzymani — do decyzji ręcznej"
        description="Usunięcie skasowałoby albo osierociło znalezione dane. Zostają w zakładce."
        count={preview.held.length}
      >
        {preview.held.map((client) => (
          <HeldRow key={client.client_id} client={client} />
        ))}
      </ListSection>
      <KeptSummary preview={preview} />
    </div>
  );
}

/** Potwierdzenie + przyciski stopki. Usunięcie jest nieaktywne bez zgody. */
export function InactiveCleanupConfirm({
  deleteCount,
  acknowledged,
  executing,
  onAcknowledgedChange,
  onCancel,
  onExecute,
}: {
  deleteCount: number;
  acknowledged: boolean;
  executing: boolean;
  onAcknowledgedChange: (value: boolean) => void;
  onCancel: () => void;
  onExecute: () => void;
}) {
  return (
    <>
      <label className="mr-auto flex max-w-md items-start gap-2 text-left text-xs text-foreground">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 shrink-0 accent-destructive"
          checked={acknowledged}
          disabled={executing}
          onChange={(event) => onAcknowledgedChange(event.target.checked)}
        />
        <span>
          {deleteCount > 0
            ? `Rozumiem, że klienci z listy „Do trwałego usunięcia” (${deleteCount}) zostaną usunięci na zawsze. Operacja jest jednorazowa.`
            : "Rozumiem, że nic nie zostanie usunięte, a raport zakończy jednorazową operację."}
        </span>
      </label>
      <Button variant="outline" disabled={executing} onClick={onCancel}>
        Anuluj
      </Button>
      <Button
        variant="destructive"
        disabled={!acknowledged || executing}
        loading={executing}
        onClick={onExecute}
      >
        {deleteCount > 0
          ? `Usuń trwale (${deleteCount})`
          : "Zakończ i zapisz raport"}
      </Button>
    </>
  );
}

export function InactiveClientsCleanupDialog({
  onClose,
  onExecuted,
}: {
  onClose: () => void;
  onExecuted: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [acknowledged, setAcknowledged] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [freshReport, setFreshReport] = useState<InactiveCleanupReport | null>(
    null,
  );

  const statusQuery = useQuery({
    queryKey: INACTIVE_CLEANUP_STATUS_KEY,
    queryFn: () =>
      inactiveClientsCleanupApi.status().then((response) => response.data),
    retry: false,
  });
  const alreadyExecuted = Boolean(statusQuery.data?.report);
  const previewQuery = useQuery({
    queryKey: PREVIEW_KEY,
    queryFn: () =>
      inactiveClientsCleanupApi.preview().then((response) => response.data),
    enabled: statusQuery.isSuccess && !alreadyExecuted && !freshReport,
    retry: false,
    // Podgląd ma pokazywać stan z chwili otwarcia okna, nie z pamięci.
    gcTime: 0,
    staleTime: 0,
  });

  const report = freshReport ?? statusQuery.data?.report ?? null;
  const preview = previewQuery.data;
  const deleteCount = preview?.to_delete.length ?? 0;

  const execute = async () => {
    if (!preview || executing || !acknowledged) return;
    setExecuting(true);
    setExecuteError(null);
    try {
      const response = await inactiveClientsCleanupApi.execute(
        preview.to_delete.map((client) => client.client_id),
      );
      setFreshReport(response.data);
      void queryClient.invalidateQueries({
        queryKey: INACTIVE_CLEANUP_STATUS_KEY,
      });
      void queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
      onExecuted(
        `Czyszczenie zakończone: usunięto ${response.data.deleted_count}, wstrzymano ${response.data.held_count}.`,
      );
    } catch (error) {
      if (httpStatusFromError(error) === 409) {
        // Ktoś wykonał operację w międzyczasie — pokaż jego raport.
        void statusQuery.refetch();
      }
      setExecuteError(
        errorDetail(error, "Nie udało się wykonać czyszczenia. Spróbuj ponownie."),
      );
    } finally {
      setExecuting(false);
    }
  };

  let body: React.ReactNode;
  if (statusQuery.isError) {
    body = (
      <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {errorDetail(statusQuery.error, "Nie udało się sprawdzić stanu czyszczenia.")}
      </p>
    );
  } else if (report) {
    body = <InactiveCleanupReportView report={report} />;
  } else if (previewQuery.isError) {
    body = (
      <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {errorDetail(previewQuery.error, "Nie udało się przygotować podglądu.")}
      </p>
    );
  } else if (previewQuery.isSuccess && preview) {
    body = <InactiveCleanupPreviewView preview={preview} />;
  } else {
    // Ładowanie — także przerwa, zanim zapytanie o podgląd w ogóle ruszy.
    // Pusty stan wisi WYŁĄCZNIE na `isSuccess` (awaria ≠ pustka).
    body = (
      <div className="space-y-3" aria-busy="true">
        <p className="text-sm text-muted-foreground">
          Sprawdzam klientów z zakładki „Nieaktywni klienci”…
        </p>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const showExecuteControls = !report && previewQuery.isSuccess && preview;

  return (
    <AppModal
      open
      size="xl"
      onOpenChange={(open) => {
        if (!open && !executing) onClose();
      }}
      title="Czyszczenie listy nieaktywnych klientów"
      description={
        report
          ? "Raport jednorazowej operacji: klienci usunięci i wstrzymani do decyzji ręcznej."
          : "Jednorazowe usunięcie klientów, u których nie ma żadnego śladu współpracy."
      }
      footer={
        showExecuteControls ? (
          <InactiveCleanupConfirm
            deleteCount={deleteCount}
            acknowledged={acknowledged}
            executing={executing}
            onAcknowledgedChange={setAcknowledged}
            onCancel={onClose}
            onExecute={() => void execute()}
          />
        ) : (
          <Button variant="outline" disabled={executing} onClick={onClose}>
            Zamknij
          </Button>
        )
      }
    >
      <div className="space-y-4">
        {executeError ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {executeError}
          </p>
        ) : null}
        {body}
      </div>
    </AppModal>
  );
}
