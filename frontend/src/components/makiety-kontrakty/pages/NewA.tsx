"use client";
// A · „Nowy kontrakt” jako kreator w 3 krokach: Kto i u kogo → Okres i stawki
// → Sprawdź i utwórz. Dziś to jeden długi formularz w dwóch kartach: trzy
// sekcje stawek z harmonogramami naraz, „Status” do wyboru, „Zużycie
// zamówienia” bez słowa wyjaśnienia i żadnej marży. Tu na ekranie jest jeden
// krok, stawki podpowiada rekrutacja, marża liczy się na żywo, a rzadkie pola
// (waluty, harmonogram, stawka ramowa, zużycie zamówienia) czekają w „Więcej
// opcji”. Kontrakt powstaje jako szkic.
//
// Para kandydat → klient i rekrutacja są na żywo z kontraktu 738 na stagingu,
// stawki z `GET /api/clients/{id}/recruitment-rates`. Nic się nie zapisuje.
// `?krok=1|3` otwiera inny krok (domyślnie 2).
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  ChevronsUpDown,
  Info,
  Plus,
  Search,
} from "lucide-react";
import api from "@/lib/api";
import { fetchRecruitmentRates } from "@/lib/api/recruitmentRates";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { useMkContract } from "../shared/data";
import { fmtDate, fmtNum, fmtPln, marginPct, relDays, today } from "../shared/format";

// ── Wspólne z wariantem B (NewB importuje stąd) ─────────────────────────────

/** Kontrakt na stagingu, z którego makieta bierze parę kandydat → klient. */
export const NEW_SOURCE_CONTRACT_ID = 738;

export interface MkRecruitmentOption {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage?: string | null;
  client_id?: number | null;
  client_name?: string | null;
}

export type ContractTypeKey = "b2b" | "uop" | "uzlecenie";
export const CONTRACT_TYPE_OPTIONS: { value: ContractTypeKey; label: string }[] = [
  { value: "b2b", label: "B2B" },
  { value: "uop", label: "Umowa o pracę" },
  { value: "uzlecenie", label: "Zlecenie" },
];

export type WorkModeKey = "remote" | "hybrid" | "onsite";
export const WORK_MODE_OPTIONS: { value: WorkModeKey; label: string }[] = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybrydowo" },
  { value: "onsite", label: "Stacjonarnie" },
];

export type CreateAsKey = "draft" | "active" | "ended";
export const CREATE_AS_OPTIONS: { value: CreateAsKey; label: string }[] = [
  { value: "draft", label: "Szkic" },
  { value: "active", label: "Aktywny" },
  { value: "ended", label: "Zakończony" },
];

const CURRENCIES = ["PLN", "EUR", "USD", "GBP"] as const;

/** Treść „Więcej opcji” / „Zaawansowane” — do `title` i opisu w raporcie. */
export const MORE_OPTIONS_TITLE =
  "W środku: waluta stawki klienta i konsultanta, jednostka stawki (godzinowo / miesięcznie), " +
  "godziny w miesiącu, stawka z umowy ramowej, harmonogram zmian stawek, zużycie zamówienia (RBH / MD).";

/** „157,00” — wartość do pola tekstowego (przecinek, bez spacji tysięcy). */
export function rateToInput(value: number | string | null | undefined): string {
  if (value == null || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toFixed(2).replace(".", ",") : "";
}

export interface MarginFacts {
  perHour: number;
  pct: string;
  monthly: number;
  revenue: number;
  cost: number;
}

export function marginFacts(client: number | null, candidate: number | null, hours: number): MarginFacts | null {
  if (client == null || candidate == null) return null;
  const perHour = client - candidate;
  return {
    perHour,
    pct: marginPct(client, candidate),
    monthly: perHour * hours,
    revenue: client * hours,
    cost: candidate * hours,
  };
}

/** Stan formularza „Nowy kontrakt” z wartościami domyślnymi z kontraktu 738 i jego rekrutacji. */
export function useNewContractDraft() {
  const contractQ = useMkContract(NEW_SOURCE_CONTRACT_ID);
  const c = contractQ.data;
  const candidateId = c?.candidate_id ?? null;

  const recruitmentsQ = useQuery({
    queryKey: ["mk-new-recruitments", candidateId],
    queryFn: () =>
      api
        .get<MkRecruitmentOption[]>(`/api/cv-generator/candidates/${candidateId}/recruitments`)
        .then((r) => r.data),
    enabled: candidateId != null,
  });

  const [jobChoice, setJobChoice] = useState<string | null>(null);
  const [contractType, setContractType] = useState<ContractTypeKey>("b2b");
  const [workMode, setWorkMode] = useState<WorkModeKey | null>(null);
  const [lineManager, setLineManager] = useState("");
  const [startDate, setStartDate] = useState<string | null>(null);
  const [endDate, setEndDate] = useState("");
  const [clientRate, setClientRate] = useState<string | null>(null);
  const [candidateRate, setCandidateRate] = useState<string | null>(null);
  const [clientCurrency, setClientCurrency] = useState<string>("PLN");
  const [candidateCurrency, setCandidateCurrency] = useState<string>("PLN");
  const [rateUnit, setRateUnit] = useState<"hourly" | "monthly">("hourly");
  const [hours, setHours] = useState<string | null>(null);
  const [frameworkRate, setFrameworkRate] = useState("");
  const [consumption, setConsumption] = useState("");
  const [consumptionUnit, setConsumptionUnit] = useState<"rbh" | "md">("rbh");
  const [createAs, setCreateAs] = useState<CreateAsKey>("draft");

  // Rekrutacje kandydata tylko u wybranego klienta (jak dziś — UAT B24).
  // Rekrutacja kontraktu jest na liście od razu, zanim przyjdzie lista
  // kandydata — inaczej stawki podpowiadałyby się najpierw z innej rekrutacji.
  const listed = (recruitmentsQ.data ?? []).filter(
    (r) => !c || r.client_id == null || r.client_id === c.client_id,
  );
  const own: MkRecruitmentOption | null =
    c?.job_id != null && !listed.some((r) => r.job_id === c.job_id)
      ? { stage_id: -c.job_id, job_id: c.job_id, job_title: c.job_title ?? `Rekrutacja ${c.job_id}`, client_id: c.client_id }
      : null;
  const recruitments = own ? [own, ...listed] : listed;
  const jobValue = jobChoice ?? (c?.job_id != null ? String(c.job_id) : "");
  const recruitment = recruitments.find((r) => String(r.job_id) === jobValue) ?? null;
  const jobId = recruitment?.job_id ?? null;

  const ratesQ = useQuery({
    queryKey: ["mk-new-recruitment-rates", c?.client_id, candidateId, jobId],
    queryFn: () => fetchRecruitmentRates(c?.client_id ?? 0, candidateId ?? 0, jobId),
    enabled: c != null && candidateId != null,
    retry: false,
  });
  const rec = ratesQ.data?.rate ?? null;

  const recClientRate = rec?.client_rate_value != null ? Number(rec.client_rate_value) : null;
  const recCandidateRate = rec?.candidate_rate_value != null ? Number(rec.candidate_rate_value) : null;
  const clientRateText = clientRate ?? rateToInput(recClientRate ?? c?.rate_client);
  const candidateRateText = candidateRate ?? rateToInput(recCandidateRate ?? c?.rate_candidate);
  const hoursText = hours ?? String(c?.billing_hours_per_month ?? 168);
  const hoursNum = Number(hoursText) || 168;
  const clientRateNum = parseDecimalInput(clientRateText);
  const candidateRateNum = parseDecimalInput(candidateRateText);

  return {
    loading: contractQ.isLoading,
    error: contractQ.isError,
    candidateName: c?.candidate_name ?? "",
    clientName: c?.client_name ?? "",
    recruitments,
    recruitmentsLoading: recruitmentsQ.isLoading,
    jobValue,
    setJobChoice,
    recruitment,
    contractType,
    setContractType,
    workMode,
    setWorkMode,
    lineManager,
    setLineManager,
    startDate: startDate ?? c?.start_date ?? today(),
    setStartDate,
    endDate,
    setEndDate,
    clientRateText,
    setClientRate: (v: string) => setClientRate(sanitizeDecimalInput(v)),
    candidateRateText,
    setCandidateRate: (v: string) => setCandidateRate(sanitizeDecimalInput(v)),
    clientRateNum,
    candidateRateNum,
    recClientRate,
    recCandidateRate,
    recClientRateAt: rec?.client_rate_at ?? null,
    recClientRateBy: rec?.client_rate_by_name ?? null,
    recCandidateRateAt: rec?.candidate_rate_at ?? null,
    clientCurrency,
    setClientCurrency,
    candidateCurrency,
    setCandidateCurrency,
    rateUnit,
    setRateUnit,
    hoursText,
    setHours,
    hoursNum,
    frameworkRate,
    setFrameworkRate: (v: string) => setFrameworkRate(sanitizeDecimalInput(v)),
    consumption,
    setConsumption: (v: string) => setConsumption(sanitizeDecimalInput(v)),
    consumptionUnit,
    setConsumptionUnit,
    createAs,
    setCreateAs,
    margin: marginFacts(clientRateNum, candidateRateNum, hoursNum),
  };
}

export type NewDraft = ReturnType<typeof useNewContractDraft>;

/** „PLN · godzinowo · 168 h/mies. · bez stawki ramowej …” — co dziś jest w zwiniętych opcjach. */
export function moreOptionsSummary(d: NewDraft): string {
  const currency =
    d.clientCurrency === d.candidateCurrency ? d.clientCurrency : `${d.clientCurrency} / ${d.candidateCurrency}`;
  const parts = [
    currency,
    d.rateUnit === "hourly" ? "godzinowo" : "miesięcznie",
    d.rateUnit === "hourly" ? `${d.hoursText} h/mies.` : null,
    d.frameworkRate ? `stawka ramowa ${d.frameworkRate} zł/h` : "bez stawki ramowej",
    "bez harmonogramu",
    d.consumption ? `zużycie ${d.consumption} ${d.consumptionUnit === "md" ? "MD" : "RBH"}` : "bez zużycia zamówienia",
  ];
  return parts.filter(Boolean).join(" · ");
}

export function FieldLabel({
  htmlFor,
  children,
  optional,
  required,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  optional?: boolean;
  required?: boolean;
}) {
  return (
    <Label htmlFor={htmlFor} className="mb-1 block text-[12.5px] font-medium text-foreground">
      {children}
      {required ? <span className="text-destructive"> *</span> : null}
      {optional ? <span className="ml-1 font-normal text-muted-foreground">(opcjonalnie)</span> : null}
    </Label>
  );
}

/** Pole wyboru osoby / klienta — w makiecie wybór jest stały (para z kontraktu na stagingu). */
export function PickerButton({ id, value, placeholder }: { id?: string; value: string; placeholder: string }) {
  return (
    <button
      id={id}
      type="button"
      title="W makiecie wybór jest stały — para z kontraktu na stagingu"
      className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 text-left text-sm text-foreground transition-colors hover:bg-muted/50"
    >
      <span className="flex min-w-0 items-center gap-2">
        <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className={cn("truncate", !value && "text-muted-foreground")}>{value || placeholder}</span>
      </span>
      <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
    </button>
  );
}

export function RecruitmentSelect({ d, id }: { d: NewDraft; id?: string }) {
  return (
    <Select value={d.jobValue} onValueChange={d.setJobChoice} disabled={d.recruitments.length === 0}>
      <SelectTrigger id={id} className="h-9 [&>span]:truncate [&>span]:text-left" title={d.recruitment?.job_title}>
        <SelectValue placeholder={d.recruitmentsLoading ? "Wczytuję rekrutacje kandydata…" : "Bez rekrutacji"} />
      </SelectTrigger>
      <SelectContent>
        {d.recruitments.map((r) => (
          <SelectItem key={r.job_id} value={String(r.job_id)}>
            {r.job_title}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Podpis pod polem stawki: skąd jest wartość albo „w rekrutacji: … · Użyj”. */
function rateSource(current: number | null, fromRecruitment: number | null, note: string): React.ReactNode {
  if (fromRecruitment == null) return "Rekrutacja nie ma tej stawki — wpisz z umowy.";
  if (current != null && Math.abs(current - fromRecruitment) < 0.005) {
    return `z rekrutacji: ${fmtNum(fromRecruitment)} zł/h · ${note}`;
  }
  return `w rekrutacji: ${fmtNum(fromRecruitment)} zł/h · ${note}`;
}

export function RateInput({
  id,
  label,
  value,
  onChange,
  current,
  fromRecruitment,
  note,
  onUseRecruitment,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  current: number | null;
  fromRecruitment: number | null;
  note: string;
  onUseRecruitment: () => void;
}) {
  const differs = fromRecruitment != null && (current == null || Math.abs(current - fromRecruitment) >= 0.005);
  return (
    <div className="min-w-0">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="np. 150,00"
        className="h-9 tabular-nums"
        trailingIcon={<span className="text-xs">zł/h</span>}
      />
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11.5px] leading-4 text-muted-foreground">
        <span>{rateSource(current, fromRecruitment, note)}</span>
        {differs ? (
          <button type="button" onClick={onUseRecruitment} className="font-medium text-primary hover:underline">
            Użyj
          </button>
        ) : null}
      </p>
    </div>
  );
}

/** Ramka „Marża X zł/h · Y % · ≈ Z zł/mies.” liczona na żywo z pól. */
export function MarginStrip({ d, className }: { d: NewDraft; className?: string }) {
  const m = d.margin;
  if (!m) {
    return (
      <p className={cn("rounded-lg border border-dashed border-border px-3.5 py-2.5 text-[13px] text-muted-foreground", className)}>
        Wpisz obie stawki — marża policzy się sama.
      </p>
    );
  }
  const negative = m.perHour < 0;
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border px-3.5 py-2.5 text-[13px] tabular-nums",
        negative
          ? "border-destructive/30 bg-destructive-muted text-destructive-muted-foreground"
          : "border-success/25 bg-success-muted text-success-muted-foreground",
        className,
      )}
    >
      <span className="font-semibold">Marża {fmtNum(m.perHour)} zł/h</span>
      <span aria-hidden>·</span>
      <span>{m.pct}</span>
      <span aria-hidden>·</span>
      <span>
        ≈ {fmtPln(m.monthly)}/mies. ({d.hoursNum} h)
      </span>
      {negative ? <span className="basis-full text-[12px]">Konsultant kosztuje więcej, niż płaci klient.</span> : null}
    </div>
  );
}

/** Zawartość „Więcej opcji” (A) i „Zaawansowane” (B). */
export function MoreOptionsFields({ d }: { d: NewDraft }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">
      <div>
        <FieldLabel htmlFor="mk-cur-client">Waluta stawki klienta</FieldLabel>
        <Select value={d.clientCurrency} onValueChange={d.setClientCurrency}>
          <SelectTrigger id="mk-cur-client" className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CURRENCIES.map((cur) => (
              <SelectItem key={cur} value={cur}>
                {cur}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <FieldLabel htmlFor="mk-cur-cand">Waluta stawki konsultanta</FieldLabel>
        <Select value={d.candidateCurrency} onValueChange={d.setCandidateCurrency}>
          <SelectTrigger id="mk-cur-cand" className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CURRENCIES.map((cur) => (
              <SelectItem key={cur} value={cur}>
                {cur}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">Ta sama waluta obowiązuje stawkę z umowy ramowej.</p>
      </div>
      <div>
        <FieldLabel>Jednostka stawki</FieldLabel>
        <SegmentedRadio<"hourly" | "monthly">
          label="Jednostka stawki"
          size="sm"
          value={d.rateUnit}
          onChange={d.setRateUnit}
          options={[
            { value: "hourly", label: "Za godzinę" },
            { value: "monthly", label: "Ryczałt miesięczny" },
          ]}
        />
      </div>
      {d.rateUnit === "hourly" ? (
        <div>
          <FieldLabel htmlFor="mk-hours">Godziny w miesiącu</FieldLabel>
          <Input
            id="mk-hours"
            type="text"
            inputMode="numeric"
            value={d.hoursText}
            onChange={(e) => d.setHours(e.target.value.replace(/\D/g, ""))}
            className="h-9 tabular-nums"
          />
          <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">Do przeliczeń miesięcznych (marża, MRR).</p>
        </div>
      ) : (
        <div />
      )}
      <div>
        <FieldLabel htmlFor="mk-framework" optional>
          Stawka z umowy ramowej
        </FieldLabel>
        <Input
          id="mk-framework"
          type="text"
          inputMode="decimal"
          value={d.frameworkRate}
          onChange={(e) => d.setFrameworkRate(e.target.value)}
          placeholder="—"
          className="h-9 tabular-nums"
          trailingIcon={<span className="text-xs">zł/h</span>}
        />
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
          Pułap z cennika klienta (umowa ramowa). Nie wchodzi do marży.
        </p>
      </div>
      <div>
        <FieldLabel optional>Zmiany stawek w czasie</FieldLabel>
        <Button type="button" variant="outline" size="sm" className="h-9 w-full justify-start">
          <Plus className="size-3.5" aria-hidden />
          Zaplanuj zmianę stawki od daty
        </Button>
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
          Np. podwyżka od 1 stycznia — kontrakt sam przełączy stawkę klienta, konsultanta albo ramową.
        </p>
      </div>
      <div className="col-span-2">
        <FieldLabel htmlFor="mk-consumption" optional>
          Zużycie zamówienia
        </FieldLabel>
        <div className="flex items-center gap-2">
          <Input
            id="mk-consumption"
            type="text"
            inputMode="decimal"
            value={d.consumption}
            onChange={(e) => d.setConsumption(e.target.value)}
            placeholder="—"
            className="h-9 w-40 tabular-nums"
          />
          <SegmentedRadio<"rbh" | "md">
            label="Jednostka zużycia"
            size="sm"
            value={d.consumptionUnit}
            onChange={d.setConsumptionUnit}
            options={[
              { value: "rbh", label: "RBH (roboczogodziny)" },
              { value: "md", label: "MD (osobodni)" },
            ]}
          />
        </div>
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
          Ile z zamówienia klienta zużywa ten kontrakt — tylko u klientów rozliczanych per zamówienie (np. BNP, BIK,
          Polkomtel, Bosch). U pozostałych zostaw puste.
        </p>
      </div>
    </div>
  );
}

export function PageIntro({ subtitle }: { subtitle: string }) {
  return (
    <header className="space-y-1">
      <Link
        href="/contracts?status=active&status=ending"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Kontrakty
      </Link>
      <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Nowy kontrakt</h1>
      <p className="text-[13px] text-muted-foreground">{subtitle}</p>
    </header>
  );
}

// ── Wariant A ────────────────────────────────────────────────────────────────

type Step = 1 | 2 | 3;

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: "Kto i u kogo" },
  { n: 2, label: "Okres i stawki" },
  { n: 3, label: "Sprawdź i utwórz" },
];

function Stepper({ step, onGo, notes }: { step: Step; onGo: (s: Step) => void; notes: Record<Step, string> }) {
  return (
    <nav aria-label="Kroki">
      <ol className="flex items-center gap-3">
        {STEPS.map((s, i) => {
          const done = s.n < step;
          const current = s.n === step;
          return (
            <li key={s.n} className={cn("flex min-w-0 items-center gap-3", i < STEPS.length - 1 && "flex-1")}>
              <button
                type="button"
                onClick={() => onGo(s.n)}
                aria-current={current ? "step" : undefined}
                className="flex min-w-0 items-center gap-2.5 rounded-lg py-1 pr-1 text-left"
              >
                <span
                  className={cn(
                    "grid size-7 shrink-0 place-items-center rounded-full text-[12.5px] font-semibold tabular-nums",
                    done && "bg-success-muted text-success-muted-foreground",
                    current && "bg-primary text-primary-foreground",
                    !done && !current && "border border-border bg-card text-muted-foreground",
                  )}
                >
                  {done ? <Check className="size-3.5" aria-label="zrobione" /> : s.n}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-[13px] leading-4", current ? "font-semibold text-foreground" : "font-medium text-foreground")}>
                    {s.label}
                  </span>
                  <span className="block truncate text-[11.5px] leading-4 text-muted-foreground" title={notes[s.n]}>
                    {notes[s.n]}
                  </span>
                </span>
              </button>
              {i < STEPS.length - 1 ? (
                <span aria-hidden className={cn("h-px min-w-6 flex-1", done ? "bg-success/40" : "bg-border")} />
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function StepCard({
  title,
  step,
  children,
  footer,
}: {
  title: string;
  step: Step;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-card shadow-xs">
      <header className="flex items-baseline justify-between gap-3 border-b border-border/70 px-5 py-2.5">
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
        <span className="text-[12px] tabular-nums text-muted-foreground">Krok {step} z 3</span>
      </header>
      <div className="px-5 py-3.5">{children}</div>
      <footer className="flex items-center justify-between gap-3 border-t border-border/70 px-5 py-2.5">{footer}</footer>
    </section>
  );
}

/** Krok 1 zwinięty do jednej linii nad krokiem 2. */
function WhoSummary({ d, onChange }: { d: NewDraft; onChange: () => void }) {
  const type = CONTRACT_TYPE_OPTIONS.find((o) => o.value === d.contractType)?.label ?? "B2B";
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-2.5 shadow-xs">
      <span className="grid size-5 shrink-0 place-items-center rounded-full bg-success-muted text-success-muted-foreground">
        <Check className="size-3" aria-hidden />
      </span>
      <p className="flex min-w-0 flex-1 items-center gap-x-2 text-[13px] leading-5">
        <span className="shrink-0 text-muted-foreground">Kto i u kogo</span>
        <span className="shrink-0 font-semibold text-foreground">{d.candidateName}</span>
        <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="shrink-0 font-semibold text-foreground">{d.clientName}</span>
        {d.recruitment ? (
          <>
            <span aria-hidden className="text-muted-foreground">
              ·
            </span>
            <span className="min-w-0 truncate text-muted-foreground" title={d.recruitment.job_title}>
              {d.recruitment.job_title}
            </span>
          </>
        ) : null}
        <span aria-hidden className="text-muted-foreground">
          ·
        </span>
        <span className="shrink-0 text-muted-foreground">{type}</span>
      </p>
      <button type="button" onClick={onChange} className="shrink-0 text-[13px] font-medium text-primary hover:underline">
        Zmień
      </button>
    </div>
  );
}

function StepWho({ d, onNext }: { d: NewDraft; onNext: () => void }) {
  return (
    <StepCard
      title="Kto i u kogo"
      step={1}
      footer={
        <>
          <Button asChild variant="ghost">
            <Link href="/contracts?status=active&status=ending">Anuluj</Link>
          </Button>
          <Button type="button" onClick={onNext}>
            Dalej
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">
        <div>
          <FieldLabel htmlFor="mk-a-cand" required>
            Kandydat
          </FieldLabel>
          <PickerButton id="mk-a-cand" value={d.candidateName} placeholder="Wybierz kandydata…" />
        </div>
        <div>
          <FieldLabel htmlFor="mk-a-client" required>
            Klient
          </FieldLabel>
          <PickerButton id="mk-a-client" value={d.clientName} placeholder="Wybierz klienta…" />
        </div>
        <div className="col-span-2">
          <FieldLabel htmlFor="mk-a-job" optional>
            Rekrutacja
          </FieldLabel>
          <RecruitmentSelect d={d} id="mk-a-job" />
          <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">
            Tylko rekrutacje kandydata u tego klienta. Z rekrutacji podpowiemy stawki w kroku 2.
          </p>
        </div>
        <div>
          <FieldLabel>Typ umowy</FieldLabel>
          <SegmentedRadio<ContractTypeKey>
            label="Typ umowy"
            size="sm"
            value={d.contractType}
            onChange={d.setContractType}
            options={CONTRACT_TYPE_OPTIONS}
          />
        </div>
        <div>
          <FieldLabel optional>Tryb pracy</FieldLabel>
          <SegmentedRadio<WorkModeKey>
            label="Tryb pracy"
            size="sm"
            value={d.workMode}
            onChange={d.setWorkMode}
            options={WORK_MODE_OPTIONS}
          />
        </div>
        <div className="col-span-2">
          <FieldLabel htmlFor="mk-a-lm" optional>
            Line manager
          </FieldLabel>
          <Input
            id="mk-a-lm"
            value={d.lineManager}
            onChange={(e) => d.setLineManager(e.target.value)}
            placeholder="Imię i nazwisko osoby po stronie klienta"
            className="h-9"
          />
        </div>
      </div>
    </StepCard>
  );
}

function StepTerms({ d, onBack, onNext }: { d: NewDraft; onBack: () => void; onNext: () => void }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const b2b = d.contractType === "b2b";
  const rateNote = [d.recClientRateBy, d.recClientRateAt ? fmtDate(d.recClientRateAt) : null].filter(Boolean).join(", ");
  return (
    <StepCard
      title="Okres i stawki"
      step={2}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onBack}>
            Wstecz
          </Button>
          <Button type="button" onClick={onNext}>
            Dalej
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-[180px_minmax(0,1fr)] items-start gap-4">
          <div>
            <FieldLabel htmlFor="mk-a-start" required>
              Data startu
            </FieldLabel>
            <Input
              id="mk-a-start"
              type="date"
              value={d.startDate}
              onChange={(e) => d.setStartDate(e.target.value)}
              className="h-9 tabular-nums"
            />
            <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">{relDays(d.startDate)}</p>
          </div>
          {b2b ? (
            <p className="mt-[22px] flex gap-2 rounded-lg bg-muted/70 px-3 py-2 text-[12.5px] leading-[18px] text-muted-foreground">
              <Info className="mt-px size-3.5 shrink-0" aria-hidden />
              <span>
                <span className="font-medium text-foreground">Bez daty końca</span> — umowa B2B jest bezterminowa. Koniec
                wpisuje okno „Zakończ współpracę” na stronie kontraktu.
              </span>
            </p>
          ) : (
            <div className="max-w-[180px]">
              <FieldLabel htmlFor="mk-a-end" optional>
                Data końca
              </FieldLabel>
              <Input
                id="mk-a-end"
                type="date"
                value={d.endDate}
                onChange={(e) => d.setEndDate(e.target.value)}
                className="h-9 tabular-nums"
              />
            </div>
          )}
        </div>

        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-foreground">
            Stawki <span className="font-normal text-muted-foreground">— netto za godzinę</span>
          </h3>
          <div className="grid grid-cols-2 gap-x-4">
            <RateInput
              id="mk-a-rate-client"
              label="Klient płaci"
              value={d.clientRateText}
              onChange={d.setClientRate}
              current={d.clientRateNum}
              fromRecruitment={d.recClientRate}
              note={rateNote}
              onUseRecruitment={() => d.setClientRate(rateToInput(d.recClientRate))}
            />
            <RateInput
              id="mk-a-rate-cand"
              label="Konsultant dostaje"
              value={d.candidateRateText}
              onChange={d.setCandidateRate}
              current={d.candidateRateNum}
              fromRecruitment={d.recCandidateRate}
              note={d.recCandidateRateAt ? fmtDate(d.recCandidateRateAt) : "karta kandydata"}
              onUseRecruitment={() => d.setCandidateRate(rateToInput(d.recCandidateRate))}
            />
          </div>
          <MarginStrip d={d} className="mt-3" />
        </div>

        <div className="rounded-lg border border-border">
          <button
            type="button"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen((v) => !v)}
            title={MORE_OPTIONS_TITLE}
            className="flex w-full items-center gap-2 px-3 py-2 text-left"
          >
            <ChevronRight
              className={cn("size-4 shrink-0 text-muted-foreground transition-transform", moreOpen && "rotate-90")}
              aria-hidden
            />
            <span className="shrink-0 text-[13px] font-medium text-foreground">Więcej opcji</span>
            <span className="min-w-0 truncate text-[12px] text-muted-foreground">{moreOptionsSummary(d)}</span>
          </button>
          {moreOpen ? (
            <div className="border-t border-border/70 px-3 py-3">
              <MoreOptionsFields d={d} />
            </div>
          ) : null}
        </div>
      </div>
    </StepCard>
  );
}

function ReviewRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[150px_minmax(0,1fr)] gap-3 py-2 text-[13px] leading-5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function StepReview({ d, onBack, onEdit }: { d: NewDraft; onBack: () => void; onEdit: (s: Step) => void }) {
  const [statusOpen, setStatusOpen] = useState(d.createAs !== "draft");
  const type = CONTRACT_TYPE_OPTIONS.find((o) => o.value === d.contractType)?.label ?? "B2B";
  const mode = WORK_MODE_OPTIONS.find((o) => o.value === d.workMode)?.label;
  const cta = d.createAs === "draft" ? "Utwórz szkic" : d.createAs === "active" ? "Utwórz jako aktywny" : "Utwórz jako zakończony";
  const missingOptional = [!d.lineManager.trim() ? "line manager" : null, !mode ? "tryb pracy" : null].filter(Boolean);
  const edit = (s: Step) => (
    <button type="button" onClick={() => onEdit(s)} className="ml-2 text-[12.5px] font-medium text-primary hover:underline">
      Zmień
    </button>
  );
  return (
    <StepCard
      title="Sprawdź i utwórz"
      step={3}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onBack}>
            Wstecz
          </Button>
          <Button type="button">{cta}</Button>
        </>
      }
    >
      <dl className="divide-y divide-border/60">
        <ReviewRow label="Kandydat → klient">
          <span className="font-medium">{d.candidateName}</span> → <span className="font-medium">{d.clientName}</span>
          {edit(1)}
        </ReviewRow>
        <ReviewRow label="Rekrutacja">
          <span className="line-clamp-1" title={d.recruitment?.job_title}>
            {d.recruitment?.job_title ?? "bez rekrutacji"}
          </span>
        </ReviewRow>
        <ReviewRow label="Typ i okres">
          {type} · od {fmtDate(d.startDate)} ({relDays(d.startDate)}) ·{" "}
          {d.contractType === "b2b" ? "bezterminowo" : d.endDate ? `do ${fmtDate(d.endDate)}` : "bez daty końca"}
          {edit(2)}
        </ReviewRow>
        <ReviewRow label="Stawki">
          <span className="tabular-nums">
            klient {d.clientRateNum != null ? `${fmtNum(d.clientRateNum)} zł/h` : "—"} · konsultant{" "}
            {d.candidateRateNum != null ? `${fmtNum(d.candidateRateNum)} zł/h` : "—"}
          </span>
        </ReviewRow>
        <ReviewRow label="Marża">
          {d.margin ? (
            <span className={cn("tabular-nums", d.margin.perHour < 0 ? "text-destructive" : "text-success")}>
              {fmtNum(d.margin.perHour)} zł/h · {d.margin.pct} · ≈ {fmtPln(d.margin.monthly)}/mies. ({d.hoursNum} h)
            </span>
          ) : (
            <span className="text-muted-foreground">brak — wpisz obie stawki</span>
          )}
        </ReviewRow>
        <ReviewRow label="Opcjonalne">
          {missingOptional.length === 0 ? (
            <span>
              {mode} · line manager: {d.lineManager}
            </span>
          ) : (
            <span className="text-muted-foreground">
              Nie podano: {missingOptional.join(", ")} — uzupełnisz później na stronie kontraktu.
            </span>
          )}
        </ReviewRow>
      </dl>
      <div className="mt-3 rounded-lg bg-info-muted px-3.5 py-2.5 text-[12.5px] leading-[18px] text-info-muted-foreground">
        <p>
          <span className="font-semibold">Po utworzeniu: {d.createAs === "draft" ? "szkic" : CREATE_AS_OPTIONS.find((o) => o.value === d.createAs)?.label.toLowerCase()}.</span>{" "}
          {d.createAs === "draft"
            ? "Aktywujesz go po podpisaniu umowy. Umowę z Generatora, dokumenty i aneksy dodasz na stronie kontraktu."
            : "Wpis umowy już podpisanej — wymaga kompletu stawek."}
        </p>
        {statusOpen ? (
          <div className="mt-2 flex items-center gap-2">
            <span>Status przy utworzeniu:</span>
            <SegmentedRadio<CreateAsKey>
              label="Status przy utworzeniu"
              size="sm"
              value={d.createAs}
              onChange={d.setCreateAs}
              options={CREATE_AS_OPTIONS}
            />
          </div>
        ) : (
          <button type="button" onClick={() => setStatusOpen(true)} className="mt-1 font-medium underline underline-offset-2">
            Umowa już podpisana albo zakończona? Zmień status przy utworzeniu
          </button>
        )}
      </div>
    </StepCard>
  );
}

export function NewA() {
  const params = useSearchParams();
  const asked = Number(params.get("krok"));
  const [step, setStep] = useState<Step>(asked === 1 || asked === 3 ? asked : 2);
  const d = useNewContractDraft();

  if (d.loading) return <p className="text-sm text-muted-foreground">Ładowanie danych ze stagingu…</p>;
  if (d.error) return <p className="text-sm text-destructive">Nie udało się pobrać kontraktu ze stagingu.</p>;

  const notes: Record<Step, string> = {
    1: `${d.candidateName} → ${d.clientName}`,
    2:
      step < 2
        ? "start i stawki"
        : d.margin
          ? `od ${fmtDate(d.startDate)} · marża ${fmtNum(d.margin.perHour)} zł/h`
          : `od ${fmtDate(d.startDate)}`,
    3: "powstaje szkic",
  };

  return (
    <div className="mx-auto max-w-[800px] space-y-3">
      <PageIntro subtitle="Trzy kroki. Kontrakt powstaje jako szkic — umowę, dokumenty i aneksy dodasz po utworzeniu." />
      <Stepper step={step} onGo={setStep} notes={notes} />
      {step === 2 ? <WhoSummary d={d} onChange={() => setStep(1)} /> : null}
      {step === 1 ? (
        <StepWho d={d} onNext={() => setStep(2)} />
      ) : step === 2 ? (
        <StepTerms d={d} onBack={() => setStep(1)} onNext={() => setStep(3)} />
      ) : (
        <StepReview d={d} onBack={() => setStep(2)} onEdit={setStep} />
      )}
    </div>
  );
}
