"use client";

import { useDeferredValue, useState } from "react";
import { Link2, RefreshCw, Search } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useEquipmentItems } from "@/lib/api/equipment";
import {
  useIntuneDiscrepancies,
  useIntuneStatus,
  useIntuneSync,
  useLinkIntuneDevice,
  useResolveIntuneDevice,
  useUnresolveIntuneDevice,
  type IntuneDiscrepancy,
  type IntuneDiscrepancyKind,
  type IntuneMode,
  type IntuneResolution,
  type IntuneResolvedRow,
  type IntuneStatus,
} from "@/lib/api/equipment-intune";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { CATEGORY_LABELS, ITEM_STATUS_LABELS, formatDatePl, itemIdentifier } from "./equipment-format";
import { FilterSelect } from "./FilterSelect";

export const INTUNE_KINDS: IntuneDiscrepancyKind[] = [
  "zniknal_z_intune",
  "brak_w_ewidencji",
  "inny_posiadacz",
  "brak_w_intune",
];

export const INTUNE_KIND_LABELS: Record<IntuneDiscrepancyKind, string> = {
  zniknal_z_intune: "Zniknęło z Intune",
  brak_w_ewidencji: "Brak w ewidencji",
  inny_posiadacz: "Inny posiadacz",
  brak_w_intune: "Brak w Intune",
};

/** Widok „Wyjaśnione i pominięte” w tym samym filtrze co rodzaje rozjazdów. */
const RESOLVED_VIEW = "wyjasnione" as const;
type IntuneFilter = IntuneDiscrepancyKind | typeof RESOLVED_VIEW;

const RESOLUTION_LABELS: Record<IntuneResolution, string> = {
  wyjasnione: "Wyjaśnione",
  pominiete: "Pominięte",
};

const KIND_TONE: Record<IntuneDiscrepancyKind, StatusDotTone> = {
  zniknal_z_intune: "warning",
  brak_w_ewidencji: "warning",
  inny_posiadacz: "danger",
  brak_w_intune: "warning",
};

const KIND_HINTS: Record<IntuneDiscrepancyKind, string> = {
  zniknal_z_intune: "Urządzenie było w Intune, a w ostatnim odczycie go zabrakło.",
  brak_w_ewidencji: "Urządzenie jest w Intune, a w rejestrze nie ma egzemplarza z tym S/N.",
  inny_posiadacz: "W rejestrze laptop jest wydany komuś innemu niż użytkownik w Intune.",
  brak_w_intune: "Laptop jest wydany w rejestrze, a Intune go nie widzi.",
};

export const INTUNE_MODE_LABELS: Record<IntuneMode, string> = {
  off: "wyłączony",
  simulate: "tryb próbny",
  live: "włączony",
};

const MODE_NOTE: Record<IntuneMode, string> = {
  off:
    "NEXUS nie czyta jeszcze urządzeń z Intune — odczyt czeka na zgodę administratora " +
    "Microsoft 365. Potem lista będzie się odświeżać co noc, wyłącznie do odczytu, bez kluczy i haseł.",
  simulate:
    "Fikcyjne urządzenia do sprawdzenia ekranu. Nic nie łączy się z Microsoftem.",
  live: "NEXUS czyta urządzenia z Intune co noc, wyłącznie do odczytu. Rejestru sam nie zmienia.",
};

/** Ton kropki stanu: wyłączony szary, próbny niebieski, potem zdrowie odczytu. */
export function intuneStatusTone(status: Pick<IntuneStatus, "mode" | "health">): StatusDotTone {
  if (status.mode === "off") return "neutral";
  if (status.mode === "simulate") return "info";
  return status.health === "healthy" ? "success" : "warning";
}

/** Chwila ISO → „16.10.2026, 05:31” w czasie warszawskim. */
export function formatMoment(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

interface IntuneTabProps {
  /** Ręczny odczyt uruchamia tylko admin. */
  isAdmin: boolean;
  onOpenItem: (itemId: number) => void;
}

type ResolveTarget = { row: IntuneDiscrepancy; resolution: IntuneResolution };

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
                Ostatni udany odczyt: {formatMoment(status.data.last_success_at)} · urządzeń:{" "}
                <span className="tabular-nums">{status.data.device_count}</span>
              </p>
            ) : null}
            {status.data.error ? (
              <p className="text-xs text-destructive">
                Odczyt {formatMoment(status.data.last_run_at)} się nie udał. {status.data.error}
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
              ? `od ${formatDatePl(device.missing_since)}`
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
            note={device.resolved_at ? formatDatePl(device.resolved_at) : undefined}
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

function deviceLabel(row: IntuneDiscrepancy): string {
  const device = row.device;
  if (!device) return "";
  const name = device.device_name ?? "Urządzenie bez nazwy";
  return device.serial_number ? `${name} · S/N ${device.serial_number}` : name;
}

function ResolveDialog({ target, onClose }: { target: ResolveTarget; onClose: () => void }) {
  const { showToast } = useToast();
  const resolve = useResolveIntuneDevice();
  const [note, setNote] = useState("");
  const explained = target.resolution === "wyjasnione";
  const deviceId = target.row.device?.id;

  const submit = () => {
    if (!deviceId) return;
    resolve.mutate(
      { deviceId, resolution: target.resolution, note: note.trim() || null },
      {
        onSuccess: () => {
          showToast(explained ? "Oznaczone jako wyjaśnione" : "Urządzenie pominięte", "success");
          onClose();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={explained ? "Rozjazd wyjaśniony" : "Pomiń urządzenie"}
      description={
        explained
          ? "Rozjazd zniknie z listy. Notatka zostaje przy urządzeniu."
          : "Urządzenie nie będzie pokazywane jako rozjazd (np. sprzęt testowy albo klienta)."
      }
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={resolve.isPending}>
            {resolve.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <p className="text-sm font-medium">{deviceLabel(target.row)}</p>
        <label className="block space-y-1 text-sm">
          <span className="text-xs text-muted-foreground">Notatka (opcjonalnie)</span>
          <Textarea
            value={note}
            maxLength={500}
            rows={3}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Np. laptop oddany do serwisu, wpis w Intune zostanie usunięty."
          />
        </label>
      </div>
    </AppModal>
  );
}

function LinkDialog({ row, onClose }: { row: IntuneDiscrepancy; onClose: () => void }) {
  const { showToast } = useToast();
  const link = useLinkIntuneDevice();
  // Podpowiedź „przypisz do …”: zaczynamy od osoby, która używa urządzenia.
  const [query, setQuery] = useState(row.device?.user?.name ?? "");
  const deferred = useDeferredValue(query.trim());
  const enabled = deferred.length >= 2;
  const items = useEquipmentItems({ q: deferred }, enabled);
  const found = items.data?.items.slice(0, 8) ?? [];
  const deviceId = row.device?.id;

  const choose = (itemId: number) => {
    if (!deviceId) return;
    link.mutate(
      { deviceId, itemId },
      {
        onSuccess: () => {
          showToast("Powiązano z egzemplarzem", "success");
          onClose();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się powiązać."), "error"),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Powiąż z egzemplarzem"
      description="Wybierz pozycję z rejestru, która jest tym urządzeniem (np. gdy S/N w rejestrze ma literówkę)."
      size="lg"
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{deviceLabel(row)}</p>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj pozycji w rejestrze"
            placeholder="S/N, numer ewidencyjny, model albo osoba…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 pl-8"
          />
        </div>
        {!enabled ? (
          <p className="text-sm text-muted-foreground">Wpisz co najmniej 2 znaki.</p>
        ) : items.isLoading ? (
          <p className="text-sm text-muted-foreground">Szukanie…</p>
        ) : items.isError ? (
          <p className="text-sm text-destructive">
            {apiErrorMessage(items.error, "Nie udało się przeszukać rejestru.")}
          </p>
        ) : found.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {found.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {CATEGORY_LABELS[item.category]} {item.model.name}
                    {item.inventory_number ? ` (${item.inventory_number})` : ""}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {itemIdentifier(item)} · {item.holder?.name ?? ITEM_STATUS_LABELS[item.status].toLowerCase()}
                  </span>
                </span>
                <Button size="sm" variant="outline" onClick={() => choose(item.id)} disabled={link.isPending}>
                  Powiąż
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppModal>
  );
}
