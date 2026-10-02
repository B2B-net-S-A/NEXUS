"use client";

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  HelpCircle,
  RefreshCw,
  Upload,
} from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { ConfirmTwoStepButton } from "@/components/orders/ConfirmTwoStepButton";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  mdConsumptionApi,
  type ImportDetail,
  type ImportRow,
  type PolkomtelReprocessResponse,
  type PolkomtelReprocessTarget,
} from "@/lib/api/orderGroups";
import {
  countImportRowTones,
  importRowTone,
  type ImportRowTone,
} from "@/lib/md-import-row-tone";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { pluralPl } from "@/lib/plural-pl";
import { cn, formatCurrency } from "@/lib/utils";

const inputClass =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring pointer-coarse:h-10";

/** Kolor etykiety wg stanu wiersza (`lib/md-import-row-tone.ts`). */
const TONE_STYLE: Record<ImportRowTone, { className: string; icon: typeof CheckCircle2 }> = {
  applied: { className: "text-success-muted-foreground bg-success-muted", icon: CheckCircle2 },
  pending: { className: "text-warning-muted-foreground bg-warning-muted", icon: HelpCircle },
  cost: { className: "text-info-muted-foreground bg-info-muted", icon: CheckCircle2 },
  // U14 (audyt 24.09.2026): osoba bez zamówienia MD to zwykły kontraktor
  // okresowy, nie błąd — szary stan, bez czerwonego nazwiska.
  neutral: { className: "text-muted-foreground bg-muted", icon: HelpCircle },
  danger: { className: "text-destructive bg-destructive/10", icon: AlertTriangle },
};

/**
 * Wiersz, z którego NIC nie zeszło z żadnego budżetu i który wymaga uwagi —
 * numer z „Uwag” bez zamówienia albo faktura bez zamówienia. Osoba bez
 * zamówienia MD (stan `neutral`) nie jest „zgubiona” (audyt 24.09.2026, U14).
 */
export function isLostImportRow(row: ImportRow): boolean {
  return importRowTone(row) === "danger";
}

/**
 * Bieżący miesiąc wg zegara użytkownika (RRRR-MM). N7 (audyt 24.09.2026):
 * `toISOString()` liczy w UTC, więc 1. dnia miesiąca między północą a 1–2:00
 * czasu polskiego podpowiadał poprzedni miesiąc.
 */
export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function formatMd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pl-PL", {
    maximumFractionDigits: 3,
    useGrouping: false,
  }).format(value);
}

function apiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  return typeof detail === "string" ? detail : fallback;
}

const REPROCESS_KIND_LABEL: Record<PolkomtelReprocessTarget["kind"], string> = {
  md_line: "MD konsultanta",
  shared_md: "Wspólna pula MD",
  cost: "Zamówienie kosztowe",
};

function formatReprocessValue(
  value: number | string | null,
  kind: PolkomtelReprocessTarget["kind"],
): string {
  if (value === null) return "brak";
  return `${formatMd(Number(value))} ${kind === "cost" ? "PLN" : "MD"}`;
}

function reprocessConflictsFromError(err: unknown): string[] {
  const detail = (
    err as {
      response?: { data?: { detail?: { conflicts?: unknown } } };
    }
  )?.response?.data?.detail;
  if (!detail || !Array.isArray(detail.conflicts)) return [];
  return detail.conflicts.filter(
    (conflict): conflict is string => typeof conflict === "string",
  );
}

/**
 * Import miesięcznego raportu MD z Finansów.
 *
 * Historyczne budżety MD są dopasowywane po imieniu i nazwisku. Zamówienia
 * kosztowe oraz wspólne pule MD wymagają dodatkowo numeru zamówienia
 * wyciągniętego z kolumny „Uwagi". Wiersz niejednoznaczny NIE jest zgadywany.
 */
export function MdImportWorkspace() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const [file, setFile] = useState<File | null>(null);
  const [periodMonth, setPeriodMonth] = useState(currentMonth());
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ImportDetail | null>(null);
  const [reprocessPreview, setReprocessPreview] =
    useState<PolkomtelReprocessResponse | null>(null);
  const [reprocessRaceConflict, setReprocessRaceConflict] = useState<{
    importId: number;
    conflicts: string[];
  } | null>(null);

  const history = useQuery({
    queryKey: ["md-imports"],
    queryFn: async () => (await mdConsumptionApi.listImports(100)).data,
  });

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Wybierz plik");
      return (await mdConsumptionApi.upload(file, periodMonth)).data;
    },
    onSuccess: (data) => {
      setDetail(data);
      setReprocessPreview(null);
      setReprocessRaceConflict(null);
      setUploadError(null);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      queryClient.invalidateQueries({ queryKey: ["md-imports"] });
      showToast(
        `Zaimportowano ${data.rows_applied} z ${data.rows_total} ${pluralPl(data.rows_total, "wiersza", "wierszy", "wierszy")}`,
        "success",
      );
    },
    onError: (err) =>
      setUploadError(apiError(err, "Nie udało się zaimportować pliku.")),
  });

  const assign = useMutation({
    mutationFn: async ({
      rowId,
      orderId,
      confirmOverflow = false,
    }: {
      rowId: number;
      orderId: number;
      confirmOverflow?: boolean;
    }) => {
      if (!detail) throw new Error("Brak importu");
      const assigned = (
        await mdConsumptionApi.assignRow(detail.id, rowId, orderId, confirmOverflow)
      ).data;
      return {
        held: assigned.status === "overflow",
        confirmed: confirmOverflow,
        detail: (await mdConsumptionApi.getImport(detail.id)).data,
      };
    },
    onSuccess: ({ held, confirmed, detail: data }) => {
      setDetail(data);
      setReprocessPreview(null);
      setReprocessRaceConflict(null);
      queryClient.invalidateQueries({ queryKey: ["md-imports"] });
      showToast(
        held
          ? "Zejście przekroczyłoby pulę — wiersz czeka na zatwierdzenie przekroczenia"
          : confirmed
            ? "Zatwierdzono przekroczenie puli i zaksięgowano MD"
            : "Przypisano zamówienie i zaktualizowano MD",
        held ? "error" : "success",
      );
    },
    onError: (err) => showToast(apiError(err, "Nie udało się przypisać."), "error"),
  });

  const reprocessDryRun = useMutation({
    mutationFn: async (importId: number) => {
      return (await mdConsumptionApi.reprocessPolkomtel(importId, false)).data;
    },
    onMutate: () => {
      setReprocessPreview(null);
      setReprocessRaceConflict(null);
    },
    onSuccess: (data) => {
      setReprocessPreview(data);
      showToast("Analiza ponownego dopasowania Polkomtel jest gotowa", "success");
    },
    onError: (err) =>
      showToast(
        apiError(err, "Nie udało się sprawdzić ponownego dopasowania."),
        "error",
      ),
  });

  const reprocessApply = useMutation({
    mutationFn: async (importId: number) => {
      return (await mdConsumptionApi.reprocessPolkomtel(importId, true)).data;
    },
    onSuccess: async (data) => {
      setReprocessPreview(data);
      setReprocessRaceConflict(null);
      queryClient.invalidateQueries({ queryKey: ["md-imports"] });
      try {
        if (detail?.id === data.import_id) {
          setDetail((await mdConsumptionApi.getImport(data.import_id)).data);
        }
      } catch {
        // Sam APPLY już się udał. Nie zmieniamy komunikatu sukcesu tylko dlatego,
        // że wtórne odświeżenie tabeli importu chwilowo się nie powiodło.
      }
      showToast("Ponowne dopasowanie Polkomtel zostało zastosowane", "success");
    },
    onError: (err, importId) => {
      // Endpoint ponownie waliduje plan pod blokadami. Po konflikcie podgląd
      // jest nieaktualny i operator musi świadomie uruchomić nowy dry-run.
      setReprocessPreview(null);
      const conflicts = reprocessConflictsFromError(err);
      setReprocessRaceConflict({ importId, conflicts });
      showToast(
        conflicts.length > 0
          ? "Stan danych się zmienił. Sprawdź konflikty i uruchom analizę ponownie."
          : apiError(err, "Stan danych się zmienił. Uruchom analizę ponownie."),
        "error",
      );
    },
  });

  const pendingCount = useMemo(
    () =>
      (detail?.rows ?? []).filter(
        (r) => r.status === "needs_assignment" || r.status === "overflow",
      ).length,
    [detail],
  );
  const toneCounts = useMemo(() => countImportRowTones(detail?.rows ?? []), [detail]);

  const currentReprocessPreview =
    reprocessPreview?.import_id === detail?.id ? reprocessPreview : null;
  const currentReprocessRaceConflicts =
    reprocessRaceConflict && reprocessRaceConflict.importId === detail?.id
      ? reprocessRaceConflict.conflicts
      : [];
  const reprocessHasChanges = Boolean(
    currentReprocessPreview &&
      (currentReprocessPreview.rows_to_update > 0 ||
        currentReprocessPreview.targets_to_recalculate > 0),
  );
  const reprocessCanApply = Boolean(
    currentReprocessPreview &&
      !currentReprocessPreview.applied &&
      currentReprocessPreview.conflicts.length === 0 &&
      reprocessHasChanges,
  );

  const recentImports = history.data?.imports ?? [];

  return (
    <div className="flex flex-col gap-3.5">
      {confirmDialog}
      {/* Wąski pasek z przerywaną ramką (makieta 02.10.2026): miesiąc, plik
          i „Importuj” w jednym rzędzie, opis drobnym drukiem pod spodem. */}
      <section
        className="relative rounded-[10px] border border-dashed border-border bg-card px-3.5 py-2.5"
        data-help="finance.md_import"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="text-[13px] font-semibold text-foreground">Import zużycia MD</h2>
          <div className="flex items-center gap-1.5">
            <label htmlFor="md-period" className="text-xs font-semibold text-muted-foreground">
              Miesiąc raportu *
            </label>
            <input
              id="md-period"
              type="month"
              value={periodMonth}
              onChange={(e) => setPeriodMonth(e.target.value)}
              className={inputClass}
            />
          </div>
          <div className="flex min-w-0 items-center gap-1.5">
            <label htmlFor="md-file" className="shrink-0 text-xs font-semibold text-muted-foreground">
              Plik XLSX *
            </label>
            <input
              id="md-file"
              ref={fileInput}
              type="file"
              accept=".xlsx,.xlsm"
              onChange={(e) => {
                const picked = e.target.files?.[0] ?? null;
                if (picked && !/\.(xlsx|xlsm)$/i.test(picked.name)) {
                  setUploadError("Dozwolone są tylko pliki XLSX.");
                  setFile(null);
                  return;
                }
                setUploadError(null);
                setFile(picked);
              }}
              className={cn(
                inputClass,
                "min-w-0 max-w-full py-1 text-xs file:mr-3 file:rounded file:border-0 file:bg-muted file:px-2 file:py-0.5 file:text-xs",
              )}
            />
          </div>
          <button
            type="button"
            disabled={!file || !periodMonth || upload.isPending}
            onClick={() => upload.mutate()}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 pointer-coarse:min-h-10"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
            {upload.isPending ? "Importowanie…" : "Importuj"}
          </button>
          <p className="basis-full text-xs text-muted-foreground 2xl:ml-auto 2xl:basis-auto">
            Powtórny import tego samego miesiąca nadpisuje wcześniejsze zużycie — MD nie
            odejmą się drugi raz.
          </p>
        </div>

        {uploadError ? (
          <p role="alert" className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {uploadError}
          </p>
        ) : null}

        <p className="mt-1.5 text-xs text-muted-foreground">
          Wgraj miesięczny raport (XLSX) z kolumnami konsultanta i liczby MD.
          Nagłówki rozpoznawane są automatycznie — m.in. „Konsultant" / „Imię
          i nazwisko" oraz „MD" / „Osobodni". Dla zamówień kosztowych i
          wspólnej puli MD system dopasowuje również numer zamówienia z kolumny
          „Uwagi".
        </p>
      </section>

      {/* Od `lg`: lista importów po lewej, wybrany import po prawej. Poniżej
          `lg` kolejność jak dotąd — wynik importu, pod nim historia. */}
      <div className="grid gap-3.5 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
        <section className="order-2 min-w-0 lg:order-1">
          <div className="rounded-[10px] border border-border bg-card p-1.5">
            <h2 className={cn("px-2.5 pb-1 pt-2", CALM_HEAD)}>Ostatnie importy</h2>
            {history.isError ? (
              <div className="p-1">
                <QueryStateNotice
                  state="error"
                  description="Nie udało się wczytać historii importów."
                  onRetry={() => history.refetch()}
                />
              </div>
            ) : !history.isSuccess ? (
              // `isSuccess`, nie `isLoading` — między ponowieniami react-query nie
              // jest ani „loading", ani „error", a `data` jest puste, więc gałąź
              // pustego stanu wygrywała i twierdziła, że importów nie ma.
              <p className="px-2.5 py-2 text-sm text-muted-foreground">Wczytywanie…</p>
            ) : recentImports.length === 0 ? (
              <EmptyState
                title="Brak importów"
                description="Nie wgrano jeszcze żadnego raportu MD."
              />
            ) : (
              <ul className="flex flex-col gap-0.5 lg:max-h-[70dvh] lg:overflow-y-auto">
                {recentImports.map((imp) => {
                  const open = detail?.id === imp.id;
                  return (
                    <li key={imp.id}>
                      <button
                        type="button"
                        title="Otwórz import"
                        aria-current={open ? "true" : undefined}
                        onClick={async () => {
                          try {
                            setDetail((await mdConsumptionApi.getImport(imp.id)).data);
                            setReprocessPreview(null);
                            setReprocessRaceConflict(null);
                          } catch {
                            showToast("Nie udało się otworzyć importu", "error");
                          }
                        }}
                        className={cn(
                          "flex w-full min-w-0 items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
                          open ? "bg-primary/10" : "hover:bg-muted/60",
                        )}
                      >
                        <FileSpreadsheet
                          className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-semibold text-foreground">
                            {imp.period_month}
                          </span>
                          <span className="block truncate text-[11.5px] text-muted-foreground">
                            {imp.filename}
                          </span>
                          <span className="mt-1 flex flex-wrap gap-1">
                            <span className="rounded-md bg-muted px-1.5 py-px text-[11px] font-medium text-muted-foreground">
                              {imp.rows_applied}/{imp.rows_total} zastosowanych
                            </span>
                            {imp.rows_ambiguous > 0 ? (
                              <span className="rounded-md bg-warning-muted px-1.5 py-px text-[11px] font-medium text-warning-muted-foreground">
                                {imp.rows_ambiguous} do przypisania
                              </span>
                            ) : null}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <div className="order-1 flex min-w-0 flex-col gap-3 lg:order-2">
          {detail ? (
            <>
              <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="text-sm font-semibold text-foreground">
                  Wynik importu — {detail.period_month}
                </h2>
                <p className="min-w-0 text-xs text-muted-foreground">
                  {detail.filename}
                  {detail.sheet_name ? ` · arkusz „${detail.sheet_name}"` : ""}
                </p>
              </header>

              {/* Liczniki stanów — każdy wiersz ma dokładnie jeden stan, więc
                  pigułki sumują się do liczby wierszy tabeli pod spodem. */}
              <div className="flex flex-wrap gap-1.5 text-xs">
                <span className={cn(COUNTER_PILL, "text-success-muted-foreground")}>
                  Zaktualizowano: <strong>{toneCounts.applied}</strong>
                </span>
                <span
                  className={cn(
                    COUNTER_PILL,
                    toneCounts.pending > 0
                      ? "border-transparent bg-warning-muted text-warning-muted-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  Wymaga przypisania: <strong>{toneCounts.pending}</strong>
                </span>
                {toneCounts.cost > 0 ? (
                  <span className={cn(COUNTER_PILL, "text-info-muted-foreground")}>
                    Rozliczono kwotowo: <strong>{toneCounts.cost}</strong>
                  </span>
                ) : null}
                <span className={cn(COUNTER_PILL, "text-muted-foreground")}>
                  Bez zamówienia MD: <strong>{toneCounts.neutral}</strong>
                </span>
                <span
                  className={cn(
                    COUNTER_PILL,
                    toneCounts.danger > 0
                      ? "border-transparent bg-destructive/10 text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  Do sprawdzenia: <strong>{toneCounts.danger}</strong>
                </span>
              </div>

              {pendingCount > 0 ? (
                <p className="rounded-lg bg-warning-muted px-3 py-1.5 text-xs text-warning-muted-foreground">
                  {pendingCount}{" "}
                  {pluralPl(pendingCount, "wiersz pasuje", "wiersze pasują", "wierszy pasuje")} do
                  więcej niż jednego zamówienia. System nie
                  wybiera za Ciebie — wskaż właściwe zamówienie w kolumnie obok.
                </p>
              ) : null}

              <section className="rounded-[10px] border border-border bg-card px-3.5 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-[13px] font-semibold text-foreground">
                      Ponowne dopasowanie Polkomtel
                    </h3>
                    <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
                      Najpierw wykonaj bezpieczną analizę. System pokaże dokładne
                      zamówienia, identyfikatory wierszy i wartości przed oraz po korekcie.
                      Samo sprawdzenie nie zapisuje żadnych zmian.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={reprocessDryRun.isPending || reprocessApply.isPending}
                    onClick={() => reprocessDryRun.mutate(detail.id)}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50 pointer-coarse:min-h-10"
                  >
                    <RefreshCw
                      className={cn("h-3.5 w-3.5", reprocessDryRun.isPending && "animate-spin")}
                      aria-hidden="true"
                    />
                    {reprocessDryRun.isPending
                      ? "Sprawdzanie…"
                      : "Sprawdź dopasowanie Polkomtel"}
                  </button>
                </div>

                {currentReprocessRaceConflicts.length > 0 ? (
                  <div role="alert" className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    <p className="font-semibold">
                      Stan danych zmienił się po analizie. Korekta nie została
                      zastosowana. Sprawdź konflikty i uruchom analizę ponownie:
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5">
                      {currentReprocessRaceConflicts.map((conflict, index) => (
                        <li key={`${conflict}-${index}`}>{conflict}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {currentReprocessPreview ? (
                  <div className="mt-3 flex flex-col gap-3" aria-label="Podgląd korekty Polkomtel">
                    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                      <span>
                        Import: <strong className="text-foreground">#{currentReprocessPreview.import_id}</strong>
                      </span>
                      <span>
                        Miesiąc: <strong className="text-foreground">{currentReprocessPreview.period_month}</strong>
                      </span>
                      <span>
                        Sprawdzone wiersze: <strong className="text-foreground">{currentReprocessPreview.rows_scanned}</strong>
                      </span>
                      <span>
                        Wiersze do korekty: <strong className="text-foreground">{currentReprocessPreview.rows_to_update}</strong>
                      </span>
                      <span>
                        Budżety do przeliczenia: <strong className="text-foreground">{currentReprocessPreview.targets_to_recalculate}</strong>
                      </span>
                    </div>

                    {currentReprocessPreview.targets.length > 0 ? (
                      <div className="relative overflow-x-auto rounded-md border border-border bg-background">
                        <table className="w-full text-xs">
                          <thead className={CALM_HEAD}>
                            <tr className="border-b border-border text-left">
                              <th className="px-3 py-2 font-semibold">Typ</th>
                              <th className="px-3 py-2 font-semibold">Zamówienie</th>
                              <th className="px-3 py-2 font-semibold">Wiersze importu</th>
                              <th className="px-3 py-2 font-semibold">Zmiana wartości</th>
                              <th className="px-3 py-2 font-semibold">Zapis</th>
                            </tr>
                          </thead>
                          <tbody>
                            {currentReprocessPreview.targets.map((target) => (
                              <tr
                                key={`${target.kind}-${target.group_id}-${target.order_id ?? "group"}`}
                                className={cn(CALM_ROW, "last:border-b-0")}
                              >
                                <td className="px-3 py-2 text-foreground">
                                  {REPROCESS_KIND_LABEL[target.kind]}
                                </td>
                                <td className="px-3 py-2 text-foreground">
                                  <span className="font-medium">{target.order_number}</span>
                                  <span className="ml-1 text-muted-foreground">
                                    (grupa #{target.group_id}
                                    {target.order_id !== null ? `, linia #${target.order_id}` : ""})
                                  </span>
                                </td>
                                <td className="px-3 py-2 text-muted-foreground">
                                  <span>ID: {target.row_ids.join(", ") || "—"}</span>
                                  <br />
                                  <span>
                                    Do korekty: {target.row_ids_to_update.join(", ") || "—"}
                                  </span>
                                </td>
                                <td className="px-3 py-2 tabular-nums text-foreground">
                                  {formatReprocessValue(target.current_value, target.kind)} →{" "}
                                  {formatReprocessValue(target.expected_value, target.kind)}
                                </td>
                                <td className="px-3 py-2">
                                  {target.write_required ? (
                                    <span className="font-medium text-warning-muted-foreground">wymagany</span>
                                  ) : (
                                    <span className="text-muted-foreground">bez zmiany budżetu</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}

                    {currentReprocessPreview.conflicts.length > 0 ? (
                      <div role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        <p className="font-semibold">
                          Nie można zastosować korekty — najpierw rozwiąż konflikty:
                        </p>
                        <ul className="mt-1 list-disc space-y-0.5 pl-5">
                          {currentReprocessPreview.conflicts.map((conflict, index) => (
                            <li key={`${conflict}-${index}`}>{conflict}</li>
                          ))}
                        </ul>
                      </div>
                    ) : currentReprocessPreview.applied ? (
                      <p className="rounded-md bg-success-muted px-3 py-2 text-xs font-medium text-success-muted-foreground">
                        Korekta została zastosowana. Możesz uruchomić analizę ponownie,
                        aby potwierdzić brak dalszych zmian.
                      </p>
                    ) : !reprocessHasChanges ? (
                      <p className="rounded-md bg-success-muted px-3 py-2 text-xs font-medium text-success-muted-foreground">
                        Brak zmian do zastosowania — import jest już poprawnie dopasowany.
                      </p>
                    ) : null}

                    {reprocessCanApply ? (
                      <div className="flex justify-end">
                        <button
                          type="button"
                          disabled={reprocessApply.isPending || reprocessDryRun.isPending}
                          onClick={async () => {
                            const preview = currentReprocessPreview;
                            const confirmed = await askConfirm({
                              title: `Zastosować korektę dla importu #${preview.import_id} (${preview.period_month})?`,
                              description: `Zostanie poprawionych ${preview.rows_to_update} wierszy i przeliczonych ${preview.targets_to_recalculate} budżetów.`,
                              confirmLabel: "Zastosuj korektę",
                            });
                            if (confirmed) {
                              reprocessApply.mutate(preview.import_id);
                            }
                          }}
                          className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 pointer-coarse:min-h-10"
                        >
                          {reprocessApply.isPending
                            ? "Stosowanie korekty…"
                            : "Zastosuj sprawdzoną korektę"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </section>

              <section className="rounded-[10px] border border-border bg-card">
                <div className="relative overflow-x-auto">
                  <table className="w-full min-w-[52rem] text-[13px]">
                    <thead className={cn("bg-background", CALM_HEAD)}>
                      <tr className="border-b border-border text-left">
                        <th className="rounded-tl-[10px] px-3.5 py-2 font-semibold">Wiersz</th>
                        <th className="px-3.5 py-2 font-semibold">Konsultant</th>
                        <th className="px-3.5 py-2 text-right font-semibold">MD</th>
                        <th className="px-3.5 py-2 text-right font-semibold">Faktura</th>
                        <th className="px-3.5 py-2 font-semibold">Status</th>
                        <th className="rounded-tr-[10px] px-3.5 py-2 font-semibold">Zamówienie</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.rows.map((row) => (
                        <ImportRowLine
                          key={row.id}
                          row={row}
                          busy={assign.isPending}
                          onAssign={(orderId, confirmOverflow) =>
                            assign.mutate({ rowId: row.id, orderId, confirmOverflow })
                          }
                        />
                      ))}
                    </tbody>
                  </table>
                </div>

                {detail.skipped_rows.length > 0 ? (
                  <div className="border-t border-border px-3.5 py-2.5">
                    <p className="text-xs font-medium text-foreground">
                      Pominięte wiersze ({detail.skipped_rows.length})
                    </p>
                    <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
                      {detail.skipped_rows.slice(0, 20).map((s, i) => (
                        <li key={`${s.row}-${i}`}>
                          wiersz {s.row}: {s.reason}
                          {s.consultant_name ? ` (${s.consultant_name})` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </section>
            </>
          ) : (
            // Tylko od `lg` — poniżej lista importów stoi sama, jak dotąd.
            <p className="hidden rounded-[10px] border border-dashed border-border p-8 text-center text-sm text-muted-foreground lg:block">
              Wgraj raport albo wybierz import z listy — tutaj pojawią się jego
              wiersze.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** Pigułka licznika nad tabelą wierszy importu. */
const COUNTER_PILL =
  "inline-flex h-7 items-center gap-1 rounded-full border border-border bg-card px-2.5 font-medium";

/** „połączono N wierszy” — ta sama osoba z tym samym numerem (ticket 1.1). */
function mergedNote(row: ImportRow) {
  const merged = row.merged_rows ?? 1;
  if (merged < 2) return null;
  return (
    <span className="ml-1">
      · połączono {merged} {pluralPl(merged, "wiersz", "wiersze", "wierszy")} arkusza
    </span>
  );
}

function ImportRowLine({
  row,
  busy,
  onAssign,
}: {
  row: ImportRow;
  busy: boolean;
  onAssign: (orderId: number, confirmOverflow?: boolean) => void;
}) {
  const [choice, setChoice] = useState("");
  const tone = importRowTone(row);
  const style = TONE_STYLE[tone];
  const Icon = style.icon;
  const costSettled = row.cost_status === "applied";
  const costFailed = row.cost_status != null && !costSettled;
  // Czerwone nazwisko = wiersz, z którego nic nie zeszło, a powinno —
  // numer z „Uwag” albo faktura bez zamówienia. Osoba bez zamówienia MD
  // (zwykły kontraktor okresowy) nie jest błędem (audyt 24.09.2026, U14).
  const unmatchedRow = tone === "danger";

  return (
    <tr className={cn(CALM_ROW, "last:border-b-0")}>
      <td className="px-3.5 py-2 text-[11.5px] tabular-nums text-muted-foreground">
        {row.row_number}
      </td>
      {/* Czerwone nazwisko = wiersz, który NIE trafił na żadne zamówienie —
          ani po nazwisku (MD), ani po numerze z „Uwag" (kwota). To jedyny
          sygnał, że zaraportowana praca nie zeszła z niczyjego budżetu. */}
      <td className="px-3.5 py-2">
        <span
          className={cn(
            "font-semibold",
            unmatchedRow ? "text-destructive" : "text-foreground",
          )}
        >
          {row.consultant_name}
        </span>
        {row.order_number_hint ? (
          <span className={CALM_SUBLINE}>nr {row.order_number_hint}</span>
        ) : null}
      </td>
      <td className="px-3.5 py-2 text-right tabular-nums">
        {row.md_reported == null ? (
          <span className={CALM_EMPTY}>—</span>
        ) : (
          formatMd(row.md_reported)
        )}
      </td>
      <td className="whitespace-nowrap px-3.5 py-2 text-right tabular-nums">
        {/* Kwota z walutą (E10) — ten sam formater co reszta modułu. */}
        {formatCurrency(row.invoice_amount)}
      </td>
      <td className="px-3.5 py-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium",
            style.className,
          )}
        >
          <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
          {row.status_label}
        </span>
      </td>
      <td className="px-3.5 py-2">
        {row.status === "needs_assignment" ? (
          <div className="flex items-center gap-2">
            <select
              aria-label={`Wybierz zamówienie dla ${row.consultant_name}`}
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              className="h-7 min-w-0 max-w-[22rem] rounded-md border border-border bg-background px-2 text-xs pointer-coarse:h-10"
            >
              <option value="">— wybierz zamówienie —</option>
              {row.options.map((o) => (
                <option key={o.order_id} value={o.order_id}>
                  {o.client_name} · nr {o.order_number} ({formatMd(o.md_remaining)} MD)
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!choice || busy}
              onClick={() => onAssign(Number(choice))}
              className="inline-flex h-7 items-center rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 pointer-coarse:min-h-10"
            >
              Przypisz
            </button>
          </div>
        ) : row.status === "overflow" && row.matched ? (
          // Ticket 1.1: zejście zepchnęłoby saldo poniżej zera — nic nie
          // zostało zaksięgowane, dopóki człowiek nie zatwierdzi przekroczenia.
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {row.matched.client_name} · nr {row.matched.order_number} (pozostało{" "}
              {formatMd(row.matched.md_remaining)} MD)
              {mergedNote(row)}
            </span>
            <ConfirmTwoStepButton
              onConfirm={() => onAssign(row.matched!.order_id, true)}
              disabled={busy}
              confirmLabel="Na pewno? Saldo spadnie poniżej zera"
              ariaLabel={`Zatwierdź przekroczenie puli dla ${row.consultant_name}`}
              confirmAriaLabel={`Na pewno zatwierdzić przekroczenie puli dla ${row.consultant_name}? Saldo spadnie poniżej zera`}
              className="rounded-md border border-border px-2 py-1 text-xs font-medium"
            >
              Zatwierdź mimo przekroczenia
            </ConfirmTwoStepButton>
          </div>
        ) : row.matched ? (
          <span className="text-xs text-muted-foreground">
            {row.matched.client_name} · nr {row.matched.order_number}
            {mergedNote(row)}
          </span>
        ) : row.status_reason ? (
          // Wiersz wskazał zamówienie numerem, a ta osoba go w tym miesiącu
          // nie rozlicza — zużycie świadomie NIE trafiło na inne zamówienie.
          <span className="text-xs text-destructive">{row.status_reason}</span>
        ) : costFailed ? (
          <span className="text-xs text-destructive">{row.cost_status_label}</span>
        ) : costSettled ? (
          <span className="text-xs text-muted-foreground">
            Rozliczono kwotowo · nr {row.order_number_hint}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">
            Żadne zamówienie tej osoby nie obejmuje tego miesiąca
          </span>
        )}
      </td>
    </tr>
  );
}
