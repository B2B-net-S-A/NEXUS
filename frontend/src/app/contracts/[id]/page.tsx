"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, {
  contractsApi,
  extractErrorMsg,
  type ContractSiblingRef,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";
import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";
import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";
import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { ContractOnboardingTab } from "@/components/ContractOnboardingTab";
import { ContractInvoicesTab } from "@/components/ContractInvoicesTab";
import { ContractEquipmentTab } from "@/components/contracts/ContractEquipmentTab";
import {
  FinancialRatesCard,
  type EurPlnRate,
} from "@/components/contracts/FinancialRatesCard";
import { ContractNotesTab } from "@/components/contracts/ContractNotesTab";
import {
  contractActivityDetailRows,
  contractActivityLabel,
} from "@/components/contracts/contract-timeline-labels";
import { ContractCandidateContactRow } from "@/components/contracts/ContractCandidateContactRow";
import { ContractRateBenchmarkCard } from "@/components/contracts/ContractRateBenchmarkCard";
import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";
import { ContractTerminationRecoveryPanel } from "@/components/contracts/ContractTerminationRecovery";
import {
  SignedContractDeleteConfirmation,
  signedDeleteActionFromError,
  type SignedDeleteRequirement,
} from "@/components/contracts/SignedContractDeleteConfirmation";
import { CONTRACT_TERMINATION_REASONS, type ContractTerminationReason } from "@/lib/api";
import { ContractDocument, summariseComplianceRisk } from "@/components/ContractDocumentsTab";
import {
  formatCurrency,
  parseDecimalInput,
  sanitizeDecimalInput,
} from "@/lib/utils";
// DD.MM.RRRR z zerem wiodącym (UAT M08-B06) — `Intl` dawało „1.09.2026".
import { formatDateTimePl, formatIsoDatePl as formatDate } from "@/lib/date-pl";
import {
  B2B_END_DATE_HOW,
  b2bEndDateLocked,
  b2bExtensionLocked,
  terminationSeedDate,
} from "@/lib/contract-end-date";
import { celebrate } from "@/lib/celebrate";
import { getAuthenticatedRequestHeaders } from "@/lib/session";
import { hasSectionAccess } from "@/lib/section-access";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { HOURS_PER_MONTH } from "@/lib/work-time";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  canManageCandidateFinance,
  canManageContractStatus,
  canRecoverContractTermination,
  canViewClientFinance,
  hasRole,
  useAuthStore,
} from "@/store/auth";
import {
  buildContractDetailHref,
  parseContractsReturnContext,
  type ContractsReturnContext,
} from "@/lib/contracts-list-navigation";
import {
  ArrowLeft,
  Pencil,
  Trash2,
  Save,
  X,
  Plus,
  Activity as ActivityIcon,
  History,
  FileText,
  FileEdit,
  AlertCircle,
  Loader2,
  User,
  Building2,
  Briefcase,
  Calendar,
  Banknote,
  TrendingUp,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ContractDetail {
  id: number;
  /**
   * NULL = umowa odpięta od usuniętego kandydata (migracja 0225). Rejestr
   * pokazuje takie umowy dalej, bo wiszą na nich faktury i podpisy.
   */
  candidate_id: number | null;
  client_id: number;
  job_id: number | null;
  candidate_name: string | null;
  client_name: string | null;
  job_title: string | null;
  // Kontakt do konsultanta. `candidate_email`/`candidate_phone` to zapisane na
  // umowie NADPISANIE (puste = brak nadpisania), `*_effective` to wartość po
  // fallbacku do profilu kandydata, `*_source` mówi, skąd pochodzi — bez tego
  // ekran nie umie oznaczyć „z profilu".
  candidate_email?: string | null;
  candidate_phone?: string | null;
  candidate_email_effective?: string | null;
  candidate_phone_effective?: string | null;
  candidate_email_source?: "contract" | "candidate_profile" | null;
  candidate_phone_source?: "contract" | "candidate_profile" | null;
  start_date: string;
  end_date: string | null;
  client_order_start_date?: string | null;
  client_order_end_date: string | null;
  rate_candidate: number | null;
  rate_client: number | null;
  candidate_rate_schedule: {
    id: number;
    rate: number;
    effective_from: string;
    effective_to: string | null;
    note: string | null;
    created_at: string;
  }[];
  client_rate_schedule: {
    id: number;
    rate: number;
    effective_from: string;
    note: string | null;
    created_at: string;
    /** Krok z zamówienia klienta; `null` = ręczny albo z aneksu. */
    source_order_id?: number | null;
  }[];
  framework_rate_schedule: {
    id: number;
    rate: number;
    effective_from: string;
    effective_to: string | null;
    note: string | null;
    created_at: string;
  }[];
  framework_rate: number | null;
  target_rate_min: number | null;
  target_rate_max: number | null;
  currency: string;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  eur_pln_rate?: EurPlnRate | null;
  rate_unit: "hourly" | "daily" | "monthly";
  billing_hours_per_month: number;
  margin: number | null;
  contract_type: "b2b" | "uop" | "uzlecenie";
  status: "draft" | "active" | "ending" | "ended";
  documents: unknown;
  client_pm_name: string | null;
  client_pm_email: string | null;
  line_manager: string | null;
  work_mode: "remote" | "hybrid" | "onsite" | null;
  office_location: string | null;
  team_name: string | null;
  project_name: string | null;
  handover_notes: string | null;
  order_consumption: number | null;
  order_consumption_unit: "rbh" | "md" | null;
  termination_reason: ContractTerminationReason | null;
  termination_lessons: string | null;
  terminated_at: string | null;
  monthly_rate_candidate: number | null;
  monthly_rate_client: number | null;
  monthly_margin: number | null;
  created_at: string;
  updated_at: string;
  // Pozostałe kontrakty tej samej osoby (konsolidacja wieloklientowa) —
  // zasilają przełącznik zakładek nazwanych po kliencie.
  related_contracts?: ContractSiblingRef[];
  // „Cofnij zakończenie" / „Powrót po przerwie" (0355).
  returned_from_contract_id?: number | null;
  return_contract_id?: number | null;
  can_reverse_termination?: boolean;
  can_return_after_break?: boolean;
  termination_reversed_at?: string | null;
  termination_reversed_by_name?: string | null;
}

interface ActivityEntry {
  id: number;
  action: string;
  details: Record<string, unknown> | null;
  user_id: number | null;
  user_name: string | null;
  created_at: string;
}

interface RateHistoryEntry {
  id: number;
  rate: number;
  currency: string;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-muted text-foreground border border-border dark:bg-muted dark:text-muted-foreground",
  active: "bg-emerald-100 text-emerald-700 border border-emerald-200",
  ending: "bg-orange-100 text-orange-700 border border-orange-200",
  ended: "bg-destructive/15 text-destructive border border-destructive/20",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
};

const TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uzlecenie: "Zlecenie",
};

const WORK_MODE_LABELS: Record<string, string> = {
  remote: "Zdalnie",
  hybrid: "Hybrydowo",
  onsite: "Stacjonarnie",
};

interface ContractTemplate {
  id: number;
  name: string;
  contract_type: string;
}

function GenerateDocumentButton({
  contractId,
  contractType,
}: {
  contractId: number;
  contractType: string;
}) {
  const { data: templates } = useQuery<ContractTemplate[]>({
    queryKey: ["contract-templates-by-type", contractType],
    queryFn: () =>
      api
        .get("/api/contract-templates", { params: { contract_type: contractType } })
        .then((r) => r.data),
  });

  if (!templates || templates.length === 0) return null;

  const openRendered = async (templateId: number) => {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const url = `${base}/api/contract-templates/${templateId}/render?contract_id=${contractId}`;
    try {
      const resp = await fetch(url, {
        headers: getAuthenticatedRequestHeaders(),
      });
      if (!resp.ok) {
        alert(`Błąd renderowania: ${resp.status}`);
        return;
      }
      const html = await resp.text();
      const win = window.open("", "_blank");
      if (!win) {
        alert("Popupy są blokowane — pozwól na okno i spróbuj ponownie.");
        return;
      }
      win.document.write(html);
      win.document.close();
    } catch (err) {
      alert(`Błąd: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="relative">
      <select
        id="contract-template-render"
        aria-label="Generuj dokument z szablonu"
        onChange={(e) => {
          const id = Number(e.target.value);
          if (id) openRendered(id);
          e.target.value = "";
        }}
        className="flex items-center gap-2 border border-border dark:border-border text-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted px-3 py-2 rounded-lg text-sm font-medium"
      >
        <option value="">Generuj z szablonu…</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

type TabKey =
  | "details"
  | "documents"
  | "amendments"
  | "onboarding"
  | "equipment"
  | "notes"
  | "invoices"
  | "rateHistory"
  | "timeline";

interface Tab {
  key: TabKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: Tab[] = [
  { key: "details", label: "Szczegóły", icon: FileEdit },
  { key: "documents", label: "Dokumenty", icon: FileText },
  { key: "amendments", label: "Aneksy", icon: FileEdit },
  { key: "onboarding", label: "Onboarding", icon: FileText },
  { key: "equipment", label: "Sprzęt", icon: Briefcase },
  { key: "notes", label: "Notatki / Rozmowy", icon: ActivityIcon },
  { key: "invoices", label: "Faktury", icon: Banknote },
  { key: "rateHistory", label: "Historia stawek", icon: History },
  { key: "timeline", label: "Timeline", icon: ActivityIcon },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[status] ?? ""}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function InfoRow({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <Icon className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-muted-foreground dark:text-muted-foreground">{label}</div>
        <div className="text-sm text-foreground dark:text-foreground">{children}</div>
      </div>
    </div>
  );
}

// ── Edit form ─────────────────────────────────────────────────────────────────

/** One editable step of the candidate-rate schedule ("stawka progresywna"). */
interface RateScheduleRow {
  rate: string;
  effectiveFrom: string;
  effectiveTo: string;
}

interface EditForm {
  start_date: string;
  end_date: string;
  client_order_end_date: string;
  rate_candidate: string;
  // Progressive candidate-rate schedule. Empty ⇒ plain single `rate_candidate`;
  // non-empty ⇒ the schedule editor drives the candidate rate over time.
  candidate_rate_schedule: RateScheduleRow[];
  rate_client: string;
  framework_rate: string;
  // Progressive framework-rate schedule ("stawka z umowy ramowej"). Empty ⇒ plain
  // single `framework_rate`; non-empty ⇒ the schedule editor drives it over time.
  framework_rate_schedule: RateScheduleRow[];
  target_rate_min: string;
  target_rate_max: string;
  rate_client_currency: string;
  rate_candidate_currency: string;
  rate_unit: string;
  billing_hours_per_month: string;
  contract_type: string;
  status: string;
  client_pm_name: string;
  client_pm_email: string;
  line_manager: string;
  work_mode: string;
  office_location: string;
  team_name: string;
  project_name: string;
  handover_notes: string;
  order_consumption: string;
  order_consumption_unit: string;
}

function contractToForm(c: ContractDetail): EditForm {
  return {
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    client_order_end_date: c.client_order_end_date ?? "",
    rate_candidate: c.rate_candidate?.toString() ?? "",
    // Prefill the schedule editor from the persisted schedule (oldest → newest).
    // Empty when the contract has no schedule yet — then the plain rate input is
    // shown and "Dodaj stawkę progresywną" seeds the first step on demand.
    candidate_rate_schedule: [...c.candidate_rate_schedule]
      .sort((a, b) => a.effective_from.localeCompare(b.effective_from))
      .map((s) => ({
        rate: s.rate?.toString() ?? "",
        effectiveFrom: s.effective_from ?? "",
        effectiveTo: s.effective_to ?? "",
      })),
    rate_client: c.rate_client?.toString() ?? "",
    framework_rate: c.framework_rate?.toString() ?? "",
    // Prefill the framework schedule editor from the persisted schedule
    // (oldest → newest). Empty when the contract has no framework schedule yet.
    framework_rate_schedule: [...(c.framework_rate_schedule ?? [])]
      .sort((a, b) => a.effective_from.localeCompare(b.effective_from))
      .map((s) => ({
        rate: s.rate?.toString() ?? "",
        effectiveFrom: s.effective_from ?? "",
        effectiveTo: s.effective_to ?? "",
      })),
    target_rate_min: c.target_rate_min?.toString() ?? "",
    target_rate_max: c.target_rate_max?.toString() ?? "",
    rate_client_currency: c.rate_client_currency ?? c.currency ?? "PLN",
    rate_candidate_currency: c.rate_candidate_currency ?? c.currency ?? "PLN",
    rate_unit: c.rate_unit ?? "monthly",
    billing_hours_per_month: (
      c.billing_hours_per_month ?? HOURS_PER_MONTH
    ).toString(),
    contract_type: c.contract_type,
    status: c.status,
    client_pm_name: c.client_pm_name ?? "",
    client_pm_email: c.client_pm_email ?? "",
    line_manager: c.line_manager ?? "",
    work_mode: c.work_mode ?? "",
    office_location: c.office_location ?? "",
    team_name: c.team_name ?? "",
    project_name: c.project_name ?? "",
    handover_notes: c.handover_notes ?? "",
    order_consumption: c.order_consumption?.toString() ?? "",
    order_consumption_unit: c.order_consumption_unit ?? "rbh",
  };
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ContractDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canManageFinance = canManageCandidateFinance(user);
  const isAdmin = hasRole(user, "admin");
  const canEditContract =
    !impersonating &&
    hasRole(user, "admin", "delivery_lead") &&
    hasSectionAccess(user, "delivery", "write");
  // Finanse zmieniają WYŁĄCZNIE kwoty (backend: `finance_amounts_only`),
  // więc bez roli admin/DL dostają edycję ograniczoną do sekcji stawek.
  const financeAmountsOnly =
    !impersonating && !canEditContract && canManageFinance;
  const canEditContractStatus = !impersonating && canManageContractStatus(user);
  const canRecoverTermination =
    !impersonating && canRecoverContractTermination(user);
  const [recoveryHint, setRecoveryHint] = useState("");
  const id = Number(params.id);

  // A profile can be opened from many places (candidate, any contracts view,
  // a copied deep-link). Only module links carry a validated return target.
  // Everything else falls back to a fresh queryless `/contracts`, which
  // intentionally starts with Active.
  const [returnContext, setReturnContext] = useState<ContractsReturnContext>({
    fromContracts: false,
    hasReturnTarget: false,
    returnTarget: "/contracts",
  });
  useEffect(() => {
    setReturnContext(parseContractsReturnContext(window.location.search));
  }, []);

  const [activeTab, setActiveTab] = useState<TabKey>("details");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm | null>(null);
  const [error, setError] = useState("");

  // Fetch contract
  const { data: contract, isLoading, isError } = useQuery<ContractDetail>({
    queryKey: ["contract", id],
    queryFn: () => contractsApi.get(id).then((r) => r.data),
    enabled: !Number.isNaN(id),
  });
  const canViewFinance = contract
    ? canViewClientFinance(user, contract.client_id)
    : false;
  // Opaque documents and rendered drafts can contain rates that cannot be
  // redacted safely. They retain the same assigned-client boundary as finance.
  const canViewContractDocuments = Boolean(contract) && (isAdmin || canViewFinance);
  const canEditContractDocuments = canEditContract && canViewContractDocuments;

  // Fetch activity timeline (lazy)
  const activitiesQuery = useQuery<ActivityEntry[]>({
    queryKey: ["contract-activities", id],
    queryFn: () => contractsApi.activities(id).then((r) => r.data),
    enabled: !Number.isNaN(id) && activeTab === "timeline",
  });
  const activities = activitiesQuery.data;
  // Ładowanie i błąd to nie „brak wpisów” (retest UAT B23: pusta historia
  // kontraktu przy znanych zdarzeniach).
  const activitiesViewState = resolveViewState({
    isLoading: activitiesQuery.isLoading,
    isError: activitiesQuery.isError,
    error: activitiesQuery.error,
    isSuccess: activitiesQuery.isSuccess,
    isEmpty: (activities ?? []).length === 0,
  });

  // Fetch rate history (lazy)
  const { data: rateHistory } = useQuery<RateHistoryEntry[]>({
    queryKey: ["contract-rate-history", id],
    queryFn: () => contractsApi.rateHistory(id).then((r) => r.data),
    enabled:
      canViewFinance &&
      !Number.isNaN(id) &&
      activeTab === "rateHistory",
  });

  // Compliance risk — eagerly fetch documents so the badge works on all tabs.
  const { data: contractDocs } = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", id],
    queryFn: () => contractsApi.documents(id).then((r) => r.data),
    enabled: !Number.isNaN(id) && canViewContractDocuments,
  });
  const complianceRisk = summariseComplianceRisk(contractDocs);

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => contractsApi.update(id, data),
    onSuccess: (_res, variables) => {
      queryClient.invalidateQueries({ queryKey: ["contract", id] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", id] });
      // Kids mode: celebrate activating a contract (draft → active). No-op otherwise.
      if (variables?.status === "active" && contract?.status === "draft") {
        celebrate({ message: "Kontrakt aktywny! 🎉" });
      }
      setEditing(false);
      setError("");
    },
    // `err.message` na AxiosError to „Request failed with status code 409" —
    // kod HTTP zamiast powodu. Odmowa aktywacji NIESIE powód
    // ({message: "Missing required fields", missing: [...]}), a użytkownik
    // widział surowy status i nie miał z czego się domyślić, czego brakuje
    // (zgłoszenie: zapis kontraktu ze statusem „Aktywny").
    onError: (err: unknown) => {
      setError(extractErrorMsg(err));
    },
  });

  // Kontakt do konsultanta zapisuje się POZA `updateMutation`: tamta zamyka
  // tryb edycji całej karty i przy błędzie pisze do wspólnego `error`, a tu
  // edytujemy jedno pole w miejscu. `InlineText` oczekuje Promise'a, którego
  // ODRZUCENIE niesie gotowy komunikat — surowy AxiosError dałby użytkownikowi
  // „Request failed with status code 422" zamiast powodu z backendu.
  const saveCandidateContact = async (patch: Record<string, string>) => {
    try {
      await contractsApi.update(id, patch);
    } catch (err: unknown) {
      throw new Error(extractErrorMsg(err));
    }
    await queryClient.invalidateQueries({ queryKey: ["contract", id] });
    setError("");
  };

  const statusMutation = useMutation({
    mutationFn: (status: string) => contractsApi.updateStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract", id] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", id] });
      setError("");
    },
    onError: (err: unknown) => setError(extractErrorMsg(err)),
  });

  // Usuwanie: modal potwierdzenia zamiast natywnego `window.confirm` (ten
  // wzorzec jest w repo zbanowany — patrz ContractTerminationDialog) ORAZ
  // jawna obsługa błędu. Wcześniej mutacja nie miała `onError`: odmowa 409 /
  // 500 z backendu kończyła się ciszą — spinner gasł, kontrakt zostawał, a
  // użytkownik widział „potwierdziłem i nic" (zgłoszony bug).
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [signedDeleteRequirement, setSignedDeleteRequirement] =
    useState<SignedDeleteRequirement | null>(null);
  const [showSignedDeleteDialog, setShowSignedDeleteDialog] = useState(false);
  const [signedDeleteError, setSignedDeleteError] = useState("");

  const finishDelete = () => {
    // Lista używa klucza "contracts-v2"; stary "contracts" zostaje dla
    // pozostałych konsumentów (profil kandydata itd.).
    queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contracts"] });
    router.push(returnContext.returnTarget);
  };

  const deleteMutation = useMutation({
    mutationFn: () => contractsApi.delete(id),
    onSuccess: finishDelete,
    onError: (err: unknown) => {
      const action = signedDeleteActionFromError(err, isAdmin);
      if (action?.kind === "confirm") {
        setSignedDeleteRequirement(action.requirement);
        setShowDeleteDialog(false);
        setSignedDeleteError("");
        setShowSignedDeleteDialog(true);
        return;
      }
      if (action?.kind === "admin_required") {
        setDeleteError(
          "Usunięcie kontraktu z podpisaną umową jest dostępne wyłącznie dla administratora.",
        );
        return;
      }
      setDeleteError(extractErrorMsg(err));
    },
  });
  const forceDeleteMutation = useMutation({
    mutationFn: (confirmation: string) =>
      contractsApi.forceDeleteSigned(id, confirmation),
    onSuccess: finishDelete,
    onError: (err: unknown) => {
      setSignedDeleteError(extractErrorMsg(err));
    },
  });

  const handleStartEdit = () => {
    if (!contract) return;
    setForm(contractToForm(contract));
    setEditing(true);
    setError("");
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setForm(null);
    setError("");
  };

  const [showTerminationDialog, setShowTerminationDialog] = useState(false);
  // Data wpisana w formularzu, zapamiętana dla dialogu „Zakończ współpracę".
  // Musi być zdjęta z `form` w tym samym zdarzeniu — zaraz niżej cofamy status,
  // a po otwarciu dialogu formularz bywa odmontowany.
  const [terminationDate, setTerminationDate] = useState<string | undefined>(
    undefined,
  );

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form || !contract) return;
    // Transitioning to "ended" — collect structured reason via dialog rather
    // than silently flipping status. Revert the form value so the save below
    // doesn't double-fire.
    if (form.status === "ended" && contract.status !== "ended") {
      setTerminationDate(terminationSeedDate(form.end_date, contract.end_date));
      setShowTerminationDialog(true);
      setForm({ ...form, status: contract.status });
      return;
    }
    // Zakończony kontrakt nie wraca zwykłą edycją statusu — ta nie przywraca
    // zamówień (zgłoszenie 09.2026). Wraca przez „Cofnij zakończenie" albo
    // „Powrót po przerwie".
    if (contract.status === "ended" && form.status !== "ended") {
      setError(
        "Zakończony kontrakt przywracasz akcją „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie” — nie zmianą statusu w formularzu.",
      );
      setForm({ ...form, status: contract.status });
      return;
    }
    // ── Candidate rate: plain single value vs progressive schedule ──────────
    // Rows with a numeric rate become schedule steps; an empty "Obowiązuje od"
    // defaults to the contract start date (mirrors the "Nowy kontrakt" form).
    const scheduleSteps = form.candidate_rate_schedule
      .map((r) => ({
        rate: parseDecimalInput(r.rate),
        effective_from: r.effectiveFrom || form.start_date,
        effective_to: r.effectiveTo || null,
      }))
      .filter(
        (
          r,
        ): r is { rate: number; effective_from: string; effective_to: string | null } =>
          r.rate !== null && !!r.effective_from,
      );
    // Reject duplicate "Obowiązuje od" — the resolver keys steps by that date.
    const fromDates = scheduleSteps.map((s) => s.effective_from);
    if (new Set(fromDates).size !== fromDates.length) {
      setError('Każdy etap stawki musi mieć inną datę „Obowiązuje od".');
      return;
    }
    // Reject an "Obowiązuje do" earlier than its "Obowiązuje od".
    if (scheduleSteps.some((s) => s.effective_to && s.effective_to < s.effective_from)) {
      setError('„Obowiązuje do" nie może być wcześniejsze niż „Obowiązuje od".');
      return;
    }
    const hadSchedule = contract.candidate_rate_schedule.length > 0;
    // A genuine schedule: >1 step, any explicit "Obowiązuje do", or a single
    // step starting on a custom (non-start) date. A former schedule is always
    // replaced so we don't silently drop planned steps.
    const isProgressive =
      scheduleSteps.length >= 2 ||
      scheduleSteps.some((s) => s.effective_to) ||
      form.candidate_rate_schedule.some(
        (r) =>
          parseDecimalInput(r.rate) !== null &&
          !!r.effectiveFrom &&
          r.effectiveFrom !== form.start_date,
      );

    // ── Framework rate: plain single value vs progressive schedule ──────────
    // Same shape/logic as the candidate schedule above ("Stawka z umowy ramowej").
    const frameworkSteps = form.framework_rate_schedule
      .map((r) => ({
        rate: parseDecimalInput(r.rate),
        effective_from: r.effectiveFrom || form.start_date,
        effective_to: r.effectiveTo || null,
      }))
      .filter(
        (
          r,
        ): r is { rate: number; effective_from: string; effective_to: string | null } =>
          r.rate !== null && !!r.effective_from,
      );
    const frameworkFromDates = frameworkSteps.map((s) => s.effective_from);
    if (new Set(frameworkFromDates).size !== frameworkFromDates.length) {
      setError(
        'Każdy etap stawki z umowy ramowej musi mieć inną datę „Obowiązuje od".',
      );
      return;
    }
    if (
      frameworkSteps.some((s) => s.effective_to && s.effective_to < s.effective_from)
    ) {
      setError('„Obowiązuje do" nie może być wcześniejsze niż „Obowiązuje od".');
      return;
    }
    const hadFrameworkSchedule = contract.framework_rate_schedule.length > 0;
    const isFrameworkProgressive =
      frameworkSteps.length >= 2 ||
      frameworkSteps.some((s) => s.effective_to) ||
      form.framework_rate_schedule.some(
        (r) =>
          parseDecimalInput(r.rate) !== null &&
          !!r.effectiveFrom &&
          r.effectiveFrom !== form.start_date,
      );

    // Umowa B2B bez ręcznego zakończenia jest bezterminowa
    // (`lib/contract-end-date.ts`) — zapis wysyła `null` zamiast daty.
    const endDateLocked = b2bEndDateLocked({
      contract_type: form.contract_type,
      status: form.status,
      terminated_at: contract?.terminated_at,
      termination_reason: contract?.termination_reason,
    });
    const operationalPayload: Record<string, unknown> = {
      start_date: form.start_date || null,
      end_date: endDateLocked ? null : form.end_date || null,
      client_order_end_date: form.client_order_end_date || null,
      contract_type: form.contract_type,
      status: form.status,
      client_pm_name: form.client_pm_name || null,
      client_pm_email: form.client_pm_email || null,
      line_manager: form.line_manager || null,
      work_mode: form.work_mode || null,
      office_location: form.office_location || null,
      team_name: form.team_name || null,
      project_name: form.project_name || null,
      handover_notes: form.handover_notes || null,
      order_consumption: parseDecimalInput(form.order_consumption),
      order_consumption_unit:
        parseDecimalInput(form.order_consumption) !== null
          ? form.order_consumption_unit
          : null,
    };
    const payload: Record<string, unknown> = financeAmountsOnly
      ? {}
      : operationalPayload;
    if (canManageFinance) {
      Object.assign(payload, {
        rate_client: parseDecimalInput(form.rate_client),
        target_rate_min: parseDecimalInput(form.target_rate_min),
        target_rate_max: parseDecimalInput(form.target_rate_max),
        rate_client_currency: form.rate_client_currency,
        rate_candidate_currency: form.rate_candidate_currency,
        rate_unit: form.rate_unit,
        billing_hours_per_month:
          Number(form.billing_hours_per_month) || HOURS_PER_MONTH,
      });
      if ((isProgressive || hadSchedule) && scheduleSteps.length > 0) {
        payload.candidate_rate_schedule = scheduleSteps;
      } else if (hadSchedule && scheduleSteps.length === 0) {
        payload.candidate_rate_schedule = [];
        payload.rate_candidate = parseDecimalInput(form.rate_candidate);
      } else {
        payload.rate_candidate =
          scheduleSteps.length > 0
            ? scheduleSteps[0].rate
            : parseDecimalInput(form.rate_candidate);
      }
      if (
        (isFrameworkProgressive || hadFrameworkSchedule) &&
        frameworkSteps.length > 0
      ) {
        payload.framework_rate_schedule = frameworkSteps;
      } else if (hadFrameworkSchedule && frameworkSteps.length === 0) {
        payload.framework_rate_schedule = [];
        payload.framework_rate = parseDecimalInput(form.framework_rate);
      } else {
        payload.framework_rate =
          frameworkSteps.length > 0
            ? frameworkSteps[0].rate
            : parseDecimalInput(form.framework_rate);
      }
    }
    updateMutation.mutate(payload);
  };

  const handleDelete = () => {
    setDeleteError("");
    setSignedDeleteError("");
    setSignedDeleteRequirement(null);
    setShowDeleteDialog(true);
  };

  const [showAddProject, setShowAddProject] = useState(false);

  // ── Render ──────────────────────────────────────────────────────────────────

  if (Number.isNaN(id)) {
    return (
      <div className="p-6">
        <p className="text-destructive">Nieprawidłowe ID kontraktu.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Ładowanie kontraktu…
      </div>
    );
  }

  if (isError || !contract) {
    return (
      <div className="p-6">
        <Link
          href={returnContext.returnTarget}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground dark:text-muted-foreground"
        >
          <ArrowLeft className="w-4 h-4" /> Wróć do listy
        </Link>
        <p className="mt-4 text-destructive">Nie udało się wczytać kontraktu.</p>
      </div>
    );
  }

  const visibleTabs = TABS.filter(
    (tab) =>
      (canViewContractDocuments || tab.key !== "documents") &&
      (canViewFinance ||
        (tab.key !== "invoices" && tab.key !== "rateHistory")),
  );

  // Konsolidacja wieloklientowa: pozostałe kontrakty tej samej osoby.
  // Chipy = zakładki nazwane po kliencie (klik → pełny widok tamtej umowy:
  // okres, stawki, marża, benchmark, dokumenty, aneksy — wszystko per klient,
  // bo to po prostu ta strona dla tamtego kontraktu).
  const relatedContracts = contract.related_contracts ?? [];
  // ODRĘBNI klienci z żywych umów — dwie żywe umowy u tego samego klienta
  // (dane historyczne) to nadal praca u JEDNEGO klienta.
  const liveClientCount = new Set(
    [
      ...(["active", "ending"].includes(contract.status)
        ? [contract.client_id]
        : []),
      ...relatedContracts
        .filter((r) => r.status === "active" || r.status === "ending")
        .map((r) => r.client_id),
    ],
  ).size;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <Link
            href={returnContext.returnTarget}
            className="inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-muted-foreground"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Kontrakty
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-3 flex-wrap">
            Kontrakt #{contract.id}
            <StatusBadge status={contract.status} />
            {canEditContractStatus && !editing && (
              <select
                aria-label="Zmień status kontraktu"
                value={contract.status}
                disabled={statusMutation.isPending}
                onChange={(event) => {
                  const next = event.target.value;
                  // „Zakończony → Aktywny" przestało być jedną akcją: pomyłka
                  // i powrót po przerwie to dwie różne operacje, a zwykła
                  // zmiana statusu nie przywraca zamówień (zgłoszenie 09.2026).
                  if (contract.status === "ended" && next !== "ended") {
                    setRecoveryHint(
                      canRecoverTermination
                        ? "Zakończony kontrakt przywracasz jedną z dwóch akcji poniżej: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie” (nowy kontrakt)."
                        : "Zakończony kontrakt przywraca Admin, Finanse albo Talent Community Manager: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie”.",
                    );
                    return;
                  }
                  setRecoveryHint("");
                  statusMutation.mutate(next);
                }}
                className="rounded-md border border-border bg-card px-2 py-1 text-sm font-medium"
              >
                <option value="draft">Draft</option>
                <option value="active">Aktywny</option>
                <option value="ending">Kończący się</option>
                <option value="ended">Zakończony</option>
              </select>
            )}
            {complianceRisk.risk === "overdue" && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-destructive/15 text-destructive border border-destructive/20">
                Compliance: dokument wygasł
              </span>
            )}
            {complianceRisk.risk === "soon" && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700 border border-orange-200">
                Compliance: {complianceRisk.docType} wygasa {formatDate(complianceRisk.soonestDate)}
              </span>
            )}
          </h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground">
            {/* Bez `candidate_id` nie ma do czego linkować — link
                `/candidates/null` udawałby istniejącą osobę i prowadził w 404. */}
            {contract.candidate_name && contract.candidate_id != null ? (
              <Link
                className="text-primary hover:underline dark:text-primary"
                href={`/candidates/${contract.candidate_id}`}
              >
                {contract.candidate_name}
              </Link>
            ) : contract.candidate_id != null ? (
              `#${contract.candidate_id}`
            ) : (
              "kandydat usunięty z systemu"
            )}
            {" · "}
            {contract.client_name ? (
              <Link
                className="text-primary hover:underline dark:text-primary"
                href={`/clients/${contract.client_id}`}
              >
                {contract.client_name}
              </Link>
            ) : (
              `Klient #${contract.client_id}`
            )}
            {contract.job_title ? ` · ${contract.job_title}` : ""}
            {contract.returned_from_contract_id != null && (
              <span className="ml-2 inline-flex items-center gap-1">
                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide bg-amber-100 text-amber-800 border border-amber-300">
                  POWRÓT PO PRZERWIE
                </span>
                <Link
                  className="text-xs text-primary hover:underline"
                  href={`/contracts/${contract.returned_from_contract_id}`}
                >
                  poprzedni kontrakt #{contract.returned_from_contract_id}
                </Link>
              </span>
            )}
            {contract.return_contract_id != null && (
              <Link
                className="ml-2 text-xs text-primary hover:underline"
                href={`/contracts/${contract.return_contract_id}`}
              >
                Powrót po przerwie: kontrakt #{contract.return_contract_id}
              </Link>
            )}
            {liveClientCount > 1 && (
              <span className="ml-2 text-xs font-medium text-primary">
                pracuje u {liveClientCount} klientów
              </span>
            )}
          </p>
        </div>

        {financeAmountsOnly && !editing && (
          <button
            onClick={handleStartEdit}
            className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium"
          >
            <Pencil className="w-4 h-4" /> Edytuj stawki
          </button>
        )}
        {canEditContract && (
          <div className="flex gap-2 flex-wrap">
            <GenerateDocumentButton contractId={id} contractType={contract.contract_type} />
            {contract.candidate_id != null && (
              <button
                onClick={() => setShowAddProject(true)}
                className="flex items-center gap-2 border border-primary/40 text-primary hover:bg-primary/10 px-4 py-2 rounded-lg text-sm font-medium"
              >
                <Plus className="w-4 h-4" /> Dodaj kolejny projekt
              </button>
            )}
            {!editing && (
              <button
                onClick={handleStartEdit}
                className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium"
              >
                <Pencil className="w-4 h-4" /> Edytuj
              </button>
            )}
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="flex items-center gap-2 bg-red-600 hover:bg-red-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}{" "}
              Usuń
            </button>
          </div>
        )}
      </div>

      {/* Zakładki per klient — widoczne tylko dla osoby wieloklientowej.
          Nazwą zakładki jest KLIENT (bez generycznego „Projekt 1/2"); dane
          finansowe i benchmark liczą się per kontrakt, więc per klient. */}
      {relatedContracts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-lg bg-primary text-white px-3 py-1.5 text-sm font-medium">
            <Building2 className="w-3.5 h-3.5" />
            {contract.client_name ?? `Klient #${contract.client_id}`}
          </span>
          {relatedContracts.map((sibling) => (
            <Link
              key={sibling.id}
              href={
                returnContext.hasReturnTarget
                  ? buildContractDetailHref(
                      sibling.id,
                      returnContext.returnTarget,
                    )
                  : `/contracts/${sibling.id}`
              }
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary/50 hover:text-primary"
              title={`${STATUS_LABELS[sibling.status] ?? sibling.status} · ${
                sibling.start_date ? formatDate(sibling.start_date) : "—"
              }${sibling.end_date ? ` – ${formatDate(sibling.end_date)}` : ""}`}
            >
              {sibling.client_name ?? `Klient #${sibling.client_id}`}
              <span
                className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                  STATUS_STYLES[sibling.status] ?? ""
                }`}
              >
                {STATUS_LABELS[sibling.status] ?? sibling.status}
              </span>
            </Link>
          ))}
        </div>
      )}

      {/* Potwierdzenie usunięcia — modal z jawnym stanem błędu (409/500 nie
          może już kończyć się ciszą). */}
      <AppModal
        open={showDeleteDialog}
        onOpenChange={(open) => {
          if (!deleteMutation.isPending) setShowDeleteDialog(open);
        }}
        title="Usunąć kontrakt?"
        description="Operacja jest nieodwracalna. Usunięty zostanie kontrakt WRAZ z jego dokumentami, aneksami, fakturami, zamówieniami i harmonogramami stawek. Zostają: kandydat w module Kandydaci, wygenerowane umowy B2B w „Wygenerowane umowy” oraz notatki i rozmowy (odpięte od kontraktu)."
        footer={
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowDeleteDialog(false)}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium border border-border text-foreground hover:bg-muted"
            >
              Anuluj
            </button>
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="flex items-center gap-2 bg-red-600 hover:bg-red-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              Usuń kontrakt
            </button>
          </div>
        }
      >
        {deleteError ? (
          <div className="rounded-lg bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {deleteError}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Kontrakt #{contract.id}
            {contract.candidate_name ? ` · ${contract.candidate_name}` : ""}
            {contract.client_name ? ` · ${contract.client_name}` : ""}
          </p>
        )}
      </AppModal>

      <SignedContractDeleteConfirmation
        open={showSignedDeleteDialog}
        onOpenChange={(open) => {
          setShowSignedDeleteDialog(open);
          if (!open) {
            setSignedDeleteError("");
            setSignedDeleteRequirement(null);
          }
        }}
        contractId={contract.id}
        contractorName={
          signedDeleteRequirement?.contractorName ?? contract.candidate_name
        }
        isPending={forceDeleteMutation.isPending}
        error={signedDeleteError}
        onConfirm={(confirmation) => forceDeleteMutation.mutate(confirmation)}
      />

      {contract.candidate_id != null && (
        <AddProjectDialog
          open={showAddProject}
          onOpenChange={setShowAddProject}
          candidateId={contract.candidate_id}
          candidateName={contract.candidate_name}
          canManageFinance={canManageFinance}
          baseContract={{
            id: contract.id,
            client_id: contract.client_id,
            contract_type: contract.contract_type,
            rate_unit: contract.rate_unit,
            currency: contract.currency,
            rate_client_currency: contract.rate_client_currency,
            rate_candidate_currency: contract.rate_candidate_currency,
            billing_hours_per_month: contract.billing_hours_per_month,
            work_mode: contract.work_mode,
          }}
        />
      )}

      {/* Tabs */}
      <div className="border-b border-border dark:border-border flex gap-1 overflow-x-auto">
        {visibleTabs.map((t) => {
          const active = t.key === activeTab;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
                active
                  ? "border-primary text-primary font-medium"
                  : "border-transparent text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground"
              }`}
            >
              <Icon className="w-4 h-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab: Szczegóły */}
      {activeTab === "details" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {/* View mode */}
            {!editing && (
              <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-1">
                <h2 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-3">
                  Informacje o kontrakcie
                </h2>
                <InfoRow icon={User} label="Kandydat">
                  {contract.candidate_name && contract.candidate_id != null ? (
                    <Link
                      href={`/candidates/${contract.candidate_id}`}
                      className="text-primary hover:underline dark:text-primary"
                    >
                      {contract.candidate_name}
                    </Link>
                  ) : contract.candidate_id != null ? (
                    `#${contract.candidate_id}`
                  ) : (
                    "kandydat usunięty z systemu"
                  )}
                </InfoRow>
                <InfoRow icon={Building2} label="Klient">
                  {contract.client_name ? (
                    <Link
                      href={`/clients/${contract.client_id}`}
                      className="text-primary hover:underline dark:text-primary"
                    >
                      {contract.client_name}
                    </Link>
                  ) : (
                    `#${contract.client_id}`
                  )}
                </InfoRow>
                {/* Zamówienia tej osoby żyją w zakładce klienta (UAT M08-B04). */}
                <InfoRow icon={FileText} label="Zamówienia">
                  <Link
                    href={`/clients/${contract.client_id}?tab=zamowienia`}
                    className="text-primary hover:underline dark:text-primary"
                  >
                    Zamówienia u klienta →
                  </Link>
                </InfoRow>
                <InfoRow icon={Briefcase} label="Rekrutacja">
                  {contract.job_title ? (
                    <Link
                      href={`/jobs/${contract.job_id}`}
                      className="text-primary hover:underline dark:text-primary"
                    >
                      {contract.job_title}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </InfoRow>
                <InfoRow icon={Calendar} label="Okres umowy">
                  {formatDate(contract.start_date)} –{" "}
                  {contract.end_date ? formatDate(contract.end_date) : (
                    <span className="italic text-muted-foreground">bezterminowo</span>
                  )}
                </InfoRow>
                {contract.client_order_start_date ? (
                  // Okres ZAMÓWIENIA — z najnowszego uzupełnionego zamówienia
                  // tej osoby (synchronizacja 09.2026). Osobno od okresu umowy.
                  <InfoRow icon={Calendar} label="Okres zamówienia">
                    {formatDate(contract.client_order_start_date)} –{" "}
                    {contract.client_order_end_date ? (
                      formatDate(contract.client_order_end_date)
                    ) : (
                      <span className="italic text-muted-foreground">bezterminowo</span>
                    )}
                  </InfoRow>
                ) : (
                  contract.client_order_end_date && (
                    <InfoRow icon={Calendar} label="Koniec zamówienia u klienta">
                      {formatDate(contract.client_order_end_date)}
                    </InfoRow>
                  )
                )}
                <InfoRow icon={FileEdit} label="Typ kontraktu">
                  {TYPE_LABELS[contract.contract_type] ?? contract.contract_type}
                </InfoRow>
                {/* Kontakt do konsultanta — jeden wiersz pod „Typ kontraktu".
                    Wartość leci z backendu już po fallbacku (umowa → profil
                    kandydata → puste), więc ekran nie powtarza tej reguły. */}
                <ContractCandidateContactRow
                  email={contract.candidate_email_effective ?? null}
                  emailSource={contract.candidate_email_source ?? null}
                  phone={contract.candidate_phone_effective ?? null}
                  phoneSource={contract.candidate_phone_source ?? null}
                  editable={canEditContract}
                  onSaveEmail={(raw) =>
                    saveCandidateContact({ candidate_email: raw })
                  }
                  onSavePhone={(raw) =>
                    saveCandidateContact({ candidate_phone: raw })
                  }
                  onError={setError}
                />
                {canViewFinance &&
                  (contract.target_rate_min || contract.target_rate_max) && (
                  <InfoRow icon={TrendingUp} label="Widełki docelowe stawki">
                    {contract.target_rate_min != null
                      ? formatCurrency(
                          contract.target_rate_min,
                          contract.rate_client_currency ?? contract.currency ?? "PLN",
                        )
                      : "—"}
                    {" / "}
                    {contract.target_rate_max != null
                      ? formatCurrency(
                          contract.target_rate_max,
                          contract.rate_client_currency ?? contract.currency ?? "PLN",
                        )
                      : "—"}
                  </InfoRow>
                )}
              </div>
            )}

            {/* Rate benchmark card — compare vs internal avg + market */}
            {!editing && canViewFinance && (
              <ContractRateBenchmarkCard
                contractId={id}
                currency={contract.rate_client_currency ?? contract.currency ?? "PLN"}
              />
            )}

            {!editing && recoveryHint && (
              <p role="status" className="text-sm text-amber-800 dark:text-amber-200">
                {recoveryHint}
              </p>
            )}
            {!editing && canRecoverTermination && (
              <ContractTerminationRecoveryPanel
                contractId={contract.id}
                canReverse={Boolean(contract.can_reverse_termination)}
                canReturn={Boolean(contract.can_return_after_break)}
              />
            )}
            {!editing && contract.termination_reversed_at && (
              <p className="text-sm text-muted-foreground" data-testid="termination-reversed">
                Zakończenie cofnięte {formatDateTimePl(contract.termination_reversed_at)}
                {contract.termination_reversed_by_name
                  ? ` przez ${contract.termination_reversed_by_name}`
                  : ""}
              </p>
            )}

            {/* Zakończenie współpracy — także zaplanowane na przyszłość: umowa
                wypowiedziana z datą za miesiąc pracuje do tej daty („Aktywny”/
                „Kończący się”), ale kto i dlaczego zakończył ma być widać od
                razu, nie dopiero w dniu zakończenia. */}
            {!editing &&
              ((contract.status === "ended" && contract.termination_reason) ||
                // `end_date` odróżnia zakończenie zaplanowane od umowy
                // przywróconej: wskrzeszenie zostawia `terminated_at`, ale
                // czyści datę końca (umowa znów bezterminowa).
                (contract.terminated_at && contract.end_date)) && (
              <div className="bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-900 rounded-2xl p-5">
                <h2 className="text-sm font-semibold text-red-800 dark:text-red-200 mb-2">
                  {contract.status === "ended"
                    ? "Zakończenie współpracy"
                    : "Zaplanowane zakończenie współpracy"}
                </h2>
                {contract.termination_reason && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">Powód: </span>
                    {CONTRACT_TERMINATION_REASONS.find(
                      (r) => r.value === contract.termination_reason,
                    )?.label ?? contract.termination_reason}
                  </p>
                )}
                {contract.terminated_at && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">Data: </span>
                    {formatDate(contract.terminated_at)}
                  </p>
                )}
                {contract.termination_lessons && (
                  <p className="text-sm mt-2 whitespace-pre-wrap">
                    <span className="text-muted-foreground block">
                      Kto i dlaczego / wnioski:
                    </span>
                    {contract.termination_lessons}
                  </p>
                )}
              </div>
            )}

            {/* Assignment context */}
            {!editing && (contract.client_pm_name || contract.line_manager || contract.work_mode || contract.project_name || contract.team_name || contract.office_location) && (
              <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-1">
                <h2 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-3">
                  Osadzenie u klienta
                </h2>
                {contract.client_pm_name && (
                  <InfoRow icon={User} label="PM po stronie klienta">
                    {contract.client_pm_name}
                    {contract.client_pm_email && (
                      <span className="block text-xs text-muted-foreground dark:text-muted-foreground">
                        {contract.client_pm_email}
                      </span>
                    )}
                  </InfoRow>
                )}
                {contract.line_manager && (
                  <InfoRow icon={User} label="Line Manager">
                    {contract.line_manager}
                  </InfoRow>
                )}
                {contract.work_mode && (
                  <InfoRow icon={Building2} label="Tryb pracy">
                    {WORK_MODE_LABELS[contract.work_mode] ?? contract.work_mode}
                    {contract.office_location && ` · ${contract.office_location}`}
                  </InfoRow>
                )}
                {contract.project_name && (
                  <InfoRow icon={Briefcase} label="Projekt">
                    {contract.project_name}
                  </InfoRow>
                )}
                {contract.team_name && (
                  <InfoRow icon={Briefcase} label="Zespół">
                    {contract.team_name}
                  </InfoRow>
                )}
              </div>
            )}

            {/* Handover notes (C6) — wewnętrzne */}
            {!editing && contract.handover_notes && (
              <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-900 rounded-2xl p-5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200 mb-2">
                  Notatki wewnętrzne (handover)
                </h2>
                <p className="text-sm text-amber-900 dark:text-amber-100 whitespace-pre-line">
                  {contract.handover_notes}
                </p>
              </div>
            )}

            {/* Edit mode */}
            {editing && form && (
              <form
                onSubmit={handleSave}
                className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-4"
              >
                <h2 className="text-sm font-semibold text-foreground dark:text-muted-foreground">
                  {financeAmountsOnly ? "Edycja stawek" : "Edycja kontraktu"}
                </h2>

                {error && (
                  <div className="text-sm text-destructive bg-destructive/10 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-4 py-2 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" /> {error}
                  </div>
                )}

                {!financeAmountsOnly && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="contract-edit-start-date" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Data rozpoczęcia
                    </label>
                    <input id="contract-edit-start-date"
                      type="date"
                      value={form.start_date}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, start_date: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="contract-edit-end-date"
                      className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1"
                    >
                      Data zakończenia
                    </label>
                    {b2bEndDateLocked({
                      contract_type: form.contract_type,
                      status: form.status,
                      terminated_at: contract.terminated_at,
                      termination_reason: contract.termination_reason,
                    }) ? (
                      <p
                        className="rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted-foreground"
                        data-testid="end-date-b2b-indefinite"
                      >
                        Bezterminowo. {B2B_END_DATE_HOW}
                      </p>
                    ) : (
                      <input
                        id="contract-edit-end-date"
                        type="date"
                        value={form.end_date}
                        onChange={(e) =>
                          setForm((f) => (f ? { ...f, end_date: e.target.value } : f))
                        }
                        className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                      />
                    )}
                  </div>
                  <div>
                    <label htmlFor="contract-edit-client-order-end-date" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Koniec zamówienia u klienta
                    </label>
                    <input id="contract-edit-client-order-end-date"
                      type="date"
                      value={form.client_order_end_date}
                      onChange={(e) =>
                        setForm((f) =>
                          f ? { ...f, client_order_end_date: e.target.value } : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  </div>
                  <div>
                    <label htmlFor="contract-edit-contract-type" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Typ kontraktu
                    </label>
                    <select id="contract-edit-contract-type"
                      value={form.contract_type}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, contract_type: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="b2b">B2B</option>
                      <option value="uop">UoP</option>
                      <option value="uzlecenie">Zlecenie</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="contract-edit-status" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Status
                    </label>
                    <select id="contract-edit-status"
                      value={form.status}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, status: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="draft">Draft</option>
                      <option value="active">Aktywny</option>
                      <option value="ending">Kończący się</option>
                      <option value="ended">Zakończony</option>
                    </select>
                  </div>
                </div>
                )}

                {canManageFinance && (
                  <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <label htmlFor="contract-edit-rate-client" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Stawka klienta
                    </label>
                    <input id="contract-edit-rate-client"
                      type="text"
                      inputMode="decimal"
                      value={form.rate_client}
                      disabled={contract.client_rate_schedule.length > 0}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? { ...f, rate_client: sanitizeDecimalInput(e.target.value) }
                            : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground disabled:opacity-60 disabled:cursor-not-allowed"
                    />
                    {contract.client_rate_schedule.length > 0 && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Stawka klienta ma harmonogram — zmień ją przez aneks
                        „Zmień stawkę” (z datą wejścia w życie).
                      </p>
                    )}
                  </div>
                  <div>
                    <label htmlFor="contract-edit-target-rate-min" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Widełki docelowe (min)
                    </label>
                    <input id="contract-edit-target-rate-min"
                      type="text"
                      inputMode="decimal"
                      value={form.target_rate_min}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? { ...f, target_rate_min: sanitizeDecimalInput(e.target.value) }
                            : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  </div>
                  <div>
                    <label htmlFor="contract-edit-target-rate-max" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Widełki docelowe (max)
                    </label>
                    <input id="contract-edit-target-rate-max"
                      type="text"
                      inputMode="decimal"
                      value={form.target_rate_max}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? { ...f, target_rate_max: sanitizeDecimalInput(e.target.value) }
                            : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  </div>
                  <div>
                    <label htmlFor="contract-edit-rate-client-currency" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Waluta stawki przychodowej (klienta)
                    </label>
                    <select id="contract-edit-rate-client-currency"
                      value={form.rate_client_currency}
                      onChange={(e) =>
                        setForm((f) =>
                          f ? { ...f, rate_client_currency: e.target.value } : f,
                        )
                      }
                      aria-label="Waluta stawki przychodowej (klienta)"
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="PLN">PLN</option>
                      <option value="EUR">EUR</option>
                      <option value="USD">USD</option>
                      <option value="GBP">GBP</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="contract-edit-rate-candidate-currency" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Waluta stawki kosztowej (kandydata / umowy ramowej)
                    </label>
                    <select id="contract-edit-rate-candidate-currency"
                      value={form.rate_candidate_currency}
                      onChange={(e) =>
                        setForm((f) =>
                          f ? { ...f, rate_candidate_currency: e.target.value } : f,
                        )
                      }
                      aria-label="Waluta stawki kosztowej (kandydata / umowy ramowej)"
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="PLN">PLN</option>
                      <option value="EUR">EUR</option>
                      <option value="USD">USD</option>
                      <option value="GBP">GBP</option>
                    </select>
                  </div>
                </div>

                {/* Stawka z umowy ramowej — pojedyncza lub progresywna (harmonogram) */}
                <div className="space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <label id="contract-edit-framework-rate-label" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground">
                      Stawka z umowy ramowej
                    </label>
                    <span className="text-xs text-muted-foreground">
                      Zaplanuj zmianę stawki ramowej — system zastosuje aktualną od
                      wskazanej daty.
                    </span>
                  </div>

                  {form.framework_rate_schedule.length === 0 ? (
                    <input
                      id="contract-edit-framework-rate"
                      aria-labelledby="contract-edit-framework-rate-label"
                      type="text"
                      inputMode="decimal"
                      value={form.framework_rate}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? {
                                ...f,
                                framework_rate: sanitizeDecimalInput(e.target.value),
                              }
                            : f,
                        )
                      }
                      placeholder="np. 215,60"
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  ) : (
                    <div className="space-y-2">
                      {form.framework_rate_schedule.map((row, idx) => (
                        <div key={idx} className="flex items-end gap-2">
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Stawka
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki z umowy ramowej: kwota`}
                              type="text"
                              inputMode="decimal"
                              value={row.rate}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        framework_rate_schedule:
                                          f.framework_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? {
                                                  ...r,
                                                  rate: sanitizeDecimalInput(
                                                    e.target.value,
                                                  ),
                                                }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              placeholder="np. 215,60"
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Obowiązuje od
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki z umowy ramowej: obowiązuje od`}
                              type="date"
                              value={row.effectiveFrom}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        framework_rate_schedule:
                                          f.framework_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? { ...r, effectiveFrom: e.target.value }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Obowiązuje do
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki z umowy ramowej: obowiązuje do`}
                              type="date"
                              value={row.effectiveTo}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        framework_rate_schedule:
                                          f.framework_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? { ...r, effectiveTo: e.target.value }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <button
                            type="button"
                            title="Usuń etap stawki"
                            aria-label={`Usuń etap ${idx + 1} stawki z umowy ramowej`}
                            onClick={() =>
                              setForm((f) =>
                                f
                                  ? {
                                      ...f,
                                      framework_rate_schedule:
                                        f.framework_rate_schedule.filter(
                                          (_, i) => i !== idx,
                                        ),
                                    }
                                  : f,
                              )
                            }
                            className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ))}
                      {form.framework_rate_schedule[0]?.effectiveFrom === "" && (
                        <p className="text-xs text-muted-foreground">
                          Pierwszy etap bez daty obowiązuje od daty rozpoczęcia
                          kontraktu.
                        </p>
                      )}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() =>
                      setForm((f) => {
                        if (!f) return f;
                        // First click: seed the current framework rate as step 1 and
                        // open a blank step 2. Later clicks: append another blank step.
                        const next =
                          f.framework_rate_schedule.length === 0
                            ? [
                                {
                                  rate: f.framework_rate,
                                  effectiveFrom: "",
                                  effectiveTo: "",
                                },
                                { rate: "", effectiveFrom: "", effectiveTo: "" },
                              ]
                            : [
                                ...f.framework_rate_schedule,
                                { rate: "", effectiveFrom: "", effectiveTo: "" },
                              ];
                        return { ...f, framework_rate_schedule: next };
                      })
                    }
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    <Plus className="h-3.5 w-3.5" /> Dodaj etap stawki ramowej
                  </button>
                </div>

                {/* Stawka kandydata — pojedyncza lub progresywna (harmonogram) */}
                <div className="space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <label id="contract-edit-rate-candidate-label" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground">
                      Stawka kandydata
                    </label>
                    <span className="text-xs text-muted-foreground">
                      Zaplanuj etapy — system zastosuje aktualną od wskazanej daty.
                    </span>
                  </div>

                  {form.candidate_rate_schedule.length === 0 ? (
                    <input
                      id="contract-edit-rate-candidate"
                      aria-labelledby="contract-edit-rate-candidate-label"
                      type="text"
                      inputMode="decimal"
                      value={form.rate_candidate}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? { ...f, rate_candidate: sanitizeDecimalInput(e.target.value) }
                            : f,
                        )
                      }
                      placeholder="np. 215,60"
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  ) : (
                    <div className="space-y-2">
                      {form.candidate_rate_schedule.map((row, idx) => (
                        <div key={idx} className="flex items-end gap-2">
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Stawka
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki kandydata: kwota`}
                              type="text"
                              inputMode="decimal"
                              value={row.rate}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        candidate_rate_schedule:
                                          f.candidate_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? {
                                                  ...r,
                                                  rate: sanitizeDecimalInput(
                                                    e.target.value,
                                                  ),
                                                }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              placeholder="np. 215,60"
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Obowiązuje od
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki kandydata: obowiązuje od`}
                              type="date"
                              value={row.effectiveFrom}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        candidate_rate_schedule:
                                          f.candidate_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? { ...r, effectiveFrom: e.target.value }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <div className="flex-1">
                            {idx === 0 && (
                              <span className="mb-1 block text-[11px] text-muted-foreground">
                                Obowiązuje do
                              </span>
                            )}
                            <input
                              aria-label={`Etap ${idx + 1} stawki kandydata: obowiązuje do`}
                              type="date"
                              value={row.effectiveTo}
                              onChange={(e) =>
                                setForm((f) =>
                                  f
                                    ? {
                                        ...f,
                                        candidate_rate_schedule:
                                          f.candidate_rate_schedule.map((r, i) =>
                                            i === idx
                                              ? { ...r, effectiveTo: e.target.value }
                                              : r,
                                          ),
                                      }
                                    : f,
                                )
                              }
                              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                            />
                          </div>
                          <button
                            type="button"
                            title="Usuń etap stawki"
                            aria-label={`Usuń etap ${idx + 1} stawki kandydata`}
                            onClick={() =>
                              setForm((f) =>
                                f
                                  ? {
                                      ...f,
                                      candidate_rate_schedule:
                                        f.candidate_rate_schedule.filter(
                                          (_, i) => i !== idx,
                                        ),
                                    }
                                  : f,
                              )
                            }
                            className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ))}
                      {form.candidate_rate_schedule[0]?.effectiveFrom === "" && (
                        <p className="text-xs text-muted-foreground">
                          Pierwszy etap bez daty obowiązuje od daty rozpoczęcia
                          kontraktu.
                        </p>
                      )}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() =>
                      setForm((f) => {
                        if (!f) return f;
                        // First click: seed the current rate as step 1 and open a
                        // blank step 2. Later clicks: append another blank step.
                        const next =
                          f.candidate_rate_schedule.length === 0
                            ? [
                                {
                                  rate: f.rate_candidate,
                                  effectiveFrom: "",
                                  effectiveTo: "",
                                },
                                { rate: "", effectiveFrom: "", effectiveTo: "" },
                              ]
                            : [
                                ...f.candidate_rate_schedule,
                                { rate: "", effectiveFrom: "", effectiveTo: "" },
                              ];
                        return { ...f, candidate_rate_schedule: next };
                      })
                    }
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    <Plus className="h-3.5 w-3.5" /> Dodaj stawkę progresywną
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="contract-edit-rate-unit" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Jednostka stawki
                    </label>
                    <select id="contract-edit-rate-unit"
                      value={form.rate_unit}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, rate_unit: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="hourly">Godzinowo</option>
                      <option value="monthly">Miesięcznie</option>
                      {/* Stawki w Kontraktach są godzinowe — MD zostaje tylko
                          dla kontraktu sprzed przeliczenia; zapis przeliczy go
                          na zł/h (÷ 8). Nowego MD nie da się wybrać. */}
                      {form.rate_unit === "daily" && (
                        <option value="daily" disabled>
                          Dziennie (MD) — zapis przeliczy na zł/h
                        </option>
                      )}
                    </select>
                  </div>
                  {form.rate_unit === "hourly" && (
                    <div>
                      <label htmlFor="contract-edit-billing-hours-per-month" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                        Godziny / miesiąc
                      </label>
                      <input id="contract-edit-billing-hours-per-month"
                        type="number"
                        min="1"
                        step="1"
                        value={form.billing_hours_per_month}
                        onChange={(e) =>
                          setForm((f) => (f ? { ...f, billing_hours_per_month: e.target.value } : f))
                        }
                        className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                      />
                    </div>
                  )}
                </div>
                  </>
                )}

                {!financeAmountsOnly && (
                  <>
                {/* Zużycie zamówienia — ilość + jednostka (RBH / MD) */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="contract-edit-order-consumption" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Zużycie zamówienia
                    </label>
                    <input id="contract-edit-order-consumption"
                      type="text"
                      inputMode="decimal"
                      value={form.order_consumption}
                      onChange={(e) =>
                        setForm((f) =>
                          f
                            ? { ...f, order_consumption: sanitizeDecimalInput(e.target.value) }
                            : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    />
                  </div>
                  <div>
                    <label htmlFor="contract-edit-order-consumption-unit" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                      Jednostka zużycia
                    </label>
                    <select id="contract-edit-order-consumption-unit"
                      value={form.order_consumption_unit}
                      onChange={(e) =>
                        setForm((f) =>
                          f ? { ...f, order_consumption_unit: e.target.value } : f,
                        )
                      }
                      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                    >
                      <option value="rbh">RBH</option>
                      <option value="md">MD</option>
                    </select>
                  </div>
                </div>

                <div className="border-t border-border dark:border-border pt-3">
                  <label htmlFor="contract-edit-handover-notes" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                    Notatki wewnętrzne (widoczne tylko dla TAC/delivery)
                  </label>
                  <textarea id="contract-edit-handover-notes"
                    rows={3}
                    value={form.handover_notes}
                    onChange={(e) =>
                      setForm((f) => (f ? { ...f, handover_notes: e.target.value } : f))
                    }
                    placeholder="Preferencje kontraktora, quirks, historia relacji z klientem…"
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                  />
                </div>

                <details className="border-t border-border dark:border-border pt-3">
                  <summary className="cursor-pointer text-sm font-semibold text-foreground dark:text-muted-foreground mb-2">
                    Osadzenie u klienta
                  </summary>
                  <div className="space-y-3 mt-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label htmlFor="contract-edit-client-pm-name" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          PM po stronie klienta
                        </label>
                        <input id="contract-edit-client-pm-name"
                          type="text"
                          value={form.client_pm_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, client_pm_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                          placeholder="Jan Kowalski"
                        />
                      </div>
                      <div>
                        <label htmlFor="contract-edit-client-pm-email" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Email PM
                        </label>
                        <input id="contract-edit-client-pm-email"
                          type="email"
                          value={form.client_pm_email}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, client_pm_email: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                          placeholder="jan.kowalski@klient.pl"
                        />
                      </div>
                      <div>
                        <label htmlFor="contract-edit-line-manager" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Line Manager
                        </label>
                        <input id="contract-edit-line-manager"
                          type="text"
                          value={form.line_manager}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, line_manager: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                          placeholder="Imię i nazwisko (po stronie klienta)"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label htmlFor="contract-edit-work-mode" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Tryb pracy (opcjonalnie)
                        </label>
                        <select id="contract-edit-work-mode"
                          value={form.work_mode}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, work_mode: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                        >
                          <option value="">— nie określono —</option>
                          <option value="remote">Zdalnie</option>
                          <option value="hybrid">Hybrydowo</option>
                          <option value="onsite">Stacjonarnie</option>
                        </select>
                      </div>
                      <div>
                        <label htmlFor="contract-edit-office-location" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Lokalizacja biura
                        </label>
                        <input id="contract-edit-office-location"
                          type="text"
                          value={form.office_location}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, office_location: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                          placeholder="Warszawa — Domaniewska 50"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label htmlFor="contract-edit-project-name" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Projekt
                        </label>
                        <input id="contract-edit-project-name"
                          type="text"
                          value={form.project_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, project_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                        />
                      </div>
                      <div>
                        <label htmlFor="contract-edit-team-name" className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                          Zespół
                        </label>
                        <input id="contract-edit-team-name"
                          type="text"
                          value={form.team_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, team_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted dark:text-foreground"
                        />
                      </div>
                    </div>
                  </div>
                </details>
                  </>
                )}

                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={handleCancelEdit}
                    className="flex items-center gap-2 px-4 py-2 text-sm text-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted rounded-lg"
                  >
                    <X className="w-4 h-4" /> Anuluj
                  </button>
                  <button
                    type="submit"
                    disabled={updateMutation.isPending}
                    className="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
                  >
                    {updateMutation.isPending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    Zapisz
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Right sidebar: rates & margin */}
          <div className="space-y-4">
            {canViewFinance && <FinancialRatesCard contract={contract} />}

            <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 text-xs text-muted-foreground dark:text-muted-foreground space-y-1">
              <div>Utworzono: {formatDate(contract.created_at)}</div>
              <div>Aktualizacja: {formatDate(contract.updated_at)}</div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Dokumenty */}
      {activeTab === "documents" && (
        <ContractDocumentsTab
          contractId={id}
          readOnly={!canEditContractDocuments}
        />
      )}

      {/* Tab: Aneksy */}
      {activeTab === "amendments" && (
        <ContractAmendmentsTab
          contractId={id}
          clientId={contract.client_id}
          readOnly={!canEditContract}
          extensionLocked={b2bExtensionLocked(contract)}
        />
      )}

      {/* Tab: Onboarding */}
      {activeTab === "onboarding" && (
        <ContractOnboardingTab
          contractId={id}
          readOnly={!canEditContract}
        />
      )}

      {/* Tab: Sprzęt */}
      {activeTab === "equipment" && (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6">
          <ContractEquipmentTab
            contractId={id}
            readOnly={!canEditContract}
          />
        </div>
      )}

      {/* Tab: Notatki / rozmowy */}
      {activeTab === "notes" && (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6">
          <ContractNotesTab contractId={id} />
        </div>
      )}

      {/* Tab: Faktury */}
      {canViewFinance && activeTab === "invoices" && (
        <ContractInvoicesTab contractId={id} readOnly={!canManageFinance} />
      )}

      {/* Tab: Rate history */}
      {canViewFinance && activeTab === "rateHistory" && (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs overflow-hidden">
          {!rateHistory || rateHistory.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground dark:text-muted-foreground">
              Brak historii stawek dla tego kandydata i klienta.
              {/* Ta zakładka czyta historię stawek kandydata z poprzednich
                  zaangażowań (osobna tabela), nie harmonogram tego kontraktu.
                  Bez tej wskazówki pusta zakładka obok kroków w Szczegółach
                  czytała się jak zgubione dane. */}
              {(contract.client_rate_schedule.length > 0 ||
                contract.candidate_rate_schedule.length > 0) && (
                <p className="mt-2 text-xs">
                  Harmonogram stawek tego kontraktu (kroki z datami, także z
                  zamówień klienta) jest w zakładce „Szczegóły” w karcie „Stawki
                  finansowe”.
                </p>
              )}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground dark:text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-2">Od</th>
                  <th className="text-left px-4 py-2">Do</th>
                  <th className="text-left px-4 py-2">Typ</th>
                  <th className="text-right px-4 py-2">Stawka</th>
                  <th className="text-left px-4 py-2">Notatka</th>
                </tr>
              </thead>
              <tbody>
                {rateHistory.map((row) => (
                  <tr
                    key={row.id}
                    className="border-t border-border dark:border-border"
                  >
                    <td className="px-4 py-2">{formatDate(row.start_date)}</td>
                    <td className="px-4 py-2">
                      {row.end_date ? formatDate(row.end_date) : "—"}
                    </td>
                    <td className="px-4 py-2 uppercase">{row.contract_type}</td>
                    <td className="px-4 py-2 text-right font-medium">
                      {formatCurrency(row.rate, row.currency)}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground dark:text-muted-foreground">
                      {row.notes ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab: Timeline (activity log) */}
      {activeTab === "timeline" && (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6">
          {activitiesViewState === "loading" ? (
            <div role="status" className="text-center text-sm text-muted-foreground py-6">
              Wczytuję historię…
            </div>
          ) : isBlockingViewState(activitiesViewState) ? (
            <QueryStateNotice
              state={activitiesViewState as "forbidden" | "not_found" | "error"}
              onRetry={() => void activitiesQuery.refetch()}
            />
          ) : !activities || activities.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground dark:text-muted-foreground py-6">
              Brak wpisów w historii.
            </div>
          ) : (
            <ol className="space-y-4">
              {activities.map((a) => (
                <li key={a.id} className="flex gap-3">
                  <div className="w-2 h-2 rounded-full bg-primary mt-2 shrink-0" />
                  <div className="flex-1">
                    <div className="text-sm text-foreground dark:text-foreground">
                      {/* Etykieta PL zamiast slugu (UAT B23) — `synced_with_orders`
                          i `<pre>` z JSON-em kazały czytać strukturę techniczną. */}
                      <span
                        className="font-medium"
                        data-testid={`contract-activity-${a.id}-label`}
                      >
                        {contractActivityLabel(a.action)}
                      </span>
                      {a.user_name && (
                        <span className="text-muted-foreground dark:text-muted-foreground">
                          {" "}
                          · {a.user_name}
                        </span>
                      )}
                    </div>
                    {a.details && Object.keys(a.details).length > 0 && (
                      <>
                        <dl
                          className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs"
                          data-testid={`contract-activity-${a.id}-details`}
                        >
                          {contractActivityDetailRows(a.details).map((row) => (
                            <div key={row.key} className="contents">
                              <dt className="text-muted-foreground dark:text-muted-foreground">
                                {row.label}
                              </dt>
                              <dd className="text-foreground dark:text-foreground break-words">
                                {row.value}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        <details className="mt-1 text-xs text-muted-foreground">
                          <summary className="cursor-pointer select-none">
                            Dane techniczne
                          </summary>
                          <pre className="mt-1 bg-muted dark:bg-card/50 rounded px-2 py-1 overflow-x-auto">
                            {JSON.stringify(a.details, null, 2)}
                          </pre>
                        </details>
                      </>
                    )}
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {formatDate(a.created_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {showTerminationDialog && (
        <ContractTerminationDialog
          contractId={id}
          // Data z formularza edycji, nie `contract.end_date` z serwera:
          // operator wpisał ją przed chwilą obok statusu „Zakończony" i nie ma
          // jej podawać drugi raz. Pole w dialogu zostaje edytowalne.
          defaultDate={terminationDate}
          onClose={() => {
            setShowTerminationDialog(false);
            setTerminationDate(undefined);
          }}
          onSuccess={() => {
            setShowTerminationDialog(false);
            setTerminationDate(undefined);
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}
