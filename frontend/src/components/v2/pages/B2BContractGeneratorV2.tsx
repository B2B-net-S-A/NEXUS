"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Calendar,
  Check,
  CheckCircle2,
  ChevronsUpDown,
  CircleDashed,
  CircleDot,
  CircleSlash,
  Download,
  Eye,
  ExternalLink,
  FileSignature,
  Loader2,
  Mail,
  Pencil,
  Plus,
  Printer,
  Save,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
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
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import api, {
  b2bGeneratorApi,
  extractErrorMsg,
  signingApi,
  type B2BClosureReason,
  type B2BConfirmFullySignedResult,
  type B2BContractStatus,
  type B2BGeneratedContractRow,
  type B2BGeneratedContractUpdate,
  type B2BGeneratePayload,
  type B2BRenderPayload,
  type B2BRole,
  type B2BUopCheckResult,
} from "@/lib/api";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { hasRole, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

// Cały router generatora (13 endpointów) jest zabramkowany jedną rolą —
// `ContractLegalAccess` = admin/head_of_recruitment/delivery_lead/tac (PR #791,
// containment M5 PR-01). Dla osoby spoza tego grona KAŻDY request tej strony
// wraca 403, więc listy renderowały się jako puste: brak pozycji w „Obszar
// usług" i „Brak wygenerowanych umów" — co czyta się jak skasowanie danych
// (tak zostało zgłoszone). 403 musi być nazwany wprost, nie udawać pustki.
function isForbidden(error: unknown): boolean {
  return (
    (error as { response?: { status?: number } } | null)?.response?.status === 403
  );
}

const NO_ACCESS_TITLE = "Brak uprawnień do Generatora Umów B2B";
const NO_ACCESS_DESC =
  "Generator jest dostępny dla ról: administrator, head of recruitment, " +
  "delivery lead, TAC. Poproś administratora o nadanie dostępu — " +
  "wygenerowane wcześniej umowy nie zostały usunięte, są tylko niewidoczne " +
  "bez uprawnień.";

type ContractConflict = {
  message: string;
  contractIds: number[];
};

function getContractConflict(error: unknown): ContractConflict | null {
  const response = (
    error as {
      response?: {
        status?: number;
        data?: { detail?: unknown };
      };
    } | null
  )?.response;
  if (response?.status !== 409) return null;
  const detail = response.data?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) {
    return null;
  }
  const message = (detail as { message?: unknown }).message;
  const rawIds = (detail as { contract_ids?: unknown }).contract_ids;
  if (typeof message !== "string") return null;
  return {
    message,
    contractIds: Array.isArray(rawIds)
      ? rawIds.filter(
          (id): id is number => typeof id === "number" && Number.isFinite(id),
        )
      : [],
  };
}

type CandidateOption = {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  email?: string | null;
};

type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage: string;
};

type CandidateDetail = {
  full_name?: string;
  name?: string;
  lastname?: string;
  legal_name?: string;
  nip?: string;
  regon?: string;
  business_address?: string;
  email?: string;
  phone?: string;
};

type JobDetail = {
  client_id?: number | null;
  description?: string | null;
  location?: string | null;
  client_name?: string | null;
};

type Lang = "pl" | "en";
type LookupStatus = "idle" | "loading" | "ok" | "none";

/** Jeden etap stawki w „Warunkach umowy" — kwota + „Obowiązuje od/do". */
type RateStageForm = { rate: string; from: string; to: string };

const MAX_RATE_STAGES = 6;

const emptyRateStage = (): RateStageForm => ({ rate: "", from: "", to: "" });

/** Stawka bywa ułamkowa wpisana po polsku (135,5) — przecinek→kropka. */
function parseRate(raw: string): number | null {
  const v = raw.trim();
  if (!v) return null;
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}


/** Smart-prefill „Opis projektu" z roli (gdy brak oferty z rekrutacji). */
function smartDescription(role: B2BRole, lang: Lang, clientName: string): string {
  const area = lang === "pl" ? role.area_label_pl : role.area_label_en;
  const scope = (lang === "pl" ? role.scope_pl : role.scope_en).slice(0, 3);
  const client = clientName.trim();
  if (lang === "en") {
    const lead = `The Partner provides services in the area of ${area}${
      client ? ` for the Client ${client}` : ""
    }.`;
    return scope.length
      ? `${lead} The scope includes, among others: ${scope.join("; ")}.`
      : lead;
  }
  const lead = `Partner świadczy usługi w obszarze: ${area}${
    client ? ` na rzecz Klienta ${client}` : ""
  }.`;
  return scope.length
    ? `${lead} Zakres obejmuje m.in.: ${scope.join("; ")}.`
    : lead;
}

/**
 * Gotowy opis §1 do smart-prefillu z wybranego OBSZARU (roli), albo `null`, gdy
 * pola nie należy nadpisywać. Reguła: nadpisujemy tylko dopóki opis nie został
 * „dotknięty" — tzn. ani nie pochodzi z wybranej oferty, ani nie edytowano go
 * ręcznie (`descTouched`). Wybór oferty sam w sobie NIE blokuje
 * autouzupełnienia: gdy oferta nie miała opisu, wybór obszaru i tak wypełnia
 * pole gotowym opisem. Wcześniej warunek na wybranej ofercie zostawiał pole
 * puste (bug: „po wybraniu obszaru usług opis się nie uzupełnia").
 */
export function areaPrefillDescription(params: {
  role: B2BRole | null;
  language: Lang;
  clientName: string;
  descTouched: boolean;
}): string | null {
  const { role, language, clientName, descTouched } = params;
  if (!role || descTouched) return null;
  return smartDescription(role, language, clientName);
}

/** Klienci z niestandardowymi zapisami umowy — zwraca true gdy wybrany klient
 * wymaga modyfikacji. Musi być zgodne z backendem
 * (clause_override_content.CLIENT_OVERRIDES). PL i EN. */
export function hasSpecialClauses(clientName: string): boolean {
  const n = clientName.trim().toLowerCase();
  // „BNP Paribas Cardif" to odrębny Klient (ubezpieczyciel), nie Bank BNP
  // Paribas Polska — zwykły szablon. Sprawdzane PRZED „bnp paribas", spójnie
  // z kolejnością wpisów w CLIENT_OVERRIDES.
  if (n.includes("bnp paribas cardif") || n.includes("bnp cardif")) return false;
  return (
    n.includes("pfron") ||
    n.includes("rehabilitacji osób niepełnosprawnych") ||
    n.includes("e-zdrowia") ||
    n.includes("bnp paribas") ||
    n.includes("credit agricole") ||
    n.includes("biuro informacji kredytowej") ||
    n.includes("bik") ||
    n.includes("alior")
  );
}

export type GeneratedContractMemo = {
  key: string | null;
  contractId: number | null;
  pending: Promise<number> | null;
};

export function reuseOrGenerateContractId({
  key,
  memo,
  generate,
}: {
  key: string;
  memo: GeneratedContractMemo;
  generate: (contractId: number | null) => Promise<{ contract_id: number }>;
}): Promise<number> {
  if (memo.key === key && memo.pending) return memo.pending;

  if (memo.key !== key) {
    memo.key = key;
    memo.contractId = null;
  }
  const currentContractId = memo.contractId;
  const pending = generate(currentContractId)
    .then((generated) => {
      if (memo.key === key && memo.pending === pending) {
        memo.contractId = generated.contract_id;
      }
      return generated.contract_id;
    })
    .finally(() => {
      if (memo.key === key && memo.pending === pending) {
        memo.pending = null;
      }
    });
  memo.pending = pending;
  return pending;
}

/** Heurystyczna odmiana imienia i nazwiska do narzędnika („z Panem Janem
 * Kowalskim"). Best-effort — przy nietypowych/obcych nazwiskach pole jest
 * edytowalne. */
function titleCase(w: string): string {
  return w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w;
}

function declineInstrumentalToken(raw: string, gender: "m" | "k"): string {
  const w = titleCase(raw);
  const lw = w.toLowerCase();
  const cut = (n: number, suf: string) => w.slice(0, w.length - n) + suf;
  if (gender === "k") {
    if (lw.endsWith("ska") || lw.endsWith("cka") || lw.endsWith("dzka"))
      return cut(1, "ą");
    if (lw.endsWith("a")) return cut(1, "ą");
    return w; // nazwisko żeńskie zakończone spółgłoską — nieodmienne
  }
  if (lw.endsWith("ski") || lw.endsWith("cki") || lw.endsWith("dzki"))
    return cut(1, "im");
  if (lw.endsWith("y")) return cut(1, "ym");
  if (lw.endsWith("ek")) return cut(2, "kiem");
  if (lw.endsWith("eł")) return cut(2, "łem");
  if (lw.endsWith("k") || lw.endsWith("g")) return w + "iem";
  if (lw.endsWith("a")) return cut(1, "ą");
  if (
    lw.endsWith("o") ||
    lw.endsWith("i") ||
    lw.endsWith("e") ||
    lw.endsWith("u")
  )
    return w; // nieoczywiste zakończenie → zostaw (sprawdź ręcznie)
  return w + "em"; // typowa spółgłoska twarda
}

function instrumentalPl(fullName: string, gender: "m" | "k"): string {
  const tokens = (fullName || "").trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  return tokens.map((t) => declineInstrumentalToken(t, gender)).join(" ");
}

function printHtml(bodyHtml: string, title: string) {
  const w = window.open("", "_blank", "width=820,height=1000");
  if (!w) return;
  w.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>` +
      "<style>body{font-family:Helvetica,Arial,sans-serif;max-width:780px;margin:24px auto;" +
      "line-height:1.55;color:#222;padding:0 20px}h1,h2,h3{color:#111}" +
      // §nagłówek nie zostaje sam na końcu strony (#4)
      "h1,h2,h3{break-after:avoid;page-break-after:avoid;break-inside:avoid}" +
      "table{border-collapse:collapse;width:100%;margin:1em 0}" +
      "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}" +
      "@media print{body{margin:0;padding:0}}</style>" +
      "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300))</script>" +
      `</head><body>${bodyHtml}</body></html>`,
  );
  w.document.close();
}

const PREVIEW_STYLE =
  "body{font-family:Helvetica,Arial,sans-serif;margin:18px;line-height:1.5;color:#222;font-size:13px}" +
  "h1{font-size:18px}h2{font-size:15px;margin-top:1.4em}h3{font-size:13px}" +
  "h1,h2,h3{break-after:avoid;page-break-after:avoid;break-inside:avoid}" +
  "table{border-collapse:collapse;width:100%;margin:1em 0}" +
  "th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}";

// Prefiksy telefoniczne do wyboru przed numerem (#2). +48 domyślnie.
const PHONE_PREFIXES = [
  "+48",
  "+44",
  "+49",
  "+380",
  "+375",
  "+1",
  "+33",
  "+39",
  "+34",
  "+31",
  "+420",
  "+421",
  "+370",
  "+371",
  "+372",
];

export function B2BContractGeneratorV2() {
  const { user } = useAuthStore();
  const isAdmin = hasRole(user, "admin");

  return (
    // max-w-7xl (nie 4xl): zakładka „Wygenerowane umowy" ma szeroką tabelę
    // (9 kolumn + akcje: status podpisu / status umowy / Edytuj / Pobierz /
    // Usuń). Przy 4xl kolumna akcji wychodziła poza wąski kontener i „Usuń"
    // było ucięte poza ekranem — użytkownik nie widział opcji usunięcia.
    // Kolumna „Status umowy" (PR: status + wyszukiwarka) dołożyła szerokości,
    // stąd 6xl → 7xl. Szerszy kontener mieści wszystkie akcje w widocznym
    // obszarze.
    <div className="mx-auto max-w-7xl p-6">
      <div className="mb-6 flex items-center gap-3">
        <FileSignature className="h-7 w-7 text-primary" />
        <div>
          <h1 className="text-2xl font-semibold">Generator Umów B2B</h1>
          <p className="text-sm text-muted-foreground">
            Wpisz dane ręcznie lub zaciągnij z kandydata/rekrutacji, wybierz rolę
            z gotowym zakresem usług → pobierz DOCX / PDF.
          </p>
        </div>
      </div>

      <Tabs defaultValue="generator">
        <TabsList className="mb-4">
          <TabsTrigger value="generator">Generator</TabsTrigger>
          <TabsTrigger value="generated">Wygenerowane umowy</TabsTrigger>
          {isAdmin ? (
            <TabsTrigger value="roles">Zakresy ról (admin)</TabsTrigger>
          ) : null}
        </TabsList>
        {/* forceMount: nie odmontowuj formularza przy przejściu na inną
            zakładkę — inaczej wpisane dane znikają (zgłoszone przez Artura). */}
        <TabsContent
          value="generator"
          forceMount
          className="data-[state=inactive]:hidden"
        >
          <GeneratorForm />
        </TabsContent>
        <TabsContent value="generated">
          <GeneratedContractsTab />
        </TabsContent>
        {isAdmin ? (
          <TabsContent value="roles">
            <RoleScopeEditor />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

// ── Zakładka: wygenerowane umowy (numery) ───────────────────────────────────

function ConfirmFullySignedDialog({
  row,
  open,
  onOpenChange,
  onConfirmed,
}: {
  row: B2BGeneratedContractRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirmed: (result: B2BConfirmFullySignedResult) => void;
}) {
  const toast = useToast();
  const router = useRouter();
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState("");
  const [submitError, setSubmitError] = useState<ContractConflict | null>(null);

  useEffect(() => {
    if (!open) return;
    setCandidate(null);
    setCandidateOpen(false);
    setCandidateQuery("");
    setStageId("");
    setSubmitError(null);
  }, [open, row.id]);

  const effectiveCandidateId = row.candidate_id ?? candidate?.id ?? null;

  const candidatesQuery = useQuery({
    queryKey: ["b2b-signature-candidates", candidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: candidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: open && !row.candidate_id && candidateOpen,
    staleTime: 30_000,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["b2b-signature-recruitments", effectiveCandidateId],
    queryFn: async () => {
      if (!effectiveCandidateId) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${effectiveCandidateId}/recruitments`,
      );
      return res.data;
    },
    enabled: open && !!effectiveCandidateId && !row.job_id,
    staleTime: 30_000,
  });

  const selectedRecruitment = useMemo(
    () =>
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ??
      null,
    [recruitmentsQuery.data, stageId],
  );
  const effectiveJobId = row.job_id ?? selectedRecruitment?.job_id ?? null;

  const linkedCandidateQuery = useQuery({
    queryKey: ["b2b-signature-candidate", row.candidate_id],
    queryFn: async () => {
      if (!row.candidate_id) return null;
      const res = await api.get<CandidateDetail>(
        `/api/candidates/${row.candidate_id}`,
      );
      return res.data;
    },
    enabled: open && !!row.candidate_id && !row.candidate_name,
    staleTime: 300_000,
  });

  const jobQuery = useQuery({
    queryKey: ["b2b-signature-job", effectiveJobId],
    queryFn: async () => {
      if (!effectiveJobId) return null;
      const res = await api.get<JobDetail & { title?: string | null }>(
        `/api/jobs/${effectiveJobId}`,
      );
      return res.data;
    },
    enabled: open && !!effectiveJobId,
    staleTime: 300_000,
  });

  const confirmMut = useMutation({
    onMutate: () => setSubmitError(null),
    mutationFn: () => {
      if (!effectiveCandidateId || !effectiveJobId) {
        throw new Error("Wybierz kandydata i konkretną rekrutację.");
      }
      return b2bGeneratorApi.confirmFullySigned(row.id, {
        candidate_id: effectiveCandidateId,
        job_id: effectiveJobId,
      });
    },
    onSuccess: (result) => {
      onConfirmed(result);
      onOpenChange(false);
    },
    onError: (error) => {
      const conflict = getContractConflict(error);
      const normalized = conflict ?? {
        message: extractErrorMsg(error),
        contractIds: [],
      };
      setSubmitError(normalized);
      if (normalized.contractIds.length > 0) {
        toast.showActionToast(normalized.message, {
          actionLabel:
            normalized.contractIds.length === 1
              ? "Otwórz kontrakt"
              : "Otwórz pierwszy kontrakt",
          onAction: () =>
            router.push(`/contracts/${normalized.contractIds[0]}`),
          durationMs: 10_000,
        });
      } else {
        toast.showError(normalized.message);
      }
    },
  });

  const candidateLabel =
    row.candidate_name ??
    linkedCandidateQuery.data?.full_name ??
    candidate?.full_name ??
    row.partner_name ??
    "—";
  const recruitmentLabel =
    row.job_title ??
    selectedRecruitment?.job_title ??
    jobQuery.data?.title ??
    "—";
  const canonicalClient =
    jobQuery.data?.client_name ?? row.canonical_client_name ?? "—";
  const canonicalClientMismatch =
    row.client_id !== null &&
    jobQuery.data?.client_id != null &&
    row.client_id !== jobQuery.data.client_id;
  const canConfirm =
    !!effectiveCandidateId &&
    !!effectiveJobId &&
    jobQuery.isSuccess &&
    !canonicalClientMismatch &&
    !confirmMut.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!confirmMut.isPending) onOpenChange(next);
      }}
    >
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Potwierdź podpisanie umowy</DialogTitle>
          <DialogDescription>
            Umowa {row.contract_number} zostanie oznaczona jako podpisana przez
            obie strony. To jednokierunkowa, audytowana deklaracja.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4">
          {!row.candidate_id ? (
            <div>
              <Label className="mb-1.5 block">Kandydat</Label>
              <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-expanded={candidateOpen}
                    className="w-full justify-between font-normal"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {candidate?.full_name ?? "Wybierz kandydata…"}
                      </span>
                    </span>
                    <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  className="w-(--radix-popover-trigger-width) p-0"
                >
                  <Command shouldFilter={false}>
                    <CommandInput
                      placeholder="Szukaj kandydata…"
                      value={candidateQuery}
                      onValueChange={setCandidateQuery}
                    />
                    <CommandList>
                      {candidatesQuery.isLoading ? (
                        <div className="p-3 text-sm text-muted-foreground">
                          Szukam…
                        </div>
                      ) : (
                        <CommandEmpty>Brak wyników.</CommandEmpty>
                      )}
                      <CommandGroup>
                        {(candidatesQuery.data ?? []).map((item) => (
                          <CommandItem
                            key={item.id}
                            value={String(item.id)}
                            onSelect={() => {
                              setCandidate(item);
                              setStageId("");
                              setCandidateOpen(false);
                            }}
                          >
                            <Check
                              className={cn(
                                "mr-2 h-4 w-4",
                                candidate?.id === item.id
                                  ? "opacity-100"
                                  : "opacity-0",
                              )}
                            />
                            <span className="truncate">
                              {item.full_name}
                              {item.email ? (
                                <span className="ml-1 text-xs text-muted-foreground">
                                  {item.email}
                                </span>
                              ) : null}
                            </span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
          ) : null}

          {!row.job_id ? (
            <div>
              <Label className="mb-1.5 block">Rekrutacja</Label>
              <Select
                value={stageId}
                onValueChange={setStageId}
                disabled={!effectiveCandidateId || recruitmentsQuery.isLoading}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      effectiveCandidateId
                        ? "Wybierz konkretną rekrutację…"
                        : "Najpierw wybierz kandydata"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {(recruitmentsQuery.data ?? []).map((item) => (
                    <SelectItem
                      key={item.stage_id}
                      value={String(item.stage_id)}
                    >
                      {item.job_title} · {item.stage}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {effectiveCandidateId &&
              !recruitmentsQuery.isLoading &&
              (recruitmentsQuery.data?.length ?? 0) === 0 ? (
                <p className="mt-1.5 text-xs text-destructive">
                  Kandydat nie ma rekrutacji, którą można powiązać z umową.
                </p>
              ) : null}
            </div>
          ) : null}

          <dl className="grid gap-3 rounded-lg border border-border bg-muted/40 p-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs font-medium text-muted-foreground">
                Kandydat
              </dt>
              <dd className="mt-1 text-sm font-medium text-foreground">
                {candidateLabel}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted-foreground">
                Rekrutacja
              </dt>
              <dd className="mt-1 text-sm font-medium text-foreground">
                {recruitmentLabel}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted-foreground">
                Klient kanoniczny
              </dt>
              <dd className="mt-1 text-sm font-medium text-foreground">
                {jobQuery.isLoading
                  ? "Ładowanie…"
                  : jobQuery.isError
                    ? "Nie udało się pobrać"
                    : canonicalClient}
              </dd>
            </div>
          </dl>

          {jobQuery.isError || canonicalClientMismatch ? (
            <Alert
              variant="error"
              title="Nie można potwierdzić klienta"
              description={
                canonicalClientMismatch
                  ? "Klient zapisany przy umowie nie odpowiada aktualnemu klientowi rekrutacji. Otwórz rekord i wyjaśnij powiązanie."
                  : "Nie udało się pobrać aktualnych danych rekrutacji. Odśwież widok i spróbuj ponownie."
              }
            />
          ) : null}

          <Alert
            variant="warning"
            title="To nie jest walidacja podpisu elektronicznego"
            description="Potwierdzenie zapisze autora i czas deklaracji, ale nie utworzy pliku podpisanej umowy ani wpisu QES."
          />

          {submitError ? (
            <Alert variant="error" title="Nie można zakończyć automatyzacji">
              <p className="mt-0.5 text-xs opacity-90">{submitError.message}</p>
              {submitError.contractIds.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {submitError.contractIds.map((contractId) => (
                    <Link
                      key={contractId}
                      href={`/contracts/${contractId}`}
                      className="inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-2"
                    >
                      Kontrakt #{contractId}
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  ))}
                </div>
              ) : null}
            </Alert>
          ) : null}

          <div className="rounded-lg border border-border p-4">
            <p className="text-sm font-medium text-foreground">
              System wykona atomowo:
            </p>
            <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
              <li>• utworzy albo powiąże istniejącego kontraktora,</li>
              <li>• zapewni szkic zamówienia klienta,</li>
              <li>• ustawi etap kandydata na „Zatrudniony”,</li>
              <li>• zapisze pełny ślad audytowy.</li>
            </ul>
          </div>
        </DialogBody>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={confirmMut.isPending}
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!canConfirm}
            onClick={() => confirmMut.mutate()}
          >
            {confirmMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Potwierdź podpisanie
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Etykiety PL dla statusu handlowego umowy. Trzymane w warstwie prezentacji
// (nie w `lib/api`), bo to teksty UI, a nie kontrakt z backendem — i dzięki
// temu testy mockujące `@/lib/api` nadal dostają prawdziwe napisy.
export const B2B_CONTRACT_STATUS_LABEL: Record<B2BContractStatus, string> = {
  active: "Aktywna",
  in_progress: "W trakcie",
  closed: "Zamknięta",
};

/**
 * Warianty badge'a statusu umowy.
 *
 * „Zamknięta" przeszła z `warning` (pomarańcz) na `neutral` (szary), żeby
 * zwolnić pomarańcz dla „W trakcie". Nie jest to tylko przetasowanie kolorów:
 * stan terminalny nie jest ostrzeżeniem, a umowa w drodze do podpisu wymaga
 * uwagi. Dwa pomarańczowe statusy obok siebie byłyby nierozróżnialne.
 */
export const B2B_CONTRACT_STATUS_VARIANT: Record<
  B2BContractStatus,
  "info" | "warning" | "neutral"
> = {
  active: "info",
  in_progress: "warning",
  closed: "neutral",
};

/**
 * Filtr zakresu daty rozpoczęcia usług — ikona kalendarza w nagłówku kolumny.
 *
 * Trzy tryby z ticketu sprowadzają się do JEDNEJ pary granic, bo tak wygląda
 * kontrakt z backendem (`start_from`/`start_to`, obie włącznie): „cały miesiąc"
 * to pierwszy i ostatni dzień, „konkretny dzień" to ta sama data w obu polach.
 * Osobne tryby w stanie byłyby trzema reprezentacjami tego samego.
 *
 * Natywne `<input type="date">`, NIE biblioteka kalendarza: w repo nie ma
 * żadnego pickera zakresu, a `react-day-picker` byłby tu jedyną taką
 * zależnością. Konwencja repo (`StageFilterPanel`, `ClientContractRegister`) to
 * para inputów ze skrzyżowanymi `min`/`max` — i ta krzyżowa walidacja jest
 * potrzebna, bo odwrócony zakres backend odrzuca 422.
 *
 * `Popover`, nie `DropdownMenu`: menu Radiksa przechwytuje strzałki i zamyka się
 * na kliknięcie pozycji, co walczy z polem daty. Do tego `PopoverContent`
 * renderuje w portalu, więc panel nie jest obcinany przez `overflow-x-auto`
 * tabeli.
 */
function StartDateRangeFilter({
  from,
  to,
  onChange,
}: {
  from: string;
  to: string;
  onChange: (next: { from: string; to: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = Boolean(from || to);
  // Miesiąc jako `YYYY-MM` — `type="month"` daje natywny wybór miesiąca,
  // a granice liczymy z `Date`, żeby nie zgadywać długości lutego.
  const [month, setMonth] = useState("");

  const applyMonth = (value: string) => {
    setMonth(value);
    if (!value) return;
    const [y, m] = value.split("-").map(Number);
    if (!y || !m) return;
    const pad = (n: number) => String(n).padStart(2, "0");
    // Dzień 0 następnego miesiąca = ostatni dzień wybranego.
    const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    onChange({ from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last)}` });
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Filtruj po dacie rozpoczęcia"
          aria-expanded={open}
          title="Filtruj po dacie rozpoczęcia"
          className={cn(
            "rounded p-0.5 transition-colors",
            active
              ? "text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Calendar className="h-3.5 w-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 space-y-3">
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">Zakres dat</p>
          <div className="flex items-center gap-2">
            <Input
              type="date"
              aria-label="Data rozpoczęcia — od"
              value={from}
              max={to || undefined}
              onChange={(e) => {
                setMonth("");
                onChange({ from: e.target.value, to });
              }}
              className="h-8 text-xs"
            />
            <span className="text-xs text-muted-foreground" aria-hidden>
              –
            </span>
            <Input
              type="date"
              aria-label="Data rozpoczęcia — do"
              value={to}
              min={from || undefined}
              onChange={(e) => {
                setMonth("");
                onChange({ from, to: e.target.value });
              }}
              className="h-8 text-xs"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            Cały miesiąc
          </p>
          <Input
            type="month"
            aria-label="Data rozpoczęcia — cały miesiąc"
            value={month}
            onChange={(e) => applyMonth(e.target.value)}
            className="h-8 text-xs"
          />
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            Konkretny dzień
          </p>
          <Input
            type="date"
            aria-label="Data rozpoczęcia — konkretny dzień"
            value={from && from === to ? from : ""}
            onChange={(e) => {
              setMonth("");
              onChange({ from: e.target.value, to: e.target.value });
            }}
            className="h-8 text-xs"
          />
        </div>

        <div className="flex justify-end gap-2 border-t pt-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!active}
            onClick={() => {
              setMonth("");
              onChange({ from: "", to: "" });
            }}
          >
            Wyczyść
          </Button>
          <Button type="button" size="sm" onClick={() => setOpen(false)}>
            Zamknij
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export const B2B_CLOSURE_REASON_LABEL: Record<B2BClosureReason, string> = {
  resignation_before_signing: "Rezygnacja przed podpisaniem umowy",
  termination: "Wypowiedzenie",
  mutual_agreement: "Porozumienie o rozwiązaniu umowy",
  other: "Inne",
};

// Kolejność w liście rozwijanej „Powód zamknięcia umowy" — jak w zgłoszeniu.
const CLOSURE_REASONS: B2BClosureReason[] = [
  "resignation_before_signing",
  "termination",
  "mutual_agreement",
  "other",
];

/**
 * Zmiana statusu handlowego umowy. Zamknięcie NIE usuwa wpisu — dopisuje mu
 * powód i datę zakończenia, więc umowa zostaje w rejestrze.
 *
 * Dialog (nie edycja „w miejscu" jak nazwa Klienta), bo „Zamknięta" odsłania
 * trzy zależne pola, których nie da się sensownie zmieścić w komórce tabeli.
 */
export function ContractStatusDialog({
  row,
  open,
  onOpenChange,
}: {
  row: B2BGeneratedContractRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<B2BContractStatus>(row.contract_status);
  const [reason, setReason] = useState<B2BClosureReason | "">(
    row.closure_reason ?? "",
  );
  const [reasonOther, setReasonOther] = useState(row.closure_reason_other ?? "");
  const [closureDate, setClosureDate] = useState(row.closure_date ?? "");

  // Ponowne otwarcie dialogu na tym samym wierszu ma pokazać stan z serwera,
  // a nie porzucony szkic z poprzedniej, anulowanej próby.
  useEffect(() => {
    if (!open) return;
    setStatus(row.contract_status);
    setReason(row.closure_reason ?? "");
    setReasonOther(row.closure_reason_other ?? "");
    setClosureDate(row.closure_date ?? "");
  }, [open, row]);

  const mut = useMutation({
    mutationFn: (body: B2BGeneratedContractUpdate) =>
      b2bGeneratorApi.updateGenerated(row.id, body),
    onSuccess: (updated) => {
      toast.showSuccess(
        updated.contract_status === "closed"
          ? "Umowa oznaczona jako zamknięta — wpis pozostaje na liście."
          : "Umowa oznaczona jako aktywna.",
      );
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      onOpenChange(false);
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const closing = status === "closed";
  const submit = () => {
    if (!closing) {
      mut.mutate({ contract_status: "active" });
      return;
    }
    // Te same reguły egzekwuje backend (422) i CHECK w bazie — tu tylko po to,
    // żeby użytkownik zobaczył powód od razu, bez round-tripu.
    if (!reason) {
      toast.showError("Wybierz powód zamknięcia umowy.");
      return;
    }
    if (reason === "other" && !reasonOther.trim()) {
      toast.showError("Wpisz własny powód zamknięcia umowy.");
      return;
    }
    if (!closureDate) {
      toast.showError("Podaj datę zakończenia umowy.");
      return;
    }
    mut.mutate({
      contract_status: "closed",
      closure_reason: reason,
      closure_reason_other: reason === "other" ? reasonOther.trim() : null,
      closure_date: closureDate,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Status umowy {row.contract_number}</DialogTitle>
          <DialogDescription>
            Zamknięcie umowy nie usuwa jej z systemu — wpis zostaje na liście
            wraz z powodem i datą zakończenia.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="b2b-contract-status">Status umowy</Label>
            <Select
              value={status}
              onValueChange={(v) => setStatus(v as B2BContractStatus)}
            >
              <SelectTrigger id="b2b-contract-status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">
                  {B2B_CONTRACT_STATUS_LABEL.active}
                </SelectItem>
                {/* „W trakcie" MUSI być na liście, ale wyszarzone. Widoczne,
                    bo bez tej pozycji Radix wyrenderowałby pusty trigger dla
                    umowy, która właśnie w tym stanie jest. Niewybieralne, bo
                    ten status ustawia wyłącznie system — backend odrzuca
                    ręczny wybór 422, a `disabled` domyka regułę po stronie UI,
                    zamiast pozwolić użytkownikowi trafić na błąd. */}
                <SelectItem value="in_progress" disabled>
                  {B2B_CONTRACT_STATUS_LABEL.in_progress}
                </SelectItem>
                <SelectItem value="closed">
                  {B2B_CONTRACT_STATUS_LABEL.closed}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {closing ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="b2b-closure-reason">
                  Powód zamknięcia umowy
                </Label>
                <Select
                  value={reason}
                  onValueChange={(v) => setReason(v as B2BClosureReason)}
                >
                  <SelectTrigger id="b2b-closure-reason">
                    <SelectValue placeholder="Wybierz powód…" />
                  </SelectTrigger>
                  <SelectContent>
                    {CLOSURE_REASONS.map((key) => (
                      <SelectItem key={key} value={key}>
                        {B2B_CLOSURE_REASON_LABEL[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {reason === "other" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="b2b-closure-reason-other">Własny powód</Label>
                  <Textarea
                    id="b2b-closure-reason-other"
                    rows={3}
                    value={reasonOther}
                    onChange={(e) => setReasonOther(e.target.value)}
                    placeholder="Opisz powód zamknięcia umowy"
                  />
                </div>
              ) : null}

              <div className="space-y-1.5">
                <Label htmlFor="b2b-closure-date">Data zakończenia umowy</Label>
                {/* type="date" = wpisanie z klawiatury ORAZ natywny kalendarz. */}
                <Input
                  id="b2b-closure-date"
                  type="date"
                  value={closureDate}
                  onChange={(e) => setClosureDate(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Pole obowiązkowe dla statusu „Zamknięta".
                </p>
              </div>
            </>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            disabled={mut.isPending}
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button type="button" disabled={mut.isPending} onClick={submit}>
            {mut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Zapisz status
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function GeneratedContractsTab() {
  const toast = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [signatureRow, setSignatureRow] =
    useState<B2BGeneratedContractRow | null>(null);
  const [statusRow, setStatusRow] = useState<B2BGeneratedContractRow | null>(
    null,
  );
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<B2BContractStatus | "all">(
    "all",
  );
  // Zakres daty ROZPOCZĘCIA USŁUG. Trzy tryby panelu (zakres / cały miesiąc /
  // konkretny dzień) sprowadzają się do jednej pary granic: miesiąc to pierwszy
  // i ostatni dzień, dzień to ta sama data w obu polach. `""` = brak granicy.
  const [startFrom, setStartFrom] = useState("");
  const [startTo, setStartTo] = useState("");
  const dateFilterActive = Boolean(startFrom || startTo);
  // Debounce, żeby nie strzelać zapytaniem na każdą literę wpisaną w szukajkę.
  const debouncedSearch = useDebouncedValue(search, 300);
  const q = useQuery({
    // Filtr daty MUSI być w kluczu — bez tego react-query oddaje wynik
    // poprzedniego zakresu z cache i zmiana granic „nic nie robi".
    queryKey: ["b2b-generated", debouncedSearch, statusFilter, startFrom, startTo],
    queryFn: () =>
      b2bGeneratorApi.generated(100, {
        q: debouncedSearch,
        contractStatus: statusFilter === "all" ? undefined : statusFilter,
        startFrom: startFrom || undefined,
        startTo: startTo || undefined,
      }),
    staleTime: 10_000,
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => b2bGeneratorApi.deleteGenerated(id),
    onSuccess: () => {
      toast.showSuccess("Umowa usunięta — numer zwolniony do ponownego użycia.");
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      // Numeracja to max(numer)+1 liczone na żywo z listy → skasowanie
      // najnowszej umowy zwalnia jej numer. Odśwież podpowiedź „następny wolny
      // numer" w generatorze, by od razu cofnęła się do zwolnionego numeru.
      queryClient.invalidateQueries({ queryKey: ["b2b-next-number"] });
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });
  const downloadMut = useMutation({
    mutationFn: async (r: B2BGeneratedContractRow) => {
      const res = await b2bGeneratorApi.downloadGenerated(r.id);
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa B2B ${r.contract_number.replaceAll("/", "-")}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });
  // Edycja nazwy Klienta „w miejscu" — poprawa literówki bez ponownej generacji.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editClientName, setEditClientName] = useState("");
  const updateMut = useMutation({
    mutationFn: ({ id, client_name }: { id: number; client_name: string }) =>
      b2bGeneratorApi.updateGenerated(id, { client_name }),
    onSuccess: () => {
      toast.showSuccess("Nazwa Klienta zaktualizowana.");
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });
  const rows = q.data ?? [];

  const handleConfirmed = (result: B2BConfirmFullySignedResult) => {
    const fallbackMessage =
      result.outcome === "created"
        ? "Umowa podpisana — utworzono szkic kontraktora."
        : result.outcome === "linked_existing"
          ? "Umowa podpisana — powiązano istniejącego kontraktora bez duplikatu."
          : "Umowa była już przetworzona — nie utworzono duplikatu.";
    toast.showActionToast(result.message || fallbackMessage, {
      actionLabel: "Otwórz kontraktora",
      onAction: () => router.push(`/contracts/${result.contract_id}`),
      durationMs: 10_000,
    });
    queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
    queryClient.invalidateQueries({ queryKey: ["candidate", result.candidate_id] });
    queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
    queryClient.invalidateQueries({ queryKey: ["candidate-pipelines"] });
  };

  const startEdit = (r: B2BGeneratedContractRow) => {
    if (r.signature_status === "signed_both") return;
    setEditingId(r.id);
    setEditClientName(r.client_name ?? "");
  };
  const saveEdit = (id: number) => {
    const name = editClientName.trim();
    if (!name) {
      toast.showError("Podaj nazwę Klienta.");
      return;
    }
    updateMut.mutate({ id, client_name: name });
  };

  const confirmDelete = (r: B2BGeneratedContractRow) => {
    const label = r.partner_name
      ? `${r.contract_number} — ${r.partner_name}`
      : r.contract_number;
    if (
      window.confirm(
        `Usunąć umowę „${label}” z listy? Tej operacji nie można cofnąć.`,
      )
    ) {
      deleteMut.mutate(r.id);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Wygenerowane umowy</CardTitle>
        <CardDescription>
          Numery dotąd wygenerowanych umów — sprawdź, czy sugerowany / wpisany
          numer nie powtarza istniejącego. Umowę można pobrać ponownie, a nazwę
          Klienta poprawić („Edytuj"). Status podpisu jest widoczny w tabeli;
          potwierdzenie podpisania uruchamia jednorazowo proces zatrudnienia.
          Niepodpisany wpis może edytować lub usunąć osoba, która go
          wygenerowała, albo administrator. Zamknięcie umowy („Status umowy")
          nie usuwa jej z listy.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isForbidden(q.error) ? null : (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[18rem] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
                placeholder="Szukaj: numer umowy albo imię i nazwisko…"
                aria-label="Szukaj wygenerowanych umów"
              />
            </div>
            <Select
              value={statusFilter}
              onValueChange={(v) =>
                setStatusFilter(v as B2BContractStatus | "all")
              }
            >
              <SelectTrigger className="w-56" aria-label="Filtr statusu umowy">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Wszystkie statusy</SelectItem>
                <SelectItem value="in_progress">
                  {B2B_CONTRACT_STATUS_LABEL.in_progress}
                </SelectItem>
                <SelectItem value="active">
                  {B2B_CONTRACT_STATUS_LABEL.active}
                </SelectItem>
                <SelectItem value="closed">
                  {B2B_CONTRACT_STATUS_LABEL.closed}
                </SelectItem>
              </SelectContent>
            </Select>
            {dateFilterActive ? (
              <button
                type="button"
                onClick={() => {
                  setStartFrom("");
                  setStartTo("");
                }}
                className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary hover:bg-primary hover:text-primary-foreground"
                aria-label="Wyczyść filtr daty rozpoczęcia"
              >
                Data rozpoczęcia: {startFrom || "…"} – {startTo || "…"}
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        )}
        {q.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : isForbidden(q.error) ? (
          <Alert
            variant="warning"
            title={NO_ACCESS_TITLE}
            description={NO_ACCESS_DESC}
          />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {/* Pustka po wyszukaniu ≠ brak umów w systemie — inaczej czyta się
                to jak utratę danych (ten sam błąd co przy 403 wyżej).
                Filtr daty MUSI być w tym warunku: bez niego odfiltrowana lista
                twierdziłaby „Brak wygenerowanych umów", czyli awaria
                wyrenderowałaby się jako utrata danych. */}
            {debouncedSearch.trim() || statusFilter !== "all" || dateFilterActive
              ? "Brak umów pasujących do wyszukiwania."
              : "Brak wygenerowanych umów."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            {/* `text-xs`, nie `text-sm`: przy 10 kolumnach rejestr nie mieści
                się na typowej szerokości i tabela uciekała w poziomy scroll. */}
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Numer</th>
                  <th className="py-2 pr-4 font-medium">Partner</th>
                  <th className="py-2 pr-4 font-medium">NIP</th>
                  <th className="py-2 pr-4 font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      Data rozpoczęcia
                      <StartDateRangeFilter
                        from={startFrom}
                        to={startTo}
                        onChange={(next) => {
                          setStartFrom(next.from);
                          setStartTo(next.to);
                        }}
                      />
                    </span>
                  </th>
                  <th className="py-2 pr-4 font-medium">Klient</th>
                  <th className="py-2 pr-4 font-medium">Status umowy</th>
                  <th className="py-2 pr-4 font-medium">Status podpisu</th>
                  <th className="py-2 pr-4 font-medium">Wygenerował</th>
                  <th className="py-2 pr-4 font-medium">Wygenerowano</th>
                  <th className="py-2 text-right font-medium">Akcje</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const deleting =
                    deleteMut.isPending && deleteMut.variables === r.id;
                  const downloading =
                    downloadMut.isPending && downloadMut.variables?.id === r.id;
                  const editing = editingId === r.id;
                  const saving = updateMut.isPending && editing;
                  const signed = r.signature_status === "signed_both";
                  const closed = r.contract_status === "closed";
                  return (
                    <tr key={r.id} className="border-b">
                      <td className="py-2 pr-4 font-medium">
                        {r.contract_number}
                      </td>
                      {/* Kolumna „Partner": NAZWA FIRMY z rejestru, nie nazwisko.
                          Linie liczy backend — reguła rozpoznania JDG vs spółka i kasowania
                          duplikacji nazwiska zawartego już w nazwie firmy nie może istnieć
                          w dwóch kopiach, bo ta sama reguła decyduje o zapisie snapshotu.
                          `|| r.partner_name` to fallback na wypadek starszego backendu
                          (rollback jednej strony) — bez niego cała kolumna dałaby „—". */}
                      <td className="py-2 pr-4">
                        <div className="flex flex-col gap-0.5">
                          <span>{r.partner_display_name || r.partner_name || "—"}</span>
                          {r.partner_secondary_line ? (
                            <span className="text-xs text-muted-foreground">
                              {r.partner_secondary_line}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="py-2 pr-4 tabular-nums">{r.partner_nip || "—"}</td>
                      {/* Data ROZPOCZĘCIA USŁUG — surowe ISO, bez godziny (kontrast:
                          „Wygenerowano" niżej celowo pokazuje czas). */}
                      <td className="py-2 pr-4 tabular-nums">{r.start_date || "—"}</td>
                      <td className="py-2 pr-4">
                        {editing ? (
                          <Input
                            autoFocus
                            value={editClientName}
                            onChange={(e) => setEditClientName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                saveEdit(r.id);
                              } else if (e.key === "Escape") {
                                setEditingId(null);
                              }
                            }}
                            disabled={saving}
                            className="h-8 min-w-[16rem]"
                            placeholder="Pełna nazwa Klienta"
                          />
                        ) : (
                          r.client_name || "—"
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex min-w-44 flex-col items-start gap-1.5">
                          <Badge
                            variant={
                              B2B_CONTRACT_STATUS_VARIANT[r.contract_status]
                            }
                            size="md"
                            title={
                              closed
                                ? [
                                    r.closure_reason
                                      ? `Powód: ${
                                          r.closure_reason === "other"
                                            ? r.closure_reason_other || "Inne"
                                            : B2B_CLOSURE_REASON_LABEL[
                                                r.closure_reason
                                              ]
                                        }`
                                      : null,
                                    r.closure_date
                                      ? `Zakończenie: ${r.closure_date}`
                                      : null,
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                : r.contract_status === "in_progress"
                                  ? "Wygenerowana, czeka na podpis obu stron"
                                  : "Umowa podpisana i obowiązująca"
                            }
                          >
                            {closed ? (
                              <CircleSlash className="h-3.5 w-3.5" />
                            ) : r.contract_status === "in_progress" ? (
                              <CircleDashed className="h-3.5 w-3.5" />
                            ) : (
                              <CircleDot className="h-3.5 w-3.5" />
                            )}
                            {B2B_CONTRACT_STATUS_LABEL[r.contract_status]}
                          </Badge>

                          {closed ? (
                            <span className="max-w-56 text-xs text-muted-foreground">
                              {r.closure_reason === "other"
                                ? r.closure_reason_other
                                : r.closure_reason
                                  ? B2B_CLOSURE_REASON_LABEL[r.closure_reason]
                                  : null}
                              {r.closure_date ? ` · ${r.closure_date}` : ""}
                            </span>
                          ) : null}

                          {r.can_change_status ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2"
                              onClick={() => setStatusRow(r)}
                              title="Zmień status umowy"
                            >
                              <Pencil className="h-4 w-4" />
                              <span className="ml-1">Zmień status</span>
                            </Button>
                          ) : null}
                        </div>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex min-w-48 flex-col items-start gap-1.5">
                          <Badge
                            variant={signed ? "success" : "outline"}
                            size="md"
                            title={
                              signed
                                ? [
                                    r.signed_by_name
                                      ? `Potwierdził: ${r.signed_by_name}`
                                      : null,
                                    r.signed_at
                                      ? `Data: ${r.signed_at
                                          .slice(0, 16)
                                          .replace("T", " ")}`
                                      : null,
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                : "Umowa nie została oznaczona jako podpisana"
                            }
                          >
                            {signed ? (
                              <CheckCircle2 className="h-3.5 w-3.5" />
                            ) : (
                              <CircleDashed className="h-3.5 w-3.5" />
                            )}
                            {signed
                              ? "Podpisana obustronnie"
                              : "Niepodpisana"}
                          </Badge>

                          {signed ? (
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                              {r.candidate_id ? (
                                <Link
                                  href={`/candidates/${r.candidate_id}`}
                                  className="inline-flex items-center gap-1 text-primary hover:underline"
                                >
                                  Kandydat
                                  <ExternalLink className="h-3 w-3" />
                                </Link>
                              ) : null}
                              {r.contract_id ? (
                                <Link
                                  href={`/contracts/${r.contract_id}`}
                                  className="inline-flex items-center gap-1 text-primary hover:underline"
                                >
                                  Kontraktor
                                  <ExternalLink className="h-3 w-3" />
                                </Link>
                              ) : null}
                            </div>
                          ) : r.can_confirm_signed ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-8"
                              onClick={() => setSignatureRow(r)}
                            >
                              <FileSignature className="h-4 w-4" />
                              Oznacz jako podpisaną
                            </Button>
                          ) : r.blocked_reason ? (
                            <span className="max-w-60 text-xs text-muted-foreground">
                              {r.blocked_reason}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="py-2 pr-4">{r.created_by_name || "—"}</td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {r.created_at
                          ? r.created_at.slice(0, 16).replace("T", " ")
                          : "—"}
                      </td>
                      <td className="py-2 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {editing ? (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8"
                                disabled={saving}
                                onClick={() => saveEdit(r.id)}
                                title="Zapisz nazwę Klienta"
                              >
                                {saving ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Save className="h-4 w-4" />
                                )}
                                <span className="ml-1">Zapisz</span>
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8"
                                disabled={saving}
                                onClick={() => setEditingId(null)}
                                title="Anuluj edycję"
                              >
                                <X className="h-4 w-4" />
                                <span className="ml-1">Anuluj</span>
                              </Button>
                            </>
                          ) : (
                            <>
                              {!signed && r.can_edit ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8"
                                  onClick={() => startEdit(r)}
                                  title="Popraw nazwę Klienta"
                                >
                                  <Pencil className="h-4 w-4" />
                                  <span className="ml-1">Edytuj</span>
                                </Button>
                              ) : null}
                              {r.can_download ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8"
                                  disabled={downloading}
                                  onClick={() => downloadMut.mutate(r)}
                                  title="Pobierz DOCX ponownie"
                                >
                                  {downloading ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Download className="h-4 w-4" />
                                  )}
                                  <span className="ml-1">Pobierz</span>
                                </Button>
                              ) : null}
                              {!signed && r.can_delete ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 text-destructive hover:text-destructive"
                                  disabled={deleting}
                                  onClick={() => confirmDelete(r)}
                                  title="Usuń umowę z listy"
                                >
                                  {deleting ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-4 w-4" />
                                  )}
                                  <span className="ml-1">Usuń</span>
                                </Button>
                              ) : null}
                              {(!r.can_edit || signed) &&
                              !r.can_download &&
                              (!r.can_delete || signed) ? (
                                <span className="text-xs text-muted-foreground">
                                  —
                                </span>
                              ) : null}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
      {signatureRow ? (
        <ConfirmFullySignedDialog
          row={signatureRow}
          open
          onOpenChange={(open) => {
            if (!open) setSignatureRow(null);
          }}
          onConfirmed={handleConfirmed}
        />
      ) : null}
      {statusRow ? (
        <ContractStatusDialog
          row={statusRow}
          open
          onOpenChange={(open) => {
            if (!open) setStatusRow(null);
          }}
        />
      ) : null}
    </Card>
  );
}

// ── Generator form ──────────────────────────────────────────────────────────

function GeneratorForm() {
  const toast = useToast();

  const [language, setLanguage] = useState<Lang>("pl");

  // Źródło danych — wymagane powiązanie kandydata z rekrutacją.
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState<string>("");

  // Rola + zakres
  const [roleId, setRoleId] = useState<string>("");

  // Dane Partnera (firma)
  const [partnerName, setPartnerName] = useState("");
  const [partnerLegalName, setPartnerLegalName] = useState("");
  const [partnerNip, setPartnerNip] = useState("");
  const [partnerRegon, setPartnerRegon] = useState("");
  const [partnerBusinessAddress, setPartnerBusinessAddress] = useState("");
  const [partnerCorrespondenceAddress, setPartnerCorrespondenceAddress] =
    useState("");
  const [partnerEmail, setPartnerEmail] = useState("");
  const [partnerPhone, setPartnerPhone] = useState("");
  const [phonePrefix, setPhonePrefix] = useState("+48");

  // Klient + projekt
  const [clientName, setClientName] = useState("");
  const [clientOpen, setClientOpen] = useState(false);
  const [clientQuery, setClientQuery] = useState("");
  const [projectCity, setProjectCity] = useState("");
  const [projectDescription, setProjectDescription] = useState("");

  // Warunki
  const [contractNumber, setContractNumber] = useState("");
  const [signingDate, setSigningDate] = useState(todayISO());
  const [startDate, setStartDate] = useState(todayISO());
  const [startDateMode, setStartDateMode] = useState<
    "exact" | "not_earlier" | "not_later"
  >("exact");
  // Stawka godzinowa — jeden lub kilka etapów („stawka progresywna": kwota +
  // „Obowiązuje od/do"). Pierwszy wiersz to dotychczasowa pojedyncza stawka.
  const [rateStages, setRateStages] = useState<RateStageForm[]>([
    emptyRateStage(),
  ]);
  const [currency, setCurrency] = useState("PLN");

  const setRateStage = (index: number, patch: Partial<RateStageForm>) =>
    setRateStages((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  const addRateStage = () =>
    setRateStages((prev) =>
      prev.length >= MAX_RATE_STAGES ? prev : [...prev, emptyRateStage()],
    );
  const removeRateStage = (index: number) =>
    setRateStages((prev) =>
      prev.length > 1 ? prev.filter((_, i) => i !== index) : prev,
    );

  // AI-sprawdzenie opisu pod kątem znamion umowy o pracę (#3).
  const [uop, setUop] = useState<B2BUopCheckResult | null>(null);

  // Płeć Partnera — steruje formami gramatycznymi w umowie (Panem/ią,
  // prowadzącym/cą, zwany/a, zapoznałem/am).
  const [gender, setGender] = useState<"m" | "k">("m");
  // Imię i nazwisko w narzędniku do komparycji (auto-odmiana, edytowalne) (#7).
  const [partnerInstrumental, setPartnerInstrumental] = useState("");
  const [partnerLookup, setPartnerLookup] = useState<LookupStatus>("idle");
  // Typ podmiotu z rejestru (CEIDG → JDG, KRS → spółka). Nie jest polem
  // formularza — użytkownik go nie widzi ani nie edytuje; jedzie do backendu
  // jako podpowiedź, czy lista ma pokazywać drugą linię z osobą kontaktową.
  const [partnerEntityType, setPartnerEntityType] = useState<
    "sole_trader" | "company" | null
  >(null);

  const [previewHtml, setPreviewHtml] = useState<string>("");
  // Cache is keyed by candidate + recruitment and includes the in-flight
  // promise. This makes rapid double actions single-flight; after a remount
  // the backend's candidate row lock and pair-based lookup remain the durable
  // idempotency layer.
  const generatedContractMemo = useRef<GeneratedContractMemo>({
    key: null,
    contractId: null,
    pending: null,
  });

  // Pre-fill „raz na kandydata / ofertę" — nie nadpisuje ręcznych zmian.
  const prefilledCand = useRef<number | null>(null);
  const prefilledJob = useRef<number | null>(null);
  // Użytkownik ręcznie zmienił opis → nie nadpisuj smart-prefillem.
  const descTouched = useRef(false);
  // Użytkownik ręcznie poprawił narzędnik → nie nadpisuj auto-odmianą.
  const instrTouched = useRef(false);

  const candidatesQuery = useQuery({
    queryKey: ["b2b-gen-candidates", candidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: candidateQuery, limit: 20 },
      });
      return res.data;
    },
    enabled: candidateOpen,
    staleTime: 30_000,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["b2b-gen-recruitments", candidate?.id],
    queryFn: async () => {
      if (!candidate) return [] as RecruitmentOption[];
      const res = await api.get<RecruitmentOption[]>(
        `/api/cv-generator/candidates/${candidate.id}/recruitments`,
      );
      return res.data;
    },
    enabled: !!candidate,
  });

  const rolesQuery = useQuery({
    queryKey: ["b2b-roles"],
    queryFn: () => b2bGeneratorApi.roles(),
    staleTime: 60_000,
  });

  const nextNumberQuery = useQuery({
    queryKey: ["b2b-next-number"],
    queryFn: () => b2bGeneratorApi.nextNumber(),
    staleTime: 60_000,
  });

  const clientsQuery = useQuery({
    queryKey: ["b2b-clients-lookup"],
    queryFn: () => b2bGeneratorApi.clientsLookup(),
    staleTime: 300_000,
  });

  const roles = useMemo(() => rolesQuery.data ?? [], [rolesQuery.data]);
  const selectedRole = useMemo(
    () => roles.find((r) => String(r.id) === roleId) ?? null,
    [roles, roleId],
  );
  const selectedRecruitment = useMemo(
    () =>
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null,
    [recruitmentsQuery.data, stageId],
  );

  // Detal kandydata → pre-fill danych firmowych (raz per kandydat).
  const candidateDetailQuery = useQuery({
    queryKey: ["b2b-cand-detail", candidate?.id],
    queryFn: async () => {
      if (!candidate) return null;
      const res = await api.get<CandidateDetail>(`/api/candidates/${candidate.id}`);
      return res.data;
    },
    enabled: !!candidate,
    staleTime: 300_000,
  });

  useEffect(() => {
    const c = candidateDetailQuery.data;
    if (!c || !candidate || prefilledCand.current === candidate.id) return;
    prefilledCand.current = candidate.id;
    setPartnerName(
      c.full_name || `${c.name ?? ""} ${c.lastname ?? ""}`.trim() || candidate.full_name,
    );
    setPartnerLegalName(c.legal_name || "");
    setPartnerNip(c.nip || "");
    setPartnerRegon(c.regon || "");
    setPartnerBusinessAddress(c.business_address || "");
    setPartnerEmail(c.email || "");
    setPartnerPhone(c.phone || "");
  }, [candidateDetailQuery.data, candidate]);

  // Detal oferty → pre-fill klienta / opisu / miasta (raz per oferta).
  const jobQuery = useQuery({
    queryKey: ["b2b-gen-job", selectedRecruitment?.job_id],
    queryFn: async () => {
      if (!selectedRecruitment) return null;
      const res = await api.get<JobDetail>(
        `/api/jobs/${selectedRecruitment.job_id}`,
      );
      return res.data;
    },
    enabled: !!selectedRecruitment,
    staleTime: 300_000,
  });

  useEffect(() => {
    const j = jobQuery.data;
    if (
      !j ||
      !selectedRecruitment ||
      prefilledJob.current === selectedRecruitment.job_id
    )
      return;
    prefilledJob.current = selectedRecruitment.job_id;
    if (j.description) {
      setProjectDescription(j.description);
      descTouched.current = true; // opis z rekrutacji ma priorytet nad smart-prefillem
    }
    if (j.location) setProjectCity(j.location);
    if (j.client_name) setClientName(j.client_name);
  }, [jobQuery.data, selectedRecruitment]);

  // Smart-prefill opisu projektu z wybranego OBSZARU (roli). Opis z oferty ma
  // priorytet, a ręcznych zmian nie nadpisujemy — jedno i drugie ustawia
  // `descTouched` (efekt oferty jest zadeklarowany wyżej, więc wykona się jako
  // pierwszy w tym samym commit i zdąży ustawić flagę, zanim ten efekt ją
  // sprawdzi). Nie bramkujemy już na samej wybranej ofercie: gdy oferta nie
  // miała opisu, wybór obszaru i tak wypełnia pole (wcześniej zostawało puste).
  useEffect(() => {
    const next = areaPrefillDescription({
      role: selectedRole,
      language,
      clientName,
      descTouched: descTouched.current,
    });
    if (next !== null) setProjectDescription(next);
  }, [selectedRole, language, clientName]);

  // Auto-odmiana imienia i nazwiska do narzędnika (komparycja), dopóki user
  // nie poprawi ręcznie.
  useEffect(() => {
    if (instrTouched.current) return;
    setPartnerInstrumental(instrumentalPl(partnerName, gender));
  }, [partnerName, gender]);

  // Auto numer umowy (pierwsze załadowanie, jeśli puste).
  useEffect(() => {
    if (nextNumberQuery.data && !contractNumber) {
      setContractNumber(nextNumberQuery.data.contract_number);
    }
  }, [nextNumberQuery.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-uzupełnianie danych Partnera z rejestru po NIP (Biała Lista, debounced).
  useEffect(() => {
    const nip = partnerNip.replace(/\D/g, "");
    // Klasyfikacja MUSI zniknąć razem z NIP-em, do którego należała. Bez tego
    // scenariusz „wpisz NIP spółki → popraw na NIP JDG, lookup padnie" zapisuje
    // w snapshocie `company` dla JDG — TRWALE, bo snapshot się nie przelicza.
    // To najcichszy możliwy błąd w tej ścieżce: nic nie zgłasza awarii, a lista
    // pokazuje zdublowane nazwisko.
    setPartnerEntityType(null);
    if (nip.length !== 10) {
      setPartnerLookup("idle");
      return;
    }
    let cancelled = false;
    setPartnerLookup("loading");
    const timer = setTimeout(async () => {
      try {
        const d = await b2bGeneratorApi.companyLookup({ nip });
        if (cancelled) return;
        // JDG → `person` = imię i nazwisko właściciela (osobne pole);
        // `name` = nazwa firmy (pełna z CEIDG, lub nazwisko z Białej Listy).
        if (d.person) setPartnerName(d.person);
        if (d.name) setPartnerLegalName(d.name);
        if (d.regon) setPartnerRegon(d.regon);
        if (d.address) setPartnerBusinessAddress(d.address);
        setPartnerEntityType(d.entity_type ?? null);
        setPartnerLookup("ok");
      } catch {
        if (!cancelled) setPartnerLookup("none");
      }
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [partnerNip]);

  const groupedRoles = useMemo(() => {
    const map = new Map<string, { label: string; items: B2BRole[] }>();
    for (const r of roles) {
      if (!map.has(r.category_key)) {
        map.set(r.category_key, {
          label: language === "pl" ? r.category_label_pl : r.category_label_en,
          items: [],
        });
      }
      map.get(r.category_key)!.items.push(r);
    }
    return Array.from(map.values());
  }, [roles, language]);

  const filteredClients = useMemo(() => {
    const all = clientsQuery.data ?? [];
    const q = clientQuery.trim().toLowerCase();
    const list = q
      ? all.filter((c) => c.name.toLowerCase().includes(q))
      : all;
    // Lista jest już kuratorska (featured=true → ~17 nazw); cap wysoki, żeby
    // nigdy nie ucinać w pół alfabetu (wcześniej slice(0,50) gubił > litery „D").
    return list.slice(0, 200);
  }, [clientsQuery.data, clientQuery]);

  const buildPayload = (lang: Lang): B2BRenderPayload => ({
    candidate_id: candidate?.id ?? null,
    job_id: selectedRecruitment?.job_id ?? null,
    role_id: selectedRole ? selectedRole.id : null,
    language: lang,
    gender,
    partner_name: partnerName.trim() || null,
    partner_instrumental: partnerInstrumental.trim() || null,
    partner_legal_name: partnerLegalName.trim() || null,
    partner_business_address: partnerBusinessAddress.trim() || null,
    partner_correspondence_address: partnerCorrespondenceAddress.trim() || null,
    partner_nip: partnerNip.trim() || null,
    // Podpowiedź wyświetlania, nie dane umowy: backend zapisuje ją jako
    // snapshot, a gdy jej brak — rozstrzyga heurystyką po nazwie firmy.
    partner_entity_type: partnerEntityType,
    partner_regon: partnerRegon.trim() || null,
    partner_email: partnerEmail.trim() || null,
    partner_phone: partnerPhone.trim()
      ? partnerPhone.trim().startsWith("+")
        ? partnerPhone.trim()
        : `${phonePrefix} ${partnerPhone.trim()}`
      : null,
    client_name: clientName.trim() || null,
    project_city: projectCity.trim() || null,
    project_description: projectDescription.trim() || null,
    contract_number: contractNumber.trim() || null,
    signing_date: signingDate || null,
    start_date: startDate || null,
    start_date_mode: startDateMode,
    // Stawka bywa ułamkowa (135,5); normalizuj przecinek→kropka. Backend
    // przyjmuje float i formatuje do „135,50" w umowie.
    rate_candidate: parseRate(rateStages[0]?.rate ?? ""),
    // Stawka progresywna: wysyłana tylko przy >1 etapach; pojedyncza stawka
    // idzie starym polem `rate_candidate` (pełna zgodność wstecz).
    rate_stages:
      rateStages.length > 1
        ? rateStages.map((s) => ({
            rate: parseRate(s.rate) ?? 0,
            effective_from: s.from || null,
            effective_to: s.to || null,
          }))
        : null,
    currency: currency.trim() || "PLN",
  });

  const validate = (): boolean => {
    const missing: string[] = [];
    if (!candidate) missing.push("Kandydat");
    if (!selectedRecruitment) missing.push("Rekrutacja");
    if (!selectedRole) missing.push("Rola / stanowisko");
    if (!partnerName.trim()) missing.push("Imię i nazwisko Partnera");
    if (!partnerInstrumental.trim()) missing.push("Imię i nazwisko (narzędnik)");
    if (!partnerLegalName.trim()) missing.push("Nazwa Firmy");
    if (!partnerNip.trim()) missing.push("NIP");
    if (!partnerRegon.trim()) missing.push("REGON");
    if (!partnerBusinessAddress.trim()) missing.push("Adres siedziby firmy");
    if (!partnerEmail.trim()) missing.push("E-mail");
    if (!partnerPhone.trim()) missing.push("Telefon");
    if (!clientName.trim()) missing.push("Pełna nazwa Klienta");
    if (!projectCity.trim()) missing.push("Miasto Klienta");
    if (!projectDescription.trim()) missing.push("Opis projektu");
    if (!contractNumber.trim()) missing.push("Numer umowy");
    if (!signingDate) missing.push("Data podpisania");
    if (!startDate) missing.push("Data rozpoczęcia");
    if (rateStages.length === 1) {
      const rate = parseRate(rateStages[0]?.rate ?? "");
      if (!rate || rate <= 0) missing.push("Stawka godzinowa");
    } else {
      // Stawka progresywna: każdy etap z kwotą; etapy 2+ muszą mieć
      // „Obowiązuje od" (inaczej okresy w umowie są nierozstrzygalne).
      rateStages.forEach((s, i) => {
        const rate = parseRate(s.rate);
        if (!rate || rate <= 0) missing.push(`Stawka godzinowa (etap ${i + 1})`);
        if (i > 0 && !s.from) missing.push(`„Obowiązuje od” (etap ${i + 1})`);
      });
    }
    if (missing.length) {
      toast.showError(`Uzupełnij wymagane pola: ${missing.join(", ")}.`);
      return false;
    }
    // Daty ISO (yyyy-mm-dd) porównują się leksykograficznie.
    const backwards = rateStages.find((s) => s.from && s.to && s.to < s.from);
    if (backwards) {
      toast.showError(
        "„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od” etapu stawki.",
      );
      return false;
    }
    if (!/^\d+\/\d{4}$/.test(contractNumber.trim())) {
      toast.showError(
        `Numer umowy musi być w formacie liczba/rok, np. ${
          nextNumberQuery.data?.contract_number ?? "1435/2026"
        }.`,
      );
      return false;
    }
    return true;
  };

  const docxMut = useMutation({
    mutationFn: async (lang: Lang) => {
      const res = await b2bGeneratorApi.renderDocx(buildPayload(lang));
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa B2B ${contractNumber.trim().replaceAll("/", "-")}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    },
    onSuccess: () => {
      toast.showSuccess("Umowa pobrana (DOCX).");
      // Formularz nadal opisuje właśnie pobrany dokument. Nie podmieniamy
      // numeru na N+1, bo kolejne „Wyślij/Oznacz wysłaną/Wgraj” muszą
      // zaktualizować szkic dla tego samego numeru N.
      nextNumberQuery.refetch();
    },
    onError: (e) => {
      toast.showError(extractErrorMsg(e));
      // Numer zajęty (409) → podstaw kolejny wolny, by można było od razu ponowić.
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        nextNumberQuery.refetch().then((r) => {
          if (r.data) setContractNumber(r.data.contract_number);
        });
      }
    },
  });

  const previewMut = useMutation({
    mutationFn: () => b2bGeneratorApi.renderHtml(buildPayload(language)),
    onSuccess: (d) => setPreviewHtml(d.html),
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const uopMut = useMutation({
    mutationFn: () =>
      b2bGeneratorApi.checkUop({ text: projectDescription, language }),
    // Rekomendacje znikają dopiero przy PONOWNYM kliknięciu „Sprawdź…" (czyli
    // tutaj) — nie przy edycji opisu — i od razu generują się nowe.
    onMutate: () => setUop(null),
    onSuccess: (d) => setUop(d),
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const onDocx = (lang: Lang) => {
    if (validate()) docxMut.mutate(lang);
  };
  const onPreview = () => {
    if (validate()) previewMut.mutate();
  };

  // ── Wyślij do podpisu (in-house QES) ──────────────────────────────────────
  const [signLink, setSignLink] = useState<string | null>(null);

  const buildGeneratePayload = (): B2BGeneratePayload | null => {
    if (!selectedRole || !candidate || !selectedRecruitment || !startDate) {
      return null;
    }
    return {
      role_id: selectedRole.id,
      language,
      candidate_id: candidate.id,
      job_id: selectedRecruitment.job_id,
      contract_number: contractNumber.trim() || null,
      signing_date: signingDate || null,
      start_date: startDate,
      project_city: projectCity.trim() || null,
      project_description: projectDescription.trim() || null,
      correspondence_address: partnerCorrespondenceAddress.trim() || null,
      rate_candidate: parseRate(rateStages[0]?.rate ?? ""),
      // Etapy stawki trafiają też do harmonogramu kontraktu
      // (candidate_rate_schedule) przy promocji draftu.
      rate_stages:
        rateStages.length > 1
          ? rateStages.map((s) => ({
              rate: parseRate(s.rate) ?? 0,
              effective_from: s.from || null,
              effective_to: s.to || null,
            }))
          : null,
      currency: currency.trim() || "PLN",
    };
  };

  const ensureGeneratedContractId = () => {
    if (!candidate || !selectedRecruitment) {
      return Promise.reject(
        new Error(
          "Wybierz kandydata i rekrutację, aby utworzyć lub powiązać umowę.",
        ),
      );
    }
    const key = `${candidate.id}:${selectedRecruitment.job_id}`;
    return reuseOrGenerateContractId({
      key,
      memo: generatedContractMemo.current,
      generate: async (contractId) => {
        const payload = buildGeneratePayload();
        if (!payload) {
          throw new Error(
            "Wybierz kandydata, rekrutację, rolę i datę startu, aby utworzyć umowę.",
          );
        }
        return b2bGeneratorApi.generate({
          ...payload,
          contract_id: contractId ?? undefined,
        });
      },
    });
  };

  const sendSignMut = useMutation({
    mutationFn: async () => {
      const contractId = await ensureGeneratedContractId();
      const res = await signingApi.sendForSignature(contractId, {
        provider: "upload_validate",
        signature_type: "QES",
      });
      return res.sign_url;
    },
    onSuccess: (signUrl) => {
      setSignLink(signUrl);
      toast.showSuccess("Link do podpisu wygenerowany — skopiuj i wyślij konsultantowi.");
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const onSendSign = () => {
    if (!validate()) return;
    if (!candidate || !selectedRecruitment) {
      toast.showError(
        "Wybierz kandydata i rekrutację — wymagane do wysłania do podpisu.",
      );
      return;
    }
    setSignLink(null);
    setUploadVerdict(null);
    sendSignMut.mutate();
  };

  // ── Offline (e-mail) flow: oznacz wysłaną / wgraj podpisaną ────────────────
  const signedFileRef = useRef<HTMLInputElement>(null);
  const [uploadVerdict, setUploadVerdict] = useState<{
    is_qes: boolean;
    signed_by: string | null;
    signature_level: string | null;
    both_parties_signed: boolean;
  } | null>(null);

  const markSentMut = useMutation({
    mutationFn: async () => {
      const contractId = await ensureGeneratedContractId();
      await signingApi.markSentOffline(contractId);
    },
    onSuccess: () => {
      toast.showSuccess(
        "Oznaczono jako wysłaną — kandydat przeszedł na etap „Umowa wysłana”.",
      );
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const uploadSignedMut = useMutation({
    mutationFn: async (file: File) => {
      const contractId = await ensureGeneratedContractId();
      return signingApi.uploadSigned(contractId, file);
    },
    onSuccess: (verdict) => {
      setUploadVerdict({
        is_qes: verdict.is_qes,
        signed_by: verdict.signed_by,
        signature_level: verdict.signature_level,
        both_parties_signed: verdict.both_parties_signed,
      });
      toast.showSuccess(
        verdict.both_parties_signed
          ? "Umowa podpisana przez obie strony — kandydat przeszedł na etap „Zatrudniony”."
          : "Podpisaną umowę wgrano — kandydat przeszedł na etap „Umowa podpisana”.",
      );
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const onMarkSentOffline = () => {
    if (!validate()) return;
    if (!candidate || !selectedRecruitment) {
      toast.showError(
        "Wybierz kandydata i rekrutację — wymagane do oznaczenia wysłanej.",
      );
      return;
    }
    setSignLink(null);
    setUploadVerdict(null);
    markSentMut.mutate();
  };

  const onUploadSignedClick = () => {
    if (!validate()) return;
    if (!candidate || !selectedRecruitment) {
      toast.showError(
        "Wybierz kandydata i rekrutację — wymagane do wgrania podpisanej umowy.",
      );
      return;
    }
    signedFileRef.current?.click();
  };

  const onSignedFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setSignLink(null);
    setUploadVerdict(null);
    uploadSignedMut.mutate(file);
  };

  const signingActionPending =
    sendSignMut.isPending ||
    markSentMut.isPending ||
    uploadSignedMut.isPending;

  // Bez roli legal-team każdy endpoint generatora zwraca 403: lista obszarów
  // jest pusta, numer się nie nadaje, DOCX się nie wygeneruje. Pokazanie
  // formularza sugerowałoby, że brakuje tylko słownika obszarów — stąd jeden
  // jawny komunikat zamiast rozsypanych pustych pól. Guard po wszystkich
  // hookach (rules of hooks).
  if (isForbidden(rolesQuery.error)) {
    return (
      <Alert
        variant="warning"
        title={NO_ACCESS_TITLE}
        description={NO_ACCESS_DESC}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Źródło danych */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Źródło danych</CardTitle>
          <CardDescription>
            Wybierz kandydata i konkretną rekrutację. Powiązanie jest wymagane,
            aby po podpisaniu utworzyć kontraktora bez zgadywania po nazwisku
            lub nazwie klienta.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label className="mb-1.5 block">
                Kandydat <span className="text-destructive">*</span>
              </Label>
              <div className="flex gap-2">
                <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-between font-normal"
                    >
                      <span className="flex items-center gap-2 truncate">
                        <Search className="h-4 w-4 shrink-0 opacity-60" />
                        {candidate ? candidate.full_name : "Wybierz kandydata…"}
                      </span>
                      <ChevronsUpDown className="h-4 w-4 opacity-50" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    align="start"
                    className="w-(--radix-popover-trigger-width) p-0"
                  >
                    <Command shouldFilter={false}>
                      <CommandInput
                        placeholder="Szukaj kandydata…"
                        value={candidateQuery}
                        onValueChange={setCandidateQuery}
                      />
                      <CommandList>
                        {candidatesQuery.isLoading ? (
                          <div className="p-3 text-sm text-muted-foreground">
                            Szukam…
                          </div>
                        ) : (
                          <CommandEmpty>Brak wyników.</CommandEmpty>
                        )}
                        <CommandGroup>
                          {(candidatesQuery.data ?? []).map((c) => (
                            <CommandItem
                              key={c.id}
                              value={String(c.id)}
                              onSelect={() => {
                                setCandidate(c);
                                setStageId("");
                                setCandidateOpen(false);
                              }}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  candidate?.id === c.id
                                    ? "opacity-100"
                                    : "opacity-0",
                                )}
                              />
                              <span className="truncate">
                                {c.full_name}
                                {c.email ? (
                                  <span className="ml-1 text-xs text-muted-foreground">
                                    {c.email}
                                  </span>
                                ) : null}
                              </span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
                {candidate ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Wyczyść kandydata"
                    onClick={() => {
                      setCandidate(null);
                      setStageId("");
                      prefilledCand.current = null;
                      prefilledJob.current = null;
                    }}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            </div>

            <div>
              <Label className="mb-1.5 block">
                Rekrutacja (klient z rekrutacji){" "}
                <span className="text-destructive">*</span>
              </Label>
              <Select
                value={stageId}
                onValueChange={setStageId}
                disabled={!candidate}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      candidate
                        ? "Wybierz rekrutację…"
                        : "Najpierw wybierz kandydata"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {(recruitmentsQuery.data ?? []).map((r) => (
                    <SelectItem key={r.stage_id} value={String(r.stage_id)}>
                      {r.job_title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label className="mb-1.5 block">Język umowy</Label>
            <div className="flex gap-2">
              {(["pl", "en"] as Lang[]).map((l) => (
                <Button
                  key={l}
                  type="button"
                  size="sm"
                  variant={language === l ? "primary" : "outline"}
                  onClick={() => setLanguage(l)}
                >
                  {l === "pl" ? "Polski" : "English"}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Dane Partnera (firma) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Dane Partnera (firma)</CardTitle>
          <CardDescription>
            Wpisz NIP → nazwa firmy, REGON i adres zaciągną się z rejestru
            (biznes.gov.pl + Biała Lista MF). Działa dla JDG i spółek — dla
            spółki pole „Imię i nazwisko" zostaje puste (umowa jest pod JDG).
            Pre-fill też z profilu kandydata. Wszystkie pola wymagane, edytowalne.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block">
              Płeć Partnera<span className="text-destructive"> *</span>
            </Label>
            <div className="flex gap-2">
              {(
                [
                  ["m", "Mężczyzna"],
                  ["k", "Kobieta"],
                ] as const
              ).map(([v, lbl]) => (
                <Button
                  key={v}
                  type="button"
                  size="sm"
                  variant={gender === v ? "primary" : "outline"}
                  onClick={() => setGender(v)}
                >
                  {lbl}
                </Button>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Dobiera formy w umowie (Panem/ią, prowadzącym/cą, zwany/a,
              zapoznałem/am).
            </p>
          </div>
          <Field label="Imię i nazwisko" required>
            <Input
              value={partnerName}
              onChange={(e) => setPartnerName(e.target.value)}
              placeholder="np. Jan Kowalski"
            />
          </Field>
          <Field label="Imię i nazwisko — narzędnik (komparycja)" required>
            <Input
              value={partnerInstrumental}
              onChange={(e) => {
                instrTouched.current = true;
                setPartnerInstrumental(e.target.value);
              }}
              placeholder="np. Janem Kowalskim"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              „z Panem/ią …" — auto-odmiana; popraw przy nietypowych nazwiskach.
            </p>
          </Field>
          <Field label="Nazwa Firmy" required>
            <Input
              value={partnerLegalName}
              onChange={(e) => setPartnerLegalName(e.target.value)}
              placeholder="np. JK Software Jan Kowalski"
            />
          </Field>
          <Field label="NIP (auto z rejestru)" required>
            <Input
              value={partnerNip}
              onChange={(e) => setPartnerNip(e.target.value)}
              placeholder="10 cyfr → auto-pobranie"
            />
            <div className="mt-1 h-4">{lookupHint(partnerLookup)}</div>
          </Field>
          <Field label="REGON" required>
            <Input
              value={partnerRegon}
              onChange={(e) => setPartnerRegon(e.target.value)}
            />
          </Field>
          <Field label="Adres siedziby firmy" full required>
            <Input
              value={partnerBusinessAddress}
              onChange={(e) => setPartnerBusinessAddress(e.target.value)}
              placeholder="ul., kod, miasto"
            />
          </Field>
          <Field label="Adres do korespondencji (opcjonalnie)" full>
            <Input
              value={partnerCorrespondenceAddress}
              onChange={(e) => setPartnerCorrespondenceAddress(e.target.value)}
            />
          </Field>
          <Field label="E-mail" required>
            <Input
              value={partnerEmail}
              onChange={(e) => setPartnerEmail(e.target.value)}
            />
          </Field>
          <Field label="Telefon" required>
            <div className="flex gap-2">
              <Select value={phonePrefix} onValueChange={setPhonePrefix}>
                <SelectTrigger className="w-[92px] shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PHONE_PREFIXES.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                value={partnerPhone}
                onChange={(e) => setPartnerPhone(e.target.value)}
                placeholder="600 100 200"
              />
            </div>
          </Field>
        </CardContent>
      </Card>

      {/* Klient i projekt */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Klient i projekt</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Pełna nazwa Klienta" required>
            <Popover open={clientOpen} onOpenChange={setClientOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className="w-full justify-between font-normal"
                >
                  <span className="truncate">
                    {clientName || "Wybierz lub wpisz klienta…"}
                  </span>
                  <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-(--radix-popover-trigger-width) p-0"
              >
                <Command shouldFilter={false}>
                  <CommandInput
                    placeholder="Szukaj klienta…"
                    value={clientQuery}
                    onValueChange={setClientQuery}
                  />
                  <CommandList>
                    <CommandEmpty>Brak klientów na liście.</CommandEmpty>
                    {clientQuery.trim() ? (
                      <CommandGroup heading="Własna nazwa">
                        <CommandItem
                          value={`__custom__${clientQuery}`}
                          onSelect={() => {
                            setClientName(clientQuery.trim());
                            setClientOpen(false);
                          }}
                        >
                          Użyj: „{clientQuery.trim()}"
                        </CommandItem>
                      </CommandGroup>
                    ) : null}
                    <CommandGroup heading="Klienci">
                      {filteredClients.map((c) => (
                        <CommandItem
                          key={c.id}
                          value={`${c.id}-${c.name}`}
                          onSelect={() => {
                            setClientName(c.name);
                            setClientOpen(false);
                          }}
                        >
                          <Check
                            className={cn(
                              "mr-2 h-4 w-4",
                              clientName === c.name ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <span className="truncate">{c.name}</span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            {hasSpecialClauses(clientName) ? (
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-500">
                Ten klient ma specyficzne zapisy umowy (np. zmieniony paragraf,
                dodatkowy załącznik lub klauzule) — zostaną automatycznie
                wstawione do umowy (PL i EN).
              </p>
            ) : null}
          </Field>
          <Field label="Miasto Klienta" required>
            <Input
              value={projectCity}
              onChange={(e) => setProjectCity(e.target.value)}
              placeholder="np. Warszawa"
            />
          </Field>
          <Field label="Opis projektu i zakres usług" full required>
            <Textarea
              value={projectDescription}
              onChange={(e) => {
                descTouched.current = true;
                setProjectDescription(e.target.value);
                // Wynik AI-sprawdzenia ZOSTAJE przy edycji opisu — czyści się
                // tylko przy ponownym kliknięciu „Sprawdź…" (onMutate uopMut).
              }}
              rows={4}
              placeholder="Auto z obszaru/rekrutacji — możesz nadpisać. Po wklejeniu sprawdź AI…"
            />
            <div className="mt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!projectDescription.trim() || uopMut.isPending}
                onClick={() => uopMut.mutate()}
              >
                {uopMut.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" />
                )}
                Sprawdź pod kątem umowy o pracę (AI)
              </Button>
            </div>
            {uop ? (
              <UopPanel
                uop={uop}
                onApply={() => {
                  setProjectDescription(uop.rewritten);
                  descTouched.current = true;
                  setUop(null);
                }}
                onClose={() => setUop(null)}
              />
            ) : null}
          </Field>
        </CardContent>
      </Card>

      {/* Obszar (§1 umowy) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Obszar usług (§1 umowy)</CardTitle>
          <CardDescription>
            Określa obszar specjalizacji w §1 umowy oraz wstępnie wypełnia „Opis
            projektu i zakres usług" (możesz go nadpisać powyżej).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Label className="mb-1.5 block">Obszar *</Label>
          <Select value={roleId} onValueChange={setRoleId}>
            <SelectTrigger>
              <SelectValue placeholder="Wybierz obszar…" />
            </SelectTrigger>
            <SelectContent>
              {groupedRoles.map((g) => (
                <SelectGroup key={g.label}>
                  <SelectLabel>{g.label}</SelectLabel>
                  {g.items.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>
                      {language === "pl" ? r.name_pl : r.name_en}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Warunki */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Warunki umowy</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Numer umowy (auto)" required>
            <Input
              value={contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="np. 1435/2026"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Format: liczba/rok. System podpowiada kolejny wolny numer
              {nextNumberQuery.data?.contract_number
                ? ` (${nextNumberQuery.data.contract_number})`
                : ""}
              ; ten sam numer nie może być użyty dwa razy.
            </p>
          </Field>
          <Field label="Data podpisania" required>
            <Input
              type="date"
              value={signingDate}
              onChange={(e) => setSigningDate(e.target.value)}
            />
          </Field>
          <Field label="Data rozpoczęcia usług" required>
            <div className="flex gap-2">
              <Select
                value={startDateMode}
                onValueChange={(v) =>
                  setStartDateMode(v as "exact" | "not_earlier" | "not_later")
                }
              >
                <SelectTrigger className="w-[150px] shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exact">z dniem</SelectItem>
                  <SelectItem value="not_earlier">nie wcześniej niż</SelectItem>
                  <SelectItem value="not_later">nie później niż</SelectItem>
                </SelectContent>
              </Select>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
          </Field>
          <div className="space-y-3 sm:col-span-2">
            {rateStages.length === 1 ? (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Stawka godz. (netto)" required>
                  <Input
                    type="number"
                    value={rateStages[0]?.rate ?? ""}
                    onChange={(e) => setRateStage(0, { rate: e.target.value })}
                    placeholder="np. 150"
                  />
                </Field>
                <Field label="Waluta">
                  <Input
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value)}
                  />
                </Field>
              </div>
            ) : (
              <>
                {rateStages.map((stage, i) => (
                  <div key={i} className="flex items-end gap-2">
                    <div className="grid flex-1 grid-cols-3 gap-3">
                      <Field label={`Stawka godz. (netto) — etap ${i + 1}`} required>
                        <Input
                          type="number"
                          value={stage.rate}
                          onChange={(e) => setRateStage(i, { rate: e.target.value })}
                          placeholder="np. 150"
                        />
                      </Field>
                      {/* Pierwszy etap bez „od" obowiązuje od rozpoczęcia usług. */}
                      <Field label="Obowiązuje od" required={i > 0}>
                        <Input
                          type="date"
                          value={stage.from}
                          onChange={(e) => setRateStage(i, { from: e.target.value })}
                        />
                      </Field>
                      <Field label="Obowiązuje do">
                        <Input
                          type="date"
                          value={stage.to}
                          onChange={(e) => setRateStage(i, { to: e.target.value })}
                        />
                      </Field>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={() => removeRateStage(i)}
                      title="Usuń etap stawki"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Waluta">
                    <Input
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                    />
                  </Field>
                </div>
              </>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addRateStage}
              disabled={rateStages.length >= MAX_RATE_STAGES}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Dodaj etap stawki
            </Button>
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            „Stawka słownie" liczy się automatycznie z kwoty.
            {rateStages.length > 1
              ? " Stawka progresywna: umowa wypisze każdy etap z okresem obowiązywania; etap 1 bez „od” obowiązuje od rozpoczęcia usług."
              : ""}
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          disabled={previewMut.isPending}
          onClick={onPreview}
        >
          {previewMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Eye className="mr-2 h-4 w-4" />
          )}
          Podgląd
        </Button>
        <Button disabled={docxMut.isPending} onClick={() => onDocx("pl")}>
          {docxMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Download className="mr-2 h-4 w-4" />
          )}
          Pobierz DOCX (PL)
        </Button>
        <Button
          variant="outline"
          disabled={docxMut.isPending}
          onClick={() => onDocx("en")}
        >
          <Download className="mr-2 h-4 w-4" />
          DOCX (EN)
        </Button>
        <Button
          variant="outline"
          disabled={signingActionPending}
          onClick={onSendSign}
          title="Tworzy umowę i generuje link do podpisu kwalifikowanego dla konsultanta"
        >
          {sendSignMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <FileSignature className="mr-2 h-4 w-4" />
          )}
          Wyślij do podpisu (QES)
        </Button>
        <Button
          variant="outline"
          disabled={signingActionPending}
          onClick={onMarkSentOffline}
          title="Wysłałeś umowę mailem? Oznacz wysłaną, by przenieść kandydata na etap „Umowa wysłana”."
        >
          {markSentMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Mail className="mr-2 h-4 w-4" />
          )}
          Oznacz: wysłana mailem
        </Button>
        <Button
          variant="outline"
          disabled={signingActionPending}
          onClick={onUploadSignedClick}
          title="Masz podpisaną umowę z maila? Wgraj PDF — zweryfikujemy podpis i przeniesiemy na etap „Umowa podpisana”."
        >
          {uploadSignedMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Upload className="mr-2 h-4 w-4" />
          )}
          Wgraj podpisaną (z maila)
        </Button>
        <input
          ref={signedFileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={onSignedFilePicked}
        />
      </div>

      {signLink ? (
        <Alert>
          <div className="space-y-2">
            <p className="font-medium">
              Link do podpisu — wyślij go konsultantowi:
            </p>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={signLink}
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 rounded border bg-background px-2 py-1 text-sm"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  navigator.clipboard?.writeText(signLink);
                  toast.showSuccess("Skopiowano link.");
                }}
              >
                Kopiuj
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Konsultant otworzy link, przeczyta umowę w przeglądarce, podpisze
              ją własnym podpisem kwalifikowanym i odeśle. Status zobaczysz w
              profilu kandydata.
            </p>
          </div>
        </Alert>
      ) : null}

      {uploadVerdict ? (
        <Alert>
          <div className="space-y-1">
            <p className="flex items-center gap-2 font-medium">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              {uploadVerdict.both_parties_signed
                ? "Umowa podpisana przez obie strony — kandydat na etapie „Zatrudniony”."
                : "Podpisaną umowę wgrano — kandydat na etapie „Umowa podpisana”."}
            </p>
            <p className="text-xs text-muted-foreground">
              {uploadVerdict.is_qes
                ? "Podpis kwalifikowany (QES) potwierdzony"
                : "Podpis wgrany — kwalifikowalność niepotwierdzona automatycznie (zweryfikuj ręcznie)"}
              {uploadVerdict.signed_by ? ` · podpisał: ${uploadVerdict.signed_by}` : ""}
              {uploadVerdict.signature_level
                ? ` · poziom: ${uploadVerdict.signature_level}`
                : ""}
            </p>
          </div>
        </Alert>
      ) : null}

      {/* Podgląd */}
      {previewHtml ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Podgląd umowy</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => printHtml(previewHtml, "Umowa B2B")}
            >
              <Printer className="mr-2 h-4 w-4" />
              Drukuj / PDF
            </Button>
          </CardHeader>
          <CardContent>
            <iframe
              title="Podgląd umowy"
              className="h-[520px] w-full rounded-lg border bg-white"
              srcDoc={`<style>${PREVIEW_STYLE}</style>${previewHtml}`}
            />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function lookupHint(status: LookupStatus) {
  if (status === "loading")
    return (
      <span className="text-xs text-muted-foreground">Pobieram z rejestru…</span>
    );
  if (status === "ok")
    return <span className="text-xs text-emerald-600">✓ pobrano z rejestru</span>;
  if (status === "none")
    return (
      <span className="text-xs text-amber-600">
        Nie znaleziono — wpisz ręcznie
      </span>
    );
  return null;
}

// ── Panel wyniku AI-sprawdzenia opisu (znamiona umowy o pracę) ───────────────

function UopPanel({
  uop,
  onApply,
  onClose,
}: {
  uop: B2BUopCheckResult;
  onApply: () => void;
  onClose: () => void;
}) {
  if (uop.ok) {
    return (
      <div className="mt-3 rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-300">
        ✓ AI nie wykryło znamion umowy o pracę
        {uop.summary ? ` — ${uop.summary}` : "."}
      </div>
    );
  }
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-900/50 dark:bg-amber-950/30">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
          AI wykryło {uop.issues.length}{" "}
          {uop.issues.length === 1
            ? "ryzykowne sformułowanie"
            : "ryzykowne sformułowania"}{" "}
          (możliwe znamiona umowy o pracę)
        </p>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
      {uop.summary ? (
        <p className="text-xs text-muted-foreground">{uop.summary}</p>
      ) : null}
      <ul className="space-y-2">
        {uop.issues.map((i, idx) => (
          <li key={idx} className="rounded border bg-background p-2 text-xs">
            <p className="font-medium text-destructive">„{i.phrase}"</p>
            {i.why ? (
              <p className="mt-0.5 text-muted-foreground">{i.why}</p>
            ) : null}
            {i.suggestion ? (
              <p className="mt-1">
                <span className="font-medium">Propozycja:</span> {i.suggestion}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {uop.rewritten ? (
        <Button type="button" size="sm" onClick={onApply}>
          <Check className="mr-2 h-4 w-4" />
          Zastąp bezpieczną wersją
        </Button>
      ) : null}
    </div>
  );
}

function Field({
  label,
  full,
  required,
  children,
}: {
  label: string;
  full?: boolean;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <Label className="mb-1.5 block">
        {label}
        {required ? <span className="text-destructive"> *</span> : null}
      </Label>
      {children}
    </div>
  );
}

// ── Admin: edytor katalogu zakresów ról ─────────────────────────────────────

function RoleScopeEditor() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const rolesQuery = useQuery({
    queryKey: ["b2b-roles", "all"],
    queryFn: () => b2bGeneratorApi.roles(true),
  });
  const roles = useMemo(() => rolesQuery.data ?? [], [rolesQuery.data]);
  const [selectedId, setSelectedId] = useState<string>("");
  const selected = roles.find((r) => String(r.id) === selectedId) ?? null;

  const [namePl, setNamePl] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [areaPl, setAreaPl] = useState("");
  const [areaEn, setAreaEn] = useState("");
  const [scopePl, setScopePl] = useState("");
  const [scopeEn, setScopeEn] = useState("");

  useEffect(() => {
    if (!selected) return;
    setNamePl(selected.name_pl);
    setNameEn(selected.name_en);
    setAreaPl(selected.area_label_pl);
    setAreaEn(selected.area_label_en);
    setScopePl(selected.scope_pl.join("\n"));
    setScopeEn(selected.scope_en.join("\n"));
  }, [selected]);

  const saveMut = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("Brak roli");
      return b2bGeneratorApi.updateRole(selected.id, {
        name_pl: namePl,
        name_en: nameEn,
        area_label_pl: areaPl,
        area_label_en: areaEn,
        scope_pl: scopePl.split("\n").map((l) => l.trim()).filter(Boolean),
        scope_en: scopeEn.split("\n").map((l) => l.trim()).filter(Boolean),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["b2b-roles"] });
      toast.showSuccess("Zakres roli zapisany.");
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const grouped = useMemo(() => {
    const map = new Map<string, { label: string; items: B2BRole[] }>();
    for (const r of roles) {
      if (!map.has(r.category_key)) {
        map.set(r.category_key, { label: r.category_label_pl, items: [] });
      }
      map.get(r.category_key)!.items.push(r);
    }
    return Array.from(map.values());
  }, [roles]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Zakresy ról (edytowalne)</CardTitle>
        <CardDescription>
          Zmiany zapisują się od razu i obowiązują dla nowych umów (bez deployu).
          Pamiętaj: język rezultatu/usługi — bez znamion umowy o pracę.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="max-w-md">
          <Label className="mb-1.5 block">Rola</Label>
          <Select value={selectedId} onValueChange={setSelectedId}>
            <SelectTrigger>
              <SelectValue placeholder="Wybierz rolę do edycji…" />
            </SelectTrigger>
            <SelectContent>
              {grouped.map((g) => (
                <SelectGroup key={g.label}>
                  <SelectLabel>{g.label}</SelectLabel>
                  {g.items.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>
                      {r.name_pl}
                      {!r.is_active ? (
                        <Badge variant="neutral" className="ml-2">
                          nieaktywna
                        </Badge>
                      ) : null}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </div>

        {selected ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Nazwa (PL)">
                <Input value={namePl} onChange={(e) => setNamePl(e.target.value)} />
              </Field>
              <Field label="Nazwa (EN)">
                <Input value={nameEn} onChange={(e) => setNameEn(e.target.value)} />
              </Field>
              <Field label="Obszar usług §1 (PL)">
                <Input value={areaPl} onChange={(e) => setAreaPl(e.target.value)} />
              </Field>
              <Field label="Obszar usług §1 (EN)">
                <Input value={areaEn} onChange={(e) => setAreaEn(e.target.value)} />
              </Field>
              <Field label="Zakres usług (PL) — 1 punkt/linia" full>
                <Textarea
                  value={scopePl}
                  onChange={(e) => setScopePl(e.target.value)}
                  rows={8}
                  className="font-mono text-xs"
                />
              </Field>
              <Field label="Zakres usług (EN) — 1 punkt/linia" full>
                <Textarea
                  value={scopeEn}
                  onChange={(e) => setScopeEn(e.target.value)}
                  rows={8}
                  className="font-mono text-xs"
                />
              </Field>
            </div>
            <Alert
              variant="warning"
              title="Uwaga prawna"
              description="Unikaj sformułowań o podporządkowaniu, godzinach pracy, urlopie czy poleceniach przełożonego — to znamiona umowy o pracę (art. 22 §1 KP)."
            />
            <div className="flex justify-end">
              <Button disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
                {saveMut.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                Zapisz zakres
              </Button>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
