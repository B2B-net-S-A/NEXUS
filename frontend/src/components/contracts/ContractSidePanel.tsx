"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  ChevronDown,
  Ellipsis,
  ExternalLink,
  Info,
  RotateCcw,
  UserPlus,
} from "lucide-react";
import {
  contractsApi,
  extractErrorMsg,
  type ContractSiblingRef,
  type ContractorListItem,
} from "@/lib/api";
import { cn, formatCurrency } from "@/lib/utils";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { contractRateUnitSuffix } from "@/lib/rate-unit";
import { contractStatusLabel } from "@/lib/status-labels";
import { CONTRACT_STATUS_VARIANT } from "@/lib/contract-register";
import { sharePointBadge } from "@/lib/contract-docs-sharepoint";
import { openContractDocument } from "@/lib/contract-documents";
import { documentsHref } from "@/lib/b2b-documents";
import { contractAccess } from "@/lib/contract-access";
import {
  canOfferExtension,
  contractPanelAlerts,
  contractPanelPrimary,
  type ContractPanelFacts,
} from "@/lib/contract-panel";
import { contractDetailTabHref, type ContractDetailTab } from "@/lib/contract-detail-tab";
import {
  buildContractDetailHref,
  rememberContractsListScroll,
} from "@/lib/contracts-list-navigation";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasAnalyticsCapability, hasRole, useAuthStore } from "@/store/auth";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DetailFacts, DetailPanel, DetailSection } from "@/components/ds/DetailPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { DOC_TYPE_LABEL, type ContractDocument } from "@/components/ContractDocumentsTab";
import {
  contractActivityLabel,
} from "@/components/contracts/contract-timeline-labels";
import { ContractCandidateContactRow } from "@/components/contracts/ContractCandidateContactRow";
import { ContractStatusControl } from "@/components/contracts/ContractStatusControl";
import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";
import {
  ReturnAfterBreakDialog,
  ReverseTerminationDialog,
} from "@/components/contracts/ContractTerminationRecovery";
import { ContractClientReassignDialog } from "@/components/contracts/ContractClientReassignDialog";
import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";
import { DraftCompletionModal } from "@/components/v2/modals/DraftCompletionModal";

/**
 * Boczny panel kontraktu w rejestrze (wersja B, makieta 29.09.2026).
 *
 * Czyta TE SAME zapytania co karta kontraktu (`["contract", id]`,
 * `["contract-documents", id]`, `["contract-activities", id]`), a akcje
 * otwierają TE SAME okna. Bramki liczy `lib/contract-access.ts` — wspólne
 * z kartą, więc panel nie pokaże przycisku, którego karta nie ma.
 * Rzadkie akcje (edycja, szablon, usunięcie, aneksy) prowadzą do karty.
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
  terminated_at?: string | null;
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
  /** Wiersz „Obsługi kontraktorów” — okno uzupełnienia draftu dostaje prawdziwe braki. */
  contractorItem?: ContractorListItem | null;
}

const TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uzlecenie: "Zlecenie",
};

const RECENT_LIMIT = 3;

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

function Alert({ tone, children }: { tone: "warning" | "danger" | "info"; children: ReactNode }) {
  const Icon = tone === "info" ? Info : AlertTriangle;
  return (
    <p
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
        tone === "danger" && "border-destructive/25 bg-destructive/10 text-destructive",
        tone === "warning" && "border-warning/25 bg-warning-muted text-warning-muted-foreground",
        tone === "info" && "border-border bg-muted/60 text-muted-foreground",
      )}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

/** Pozycja menu wykonana po zamknięciu menu — okno otwarte w trakcie zamykania menu gubiło fokus. */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

export function ContractSidePanel({
  contractId,
  onClose,
  preview,
  returnTarget,
  source = "contracts",
  onSelectContract,
  contractorItem,
}: ContractSidePanelProps) {
  const queryClient = useQueryClient();
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
  // Lustro `ContractAmendmentsTab`: zmiana stawki aneksem = admin albo DL
  // z `manage_finance`.
  const canAmendRates =
    hasRole(user, "admin") ||
    (hasRole(user, "delivery_lead") && hasAnalyticsCapability(user, "manage_finance"));

  const docsQuery = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", contractId],
    queryFn: () => contractsApi.documents(contractId).then((r) => r.data),
    enabled: Boolean(contract) && access.canViewContractDocuments,
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
  >(null);
  const [openingDocId, setOpeningDocId] = useState<number | null>(null);

  const detailHref = (tab?: ContractDetailTab) => {
    const base = returnTarget
      ? buildContractDetailHref(contractId, returnTarget, source)
      : `/contracts/${contractId}`;
    if (!tab || tab === "details") return base;
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
    queryClient.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
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

  const badges = status ? (
    <Badge size="sm" variant={CONTRACT_STATUS_VARIANT[status] ?? "neutral"}>
      {contractStatusLabel(status)}
    </Badge>
  ) : null;

  const subtitle = (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
      <span>
        {clientName ?? "—"}
        {jobTitle ? ` · ${jobTitle}` : ""}
      </span>
      <Link
        href={detailHref()}
        onClick={rememberScroll}
        className="inline-flex items-center gap-1 text-primary hover:underline"
      >
        Otwórz kontrakt <ExternalLink className="h-3 w-3" aria-hidden="true" />
      </Link>
    </span>
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

  const primary = contractPanelPrimary(contract, access, today);
  const alerts = contractPanelAlerts(contract, today, access.canViewFinance);
  const siblings = contract.related_contracts ?? [];
  const docs = (docsQuery.data ?? []).slice(0, RECENT_LIMIT);
  const activities = (activitiesQuery.data ?? []).slice(0, RECENT_LIMIT);
  const revenueCurrency = contract.rate_client_currency ?? contract.currency ?? "PLN";
  const costCurrency = contract.rate_candidate_currency ?? contract.currency ?? "PLN";
  const comparableCurrencies = revenueCurrency.toUpperCase() === costCurrency.toUpperCase();
  const unitSuffix = contractRateUnitSuffix(contract.rate_unit);
  const live = contract.status === "active" || contract.status === "ending";
  const addOrderHref = `/clients/${contract.client_id}?tab=zamowienia`;
  const showAmendments = access.canEditContract && contract.status !== "void";
  const offerExtension = canOfferExtension(contract);

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

  const primaryButton = (() => {
    switch (primary) {
      case "recover":
        return (
          <>
            {contract.can_reverse_termination && (
              <Button size="sm" variant="primary" onClick={() => setDialog("reverse")}>
                <RotateCcw className="h-3.5 w-3.5" /> Cofnij zakończenie
              </Button>
            )}
            {contract.can_return_after_break && (
              <Button
                size="sm"
                variant={contract.can_reverse_termination ? "outline" : "primary"}
                onClick={() => setDialog("return")}
              >
                <UserPlus className="h-3.5 w-3.5" /> Powrót po przerwie
              </Button>
            )}
          </>
        );
      case "complete_draft":
        return (
          <Button size="sm" variant="primary" onClick={() => setDialog("complete-draft")}>
            Uzupełnij i aktywuj
          </Button>
        );
      case "add_order":
        return (
          <Link href={addOrderHref} className={buttonVariants({ size: "sm", variant: "primary" })}>
            Dodaj zamówienie u klienta →
          </Link>
        );
      default:
        return (
          <Link
            href={detailHref()}
            onClick={rememberScroll}
            className={buttonVariants({ size: "sm", variant: "primary" })}
          >
            Otwórz kontrakt
          </Link>
        );
    }
  })();

  const footer = (
    <div className="flex w-full flex-wrap items-center gap-2" data-testid="contract-panel-actions">
      {primaryButton}
      {access.canEditContractStatus && (
        <ContractStatusControl
          contractId={contract.id}
          status={contract.status}
          canRecoverTermination={access.canRecoverTermination}
          onRequestTermination={() => setDialog("terminate")}
          onRecoveryHint={setRecoveryHint}
          onError={setError}
          className="h-8 text-xs"
        />
      )}
      {showAmendments && (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" aria-label="Aneksy">
              Aneks <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuLabel>Aneksy (karta kontraktu)</DropdownMenuLabel>
            {offerExtension && (
              <DropdownMenuItem asChild>
                <Link href={detailHref("amendments")} onClick={rememberScroll}>
                  Przedłużenie
                </Link>
              </DropdownMenuItem>
            )}
            {canAmendRates && (
              <DropdownMenuItem asChild>
                <Link href={detailHref("amendments")} onClick={rememberScroll}>
                  Zmiana stawki
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <Link href={detailHref("amendments")} onClick={rememberScroll}>
                Zmiana zakresu
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href={documentsHref({ newType: "annex_rate_change", contractId })}>
                Wygeneruj dokument aneksu
              </Link>
            </DropdownMenuItem>
            {!offerExtension && contract.contract_type === "b2b" && (
              <p className="px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
                Umowa B2B jest bezterminowa — przedłuża się zamówienie klienta.
              </p>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="outline" aria-label="Więcej akcji kontraktu" title="Więcej akcji">
            <Ellipsis className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuItem asChild>
            <Link href={detailHref()} onClick={rememberScroll}>
              Otwórz kontrakt
            </Link>
          </DropdownMenuItem>
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
          {access.canEditContract && access.canReassignClient && (
            <DropdownMenuItem onSelect={() => deferMenuAction(() => setDialog("reassign"))}>
              <Building2 className="h-4 w-4" /> Przepnij na innego klienta
            </DropdownMenuItem>
          )}
          {access.canEditContract && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild className="text-destructive">
                <Link href={detailHref()} onClick={rememberScroll}>
                  Usuń…
                </Link>
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {access.canEditContractStatus && live && (
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:bg-destructive/10"
          onClick={() => setDialog("terminate")}
        >
          Zakończ współpracę…
        </Button>
      )}
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

      {alerts.map((alert) => (
        <Alert key={alert.text} tone={alert.tone}>
          {alert.text}
        </Alert>
      ))}
      {recoveryHint && <Alert tone="warning">{recoveryHint}</Alert>}
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

      <DetailSection title="Umowa">
        <DetailFacts
          items={[
            ["Typ", TYPE_LABELS[contract.contract_type] ?? contract.contract_type],
            [
              "Okres umowy",
              <>
                {contract.start_date ? formatIsoDatePl(contract.start_date) : "—"} –{" "}
                {contract.end_date ? (
                  formatIsoDatePl(contract.end_date)
                ) : (
                  <span className="italic text-muted-foreground">bezterminowo</span>
                )}
              </>,
            ],
            [
              "Wypowiedzenie",
              contract.notice_period_months != null
                ? `${contract.notice_period_months} mies.`
                : "—",
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

      <DetailSection title="Zamówienie u klienta">
        <DetailFacts
          items={[
            [
              "Okres zamówienia",
              contract.client_order_start_date ? (
                <>
                  {formatIsoDatePl(contract.client_order_start_date)} –{" "}
                  {contract.client_order_end_date
                    ? formatIsoDatePl(contract.client_order_end_date)
                    : "bezterminowo"}
                </>
              ) : contract.client_order_end_date ? (
                `do ${formatIsoDatePl(contract.client_order_end_date)}`
              ) : (
                "—"
              ),
            ],
          ]}
        />
        <Link href={addOrderHref} className="text-xs text-primary hover:underline">
          Zamówienia u klienta →
        </Link>
      </DetailSection>

      {access.canViewFinance ? (
        <DetailSection title="Stawki i marża">
          <DetailFacts
            items={[
              [
                "Kosztowa",
                contract.rate_candidate != null
                  ? `${formatCurrency(contract.rate_candidate, costCurrency)}${unitSuffix}`
                  : "—",
              ],
              [
                "Przychodowa",
                contract.rate_client != null
                  ? `${formatCurrency(contract.rate_client, revenueCurrency)}${unitSuffix}`
                  : "—",
              ],
              [
                "Marża",
                contract.margin != null && comparableCurrencies
                  ? `${formatCurrency(contract.margin, revenueCurrency)}${unitSuffix}`
                  : "—",
              ],
              contract.monthly_margin != null &&
                comparableCurrencies && [
                  "Marża / mc",
                  formatCurrency(contract.monthly_margin, revenueCurrency),
                ],
            ]}
          />
        </DetailSection>
      ) : (
        <DetailSection title="Stawki i marża">
          <p className="text-xs text-muted-foreground" data-testid="contract-panel-finance-redacted">
            Stawki widzą Admin, Finanse i Delivery Lead tego klienta.
          </p>
        </DetailSection>
      )}

      <DetailSection title="Kontakt">
        <div className="[&>div]:grid-cols-1! [&>div]:pl-0!">
          <ContractCandidateContactRow
            email={contract.candidate_email_effective ?? null}
            emailSource={contract.candidate_email_source ?? null}
            phone={contract.candidate_phone_effective ?? null}
            phoneSource={contract.candidate_phone_source ?? null}
            editable={access.canEditContract}
            onSaveEmail={(raw) => saveCandidateContact({ candidate_email: raw })}
            onSavePhone={(raw) => saveCandidateContact({ candidate_phone: raw })}
            onError={setError}
          />
        </div>
      </DetailSection>

      {access.canViewContractDocuments && (
        <DetailSection
          title="Dokumenty"
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
          ) : !docsQuery.isSuccess ? (
            <p className="text-xs text-muted-foreground">Ładowanie…</p>
          ) : docs.length === 0 ? (
            <p className="text-xs text-muted-foreground">Brak dokumentów.</p>
          ) : (
            <ul className="grid gap-1">
              {docs.map((doc) => {
                const badge = sharePointBadge(doc);
                return (
                  <li key={doc.id} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                    <button
                      type="button"
                      onClick={() => void openDoc(doc)}
                      disabled={openingDocId === doc.id}
                      className="min-w-0 truncate text-left text-primary hover:underline disabled:opacity-60"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </button>
                    <span className="text-muted-foreground">
                      {DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}
                    </span>
                    {badge && (
                      <Badge variant={badge.tone} size="sm" title={badge.title}>
                        {badge.label}
                      </Badge>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </DetailSection>
      )}

      <DetailSection
        title="Ostatnie zdarzenia"
        aside={
          <Link
            href={detailHref("timeline")}
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
        ) : activities.length === 0 ? (
          <p className="text-xs text-muted-foreground">Brak wpisów w historii.</p>
        ) : (
          <ol className="grid gap-1.5">
            {activities.map((a) => (
              <li key={a.id} className="text-xs">
                <span className="font-medium text-foreground">{contractActivityLabel(a.action)}</span>
                <span className="text-muted-foreground">
                  {a.user_name ? ` · ${a.user_name}` : ""} · {formatIsoDatePl(a.created_at.slice(0, 10))}
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
          contractor={contractorItem ?? contractorItemFromDetail(contract)}
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
