"use client";

import { useState } from "react";
import { Link2, RefreshCw } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useIntuneDiscrepancies,
  useIntuneStatus,
  useIntuneSync,
  useUnresolveIntuneDevice,
  type IntuneDiscrepancy,
  type IntuneResolution,
  type IntuneResolvedRow,
} from "@/lib/api/equipment-intune";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";

import { CATEGORY_LABELS, ITEM_STATUS_LABELS } from "./equipment-format";
import { FilterSelect } from "./FilterSelect";
import { LinkDialog, ResolveDialog, type ResolveTarget } from "./IntuneDialogs";
import {
  INTUNE_KINDS,
  INTUNE_KIND_LABELS,
  INTUNE_MODE_LABELS,
  KIND_HINTS,
  KIND_TONE,
  MODE_NOTE,
  RESOLUTION_LABELS,
  RESOLVED_VIEW,
  intuneStatusTone,
  type IntuneFilter,
} from "./intune-format";

interface IntuneTabProps {
  /** Ręczny odczyt uruchamia tylko admin. */
  isAdmin: boolean;
  onOpenItem: (itemId: number) => void;
}

/** „Intune”: stan nocnego odczytu i rozjazdy z rejestrem (zamiast zakładki „InTune” w Excelu). */
export function IntuneTab({ isAdmin, onOpenItem }: IntuneTabProps) {
  const { showToast } = useToast();
  const status = useIntuneStatus();
  const report = useIntuneDiscrepancies();
  const sync = useIntuneSync();
  const unresolve = useUnresolveIntuneDevice();
  const [kind, setKind] = useState<IntuneFilter | "">("");
  const [resolving, setResolving] = useState<ResolveTarget | null>(null);
  const [linking, setLinking] = useState<IntuneDiscrepancy | null>(null);

  const all = report.data?.rows ?? [];
  const resolved = report.data?.resolved ?? [];
  const showResolved = kind === RESOLVED_VIEW;
  const rows = kind && !showResolved ? all.filter((row) => row.kind === kind) : all;
  const counts = report.data?.counts;
  const state = resolveViewState({
    isLoading: report.isLoading,
    error: report.error,
    isSuccess: report.isSuccess,
    isEmpty: all.length === 0,
  });

  const runSync = () =>
    sync.mutate(undefined, {
      onSuccess: (result) => {
        if (result.status === "ok") {
          showToast(`Odczytano urządzenia z Intune: ${result.devices ?? 0}`, "success");
        } else {
          showToast(result.error_text ?? "Odczyt z Intune się nie udał.", "error");
        }
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się uruchomić odczytu."), "error"),
    });

  const undo = (deviceId: number) =>
    unresolve.mutate(deviceId, {
      onSuccess: () => showToast("Decyzja cofnięta", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się cofnąć decyzji."), "error"),
    });

  const mode = status.data?.mode;

  return (
    <div className="space-y-3">
      <section
        aria-label="Odczyt z Intune"
        className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3"
      >
        {status.data ? (
          <div className="min-w-0 max-w-3xl space-y-1">
            <StatusDot tone={intuneStatusTone(status.data)}>
              Odczyt z Intune: {INTUNE_MODE_LABELS[status.data.mode]}
            </StatusDot>
            <p className="text-xs text-muted-foreground">{MODE_NOTE[status.data.mode]}</p>
            {status.data.mode !== "off" ? (
              <p className="text-xs text-muted-foreground">
                Ostatni udany odczyt: {formatMomentPl(status.data.last_success_at)} · urządzeń:{" "}
                <span className="tabular-nums">{status.data.device_count}</span>
              </p>
            ) : null}
            {status.data.error ? (
              <p className="text-xs text-destructive">
                Odczyt {formatMomentPl(status.data.last_run_at)} się nie udał. {status.data.error}
              </p>
            ) : null}
          </div>
        ) : status.isError ? (
          <p className="text-xs text-muted-foreground">Stan odczytu chwilowo niedostępny.</p>
        ) : (
          <p className="text-xs text-muted-foreground">Wczytywanie stanu odczytu…</p>
        )}
        {isAdmin && mode && mode !== "off" ? (
          <Button size="sm" variant="outline" onClick={runSync} disabled={sync.isPending}>
            <RefreshCw className="h-4 w-4" aria-hidden />
            {sync.isPending ? "Odczytywanie…" : "Odczytaj teraz"}
          </Button>
        ) : null}
      </section>

      {counts ? (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <InlineStats
            stats={[
              ...INTUNE_KINDS.map((value) => ({
                id: value,
                label: INTUNE_KIND_LABELS[value].toLowerCase(),
                value: counts[value],
                title:
                  value === "brak_w_intune" && !report.data?.checked
                    ? "Liczone po pierwszym udanym odczycie."
                    : KIND_HINTS[value],
              })),
              { id: "zgodne", label: "zgodne", value: counts.zgodne },
              { id: "wyjasnione", label: "wyjaśnione i pominięte", value: counts.wyjasnione },
            ]}
          />
          <FilterSelect
            label="Rodzaj rozjazdu"
            value={kind}
            allLabel="Wszystkie rozjazdy"
            options={[
              ...INTUNE_KINDS.map((value): { value: IntuneFilter; label: string } => ({
                value,
                label: `${INTUNE_KIND_LABELS[value]} (${counts[value]})`,
              })),
              { value: RESOLVED_VIEW, label: `Wyjaśnione i pominięte (${counts.wyjasnione})` },
            ]}
            onChange={setKind}
            className="h-9 w-auto min-w-52 gap-2 whitespace-nowrap"
          />
        </div>
      ) : null}

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie rozjazdów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => report.refetch()} />
      ) : showResolved ? (
        resolved.length === 0 ? (
          <p className="py-6 text-sm text-muted-foreground">
            Żadne urządzenie nie ma jeszcze decyzji recepcji.
          </p>
        ) : (
          <div className="rounded-lg border border-border bg-card">
            <Table density="compact" className="table-fixed">
              <DeviceTableHeader last="Decyzja" />
              <TableBody>
                {resolved.map((row) => (
                  <ResolvedRow
                    key={row.key}
                    row={row}
                    onOpenItem={onOpenItem}
                    onUndo={() => row.device && undo(row.device.id)}
                    pending={unresolve.isPending}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {report.data?.checked
            ? "Ewidencja zgadza się z Intune — nie ma nic do wyjaśnienia."
            : "Lista pojawi się po pierwszym odczycie urządzeń z Intune."}
        </div>
      ) : rows.length === 0 ? (
        <p className="py-6 text-sm text-muted-foreground">Brak rozjazdów tego rodzaju.</p>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <DeviceTableHeader last="Rozjazd" />
            <TableBody>
              {rows.map((row) => (
                <DiscrepancyRow
                  key={row.key}
                  row={row}
                  onOpenItem={onOpenItem}
                  onResolve={(resolution) => setResolving({ row, resolution })}
                  onLink={() => setLinking(row)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {resolving ? (
        <ResolveDialog key={resolving.row.key} target={resolving} onClose={() => setResolving(null)} />
      ) : null}
      {linking ? <LinkDialog key={linking.key} row={linking} onClose={() => setLinking(null)} /> : null}
    </div>
  );
}

function DeviceTableHeader({ last }: { last: string }) {
  return (
    <TableHeader>
      <TableRow>
        <TableHead className={`${CALM_HEAD} w-[19%]`}>Urządzenie</TableHead>
        <TableHead className={`${CALM_HEAD} w-[13%]`}>S/N</TableHead>
        <TableHead className={`${CALM_HEAD} w-[19%]`}>Użytkownik w Intune</TableHead>
        <TableHead className={`${CALM_HEAD} w-[19%]`}>W ewidencji</TableHead>
        <TableHead className={`${CALM_HEAD} w-[14%]`}>{last}</TableHead>
        <TableHead className={`${CALM_HEAD} w-[16%] text-right`}>
          <span className="sr-only">Akcje</span>
        </TableHead>
      </TableRow>
    </TableHeader>
  );
}

interface DiscrepancyRowProps {
  row: IntuneDiscrepancy;
  onOpenItem: (itemId: number) => void;
  onResolve: (resolution: IntuneResolution) => void;
  onLink: () => void;
}

function DiscrepancyRow({ row, onOpenItem, onResolve, onLink }: DiscrepancyRowProps) {
  const { device, item } = row;

  return (
    <TableRow className={`${CALM_ROW} align-top`} data-testid={`intune-row-${row.key}`}>
      <DeviceCells row={row} onOpenItem={onOpenItem} />
      <TableCell>
        <StatusDot
          tone={KIND_TONE[row.kind]}
          title={KIND_HINTS[row.kind]}
          note={
            row.kind === "zniknal_z_intune" && device?.missing_since
              ? `od ${formatIsoDatePl(device.missing_since)}`
              : undefined
          }
        >
          {INTUNE_KIND_LABELS[row.kind]}
        </StatusDot>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap justify-end gap-1">
          {device ? (
            <>
              {row.kind === "brak_w_ewidencji" ? (
                <Button size="sm" variant="outline" onClick={onLink}>
                  <Link2 className="h-4 w-4" aria-hidden />
                  Powiąż
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => onResolve("wyjasnione")}>
                Wyjaśnione
              </Button>
              <Button size="sm" variant="quiet" onClick={() => onResolve("pominiete")}>
                Pomiń
              </Button>
            </>
          ) : item ? (
            <Button size="sm" variant="ghost" onClick={() => onOpenItem(item.id)}>
              Otwórz pozycję
            </Button>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  );
}

interface ResolvedRowProps {
  row: IntuneResolvedRow;
  onOpenItem: (itemId: number) => void;
  onUndo: () => void;
  pending: boolean;
}

/** Urządzenie z decyzją recepcji: decyzja, notatka i „Cofnij decyzję”. */
function ResolvedRow({ row, onOpenItem, onUndo, pending }: ResolvedRowProps) {
  const device = row.device;
  return (
    <TableRow className={`${CALM_ROW} align-top`} data-testid={`intune-resolved-${row.key}`}>
      <DeviceCells row={row} onOpenItem={onOpenItem} />
      <TableCell className="break-words">
        {device?.resolution ? (
          <StatusDot
            tone="neutral"
            note={device.resolved_at ? formatIsoDatePl(device.resolved_at) : undefined}
          >
            {RESOLUTION_LABELS[device.resolution]}
          </StatusDot>
        ) : null}
        {device?.resolution_note ? (
          <span className={CALM_SUBLINE}>{device.resolution_note}</span>
        ) : null}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={onUndo} disabled={pending}>
            Cofnij decyzję
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/** Cztery pierwsze kolumny: urządzenie, S/N, użytkownik w Intune, pozycja w ewidencji. */
function DeviceCells({
  row,
  onOpenItem,
}: {
  row: IntuneResolvedRow;
  onOpenItem: (itemId: number) => void;
}) {
  const { device, item, holder } = row;
  const deviceModel = device
    ? [device.manufacturer, device.model, device.operating_system].filter(Boolean).join(" · ")
    : "";
  const serial = device?.serial_number ?? item?.serial_number ?? null;

  return (
    <>
      <TableCell className="break-words">
        {device ? (
          <>
            <span className="font-medium">{device.device_name ?? "Bez nazwy"}</span>
            {deviceModel ? <span className={CALM_SUBLINE}>{deviceModel}</span> : null}
          </>
        ) : (
          <span className={CALM_EMPTY}>nie ma w Intune</span>
        )}
      </TableCell>
      <TableCell className="break-all font-mono text-xs">
        {serial ?? <span className={CALM_EMPTY}>—</span>}
      </TableCell>
      <TableCell className="break-words">
        {device?.user ? (
          <>
            {device.user.name}
            <span className={`${CALM_SUBLINE} truncate`} title={device.user_principal_name ?? undefined}>
              {device.user_principal_name}
            </span>
          </>
        ) : device?.user_principal_name ? (
          <>
            <span className="block truncate" title={device.user_principal_name}>
              {device.user_principal_name}
            </span>
            <span className={CALM_SUBLINE}>bez konta w NEXUSIE</span>
          </>
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </TableCell>
      <TableCell className="break-words">
        {item ? (
          <>
            <button
              type="button"
              className="text-left hover:underline"
              onClick={() => onOpenItem(item.id)}
            >
              {CATEGORY_LABELS[item.category]} {item.model_name}
              {item.inventory_number ? ` (${item.inventory_number})` : ""}
            </button>
            <span className={CALM_SUBLINE}>
              {holder ? holder.name : ITEM_STATUS_LABELS[item.status].toLowerCase()}
            </span>
          </>
        ) : (
          <span className={CALM_EMPTY}>nie ma w rejestrze</span>
        )}
      </TableCell>
    </>
  );
}
