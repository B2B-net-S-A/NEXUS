"use client";

/**
 * Zakładka „Konsultanci” profilu klienta (decyzja Artura 18.11.2026, wariant B
 * makiety): osoba u klienta z umową, bieżącym zamówieniem, stawką i „Wymaga
 * uwagi” w jednym wierszu. Zastępuje sekcję „Konsultanci” z Przeglądu i rejestr
 * klienta z modułu Kontrakty (nr projektu, prolongata, nowy kontrakt, edycja
 * pól rejestru, eksport). Zamówienia zostają obok jako dokumenty i budżety MD.
 *
 * Dane: `GET /api/clients/{id}/profile` — to samo zapytanie co nagłówek strony
 * („Aktywni konsultanci”), więc liczby w nagłówku i na podzakładce się zgadzają.
 * Znaczniki liczy serwer (`services/consultant_order_state.py`) regułami, które
 * już działają w Zamówieniach i w eksporcie COMPASS.
 */
import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarClock,
  Download,
  FileClock,
  FileText,
  Pencil,
  Plus,
  Users,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { hasPermission } from "@/lib/permissions";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import { mayExportFiles, useAuthStore } from "@/store/auth";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import {
  filterConsultantsByExecutiveContract,
  isEzdrowieClient,
  type ConsultantAssignmentFilter,
} from "@/lib/ezdrowie";
import type { RegisterContractRow } from "@/lib/contract-register";
import {
  formatDate,
  formatPLN,
  type ActiveConsultantItem,
  type ConsultantAttention,
} from "@/types/client-profile";
import { useClientProfile } from "@/components/client-profile/useClientProfile";
import {
  ConsultantIdentity,
  ConsultantsTable,
  toConsultantRow,
} from "@/components/client-profile/ConsultantsTable";
import { ContractStructureSection } from "@/components/client-profile/ContractStructureSection";
import { ExecutiveContractFilter } from "@/components/client-profile/ExecutiveContractFilter";
import { ExtendContractMenu } from "@/components/client-profile/actions/ExtendContractMenu";
import { ReEngageButton } from "@/components/client-profile/actions/ReEngageButton";
import { ContractRegisterDialog } from "@/components/contracts/ContractRegisterDialog";
import { ProlongationSelect } from "@/components/contracts/ProlongationSelect";

type ConsultantsTabKey = "obecni" | "uwaga" | "planowani" | "szkice" | "archiwum";

const CONTRACT_STATUS: Record<string, { label: string; tone: StatusDotTone }> = {
  active: { label: "Aktywna", tone: "success" },
  ending: { label: "Wypowiedziana", tone: "warning" },
  draft: { label: "Szkic", tone: "neutral" },
  ready_for_signature: { label: "Do podpisu", tone: "info" },
};

function attentionLabel(code: ConsultantAttention, row: ActiveConsultantItem): string {
  if (code === "notice") return "Umowa wypowiedziana";
  if (code === "no_current_order") {
    return row.order_end_date ? "Brak bieżącego zamówienia" : "Brak zamówienia";
  }
  // Ta sama nazwa co pigułka „Bez kontynuacji 30 dni” w Zamówieniach.
  return row.order_ending_on
    ? `Bez kontynuacji po ${formatDate(row.order_ending_on)}`
    : "Bez kontynuacji";
}

function needsAttention(row: ActiveConsultantItem): boolean {
  return (row.attention?.length ?? 0) > 0;
}

function amount(value: number | null | undefined): ReactNode {
  return value == null ? <span className={CALM_EMPTY}>—</span> : formatPLN(value);
}

const HEAD = cn(CALM_HEAD, "py-2 pr-4");
const HEAD_RIGHT = cn(CALM_HEAD, "py-2 pr-4 text-right");

interface WorkTableProps {
  rows: ActiveConsultantItem[];
  clientId: number;
  showProject: boolean;
  showProlongation: boolean;
  canEdit: boolean;
  onEditRegister: (contractId: number) => void;
}

/** Lista robocza: umowa, bieżące zamówienie, stawka, znaczniki, pola rejestru. */
function ConsultantsWorkTable({
  rows,
  clientId,
  showProject,
  showProlongation,
  canEdit,
  onEditRegister,
}: WorkTableProps) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th className={cn(HEAD, "sticky left-0 z-10 bg-card dark:bg-muted")}>Konsultant</th>
            <th className={HEAD}>Umowa</th>
            <th className={HEAD}>Bieżące zamówienie</th>
            {showProject ? <th className={HEAD}>Projekt</th> : null}
            <th className={HEAD_RIGHT}>Stawka [godz.]</th>
            {/* Marża zostaje miesięczna — „Aktywne MRR” w nagłówku jest jej sumą. */}
            <th className={HEAD_RIGHT}>Marża [mc]</th>
            {showProlongation ? <th className={HEAD}>Prolongata</th> : null}
            <th className={cn(CALM_HEAD, "py-2 text-right")}>Akcje</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = CONTRACT_STATUS[row.contract_status ?? ""] ?? {
              label: row.contract_status ?? "—",
              tone: "neutral" as StatusDotTone,
            };
            return (
              <tr key={row.contract_id} className={cn(CALM_ROW, "h-[52px] last:border-b-0")}>
                <td className="sticky left-0 z-10 max-w-[250px] bg-card py-2 pr-4 dark:bg-muted">
                  <ConsultantIdentity r={toConsultantRow(row)} />
                </td>
                <td className="py-2 pr-4 whitespace-nowrap">
                  <StatusDot tone={status.tone}>{status.label}</StatusDot>
                  <span className={cn(CALM_SUBLINE, "tabular-nums")}>
                    {row.start_date ? `od ${formatDate(row.start_date)}` : "bez daty startu"}
                  </span>
                </td>
                <td className="py-2 pr-4 whitespace-nowrap tabular-nums">
                  {row.order_end_date || row.order_start_date ? (
                    <>
                      {row.order_end_date ? `do ${formatDate(row.order_end_date)}` : "bez daty końca"}
                      {row.order_start_date || row.order_status === "draft" ? (
                        <span className={CALM_SUBLINE}>
                          {row.order_start_date ? `od ${formatDate(row.order_start_date)}` : ""}
                          {row.order_status === "draft" ? (
                            <span className="text-warning-muted-foreground">
                              {row.order_start_date ? " · " : ""}szkic zamówienia
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                  {/* Znaczniki zamówienia pod jego datami — w 1280 px osobna
                      kolumna wypychała akcje poza ekran. Wypowiedzenie widać
                      w statusie umowy. */}
                  {(row.attention ?? [])
                    .filter((code) => code !== "notice")
                    .map((code) => (
                      <span
                        key={code}
                        className="mt-1 block w-fit max-w-[220px] whitespace-normal rounded-md border border-warning/30 bg-warning-muted px-1.5 py-0.5 text-[11px] font-medium text-warning-muted-foreground"
                      >
                        {attentionLabel(code, row)}
                      </span>
                    ))}
                </td>
                {showProject ? (
                  <td className="max-w-[180px] py-2 pr-4">
                    {row.project_code || row.project_name ? (
                      <>
                        <span className="block truncate font-medium">{row.project_code ?? "—"}</span>
                        {row.project_name ? (
                          <span className={cn(CALM_SUBLINE, "truncate")}>{row.project_name}</span>
                        ) : null}
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                ) : null}
                <td className={cn(CALM_AMOUNT, "py-2 pr-4 text-right")}>
                  {amount(row.hourly_rate_client)}
                  {row.hourly_rate_candidate != null ? (
                    <span className={CALM_SUBLINE}>koszt {formatPLN(row.hourly_rate_candidate)}</span>
                  ) : null}
                </td>
                <td
                  className={cn(
                    CALM_AMOUNT,
                    "py-2 pr-4 text-right font-medium",
                    row.monthly_margin != null &&
                      (row.monthly_margin < 0
                        ? "text-warning-muted-foreground"
                        : "text-success-muted-foreground"),
                  )}
                >
                  {amount(row.monthly_margin)}
                </td>
                {showProlongation ? (
                  <td className="py-2 pr-4">
                    <ProlongationSelect
                      contractId={row.contract_id}
                      clientId={clientId}
                      value={row.prolongation_status}
                      canEdit={canEdit}
                    />
                  </td>
                ) : null}
                <td className="py-2 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <ExtendContractMenu
                      contractId={row.contract_id}
                      clientId={clientId}
                      contractStatus={row.contract_status}
                    />
                    {canEdit ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 w-8 p-0"
                        title="Edytuj pola rejestru (nr projektu, okres, prolongata)"
                        aria-label={`Edytuj pola rejestru: ${row.candidate.name}`}
                        onClick={() => onEditRegister(row.contract_id)}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                    ) : null}
                    <Link
                      href={`/contracts/${row.contract_id}`}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="Otwórz kontrakt"
                      aria-label={`Otwórz kontrakt: ${row.candidate.name}`}
                    >
                      <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                    </Link>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EmptyRows({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
      <div className="mb-2 opacity-40">{icon}</div>
      <p className="text-sm">{children}</p>
    </div>
  );
}

interface Props {
  clientId: number;
  clientName: string;
}

export function ClientConsultantsTab({ clientId, clientName }: Props) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canEdit = !impersonating && hasPermission(user, "contracts_orders_edit");
  const canExport = mayExportFiles(user);
  const { showError } = useToast();
  const query = useClientProfile(clientId);
  const { data } = query;
  const [tab, setTab] = useState<ConsultantsTabKey>("obecni");
  const [assignmentFilter, setAssignmentFilter] = useState<ConsultantAssignmentFilter>("all");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<RegisterContractRow | null>(null);
  const [exporting, setExporting] = useState(false);
  const ezdrowie = isEzdrowieClient(clientId);

  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <div className="mr-2 h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        Ładowanie konsultantów…
      </div>
    );
  }
  if (isBlockingViewState(viewState) || !data) {
    return (
      <QueryStateNotice
        state={
          isBlockingViewState(viewState)
            ? (viewState as "forbidden" | "not_found" | "error")
            : "error"
        }
        description={viewState === "error" ? "Nie udało się wczytać konsultantów klienta." : undefined}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const active = data.active_consultants;
  const planned = data.planned_consultants ?? [];
  const pending = data.pending_consultants ?? [];
  const archived = data.historical.placements;
  const archiveCount = Math.max(data.historical.placements_total ?? 0, archived.length);
  const attention = active.filter(needsAttention);
  const live = [...active, ...planned, ...pending];
  const showProject = live.some((row) => row.project_code || row.project_name);
  const showProlongation = live.some(
    (row) => row.prolongation_status && row.prolongation_status !== "unknown",
  );
  const filteredActive = ezdrowie
    ? filterConsultantsByExecutiveContract(active, assignmentFilter)
    : active;
  const rows: Record<Exclude<ConsultantsTabKey, "archiwum">, ActiveConsultantItem[]> = {
    obecni: filteredActive,
    uwaga: attention,
    planowani: planned,
    szkice: pending,
  };

  const refresh = () => {
    void query.refetch();
  };

  const openRegisterEdit = async (contractId: number) => {
    try {
      const response = await api.get(`/api/contracts/${contractId}`);
      setEditing(response.data as RegisterContractRow);
    } catch {
      showError("Nie udało się wczytać kontraktu do edycji.");
    }
  };

  // Eksport do Excela — ten sam plik co dawny rejestr klienta w Kontraktach.
  const doExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const params = new URLSearchParams({ client_id: String(clientId) });
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
      const response = await fetch(`${apiBase}/api/contracts/register/export?${params}`, {
        credentials: "include",
        headers: getAuthenticatedRequestHeaders(),
      });
      if (!response.ok) {
        showError("Eksport nie powiódł się.");
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const slug =
        clientName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "klient";
      link.href = url;
      link.download = `konsultanci-${slug}-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } finally {
      setExporting(false);
    }
  };

  const tabs = [
    { value: "obecni", label: "Obecni", icon: Users, count: filteredActive.length },
    { value: "uwaga", label: "Wymaga uwagi", icon: AlertTriangle, count: attention.length },
    { value: "planowani", label: "Planowani", icon: CalendarClock, count: planned.length },
    ...(pending.length > 0
      ? [{ value: "szkice", label: "Szkice", icon: FileClock, count: pending.length }]
      : []),
    { value: "archiwum", label: "Zakończeni", icon: FileText, count: archiveCount },
  ];

  return (
    <section className="space-y-3" data-tour="client.consultants">
      {/* Bez nagłówka i opisu nad listą (E2E „treść w górnej części okna”,
          1280 × 720 na runnerze CI): przyciski stoją w rzędzie podzakładek. */}
      <h2 className="sr-only">Konsultanci u klienta</h2>
      {ezdrowie ? <ContractStructureSection clientId={clientId} /> : null}

      <div className="flex flex-wrap items-end gap-2">
        <TabbedNav
          value={tab}
          onValueChange={(value) => setTab(value as ConsultantsTabKey)}
          ariaLabel="Konsultanci"
          tabs={tabs}
          className="w-auto min-w-0 flex-1"
        />
        <div className="flex shrink-0 items-center gap-2 pb-1">
          {canExport ? (
            <Button size="sm" variant="outline" onClick={() => void doExport()} disabled={exporting}>
              <Download className="h-4 w-4" aria-hidden="true" /> Eksport
            </Button>
          ) : null}
          {canEdit ? (
            <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" /> Nowy kontrakt
            </Button>
          ) : null}
        </div>
      </div>

      {tab === "obecni" && data.summary.active_consultants !== active.length ? (
        <p className="text-xs text-muted-foreground">
          {countPl(active.length, "kontrakt", "kontrakty", "kontraktów")} ·{" "}
          {countPl(data.summary.active_consultants, "osoba", "osoby", "osób")} — jedna osoba może
          mieć kilka kontraktów; wiersz to kontrakt.
        </p>
      ) : null}
      {tab === "planowani" ? (
        <p className="text-xs text-muted-foreground">
          Kontrakty, które jeszcze nie wystartowały. Nie wchodzą do „Obecnych” ani do „Aktywnego
          MRR”.
        </p>
      ) : null}
      {tab === "obecni" && ezdrowie && active.length > 0 ? (
        <ExecutiveContractFilter
          clientId={clientId}
          consultants={active}
          value={assignmentFilter}
          onChange={setAssignmentFilter}
        />
      ) : null}

      {tab === "archiwum" ? (
        archived.length === 0 ? (
          <EmptyRows icon={<FileText className="h-8 w-8" />}>
            Brak zakończonych kontraktów dla tego klienta.
          </EmptyRows>
        ) : (
          <>
            {archiveCount > archived.length ? (
              <p className="text-xs text-muted-foreground">
                Pokazano {archived.length} najnowszych z {archiveCount} zakończonych kontraktów.
                Pełną historię znajdziesz w module Kontrakty.
              </p>
            ) : null}
            <ConsultantsTable
              rows={archived.map(toConsultantRow)}
              showEndDate
              renderActions={(row) => {
                // ReEngage tworzy NOWY kontrakt, nie edytuje wiersza archiwalnego.
                const placement = archived.find((p) => p.contract_id === row.contract_id);
                return placement && placement.candidate.id != null ? (
                  <ReEngageButton placement={placement} />
                ) : null;
              }}
            />
          </>
        )
      ) : rows[tab].length === 0 ? (
        <EmptyRows icon={<Users className="h-8 w-8" />}>
          {tab === "uwaga"
            ? "Nikt u tego klienta nie wymaga teraz uwagi."
            : tab === "planowani"
              ? "Brak zaplanowanych kontraktów u tego klienta."
              : tab === "szkice"
                ? "Brak szkiców i umów do podpisu."
                : "Nie mamy aktywnych konsultantów u tego klienta."}
        </EmptyRows>
      ) : (
        <ConsultantsWorkTable
          rows={rows[tab]}
          clientId={clientId}
          showProject={showProject}
          showProlongation={showProlongation}
          canEdit={canEdit}
          onEditRegister={(contractId) => void openRegisterEdit(contractId)}
        />
      )}

      {canEdit && (creating || editing) ? (
        <ContractRegisterDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setCreating(false);
              setEditing(null);
            }
          }}
          clientId={clientId}
          clientName={clientName}
          contract={editing}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            refresh();
          }}
        />
      ) : null}
    </section>
  );
}
