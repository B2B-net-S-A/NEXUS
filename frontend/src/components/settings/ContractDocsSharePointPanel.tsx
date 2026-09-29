"use client";

// Ustawienia → Umowy i stawki → „Dokumenty kontraktów z SharePointa” (admin).
//
// Ticket 9: NEXUS sam czyta folder „Umowy pracowników” (podfolder „Nazwisko
// Imię” na osobę) i podpina PDF/JPG do zakładki Dokumenty kontraktów. Link →
// podgląd (nic nie zapisuje) → „Pobierz i zapisz” → raport / cofnięcie. Niżej
// stan synchronizacji w obie strony i kolejka „Do przypisania”.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FolderSync,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  APPLIED_COUNTERS,
  DOC_TYPE_LABEL,
  RUN_MODE_LABEL,
  SUMMARY_COUNTERS,
  contractDocsSharePointApi as spApi,
  contractsWithoutDocuments,
  deselectedItemIds,
  filesLabel,
  downloadRunReport,
  groupAssignments,
  reasonsText,
  uncertainGroups,
  type ContractGroup,
  type SharePointRunDetail,
} from "@/lib/contract-docs-sharepoint";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawDateOf } from "@/lib/warsaw-date";

const STATUS_KEY = ["contract-docs-sp-status"] as const;
const RUNS_KEY = ["contract-docs-sp-runs"] as const;
const REVIEW_KEY = ["contract-docs-sp-review"] as const;

function Section({
  title,
  count,
  open = false,
  children,
}: {
  title: string;
  count: number;
  open?: boolean;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <details className="rounded-md border border-border p-3" open={open}>
      <summary className="cursor-pointer text-sm font-medium">
        {title} ({count})
      </summary>
      <div className="mt-2 max-h-96 overflow-auto text-sm">{children}</div>
    </details>
  );
}

function Counters({
  counters,
  spec,
}: {
  counters: Record<string, number>;
  spec: { key: string; label: string }[];
}) {
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {spec.map(({ key, label }) => (
        <div key={key} className="rounded-md border border-border p-2">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-lg font-semibold">{counters[key] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}

function FilesList({ group }: { group: ContractGroup }) {
  return (
    <ul className="ml-6 list-disc text-xs text-muted-foreground">
      {group.files.map((f) => (
        <li key={f.id}>
          {f.file_name} — {DOC_TYPE_LABEL[f.doc_type ?? ""] ?? f.doc_type}
          {f.note ? ` (${f.note})` : ""}
          {f.status !== "pending" && f.status !== "info"
            ? ` · ${f.status}`
            : ""}
        </li>
      ))}
    </ul>
  );
}

export function ContractDocsRunView({
  run,
  onApply,
  onRollback,
  busy,
}: {
  run: SharePointRunDetail;
  onApply: (deselected: number[]) => void;
  onRollback: () => void;
  busy: boolean;
}) {
  const [unchecked, setUnchecked] = useState<Set<number>>(new Set());
  const groups = useMemo(() => groupAssignments(run.items), [run.items]);
  const { uncertain, ambiguous } = useMemo(
    () => uncertainGroups(run.items),
    [run.items],
  );
  const sure = groups.filter((g) => g.matchKind === "sure");
  const without = contractsWithoutDocuments(run.items);
  const folders = run.items.filter((i) => i.kind === "folder");
  const skippedFiles = run.items.filter(
    (i) =>
      i.kind === "file" && (i.match_kind == null || i.match_kind === "sure"),
  );
  const excluded = run.items.filter(
    (i) => i.kind === "contract" && i.match_kind === "excluded",
  );
  const selectedFiles = groups
    .filter((g) => !unchecked.has(g.contractId))
    .reduce((sum, g) => sum + g.files.length, 0);
  const editable = run.mode === "preview";

  const toggle = (contractId: number) =>
    setUnchecked((prev) => {
      const next = new Set(prev);
      if (next.has(contractId)) next.delete(contractId);
      else next.add(contractId);
      return next;
    });

  return (
    <div className="flex flex-col gap-3" data-testid="contract-docs-sp-run">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={run.mode === "failed" ? "danger" : "neutral"}>
          {RUN_MODE_LABEL[run.mode]}
        </Badge>
        {run.created_at ? (
          <span className="text-muted-foreground">
            Przebieg #{run.id} z {formatIsoDatePl(warsawDateOf(run.created_at))}
            {run.created_by_name ? ` · ${run.created_by_name}` : ""}
          </span>
        ) : null}
      </div>
      {run.error ? (
        <p className="text-sm text-destructive">{run.error}</p>
      ) : null}
      {run.mode === "listing" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Czytam folder w
          SharePoincie — przy kilkuset osobach to do kilku minut.
        </p>
      ) : null}
      {run.mode === "applying" ? (
        <div className="flex flex-col gap-1 text-sm">
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Pobieram pliki:{" "}
            {run.progress.done} z {run.progress.total}
          </p>
          <div className="h-2 rounded bg-muted">
            <div
              className="h-2 rounded bg-primary"
              style={{
                width: `${run.progress.total ? (100 * run.progress.done) / run.progress.total : 0}%`,
              }}
            />
          </div>
        </div>
      ) : null}
      {run.mode !== "listing" && run.mode !== "failed" ? (
        <>
          <Counters counters={run.counters} spec={SUMMARY_COUNTERS} />
          {run.mode === "applied" || run.mode === "rolled_back" ? (
            <Counters counters={run.counters} spec={APPLIED_COUNTERS} />
          ) : null}
          <Section
            title="Do weryfikacji — przypisania niepewne"
            count={uncertain.length}
            open={editable}
          >
            <p className="mb-2 text-xs text-muted-foreground">
              Zaznaczone zostaną zapisane. Odznacz osobę, jeśli folder należy do
              kogoś innego.
            </p>
            <ul className="flex flex-col gap-2">
              {uncertain.map((g) => (
                <li key={g.contractId}>
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      disabled={!editable}
                      checked={!unchecked.has(g.contractId)}
                      onChange={() => toggle(g.contractId)}
                      aria-label={`Zapisz dokumenty dla ${g.personName}`}
                    />
                    <span>
                      <strong>{g.personName}</strong> (kontrakt #{g.contractId})
                      → folder „{g.folderName}” — {reasonsText(g.reasons)}
                    </span>
                  </label>
                  <FilesList group={g} />
                </li>
              ))}
            </ul>
          </Section>
          <Section
            title="Do weryfikacji — kilka pasujących folderów"
            count={ambiguous.length}
          >
            <ul className="flex flex-col gap-1">
              {ambiguous.map((i) => (
                <li key={i.id}>
                  <strong>{i.person_name}</strong> (kontrakt #{i.contract_id}) —{" "}
                  {i.note}
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Bez podfolderu lub dokumentów" count={without.length}>
            <ul className="flex flex-col gap-1">
              {without.map((i) => (
                <li key={i.id}>
                  <strong>{i.person_name}</strong> (kontrakt #{i.contract_id}) —{" "}
                  {i.note}
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Przypisania pewne" count={sure.length}>
            <ul className="flex flex-col gap-2">
              {sure.map((g) => (
                <li key={g.contractId}>
                  <strong>{g.personName}</strong> (kontrakt #{g.contractId})
                  <FilesList group={g} />
                </li>
              ))}
            </ul>
          </Section>
          <Section
            title="Foldery bez kontraktu w NEXUSIE"
            count={folders.length}
          >
            <ul className="flex flex-col gap-1">
              {folders.map((i) => (
                <li key={i.id}>
                  „{i.folder_name}” — {i.note}
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Pominięte pliki" count={skippedFiles.length}>
            <ul className="flex flex-col gap-1">
              {skippedFiles.map((i) => (
                <li key={i.id}>
                  {i.folder_name ? `${i.folder_name} / ` : ""}
                  {i.file_name} — {i.note}
                </li>
              ))}
            </ul>
          </Section>
          <Section
            title="Pominięte kontrakty (Filip Jabłoński)"
            count={excluded.length}
          >
            <ul className="flex flex-col gap-1">
              {excluded.map((i) => (
                <li key={i.id}>
                  {i.person_name} (kontrakt #{i.contract_id})
                </li>
              ))}
            </ul>
          </Section>
        </>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {editable ? (
          <Button
            disabled={busy || selectedFiles === 0}
            onClick={() => onApply(deselectedItemIds(groups, unchecked))}
          >
            Pobierz i zapisz ({filesLabel(selectedFiles)})
          </Button>
        ) : null}
        {run.mode !== "listing" && run.mode !== "failed" ? (
          <Button
            variant="outline"
            onClick={() =>
              void downloadRunReport(run.id).catch(() => undefined)
            }
          >
            <Download className="size-4" /> Raport XLSX
          </Button>
        ) : null}
        {run.can_rollback ? (
          <Button variant="outline" disabled={busy} onClick={onRollback}>
            <RotateCcw className="size-4" /> Cofnij zapis
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function SyncSection() {
  const queryClient = useQueryClient();
  const { showError, showSuccess, showInfo } = useToast();
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: spApi.status });
  const review = useQuery({
    queryKey: REVIEW_KEY,
    queryFn: spApi.review,
    enabled: (status.data?.review_count ?? 0) > 0,
  });
  const sync = useMutation({
    mutationFn: spApi.syncNow,
    onSuccess: () =>
      showInfo("Synchronizacja ruszyła w tle — stan odświeży się za chwilę."),
    onError: (e) =>
      showError(apiErrorMessage(e, "Nie udało się uruchomić synchronizacji.")),
  });
  const decide = useMutation({
    mutationFn: (v: {
      itemId: string;
      action: "assign" | "dismiss";
      ids: number[];
    }) => spApi.decide(v.itemId, v.action, v.ids),
    onSuccess: (_d, v) => {
      showSuccess(
        v.action === "assign"
          ? "Zapisano dokument na kontrakcie."
          : "Pominięto plik.",
      );
      void queryClient.invalidateQueries({ queryKey: REVIEW_KEY });
      void queryClient.invalidateQueries({ queryKey: STATUS_KEY });
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Nie udało się zapisać decyzji.")),
  });
  const s = status.data;
  if (!s || !s.initial_import_run_id) return null;
  return (
    <section className="flex flex-col gap-3 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">
          Synchronizacja SharePoint ↔ NEXUS
        </h2>
        <Button
          variant="outline"
          size="sm"
          disabled={!s.sync_enabled || sync.isPending}
          onClick={() => sync.mutate()}
        >
          <FolderSync className="size-4" /> Synchronizuj teraz
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        {s.sync_enabled
          ? "Nowe pliki z folderu trafiają do kontraktów co godzinę, a dokumenty dodane w NEXUSIE — do folderu osoby w SharePoincie."
          : "Synchronizacja jest wyłączona (flaga CONTRACT_DOCS_SP_SYNC_ENABLED) — włącza ją administrator po pierwszym pobraniu."}
      </p>
      {s.last_sync_at ? (
        <p className="text-sm">
          Ostatni bieg: {formatIsoDatePl(warsawDateOf(s.last_sync_at))} ·{" "}
          {s.last_sync_status === "error" ? (
            <span className="text-destructive">{s.last_sync_error}</span>
          ) : (
            <>
              pobrane: {s.last_sync_stats.imported_documents ?? 0}, wysłane do
              SharePointa: {s.last_sync_stats.pushed ?? 0}
            </>
          )}
        </p>
      ) : null}
      <Section title="Do przypisania" count={s.review_count} open>
        {review.isError ? (
          <QueryStateNotice
            state="error"
            onRetry={() => void review.refetch()}
          />
        ) : review.isSuccess ? (
          <ul className="flex flex-col gap-2">
            {review.data.map((item) => (
              <li key={item.item_id} className="flex flex-col gap-1">
                <span>
                  „{item.folder_name}” / {item.file_name} —{" "}
                  {reasonsText(item.reasons)}
                </span>
                <span className="flex flex-wrap gap-2">
                  {item.proposed.length > 0 ? (
                    <Button
                      size="sm"
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate({
                          itemId: item.item_id,
                          action: "assign",
                          ids: item.proposed.map((p) => p.contract_id),
                        })
                      }
                    >
                      Przypisz do:{" "}
                      {item.proposed
                        .map(
                          (p) => `${p.person_name ?? "?"} (#${p.contract_id})`,
                        )
                        .join(", ")}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({
                        itemId: item.item_id,
                        action: "dismiss",
                        ids: [],
                      })
                    }
                  >
                    Pomiń
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <Loader2 className="size-4 animate-spin" />
        )}
      </Section>
    </section>
  );
}

export function ContractDocsSharePointPanel() {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: spApi.status });
  const runs = useQuery({ queryKey: RUNS_KEY, queryFn: spApi.runs });
  const [url, setUrl] = useState("");
  const [runId, setRunId] = useState<number | null>(null);

  useEffect(() => {
    if (!url && status.data?.url) setUrl(status.data.url);
  }, [status.data?.url, url]);
  useEffect(() => {
    if (runId == null && runs.data && runs.data.length > 0)
      setRunId(runs.data[0].id);
  }, [runs.data, runId]);

  const run = useQuery({
    queryKey: ["contract-docs-sp-run", runId],
    queryFn: () => spApi.run(runId as number),
    enabled: runId != null,
    refetchInterval: (q) =>
      q.state.data &&
      (q.state.data.mode === "listing" || q.state.data.mode === "applying")
        ? 2000
        : false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: RUNS_KEY });
    void queryClient.invalidateQueries({ queryKey: STATUS_KEY });
    void queryClient.invalidateQueries({
      queryKey: ["contract-docs-sp-run", runId],
    });
  };

  const preview = useMutation({
    mutationFn: () => spApi.preview(url.trim(), null),
    onSuccess: (data) => {
      setRunId(data.run_id);
      refresh();
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Nie udało się odczytać folderu.")),
  });
  const apply = useMutation({
    mutationFn: (deselected: number[]) =>
      spApi.apply(runId as number, deselected),
    onSuccess: refresh,
    onError: (e) =>
      showError(apiErrorMessage(e, "Nie udało się rozpocząć zapisu.")),
  });
  const rollback = useMutation({
    mutationFn: () => spApi.rollback(runId as number),
    onSuccess: (data) => {
      showSuccess(`Usunięto ${data.removed} dokumentów z tego przebiegu.`);
      refresh();
    },
    onError: (e) =>
      showError(apiErrorMessage(e, "Nie udało się cofnąć przebiegu.")),
  });

  if (status.isError) {
    return (
      <QueryStateNotice state="error" onRetry={() => void status.refetch()} />
    );
  }
  if (!status.isSuccess) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  }
  const s = status.data;
  const busyRun = run.data?.mode === "listing" || run.data?.mode === "applying";

  return (
    <div className="flex flex-col gap-4">
      {confirmDialog}
      <p className="text-sm text-muted-foreground">
        NEXUS czyta folder „Umowy pracowników” (podfolder „Nazwisko Imię” na
        osobę) i zapisuje pliki PDF i JPG w zakładce Dokumenty każdego kontraktu
        tej osoby. Typ dokumentu wynika z nazwy pliku. Word jest pomijany,
        kontraktów z folderu się nie zakłada, a Filipa Jabłońskiego pomijamy
        (dokumenty dodaje człowiek).
      </p>
      {!s.configured ? (
        <div className="rounded-md border border-warning/25 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
          NEXUS nie ma jeszcze dostępu do SharePointa. Administrator M365
          zakłada rejestrację „NEXUS Contract Documents” z uprawnieniem
          Sites.Selected do tej jednej witryny i przekazuje jej dane do
          konfiguracji serwera — instrukcja w repozytorium:
          docs/contract-docs-sharepoint-setup.md.
        </div>
      ) : null}
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          preview.mutate();
        }}
      >
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Link do folderu „Umowy pracowników” w SharePoincie"
          aria-label="Link do folderu w SharePoincie"
          className="w-0 flex-1"
        />
        <Button
          type="submit"
          disabled={
            !s.configured || !url.trim() || preview.isPending || busyRun
          }
        >
          <RefreshCw className="size-4" /> Czytaj folder
        </Button>
      </form>
      {runs.data && runs.data.length > 1 ? (
        <label className="flex items-center gap-2 text-sm">
          Przebieg:
          <select
            className="rounded-md border border-border bg-background px-2 py-1"
            value={runId ?? ""}
            onChange={(e) => setRunId(Number(e.target.value))}
          >
            {runs.data.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} — {RUN_MODE_LABEL[r.mode]}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {run.isError ? (
        <QueryStateNotice state="error" onRetry={() => void run.refetch()} />
      ) : run.isSuccess ? (
        <ContractDocsRunView
          run={run.data}
          busy={apply.isPending || rollback.isPending}
          onApply={async (deselected) => {
            const ok = await askConfirm({
              title: "Zapisać dokumenty na kontraktach?",
              description:
                "NEXUS pobierze zaznaczone pliki z SharePointa i doda je do zakładki Dokumenty. Pliki, które kontrakt już ma, zostaną pominięte. Zapis da się cofnąć.",
              confirmLabel: "Pobierz i zapisz",
            });
            if (ok) apply.mutate(deselected);
          }}
          onRollback={async () => {
            const ok = await askConfirm({
              title: "Cofnąć ten zapis?",
              description:
                "Dokumenty dodane tym przebiegiem znikną z kontraktów. Pliki w SharePoincie zostają.",
              confirmLabel: "Cofnij zapis",
              variant: "destructive",
            });
            if (ok) rollback.mutate();
          }}
        />
      ) : runId != null ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : null}
      <SyncSection />
    </div>
  );
}
