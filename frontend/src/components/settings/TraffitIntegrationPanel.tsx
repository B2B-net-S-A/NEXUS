"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Clock3,
  GitCompareArrows,
  Inbox,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { AppModal, PageHeader, StatCard, StatCardGrid } from "@/components/ds";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import {
  extractErrorMsg,
  traffitIntegrationApi,
  type TraffitConflictResolutionRequest,
  type TraffitIntegrationConflict,
  type TraffitIntegrationEvent,
  type TraffitIntegrationPage,
  type TraffitIntegrationStatus,
} from "@/lib/api";
import {
  formatIntegrationDate,
  formatIntegrationValue,
  formatLagSeconds,
  getMaximumLagSeconds,
  getTraffitHealthPresentation,
} from "@/lib/traffit-integration";
import { cn } from "@/lib/utils";

export interface TraffitIntegrationMockData {
  status: TraffitIntegrationStatus;
  events: TraffitIntegrationPage<TraffitIntegrationEvent>;
  conflicts: TraffitIntegrationPage<TraffitIntegrationConflict>;
}

interface TraffitIntegrationPanelProps {
  isAdmin: boolean;
  mockData?: TraffitIntegrationMockData;
}

const STATUS_QUERY_KEY = ["traffit-integration", "status"] as const;
const EVENTS_QUERY_KEY = ["traffit-integration", "events"] as const;
const CONFLICTS_QUERY_KEY = ["traffit-integration", "conflicts"] as const;

function statusLabel(status: string | null): string {
  const labels: Record<string, string> = {
    pending: "Oczekuje",
    processing: "W toku",
    running: "W toku",
    completed: "Zakończone",
    processed: "Zakończone",
    success: "OK",
    succeeded: "OK",
    failed: "Błąd",
    error: "Błąd",
    dead_letter: "Dead-letter",
    open: "Otwarty",
    resolved: "Rozwiązany",
    disabled: "Wyłączone",
    paused: "Wstrzymane",
  };
  if (!status) return "Brak danych";
  return labels[status.toLowerCase()] ?? status;
}

function StatusPill({ status }: { status: string | null }) {
  const normalized = (status ?? "").toLowerCase();
  const isError = ["failed", "error", "dead_letter"].includes(normalized);
  const isOk = ["completed", "processed", "success", "succeeded"].includes(
    normalized,
  );
  return (
    <Badge
      variant="outline"
      className={cn(
        "border-border bg-muted text-muted-foreground",
        isOk && "border-primary/20 bg-primary/10 text-primary",
        isError && "border-destructive/20 bg-destructive/10 text-destructive",
      )}
    >
      {statusLabel(status)}
    </Badge>
  );
}

function DirectionPill({ direction }: { direction: string }) {
  const outbound = direction.toLowerCase() === "outbound";
  const Icon = outbound ? ArrowUpFromLine : ArrowDownToLine;
  return (
    <Badge
      variant="outline"
      className={cn(
        "border-border bg-muted text-foreground",
        outbound && "border-primary/20 bg-primary/10 text-primary",
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {outbound ? "Do Traffit" : "Z Traffit"}
    </Badge>
  );
}

function EmptyTableRow({ colSpan, label }: { colSpan: number; label: string }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="py-10 text-center text-muted-foreground">
        {label}
      </TableCell>
    </TableRow>
  );
}

function ControlRow({
  label,
  description,
  active,
  paused,
  canMutate,
  disabled,
  pending,
  onToggle,
}: {
  label: string;
  description: string;
  active: boolean;
  paused?: boolean;
  canMutate?: boolean;
  disabled?: boolean;
  pending?: boolean;
  onToggle?: () => void;
}) {
  const operational = active && !paused;
  return (
    <div className="flex flex-col gap-3 border-b border-border py-4 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-foreground">{label}</p>
          <StatusPill
            status={!active ? "disabled" : paused ? "paused" : "success"}
          />
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      {canMutate && onToggle ? (
        <Button
          variant="outline"
          size="sm"
          loading={pending}
          disabled={disabled}
          onClick={onToggle}
          className="self-start sm:self-auto"
        >
          {operational ? "Wstrzymaj" : "Wznów"}
        </Button>
      ) : null}
    </div>
  );
}

function ConflictValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-border bg-muted p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 max-h-28 overflow-auto break-words text-sm text-foreground">
        {formatIntegrationValue(value)}
      </p>
    </div>
  );
}

export function TraffitIntegrationPanel({
  isAdmin,
  mockData,
}: TraffitIntegrationPanelProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [selectedConflict, setSelectedConflict] =
    useState<TraffitIntegrationConflict | null>(null);
  const [resolution, setResolution] =
    useState<TraffitConflictResolutionRequest["resolution"]>("nexus");
  const [mergedValue, setMergedValue] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const canMutate = isAdmin && !mockData;

  const statusQuery = useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: traffitIntegrationApi.getStatus,
    enabled: !mockData,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const eventsQuery = useQuery({
    queryKey: EVENTS_QUERY_KEY,
    queryFn: () => traffitIntegrationApi.listEvents({ limit: 20 }),
    enabled: !mockData,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const conflictsQuery = useQuery({
    queryKey: CONFLICTS_QUERY_KEY,
    queryFn: () =>
      traffitIntegrationApi.listConflicts({ limit: 20, status: "actionable" }),
    enabled: !mockData,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const status = mockData?.status ?? statusQuery.data;
  const events = mockData?.events ?? eventsQuery.data;
  const conflicts = mockData?.conflicts ?? conflictsQuery.data;
  const health = status ? getTraffitHealthPresentation(status) : null;
  const maximumLag = status ? getMaximumLagSeconds(status) : null;

  const refreshAll = async () => {
    if (mockData) return;
    await Promise.all([
      statusQuery.refetch(),
      eventsQuery.refetch(),
      conflictsQuery.refetch(),
    ]);
  };

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: EVENTS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: CONFLICTS_QUERY_KEY }),
    ]);
  };

  const reconcileMutation = useMutation({
    mutationFn: traffitIntegrationApi.reconcile,
    onSuccess: async (result) => {
      showSuccess(`Reconcile uruchomiony · ${result.run_id}`);
      await invalidateAll();
    },
    onError: (error) => showError(extractErrorMsg(error)),
  });

  const controlMutation = useMutation({
    mutationFn: traffitIntegrationApi.control,
    onSuccess: async () => {
      showSuccess("Sterowanie synchronizacją zostało zapisane.");
      await invalidateAll();
    },
    onError: (error) => showError(extractErrorMsg(error)),
  });

  const retryMutation = useMutation({
    mutationFn: traffitIntegrationApi.retryEvent,
    onSuccess: async () => {
      showSuccess("Zdarzenie wróciło do kolejki.");
      await invalidateAll();
    },
    onError: (error) => showError(extractErrorMsg(error)),
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: TraffitConflictResolutionRequest;
    }) => traffitIntegrationApi.resolveConflict(id, payload),
    onSuccess: async () => {
      setSelectedConflict(null);
      showSuccess("Konflikt został przekazany do rozwiązania.");
      await invalidateAll();
    },
    onError: (error) => showError(extractErrorMsg(error)),
  });

  const controlPending = controlMutation.isPending;
  const retryableStatuses = useMemo(
    () => new Set(["failed", "error", "dead_letter"]),
    [],
  );

  const openConflict = (conflict: TraffitIntegrationConflict) => {
    setSelectedConflict(conflict);
    setResolution("nexus");
    setMergedValue(formatIntegrationValue(conflict.local_value));
    setResolutionNote("");
  };

  const submitResolution = () => {
    if (!selectedConflict) return;
    let parsedMergedValue: unknown = mergedValue;
    if (resolution === "merged") {
      try {
        parsedMergedValue = JSON.parse(mergedValue);
      } catch {
        parsedMergedValue = mergedValue;
      }
    }
    resolveMutation.mutate({
      id: selectedConflict.id,
      payload: {
        resolution,
        ...(resolution === "merged" ? { merged_value: parsedMergedValue } : {}),
        ...(resolutionNote.trim() ? { note: resolutionNote.trim() } : {}),
      },
    });
  };

  return (
    <div className="mx-auto max-w-[1180px] space-y-6">
      <PageHeader
        eyebrow="Integracje"
        title="Traffit ↔ NEXUS"
        description="Monitoruj dwukierunkową synchronizację, kolejki i konflikty. Celem jest widoczność każdej zmiany po drugiej stronie do 15 minut."
        breadcrumb={[
          { label: "Ustawienia", href: "/settings" },
          { label: "Traffit" },
        ]}
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void refreshAll()}
              disabled={Boolean(mockData)}
            >
              <RefreshCw
                className={cn(
                  "h-4 w-4",
                  (statusQuery.isFetching || eventsQuery.isFetching) &&
                    "animate-spin",
                )}
                aria-hidden="true"
              />
              Odśwież
            </Button>
            {isAdmin ? (
              <Button
                size="sm"
                loading={reconcileMutation.isPending}
                disabled={!canMutate}
                onClick={() => reconcileMutation.mutate({ scope: "active" })}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                Reconcile aktywnych
              </Button>
            ) : null}
          </>
        }
      />

      {mockData ? (
        <Alert
          variant="info"
          title="Podgląd z danymi testowymi"
          description="Mutujące akcje są wyłączone w harnessie /preview/traffit."
        />
      ) : null}

      {statusQuery.isError || eventsQuery.isError || conflictsQuery.isError ? (
        <Alert
          variant="error"
          title="Nie udało się pobrać pełnego stanu integracji"
          description={extractErrorMsg(
            statusQuery.error ?? eventsQuery.error ?? conflictsQuery.error,
          )}
        >
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void refreshAll()}
          >
            Spróbuj ponownie
          </Button>
        </Alert>
      ) : null}

      {!status ? (
        <StatCardGrid>
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-36 rounded-lg" />
          ))}
        </StatCardGrid>
      ) : (
        <>
          {health?.kind !== "healthy" ? (
            <Alert
              variant={health?.kind === "error" ? "error" : "warning"}
              title={health?.label}
              description={health?.description}
            />
          ) : null}

          <StatCardGrid>
            <StatCard
              label="Stan integracji"
              value={<span className="text-2xl">{health?.label}</span>}
              sub={status.dry_run ? "Bez zapisu do Traffit" : "Tryb produkcyjny"}
              icon={ShieldCheck}
            />
            <StatCard
              label="Największe opóźnienie"
              value={formatLagSeconds(maximumLag)}
              sub={maximumLag != null && maximumLag <= 900 ? "Cel ≤ 15 min" : "Poza celem 15 min"}
              icon={Clock3}
            />
            <StatCard
              label="Zdarzenia w kolejce"
              value={status.queues.inbox_pending + status.queues.outbox_pending}
              sub={`${status.queues.inbox_pending} inbound · ${status.queues.outbox_pending} outbound`}
              icon={Inbox}
            />
            <StatCard
              label="Otwarte konflikty"
              value={status.conflicts_open}
              sub={`${status.queues.dead_letter} dead-letter`}
              icon={GitCompareArrows}
            />
          </StatCardGrid>
        </>
      )}

      {status ? (
        <div className="grid gap-6 lg:grid-cols-5">
          <Card size="lg" className="lg:col-span-3">
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle>Sterowanie synchronizacją</CardTitle>
                <CardDescription>
                  Stan kierunków i ich runtime kill-switche.
                </CardDescription>
              </div>
              {status.leader ? (
                <Badge variant="outline" className="border-primary/20 bg-primary/10 text-primary">
                  Leader aktywny
                </Badge>
              ) : (
                <Badge variant="outline">Brak leadera</Badge>
              )}
            </CardHeader>
            <CardContent>
              <ControlRow
                label="Odbiór webhooków"
                description="Sygnały z Traffit są bezpiecznie zapisywane w inboxie."
                active={status.webhook_accept_enabled}
              />
              <ControlRow
                label="Zmiany Traffit → NEXUS"
                description="Worker stosuje pobrane zmiany do danych NEXUS."
                active={status.inbound_apply_enabled}
                paused={status.paused.inbound}
                canMutate={isAdmin}
                disabled={!canMutate}
                pending={controlPending}
                onToggle={() =>
                  controlMutation.mutate({
                    inbound_paused: !status.paused.inbound,
                    reason: "manual_from_settings_ui",
                  })
                }
              />
              <ControlRow
                label="Polling bezpieczeństwa"
                description="Uzupełnia zdarzenia, których Traffit nie wysyła webhookiem."
                active={status.poll_enabled}
                paused={status.paused.poll}
                canMutate={isAdmin}
                disabled={!canMutate}
                pending={controlPending}
                onToggle={() =>
                  controlMutation.mutate({
                    poll_paused: !status.paused.poll,
                    reason: "manual_from_settings_ui",
                  })
                }
              />
              <ControlRow
                label="Zmiany NEXUS → Traffit"
                description="Transactional outbox wysyła zaakceptowane operacje."
                active={status.outbound_enabled}
                paused={status.paused.outbound}
                canMutate={isAdmin}
                disabled={!canMutate}
                pending={controlPending}
                onToggle={() =>
                  controlMutation.mutate({
                    outbound_paused: !status.paused.outbound,
                    reason: "manual_from_settings_ui",
                  })
                }
              />
              {isAdmin ? (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted p-4">
                  <div>
                    <p className="text-sm font-medium text-foreground">Pełny reconcile</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Ostatni: {formatIntegrationDate(status.last_reconcile_at)}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!canMutate}
                    loading={reconcileMutation.isPending}
                    onClick={() => reconcileMutation.mutate({ scope: "full" })}
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    Uruchom pełny
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card size="lg" className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Strumienie danych</CardTitle>
              <CardDescription>
                Cursor, lag i błędy każdego obszaru synchronizacji.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {status.streams.length === 0 ? (
                <p className="rounded-lg bg-muted px-4 py-8 text-center text-sm text-muted-foreground">
                  Brak zarejestrowanych strumieni.
                </p>
              ) : (
                status.streams.map((stream) => (
                  <div
                    key={stream.phase}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="truncate text-sm font-medium text-foreground">
                        {stream.phase}
                      </p>
                      <StatusPill status={stream.last_status} />
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                      <span>Lag: {formatLagSeconds(stream.lag_seconds)}</span>
                      <span>Błędy: {stream.consecutive_failures}</span>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Sukces: {formatIntegrationDate(stream.last_success_at)}
                    </p>
                  </div>
                ))
              )}
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
                <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>
                  Leader: {status.leader?.owner_id ?? "brak"} · lease do{" "}
                  {formatIntegrationDate(status.leader?.expires_at)}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Card size="lg">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Konflikty do decyzji</CardTitle>
            <CardDescription>
              To samo pole lub etap zmieniony niezależnie w obu systemach.
            </CardDescription>
          </div>
          <Badge variant="outline">{conflicts?.total ?? 0} do decyzji</Badge>
        </CardHeader>
        <CardContent>
          <Table density="compact">
            <TableHeader>
              <TableRow>
                <TableHead>Encja</TableHead>
                <TableHead>Pole</TableHead>
                <TableHead>Typ konfliktu</TableHead>
                <TableHead>Utworzono</TableHead>
                <TableHead className="text-right">Akcja</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!conflicts || conflicts.items.length === 0 ? (
                <EmptyTableRow
                  colSpan={5}
                  label="Brak konfliktów wymagających decyzji."
                />
              ) : (
                conflicts.items.map((conflict) => (
                  <TableRow key={conflict.id}>
                    <TableCell>
                      <p className="font-medium">{conflict.entity_type}</p>
                      <p className="text-xs text-muted-foreground">
                        NEXUS {conflict.nexus_entity_id ?? "—"} · Traffit{" "}
                        {conflict.external_id ?? "—"}
                      </p>
                    </TableCell>
                    <TableCell>{conflict.field_path ?? "cała encja"}</TableCell>
                    <TableCell>
                      <StatusPill status={conflict.conflict_type} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatIntegrationDate(conflict.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {isAdmin ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openConflict(conflict)}
                        >
                          Rozwiąż
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">Admin</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card size="lg">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Ostatnie zdarzenia</CardTitle>
            <CardDescription>
              Wspólny podgląd inboxu i outboxu integracji.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={Boolean(mockData)}
            onClick={() => void eventsQuery.refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Odśwież
          </Button>
        </CardHeader>
        <CardContent>
          <Table density="compact">
            <TableHeader>
              <TableRow>
                <TableHead>Kierunek</TableHead>
                <TableHead>Zdarzenie</TableHead>
                <TableHead>Encja</TableHead>
                <TableHead>Stan</TableHead>
                <TableHead>Próby</TableHead>
                <TableHead>Utworzono</TableHead>
                <TableHead className="text-right">Akcja</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!events || events.items.length === 0 ? (
                <EmptyTableRow colSpan={7} label="Brak zdarzeń integracji." />
              ) : (
                events.items.map((event) => {
                  const retryable = retryableStatuses.has(
                    event.status.toLowerCase(),
                  );
                  return (
                    <TableRow key={event.id}>
                      <TableCell>
                        <DirectionPill direction={event.direction} />
                      </TableCell>
                      <TableCell>
                        <p className="font-medium">{event.event_type}</p>
                        {event.last_error ? (
                          <p
                            className="max-w-64 truncate text-xs text-destructive"
                            title={event.last_error}
                          >
                            {event.last_error}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {event.aggregate_type} · {event.aggregate_id}
                      </TableCell>
                      <TableCell>
                        <StatusPill status={event.status} />
                      </TableCell>
                      <TableCell className="tabular-nums">{event.attempts}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatIntegrationDate(event.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {isAdmin && retryable ? (
                          <Button
                            variant="outline"
                            size="sm"
                            loading={
                              retryMutation.isPending &&
                              retryMutation.variables === event.id
                            }
                            disabled={!canMutate}
                            onClick={() => retryMutation.mutate(event.id)}
                          >
                            Ponów
                          </Button>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <AppModal
        open={Boolean(selectedConflict)}
        onOpenChange={(open) => !open && setSelectedConflict(null)}
        title="Rozwiąż konflikt Traffit"
        description="Wybór admina ustala nową wspólną wersję danych po obu stronach."
        size="lg"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setSelectedConflict(null)}
            >
              Anuluj
            </Button>
            <Button
              loading={resolveMutation.isPending}
              disabled={!canMutate}
              onClick={submitResolution}
            >
              Zastosuj decyzję
            </Button>
          </>
        }
      >
        {selectedConflict ? (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-3">
              <ConflictValue label="Wspólna baza" value={selectedConflict.base_value} />
              <ConflictValue label="NEXUS" value={selectedConflict.local_value} />
              <ConflictValue label="Traffit" value={selectedConflict.remote_value} />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">
                Decyzja
              </label>
              <Select
                value={resolution}
                onValueChange={(value) =>
                  setResolution(
                    value as TraffitConflictResolutionRequest["resolution"],
                  )
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="nexus">Zachowaj wartość NEXUS</SelectItem>
                  <SelectItem value="traffit">Zachowaj wartość Traffit</SelectItem>
                  <SelectItem value="merged">Ustaw wartość scaloną</SelectItem>
                  <SelectItem value="manual">Oznacz jako wykonane ręcznie</SelectItem>
                  <SelectItem value="unlink">Odepnij mapowanie encji</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {resolution === "merged" ? (
              <div>
                <label className="mb-2 block text-sm font-medium text-foreground">
                  Wartość scalona
                </label>
                <Textarea
                  value={mergedValue}
                  onChange={(event) => setMergedValue(event.target.value)}
                  placeholder="Tekst lub poprawny JSON"
                />
              </div>
            ) : null}

            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">
                Notatka audytowa (opcjonalna)
              </label>
              <Textarea
                rows={3}
                value={resolutionNote}
                onChange={(event) => setResolutionNote(event.target.value)}
                placeholder="Powód decyzji administratora"
              />
            </div>

            {resolution === "unlink" ? (
              <Alert
                variant="warning"
                title="Mapowanie zostanie odpięte"
                description="Kolejne zdarzenia tej encji mogą wymagać ponownego ręcznego powiązania."
                icon={AlertTriangle}
              />
            ) : null}
          </div>
        ) : null}
      </AppModal>
    </div>
  );
}
