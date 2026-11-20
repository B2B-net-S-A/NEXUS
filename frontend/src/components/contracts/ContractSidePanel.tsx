"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  ExternalLink,
  FileText,
  Info,
  MoreHorizontal,
} from "lucide-react";
import {
  contractsApi,
  extractErrorMsg,
  type ContractSiblingRef,
  type ContractorListItem,
} from "@/lib/api";
import { cn, formatCurrency } from "@/lib/utils";
import { CALM_EMPTY } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";
import { contractRateUnitSuffix } from "@/lib/rate-unit";
import { contractStatusLabel, contractStatusVariant, type StatusVariant } from "@/lib/status-labels";
import { sharePointBadge } from "@/lib/contract-docs-sharepoint";
import { openContractDocument } from "@/lib/contract-documents";
import { dlPortalApi, type OrderDocumentItem } from "@/lib/api/dlPortal";
import { openOrderDocument } from "@/lib/order-documents";
import { documentsHref } from "@/lib/b2b-documents";
import { contractAccess } from "@/lib/contract-access";
import {
  contractPanelWarnings,
  type ContractPanelFacts,
  type PanelActionId,
  type PanelWarning,
} from "@/lib/contract-panel";
import { relativeDays } from "@/lib/contract-happening";
import { humanizeActivity } from "@/lib/contract-history";
import { B2B_EXTENSION_HINT, b2bExtensionLocked } from "@/lib/contract-end-date";
import {
  contractDetailTabHref,
  resolveContractDetailTab,
  type ContractDetailTab,
  type LegacyContractDetailTab,
} from "@/lib/contract-detail-tab";
import { canAmendContractRates } from "@/lib/contract-rate-amendment";
import { permissionLabel } from "@/lib/permissions";
import {
  buildContractDetailHref,
  rememberContractsListScroll,
} from "@/lib/contracts-list-navigation";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { DOC_TYPE_LABEL, type ContractDocument } from "@/components/ContractDocumentsTab";
import { ContractCandidateContactRow } from "@/components/contracts/ContractCandidateContactRow";
import { ContractStatusControl } from "@/components/contracts/ContractStatusControl";
import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";
import { ContractAgreementRecordDialog } from "@/components/contracts/ContractAgreementRecordDialog";
import {
  ReturnAfterBreakDialog,
  ReverseTerminationDialog,
} from "@/components/contracts/ContractTerminationRecovery";
import { ContractClientReassignDialog } from "@/components/contracts/ContractClientReassignDialog";
import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";
import { AddAnnexMenu } from "@/components/contracts/amendments/AddAnnexMenu";
import { annexIntentHref } from "@/components/contracts/amendments/annex-intent";
import { DraftCompletionModal } from "@/components/v2/modals/DraftCompletionModal";

/**
 * Boczny panel kontraktu w rejestrze (wariant A, przebudowa 20.11.2026).
 *
 * Jedno ostrzeżenie na górze zamiast dwóch o tym samym (sprawy z paska „Co się
 * dzieje” strony kontraktu plus szkic, przywrócenie i brak zamówienia), pieniądze
 * w jednej linii, okres w dwóch liniach z „ile zostało”, kontakt zwięźle, trzy
 * ostatnie dokumenty i zdarzenia. Stopka: jedna akcja główna „Otwórz kontrakt”,
 * „Dodaj aneks” i menu; status jako kropka z menu w nagłówku.
 *
 * Czyta TE SAME zapytania co karta kontraktu (`["contract", id]`,
 * `["contract-documents", id]`, `["contract-activities", id]`), a akcje
 * otwierają TE SAME okna. Bramki liczy `lib/contract-access.ts` — wspólne
 * z kartą, więc panel nie pokaże przycisku, którego karta nie ma.
 */

interface ContractPanelDetail extends ContractPanelFacts {
  id: number;
  candidate_id: number | null;
  client_id: number;
  job_id?: number | null;
  candidate_name: string | null;
  client_name: string | null;
  job_title: string | null;
  contract_type: "b2b" | "uop" | "uzlecenie";
  rate_unit: "hourly" | "daily" | "monthly";
  billing_hours_per_month: number;
  currency: string;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  margin?: number | null;
  monthly_margin?: number | null;
  work_mode?: "remote" | "hybrid" | "onsite" | null;
  notice_period_months?: number | null;
  termination_reason?: string | null;
  termination_lessons?: string | null;
  terminated_at?: string | null;
  agreement_termination_mode?: string | null;
  prolongation_status?: string | null;
  candidate_email_effective?: string | null;
  candidate_phone_effective?: string | null;
  candidate_email_source?: "contract" | "candidate_profile" | null;
  candidate_phone_source?: "contract" | "candidate_profile" | null;
  related_contracts?: ContractSiblingRef[];
  returned_from_contract_id?: number | null;
  return_contract_id?: number | null;
}

interface ActivityEntry {
  id: number;
  action: string;
  details?: Record<string, unknown> | null;
  user_name: string | null;
  created_at: string;
}

/** Dane wiersza listy — nagłówek panelu pokazuje je od razu, przed odpowiedzią API. */
export interface ContractPanelPreview {
  candidate_name?: string | null;
  client_name?: string | null;
  job_title?: string | null;
  status?: string | null;
}

export interface ContractSidePanelProps {
  contractId: number;
  onClose: () => void;
  preview?: ContractPanelPreview;
  /** Adres listy, do której wraca karta kontraktu (`returnTo`). */
  returnTarget?: string;
  source?: "contracts" | "contractors" | "client-register";
  /** Klik w chip innego klienta tej osoby — przełącza panel na tamten kontrakt. */
  onSelectContract?: (contractId: number) => void;
}

const TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uzlecenie: "Umowa zlecenie",
};

const RECENT_LIMIT = 3;

const STATUS_DOT: Record<StatusVariant, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  soft: "bg-info",
  neutral: "bg-muted-foreground/50",
};

/** Lustro `ACTIVATION_REQUIRED_FIELDS` — dla okna uzupełnienia draftu z rejestru. */
export function contractorItemFromDetail(c: ContractPanelDetail): ContractorListItem {
  const missing: string[] = [];
  if (!c.start_date) missing.push("start_date");
  if (c.rate_candidate == null) missing.push("rate_candidate");
  if (c.rate_client == null) missing.push("rate_client");
  if (!c.contract_type) missing.push("contract_type");
  return {
    contract_id: c.id,
    candidate: {
      id: c.candidate_id ?? 0,
      name: c.candidate_name ?? `Kontrakt #${c.id}`,
      lastname: "",
    },
    client_id: c.client_id,
    client_name: c.client_name,
    job_title: c.job_title,
    status: c.status as ContractorListItem["status"],
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? null,
    rate_candidate: c.rate_candidate ?? null,
    rate_client: c.rate_client ?? null,
    rate_unit: c.rate_unit,
    currency: c.currency,
    rate_client_currency: c.rate_client_currency ?? null,
    rate_candidate_currency: c.rate_candidate_currency ?? null,
    margin: c.margin ?? null,
    contract_type: c.contract_type,
    work_mode: c.work_mode ?? null,
    missing_fields: missing,
  };
}

function dayDiff(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

/** „· za 41 dni” po dacie końca; po terminie — „· minęło”. */
function remaining(end: string, today: string): string {
  const days = dayDiff(today, end);
  return days < 0 ? "minęło" : relativeDays(days);
}

/** Pozycja menu wykonana po zamknięciu menu — okno otwarte w trakcie zamykania menu gubiło fokus. */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

function StatusLabel({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
      <span aria-hidden className={cn("size-1.5 rounded-full", STATUS_DOT[contractStatusVariant(status)])} />
      {contractStatusLabel(status)}
    </span>
  );
}

function WarningBox({
  warnings,
  renderAction,
}: {
  warnings: PanelWarning[];
  renderAction: (action: PanelActionId) => ReactNode;
}) {
  const [first, ...rest] = warnings;
  if (!first) return null;
  const Icon = first.tone === "info" ? Info : AlertTriangle;
  // Akcje bez uprawnienia nie zostawiają pustego miejsca.
  const actions = first.actions
    .map((action) => ({ action, node: renderAction(action) }))
    .filter((item) => item.node != null);
  return (
    <div
      role={first.tone === "danger" ? "alert" : "status"}
      data-testid="contract-panel-warning"
      className={cn(
        "rounded-lg border px-3 py-2.5",
        first.tone === "danger" && "border-destructive/30 bg-destructive/5",
        first.tone === "warning" && "border-warning/40 bg-warning-muted/60",
        first.tone === "info" && "border-border bg-muted/50",
      )}
    >
      <p className="flex items-start gap-2 text-[13px] font-semibold leading-5 text-foreground">
        <Icon
          className={cn(
            "mt-0.5 size-3.5 shrink-0",
            first.tone === "danger" ? "text-destructive" : first.tone === "warning" ? "text-warning" : "text-muted-foreground",
          )}
          aria-hidden="true"
        />
        <span>{first.lead}</span>
      </p>
      {first.detail ? <p className="mt-0.5 pl-5.5 text-[12px] leading-4 text-muted-foreground">{first.detail}</p> : null}
      {actions.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5 pl-5.5">
          {actions.map((item) => (
            <span key={item.action}>{item.node}</span>
          ))}
        </div>
      ) : null}
      {rest.length ? (
        <p className="mt-2 border-t border-border/60 pt-1.5 text-[12px] leading-4 text-muted-foreground">
          Także: {rest.map((item) => item.lead).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

export function ContractSidePanel({
  contractId,
  onClose,
  preview,
  returnTarget,
  source = "contracts",
  onSelectContract,
}: ContractSidePanelProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const today = warsawToday();

  const contractQuery = useQuery<ContractPanelDetail>({
    queryKey: ["contract", contractId],
    queryFn: () => contractsApi.get(contractId).then((r) => r.data),
  });
  const contract = contractQuery.data;
  const access = contractAccess(user, {
    impersonating,
    clientId: contract?.client_id,
  });
  // Ta sama reguła co „Zmiana stawki” w zakładce „Aneksy”: uprawnienie
  // „Stawki i kwoty: zmiana” u klienta tego kontraktu.
  const canAmendRates = canAmendContractRates(user, contract?.client_id);

  const docsQuery = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", contractId],
    queryFn: () => contractsApi.documents(contractId).then((r) => r.data),
    enabled: Boolean(contract) && access.canViewContractDocuments,
  });
  // PDF-y przypięte do zamówień kontraktu — ta sama lista co „Dokumenty
  // zamówień” na pełnej stronie (ten sam klucz, więc wspólny cache
  // z `OrderDocumentsSection`). 403 = rola bez dostępu do zamówień klienta:
  // lista po prostu pusta, jak tam.
  const orderDocsQuery = useQuery<OrderDocumentItem[]>({
    queryKey: ["order-documents", contractId, null],
    queryFn: () =>
      dlPortalApi.listContractOrderDocuments(contractId).then((r) => r.data.documents),
    enabled: Boolean(contract) && access.canViewContractDocuments,
    retry: false,
  });
  const activitiesQuery = useQuery<ActivityEntry[]>({
    queryKey: ["contract-activities", contractId],
    queryFn: () => contractsApi.activities(contractId).then((r) => r.data),
    enabled: Boolean(contract),
  });

  const [error, setError] = useState("");
  const [recoveryHint, setRecoveryHint] = useState("");
  const [dialog, setDialog] = useState<
    | null
    | "terminate"
    | "reverse"
    | "return"
    | "reassign"
    | "add-project"
    | "complete-draft"
    | "record-agreement"
  >(null);
  const [openingDocId, setOpeningDocId] = useState<number | null>(null);
  const [openingOrderId, setOpeningOrderId] = useState<number | null>(null);

  const detailHref = (tab?: ContractDetailTab | LegacyContractDetailTab) => {
    const base = returnTarget
      ? buildContractDetailHref(contractId, returnTarget, source)
      : `/contracts/${contractId}`;
    if (!tab || resolveContractDetailTab(tab) === "overview") return base;
    const [path, query = ""] = base.split("?");
    return contractDetailTabHref(path, query, tab);
  };
  const rememberScroll = () => {
    if (returnTarget) rememberContractsListScroll(returnTarget);
  };

  const invalidateContract = () => {
    queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
    queryClient.invalidateQueries({ queryKey: ["contracts"] });
    queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
    queryClient.invalidateQueries({ queryKey: ["client-register"] });
    queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
    queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
  };

  const saveCandidateContact = async (patch: Record<string, string>) => {
    try {
      await contractsApi.update(contractId, patch);
    } catch (err: unknown) {
      throw new Error(extractErrorMsg(err));
    }
    await queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
    setError("");
  };

  const status = contract?.status ?? preview?.status ?? null;
  const title = contract?.candidate_name ?? preview?.candidate_name ?? `Kontrakt #${contractId}`;
  const clientName = contract?.client_name ?? preview?.client_name ?? null;
  const jobTitle = contract?.job_title ?? preview?.job_title ?? null;
  const typeLabel = contract ? (TYPE_LABELS[contract.contract_type] ?? contract.contract_type) : null;

  const badges = status ? (
    contract && access.canEditContractStatus ? (
      <ContractStatusControl
        contractId={contract.id}
        status={contract.status}
        canRecoverTermination={access.canRecoverTermination}
        onRequestTermination={() => setDialog("terminate")}
        onRecoveryHint={setRecoveryHint}
        onError={setError}
      />
    ) : (
      <StatusLabel status={status} />
    )
  ) : null;

  const subtitle = (
    <span className="block min-w-0">
      <span className="block truncate">
        {clientName ?? "—"}
        {typeLabel ? ` · ${typeLabel}` : ""} · #{contractId}
      </span>
      {jobTitle ? (
        <span className="block truncate" title={jobTitle}>
          {jobTitle}
        </span>
      ) : null}
    </span>
  );

  // Akcja główna stoi zawsze — także zanim przyjdą szczegóły (przeklikanie
  // nowości prowadzi przez nią na stronę kontraktu).
  const openButton = (
    <Link
      href={detailHref()}
      onClick={rememberScroll}
      data-tour="contract.panel.open"
      className={buttonVariants({ size: "sm", variant: "primary" })}
    >
      Otwórz kontrakt
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </Link>
  );

  const viewState = resolveViewState({
    isLoading: contractQuery.isLoading,
    isError: contractQuery.isError,
    error: contractQuery.error,
    isSuccess: contractQuery.isSuccess,
    isEmpty: false,
  });

  if (!contract) {
    return (
      <DetailPanel
        title={title}
        badges={badges}
        subtitle={subtitle}
        onClose={onClose}
        footer={
          <div className="flex w-full items-center gap-2" data-testid="contract-panel-actions">
            {openButton}
          </div>
        }
        data-testid="contract-side-panel"
      >
        {isBlockingViewState(viewState) ? (
          <QueryStateNotice
            state={viewState as "forbidden" | "not_found" | "error"}
            onRetry={() => void contractQuery.refetch()}
          />
        ) : (
          <p className="text-sm text-muted-foreground">Ładowanie kontraktu…</p>
        )}
      </DetailPanel>
    );
  }

  const warnings = contractPanelWarnings(contract, null, today, {
    canViewFinance: access.canViewFinance,
  });
  const siblings = contract.related_contracts ?? [];
  const allDocs = docsQuery.data ?? [];
  const docs = allDocs.slice(0, RECENT_LIMIT);
  const orderDocsForbidden =
    (orderDocsQuery.error as { response?: { status?: number } } | null)?.response
      ?.status === 403;
  const orderDocsFailed = orderDocsQuery.isError && !orderDocsForbidden;
  const orderDocsSettled = orderDocsQuery.isSuccess || orderDocsQuery.isError;
  const orderDocs = (orderDocsQuery.data ?? []).slice(0, Math.max(0, RECENT_LIMIT - docs.length));
  const docsCount = allDocs.length + (orderDocsQuery.data?.length ?? 0);
  // Ostatnio = zmiany ludzi; automatyczne (synchronizacje, migracje) są w historii.
  const recent = (activitiesQuery.data ?? [])
    .map((a) => humanizeActivity({ ...a, details: a.details ?? null }))
    .filter((event) => !event.automatic)
    .slice(0, RECENT_LIMIT);
  const hasAutomaticOnly = (activitiesQuery.data?.length ?? 0) > 0 && recent.length === 0;
  const revenueCurrency = contract.rate_client_currency ?? contract.currency ?? "PLN";
  const costCurrency = contract.rate_candidate_currency ?? contract.currency ?? "PLN";
  const comparableCurrencies = revenueCurrency.toUpperCase() === costCurrency.toUpperCase();
  const unitSuffix = contractRateUnitSuffix(contract.rate_unit);
  // Udział marży w stawce przychodowej — tylko gdy obie stawki są w jednej
  // walucie (inaczej różnica nie jest kwotą, którą da się porównać).
  const marginShare =
    contract.margin != null &&
    comparableCurrencies &&
    contract.rate_client != null &&
    contract.rate_client !== 0
      ? (contract.margin / contract.rate_client) * 100
      : null;
  const marginPct =
    marginShare != null
      ? `${new Intl.NumberFormat("pl-PL", {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        }).format(marginShare)}%`
      : null;
  const marginTone =
    marginShare == null
      ? "text-foreground"
      : marginShare < 15
        ? "text-destructive"
        : marginShare < 25
          ? "text-warning-muted-foreground"
          : "text-success-muted-foreground";
  const live = contract.status === "active" || contract.status === "ending";
  const addOrderHref = `/clients/${contract.client_id}?tab=zamowienia`;
  const showAmendments = access.canEditContract && contract.status !== "void";
  const orderEnd = contract.client_order_end_date?.slice(0, 10) ?? null;
  const contractEnd = contract.end_date?.slice(0, 10) ?? null;

  const openDoc = async (doc: ContractDocument) => {
    setOpeningDocId(doc.id);
    setError("");
    try {
      await openContractDocument(contractId, doc);
    } catch {
      setError(`Nie udało się otworzyć pliku „${doc.filename}”.`);
    } finally {
      setOpeningDocId(null);
    }
  };

  const openOrderDoc = async (doc: OrderDocumentItem) => {
    setOpeningOrderId(doc.order_id);
    setError("");
    try {
      await openOrderDocument(doc);
    } catch {
      setError(`Nie udało się otworzyć pliku zamówienia „${doc.title}”.`);
    } finally {
      setOpeningOrderId(null);
    }
  };

  // Akcje ostrzeżenia mają te same bramki co reszta panelu i strona kontraktu.
  const renderAction = (action: PanelActionId) => {
    switch (action) {
      case "record_agreement":
        return access.canEditContractStatus ? (
          <Button size="sm" variant="outline" onClick={() => setDialog("record-agreement")}>
            Zapisz rozwiązanie umowy
          </Button>
        ) : null;
      case "reverse_termination":
        return access.canRecoverTermination && contract.can_reverse_termination ? (
          <Button size="sm" variant="quiet" onClick={() => setDialog("reverse")}>
            Cofnij zakończenie…
          </Button>
        ) : null;
      case "recover":
        return access.canRecoverTermination ? (
          <span className="flex flex-wrap gap-1.5">
            {contract.can_reverse_termination && (
              <Button size="sm" variant="outline" onClick={() => setDialog("reverse")}>
                Cofnij zakończenie
              </Button>
            )}
            {contract.can_return_after_break && (
              <Button size="sm" variant="outline" onClick={() => setDialog("return")}>
                Powrót po przerwie
              </Button>
            )}
          </span>
        ) : null;
      case "add_order":
        return access.canEditContract ? (
          <Link href={addOrderHref} className={buttonVariants({ size: "sm", variant: "outline" })}>
            Dodaj zamówienie
          </Link>
        ) : null;
      case "terminate":
        return access.canEditContractStatus && live ? (
          <Button size="sm" variant="quiet" onClick={() => setDialog("terminate")}>
            Zakończ współpracę…
          </Button>
        ) : null;
      case "complete_draft":
        return access.canEditContract ? (
          <Button size="sm" variant="outline" onClick={() => setDialog("complete-draft")}>
            Uzupełnij i aktywuj
          </Button>
        ) : null;
      case "fill_rate":
        return access.canEditContract || access.financeAmountsOnly ? (
          <Link href={detailHref()} onClick={rememberScroll} className={buttonVariants({ size: "sm", variant: "outline" })}>
            Uzupełnij stawkę
          </Link>
        ) : null;
      case "log_conversation":
        return (
          <Link href={detailHref("care")} onClick={rememberScroll} className={buttonVariants({ size: "sm", variant: "outline" })}>
            Zapisz rozmowę
          </Link>
        );
      default:
        return null;
    }
  };

  const footer = (
    <div className="flex w-full items-center gap-2" data-testid="contract-panel-actions">
      {openButton}
      {showAmendments && (
        // To samo menu co w nagłówku strony kontraktu: wybór otwiera zakładkę
        // „Aneksy” od razu z oknem (`?aneks=`).
        <AddAnnexMenu
          canAmendRates={canAmendRates}
          extensionLocked={b2bExtensionLocked(contract)}
          extensionHint={B2B_EXTENSION_HINT}
          onPick={(type) => {
            rememberScroll();
            const [path, query = ""] = detailHref().split("?");
            router.push(annexIntentHref(path, query, type));
          }}
          onRequestTermination={
            access.canEditContractStatus && live ? () => setDialog("terminate") : undefined
          }
          documentHref={documentsHref({ newType: "annex_rate_change", contractId })}
          tourAnchor={false}
        />
      )}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon-sm"
            variant="ghost"
            className="ml-auto"
            aria-label="Więcej akcji kontraktu"
            title="Więcej: edycja, kolejny projekt, zamówienia, zakończenie współpracy"
            data-tour="contract.panel.more"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {(access.canEditContract || access.financeAmountsOnly) && (
            <DropdownMenuItem asChild>
              <Link href={detailHref()} onClick={rememberScroll}>
                {access.canEditContract ? "Edytuj" : "Edytuj stawki"}
              </Link>
            </DropdownMenuItem>
          )}
          {access.canEditContract && contract.candidate_id != null && (
            <DropdownMenuItem onSelect={() => deferMenuAction(() => setDialog("add-project"))}>
              Dodaj kolejny projekt
            </DropdownMenuItem>
          )}
          {access.canEditContract && (
            <DropdownMenuItem asChild>
              <Link href={detailHref()} onClick={rememberScroll}>
                Generuj z szablonu
              </Link>
            </DropdownMenuItem>
          )}
          <DropdownMenuItem asChild>
            <Link href={addOrderHref}>Zamówienia u klienta</Link>
          </DropdownMenuItem>
          {access.canEditContract && access.canReassignClient && (
            <DropdownMenuItem onSelect={() => deferMenuAction(() => setDialog("reassign"))}>
              <Building2 className="h-4 w-4" /> Przepnij na innego klienta
            </DropdownMenuItem>
          )}
          {((access.canEditContractStatus && live) || access.canEditContract) && <DropdownMenuSeparator />}
          {access.canEditContractStatus && live && (
            <DropdownMenuItem
              onSelect={() => deferMenuAction(() => setDialog("terminate"))}
              data-tour="contract.panel.end"
              className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive"
            >
              Zakończ współpracę…
            </DropdownMenuItem>
          )}
          {access.canEditContract && (
            <DropdownMenuItem asChild className="text-destructive">
              <Link href={detailHref()} onClick={rememberScroll}>
                Usuń…
              </Link>
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  return (
    <DetailPanel
      title={title}
      badges={badges}
      subtitle={subtitle}
      onClose={onClose}
      footer={footer}
      data-testid="contract-side-panel"
    >
      {siblings.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Klienci tej osoby">
          <span className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground">
            <Building2 className="h-3 w-3" aria-hidden="true" />
            {contract.client_name ?? `Klient #${contract.client_id}`}
          </span>
          {siblings.map((sibling) =>
            onSelectContract ? (
              <button
                key={sibling.id}
                type="button"
                onClick={() => onSelectContract(sibling.id)}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:border-primary/50 hover:text-primary"
              >
                {sibling.client_name ?? `Klient #${sibling.client_id}`}
                <span className="text-[10px] text-muted-foreground">
                  {contractStatusLabel(sibling.status)}
                </span>
              </button>
            ) : (
              <Link
                key={sibling.id}
                href={`/contracts/${sibling.id}`}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:border-primary/50 hover:text-primary"
              >
                {sibling.client_name ?? `Klient #${sibling.client_id}`}
                <span className="text-[10px] text-muted-foreground">
                  {contractStatusLabel(sibling.status)}
                </span>
              </Link>
            ),
          )}
        </div>
      )}

      <WarningBox warnings={warnings} renderAction={renderAction} />
      {recoveryHint && (
        <p role="status" className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{recoveryHint}</span>
        </p>
      )}
      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setError("")}
            aria-label="Zamknij komunikat"
            className="hit-area rounded px-1 hover:bg-destructive/10"
          >
            ×
          </button>
        </div>
      )}

      {/* Pieniądze w jednej linii: po nie najczęściej otwiera się panel. */}
      {access.canViewFinance ? (
        <DetailSection title="Pieniądze">
          <p className="text-[13px] tabular-nums text-foreground" data-testid="contract-panel-rates">
            <span className="text-muted-foreground">Koszt</span>{" "}
            <strong className={cn("font-semibold", contract.rate_candidate == null && CALM_EMPTY)}>
              {contract.rate_candidate != null
                ? `${formatCurrency(contract.rate_candidate, costCurrency)}${unitSuffix}`
                : "—"}
            </strong>
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            <span className="text-muted-foreground">Przychód</span>{" "}
            <strong className={cn("font-semibold", contract.rate_client == null && CALM_EMPTY)}>
              {contract.rate_client != null
                ? `${formatCurrency(contract.rate_client, revenueCurrency)}${unitSuffix}`
                : "—"}
            </strong>
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            <span className="text-muted-foreground">Marża</span>{" "}
            <strong className={cn("font-semibold", contract.margin != null && comparableCurrencies ? marginTone : CALM_EMPTY)}>
              {contract.margin != null && comparableCurrencies
                ? `${formatCurrency(contract.margin, revenueCurrency)}${unitSuffix}`
                : "—"}
            </strong>
          </p>
          {marginPct || (contract.monthly_margin != null && comparableCurrencies) ? (
            <p className="text-xs text-muted-foreground" data-testid="contract-panel-monthly-margin">
              {[
                marginPct,
                contract.monthly_margin != null && comparableCurrencies
                  ? `≈ ${formatCurrency(contract.monthly_margin, revenueCurrency)} marży miesięcznie`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : !comparableCurrencies ? (
            <p className="text-xs text-muted-foreground">Stawki w różnych walutach — marży nie liczymy.</p>
          ) : null}
        </DetailSection>
      ) : (
        <DetailSection title="Pieniądze">
          <p className="text-xs text-muted-foreground" data-testid="contract-panel-finance-redacted">
            Stawki widzą osoby z uprawnieniem „{permissionLabel("amounts_view")}”
            (Delivery Lead — u swoich klientów).
          </p>
        </DetailSection>
      )}

      {/* Okres w dwóch liniach: umowa i bieżące zamówienie, z tym, ile zostało. */}
      <DetailSection
        title="Okres"
        aside={
          <Link href={addOrderHref} className="ml-auto normal-case tracking-normal text-primary hover:underline">
            Zamówienia u klienta →
          </Link>
        }
      >
        <DetailFacts
          items={[
            [
              "Umowa",
              <span key="contract" className="tabular-nums">
                {contract.start_date ? formatIsoDatePl(contract.start_date) : "—"} –{" "}
                {contractEnd ? (
                  <>
                    {formatIsoDatePl(contractEnd)}
                    {live ? <span className="text-muted-foreground"> · {remaining(contractEnd, today)}</span> : null}
                  </>
                ) : (
                  "bezterminowo"
                )}
                {contract.notice_period_months != null ? (
                  <span className="text-muted-foreground"> · wypowiedzenie {contract.notice_period_months} mies.</span>
                ) : null}
              </span>,
            ],
            [
              "Zamówienie",
              <span key="order" className="tabular-nums">
                {contract.client_order_start_date || orderEnd ? (
                  <>
                    {contract.client_order_start_date ? formatIsoDatePl(contract.client_order_start_date) : "…"} –{" "}
                    {orderEnd ? (
                      <>
                        {formatIsoDatePl(orderEnd)}
                        {live ? <span className="text-muted-foreground"> · {remaining(orderEnd, today)}</span> : null}
                      </>
                    ) : (
                      "bezterminowo"
                    )}
                  </>
                ) : (
                  <span className="text-muted-foreground">brak</span>
                )}
              </span>,
            ],
            contract.returned_from_contract_id != null && [
              "Powrót po przerwie",
              <Link
                key="returned-from"
                href={`/contracts/${contract.returned_from_contract_id}`}
                className="text-primary hover:underline"
              >
                poprzedni kontrakt #{contract.returned_from_contract_id}
              </Link>,
            ],
            contract.return_contract_id != null && [
              "Nowy kontrakt",
              <Link
                key="return-contract"
                href={`/contracts/${contract.return_contract_id}`}
                className="text-primary hover:underline"
              >
                kontrakt #{contract.return_contract_id}
              </Link>,
            ],
          ]}
        />
      </DetailSection>

      <DetailSection title="Kontakt">
        <ContractCandidateContactRow
          compact
          email={contract.candidate_email_effective ?? null}
          emailSource={contract.candidate_email_source ?? null}
          phone={contract.candidate_phone_effective ?? null}
          phoneSource={contract.candidate_phone_source ?? null}
          editable={access.canEditContract}
          onSaveEmail={(raw) => saveCandidateContact({ candidate_email: raw })}
          onSavePhone={(raw) => saveCandidateContact({ candidate_phone: raw })}
          onError={setError}
        />
      </DetailSection>

      {access.canViewContractDocuments && (
        <DetailSection
          title={docsQuery.isSuccess && orderDocsSettled ? `Dokumenty · ${docsCount}` : "Dokumenty"}
          aside={
            <Link
              href={detailHref("documents")}
              onClick={rememberScroll}
              className="ml-auto normal-case tracking-normal text-primary hover:underline"
            >
              Wszystkie →
            </Link>
          }
        >
          {docsQuery.isError ? (
            <p className="text-xs text-destructive">Nie udało się pobrać dokumentów.</p>
          ) : !docsQuery.isSuccess || !orderDocsSettled ? (
            <p className="text-xs text-muted-foreground">Ładowanie…</p>
          ) : docs.length === 0 && orderDocs.length === 0 ? (
            orderDocsFailed ? null : (
              <p className="text-xs text-muted-foreground">Brak dokumentów.</p>
            )
          ) : (
            <ul className="grid gap-1">
              {docs.map((doc) => {
                const badge = sharePointBadge(doc);
                return (
                  <li key={doc.id} className="flex min-w-0 items-center gap-2 text-xs">
                    <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <button
                      type="button"
                      onClick={() => void openDoc(doc)}
                      disabled={openingDocId === doc.id}
                      className="min-w-0 truncate text-left text-primary hover:underline disabled:opacity-60"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </button>
                    <span className="shrink-0 text-muted-foreground">
                      {DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}
                    </span>
                    {badge && (
                      <Badge variant={badge.tone} size="sm" title={badge.title} className="shrink-0">
                        {badge.label}
                      </Badge>
                    )}
                  </li>
                );
              })}
              {orderDocs.map((doc) => (
                <li
                  key={`order-${doc.order_id}`}
                  className="flex min-w-0 items-center gap-2 text-xs"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <button
                    type="button"
                    onClick={() => void openOrderDoc(doc)}
                    disabled={openingOrderId === doc.order_id}
                    className="min-w-0 truncate text-left text-primary hover:underline disabled:opacity-60"
                    title={doc.filename ?? doc.title}
                  >
                    {doc.filename ?? doc.title}
                  </button>
                  <span className="shrink-0 text-muted-foreground">
                    Zamówienie {doc.title}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {orderDocsFailed && (
            <p className="text-xs text-destructive">
              Nie udało się pobrać dokumentów zamówień.
            </p>
          )}
        </DetailSection>
      )}

      <DetailSection
        title="Ostatnio"
        aside={
          <Link
            href={detailHref("history")}
            onClick={rememberScroll}
            className="ml-auto normal-case tracking-normal text-primary hover:underline"
          >
            Cała historia →
          </Link>
        }
      >
        {activitiesQuery.isError ? (
          <p className="text-xs text-destructive">Nie udało się pobrać historii.</p>
        ) : !activitiesQuery.isSuccess ? (
          <p className="text-xs text-muted-foreground">Ładowanie…</p>
        ) : recent.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {hasAutomaticOnly
              ? "Ostatnie zmiany zrobił NEXUS automatycznie — są w historii."
              : "Brak wpisów w historii."}
          </p>
        ) : (
          <ol className="grid gap-1" data-testid="contract-panel-recent">
            {recent.map((event) => (
              <li key={event.id} className="grid grid-cols-[76px_minmax(0,1fr)] gap-2 text-[12.5px]">
                <span className="tabular-nums text-muted-foreground">
                  {formatIsoDatePl(warsawDateOf(event.at) ?? event.at.slice(0, 10))}
                </span>
                <span className="min-w-0 truncate text-foreground" title={event.detail ?? undefined}>
                  {event.title}
                  {event.who ? <span className="text-muted-foreground"> · {event.who}</span> : null}
                </span>
              </li>
            ))}
          </ol>
        )}
      </DetailSection>

      {dialog === "terminate" && (
        <ContractTerminationDialog
          contractIds={[contract.id]}
          candidateName={contract.candidate_name}
          noticePeriodMonths={contract.notice_period_months ?? null}
          orderEndDate={contract.client_order_end_date ?? null}
          onClose={() => setDialog(null)}
          onSuccess={() => setDialog(null)}
        />
      )}
      {dialog === "record-agreement" && (
        <ContractAgreementRecordDialog
          contractId={contract.id}
          candidateName={contract.candidate_name}
          projectEnd={contract.end_date ?? null}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "reverse" && (
        <ReverseTerminationDialog contractId={contract.id} onClose={() => setDialog(null)} />
      )}
      {dialog === "return" && (
        <ReturnAfterBreakDialog contractId={contract.id} onClose={() => setDialog(null)} />
      )}
      {access.canReassignClient && (
        <ContractClientReassignDialog
          open={dialog === "reassign"}
          onOpenChange={(open) => setDialog(open ? "reassign" : null)}
          contractId={contract.id}
          currentClientName={contract.client_name}
          onDone={() => invalidateContract()}
        />
      )}
      {contract.candidate_id != null && dialog === "add-project" && (
        <AddProjectDialog
          open
          onOpenChange={(open) => setDialog(open ? "add-project" : null)}
          candidateId={contract.candidate_id}
          candidateName={contract.candidate_name}
          canManageFinance={access.canManageFinance}
          baseContract={{
            id: contract.id,
            client_id: contract.client_id,
            contract_type: contract.contract_type,
            rate_unit: contract.rate_unit,
            currency: contract.currency,
            rate_client_currency: contract.rate_client_currency,
            rate_candidate_currency: contract.rate_candidate_currency,
            billing_hours_per_month: contract.billing_hours_per_month,
            work_mode: contract.work_mode ?? null,
          }}
        />
      )}
      {dialog === "complete-draft" && access.canEditContract && (
        <DraftCompletionModal
          contractor={contractorItemFromDetail(contract)}
          open
          onOpenChange={(open) => {
            if (!open) setDialog(null);
          }}
          onActivated={() => {
            setDialog(null);
            invalidateContract();
          }}
        />
      )}
    </DetailPanel>
  );
}
