"use client";
// A · Generator umów jako „kreator z podglądem”. Dziś: 7 zakładek na górze
// (ostatnia ucięta przy 1280 px), formularz na ok. 3 ekrany i nie widać, ile
// brakuje do pobrania umowy. Tu: 5 krótszych zakładek (trzy rejestry umów
// w jednej zakładce „Umowy” z filtrem fazy), po lewej lista 7 kroków ze
// stanem, w środku formularz jednego kroku, po prawej pierwszy akapit umowy
// na „kartce”, wypełniany tym, co się wpisuje — braki są w tekście umowy jako
// wyróżnione „[REGON]”, „[adres z CEIDG]”.
//
// Dane na żywo ze stagingu (tylko GET): osoba i klient z kontraktu 199,
// rekrutacja z listy rekrutacji kandydata, rekruter / DL / stawka / start
// z `/b2b-generator/prefill`, numer z `/next-number`, obszary z `/roles`.
// NIP, REGON, adres, e-mail i telefon celowo puste — to braki do pokazania.
// Tekst „kartki” odpowiada szablonowi `templates/contract/umowa_b2b_pl.html`.
// Nic się nie zapisuje. `?krok=zrodlo|admin|partner|klient|obszar|warunki|pobierz`.
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Download, Eye, Lock, Plus, Sparkles } from "lucide-react";
import api, { b2bGeneratorApi, type AgreementFte, type B2BRole } from "@/lib/api";
import { prefillRateSource } from "@/lib/b2b-agreement";
import { instrumentalPl } from "@/lib/b2b-agreement-preview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useMkContract } from "../shared/data";
import { fmtDate, plural, today } from "../shared/format";
import { PickerButton, type MkRecruitmentOption } from "./NewA";

// ── Wspólne z wariantem B (GeneratorB importuje stąd) ───────────────────────

/** Kontrakt na stagingu, z którego makieta bierze osobę i klienta. */
export const GEN_SOURCE_CONTRACT_ID = 199;

export type GenSectionKey = "zrodlo" | "admin" | "partner" | "klient" | "obszar" | "warunki";

export const GEN_SECTIONS: { key: GenSectionKey; label: string }[] = [
  { key: "zrodlo", label: "Źródło danych" },
  { key: "admin", label: "Szczegóły administracyjne" },
  { key: "partner", label: "Partner" },
  { key: "klient", label: "Klient i projekt" },
  { key: "obszar", label: "Obszar usług" },
  { key: "warunki", label: "Warunki" },
];

export const BRAKI: [string, string, string] = ["brak", "braki", "braków"];
const POLA: [string, string, string] = ["pole", "pola", "pól"];

export interface GenMissing {
  section: GenSectionKey;
  label: string;
}

type StartMode = "exact" | "not_earlier" | "not_later";
const START_MODES: { value: StartMode; label: string }[] = [
  { value: "exact", label: "z dniem" },
  { value: "not_earlier", label: "nie wcześniej niż" },
  { value: "not_later", label: "nie później niż" },
];
const PHONE_PREFIXES = ["+48", "+44", "+49", "+380", "+375", "+1", "+33", "+39", "+34", "+31", "+420", "+421"];
const FTE_OPTIONS: { value: AgreementFte; label: string }[] = [
  { value: "1", label: "1" },
  { value: "0.75", label: "0,75" },
  { value: "0.5", label: "0,5" },
  { value: "0.25", label: "0,25" },
];

/** Rekrutacja do umowy: zatrudnienie u klienta kontraktu, inaczej pierwsza u niego. */
function pickRecruitment(list: MkRecruitmentOption[], clientId: number | null): MkRecruitmentOption | null {
  const atClient = list.filter((r) => clientId == null || r.client_id === clientId);
  return atClient.find((r) => r.stage === "hired") ?? atClient[0] ?? list[0] ?? null;
}

/** Lustro `smartDescription` z Generatora: obszar wypełnia opis projektu. */
function areaDescription(role: B2BRole, lang: "pl" | "en", client: string): string {
  const area = lang === "pl" ? role.area_label_pl : role.area_label_en;
  const scope = (lang === "pl" ? role.scope_pl : role.scope_en).slice(0, 3);
  const who = client.trim();
  if (lang === "en") {
    const lead = `The Partner provides services in the area of ${area}${who ? ` for the Client ${who}` : ""}.`;
    return scope.length ? `${lead} The scope includes, among others: ${scope.join("; ")}.` : lead;
  }
  const lead = `Partner świadczy usługi w obszarze: ${area}${who ? ` na rzecz Klienta ${who}` : ""}.`;
  return scope.length ? `${lead} Zakres obejmuje m.in.: ${scope.join("; ")}.` : lead;
}

/** Stan formularza umowy B2B z wartościami domyślnymi ze stagingu. */
export function useGeneratorDraft() {
  const contractQ = useMkContract(GEN_SOURCE_CONTRACT_ID);
  const c = contractQ.data;
  const candidateId = c?.candidate_id ?? null;

  const recruitmentsQ = useQuery({
    queryKey: ["mk-gen-recruitments", candidateId],
    queryFn: () =>
      api
        .get<MkRecruitmentOption[]>(`/api/cv-generator/candidates/${candidateId}/recruitments`)
        .then((r) => r.data),
    enabled: candidateId != null,
  });
  const numberQ = useQuery({ queryKey: ["mk-gen-next-number"], queryFn: () => b2bGeneratorApi.nextNumber() });
  const rolesQ = useQuery({ queryKey: ["mk-gen-roles"], queryFn: () => b2bGeneratorApi.roles() });

  const [jobChoice, setJobChoice] = useState<string | null>(null);
  const recruitments = recruitmentsQ.data ?? [];
  const auto = pickRecruitment(recruitments, c?.client_id ?? null);
  const jobValue = jobChoice ?? (auto ? String(auto.job_id) : "");
  const recruitment = recruitments.find((r) => String(r.job_id) === jobValue) ?? null;
  const jobId = recruitment?.job_id ?? null;

  const prefillQ = useQuery({
    queryKey: ["mk-gen-prefill", candidateId, jobId],
    queryFn: () => b2bGeneratorApi.prefill(candidateId ?? 0, jobId ?? 0),
    enabled: candidateId != null && jobId != null,
    retry: false,
  });
  const jobQ = useQuery({
    queryKey: ["mk-gen-job", jobId],
    queryFn: () =>
      api.get<{ location: string | null; client_name: string | null }>(`/api/jobs/${jobId}`).then((r) => r.data),
    enabled: jobId != null,
    retry: false,
  });
  const prefill = prefillQ.data ?? null;
  const admin = prefill?.admin ?? null;

  const [language, setLanguage] = useState<"pl" | "en">("pl");
  const [replacement, setReplacement] = useState<boolean | null>(null);
  const [fte, setFte] = useState<AgreementFte | null>(null);
  const [clientReferral, setClientReferral] = useState<boolean | null>(null);
  const [variant, setVariant] = useState<"jdg" | "company">("jdg");
  const [gender, setGender] = useState<"m" | "k">("m");
  const [partnerName, setPartnerName] = useState<string | null>(null);
  const [instrumental, setInstrumental] = useState<string | null>(null);
  const [nip, setNip] = useState("");
  const [regon, setRegon] = useState("");
  const [legalName, setLegalName] = useState("");
  const [address, setAddress] = useState("");
  const [addressForService, setAddressForService] = useState(false);
  const [correspondenceOpen, setCorrespondenceOpen] = useState(false);
  const [correspondence, setCorrespondence] = useState("");
  const [email, setEmail] = useState("");
  const [phonePrefix, setPhonePrefix] = useState("+48");
  const [phone, setPhone] = useState("");
  const [clientName, setClientName] = useState<string | null>(null);
  const [city, setCity] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [roleId, setRoleId] = useState("");
  const [number, setNumber] = useState<string | null>(null);
  const [signingDate, setSigningDate] = useState(today());
  const [startMode, setStartMode] = useState<StartMode>("exact");
  const [startDate, setStartDate] = useState<string | null>(null);
  const [rate, setRate] = useState<string | null>(null);
  const [currency, setCurrency] = useState("PLN");

  // Domyślne „Szczegóły administracyjne” po wybraniu rekrutacji — jak
  // `adminDefaults`: replacement z tytułu rekrutacji, FTE 1, „wskazany” Nie.
  const adminLoaded = prefill != null;
  const replacementValue = replacement ?? (adminLoaded ? Boolean(admin?.replacement_from_title) : null);
  const fteValue = fte ?? (adminLoaded ? "1" : null);
  const clientReferralValue = clientReferral ?? (adminLoaded ? false : null);
  const partnerNameValue = partnerName ?? c?.candidate_name ?? "";
  const instrumentalValue = instrumental ?? instrumentalPl(partnerNameValue, gender);
  const clientNameValue = clientName ?? jobQ.data?.client_name ?? recruitment?.client_name ?? c?.client_name ?? "";
  const cityValue = city ?? jobQ.data?.location ?? "";
  const roles = rolesQ.data ?? [];
  const role = roles.find((r) => String(r.id) === roleId) ?? null;
  const descriptionValue = description ?? (role ? areaDescription(role, language, clientNameValue) : "");
  const numberValue = number ?? numberQ.data?.contract_number ?? "";
  const startDateValue = startDate ?? prefill?.start_date ?? "";
  const rateValue = rate ?? (prefill?.rate ? String(prefill.rate.value) : "");
  const nipDigits = nip.replace(/\D/g, "");

  const missing: GenMissing[] = [];
  const need = (section: GenSectionKey, label: string, ok: boolean) => {
    if (!ok) missing.push({ section, label });
  };
  need("zrodlo", "Kandydat", Boolean(c));
  need("zrodlo", "Rekrutacja", recruitment != null);
  need("admin", "Replacement", replacementValue !== null);
  need("admin", "Wymiar FTE", fteValue !== null);
  need("partner", "Imię i nazwisko", partnerNameValue.trim() !== "");
  need("partner", "Narzędnik", instrumentalValue.trim() !== "");
  need("partner", "NIP", nipDigits.length === 10);
  need("partner", "REGON", regon.trim() !== "");
  need("partner", "Nazwa firmy", legalName.trim() !== "");
  need("partner", variant === "company" ? "Adres siedziby" : "Adres z CEIDG", address.trim() !== "");
  need("partner", "E-mail", email.trim() !== "");
  need("partner", "Telefon", phone.trim() !== "");
  need("klient", "Pełna nazwa Klienta", clientNameValue.trim() !== "");
  need("klient", "Miasto Klienta", cityValue.trim() !== "");
  need("klient", "Opis projektu", descriptionValue.trim() !== "");
  need("obszar", "Obszar usług", role != null);
  need("warunki", "Numer umowy", numberValue.trim() !== "");
  need("warunki", "Data podpisania", signingDate !== "");
  need("warunki", "Data rozpoczęcia usług", startDateValue !== "");
  need("warunki", "Stawka godzinowa", Number(rateValue.replace(",", ".")) > 0);

  return {
    loading: contractQ.isLoading,
    error: contractQ.isError,
    candidateName: c?.candidate_name ?? "",
    recruitments,
    recruitmentsLoading: recruitmentsQ.isLoading,
    jobValue,
    setJobChoice,
    recruitment,
    recruiter: admin?.recruiter ?? null,
    deliveryLead: admin?.delivery_lead ?? null,
    adminLoading: prefillQ.isLoading,
    language,
    setLanguage,
    replacement: replacementValue,
    setReplacement,
    fte: fteValue,
    setFte,
    clientReferral: clientReferralValue,
    setClientReferral,
    variant,
    setVariant,
    gender,
    setGender,
    partnerName: partnerNameValue,
    setPartnerName,
    instrumental: instrumentalValue,
    instrumentalAuto: instrumental == null,
    setInstrumental,
    nip,
    setNip,
    regon,
    setRegon,
    legalName,
    setLegalName,
    address,
    setAddress,
    addressForService,
    setAddressForService,
    correspondenceOpen,
    setCorrespondenceOpen,
    correspondence,
    setCorrespondence,
    email,
    setEmail,
    phonePrefix,
    setPhonePrefix,
    phone,
    setPhone,
    clientName: clientNameValue,
    setClientName,
    city: cityValue,
    cityFromJob: city == null && Boolean(jobQ.data?.location),
    setCity,
    description: descriptionValue,
    descriptionFromArea: description == null && role != null,
    setDescription,
    roles,
    role,
    roleId,
    setRoleId,
    number: numberValue,
    setNumber,
    signingDate,
    setSigningDate,
    startMode,
    setStartMode,
    startDate: startDateValue,
    setStartDate,
    availability: prefill?.availability_text ?? null,
    rate: rateValue,
    rateHint: rate == null && prefill?.rate ? prefillRateSource(prefill.rate) : null,
    setRate,
    currency,
    setCurrency,
    missing,
  };
}

export type GenDraft = ReturnType<typeof useGeneratorDraft>;

export function missingIn(d: GenDraft, key: GenSectionKey): GenMissing[] {
  return d.missing.filter((m) => m.section === key);
}

/** „NIP, REGON, Nazwa firmy …” — lista braków do paska i kroku „Pobierz”. */
export function missingLabel(d: GenDraft): string {
  return d.missing.map((m) => m.label).join(", ");
}

export function missingCountLabel(n: number): string {
  return `Brakuje ${plural(n, POLA)}`;
}

/** Krótki stan sekcji do listy kroków / spisu sekcji. */
export function sectionNote(d: GenDraft, key: GenSectionKey): string {
  const n = missingIn(d, key).length;
  if (key === "obszar" && !d.role) return "do wyboru";
  if (n > 0) return plural(n, BRAKI);
  switch (key) {
    case "zrodlo":
      return [d.candidateName, d.recruitment?.client_name].filter(Boolean).join(" · ");
    case "admin":
      return `${d.replacement ? "replacement" : "bez replacementu"} · ${(d.fte ?? "1").replace(".", ",")} FTE`;
    case "partner":
      return d.legalName || d.partnerName;
    case "klient":
      return [d.clientName, d.city].filter(Boolean).join(" · ");
    case "obszar":
      return d.role ? (d.language === "pl" ? d.role.name_pl : d.role.name_en) : "do wyboru";
    case "warunki":
      return `${d.number} · od ${fmtDate(d.startDate)} · ${d.rate} zł/h`;
  }
}

/** Pole formularza generatora: etykieta, kropka „puste wymagane”, podpowiedź. */
export function GField({
  label,
  htmlFor,
  required,
  missing,
  full,
  hint,
  tag,
  action,
  children,
}: {
  label: string;
  htmlFor?: string;
  required?: boolean;
  missing?: boolean;
  full?: boolean;
  hint?: React.ReactNode;
  /** Krótka adnotacja w linii etykiety, np. „auto” (wyjaśnienie w `title`). */
  tag?: { text: string; title: string };
  /** Rzadka akcja przy polu, wyrównana do prawej w linii etykiety. */
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("min-w-0", full && "col-span-2")}>
      <Label htmlFor={htmlFor} className="mb-1 flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
        <span>
          {label}
          {required ? <span className="text-destructive"> *</span> : null}
        </span>
        {tag && !missing ? (
          <span className="text-[11px] font-normal text-muted-foreground" title={tag.title}>
            {tag.text}
          </span>
        ) : null}
        {missing ? (
          <span
            className="inline-flex items-center gap-1 text-[11px] font-normal text-warning-muted-foreground"
            title="Pole wymagane — puste"
          >
            <span aria-hidden className="size-1.5 rounded-full bg-warning" />
            brak
          </span>
        ) : null}
        {action ? <span className="ml-auto text-[11.5px] font-normal">{action}</span> : null}
      </Label>
      {children}
      {hint ? <div className="mt-1 text-[11.5px] leading-4 text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function ReadOnlyPerson({ name, empty }: { name: string | null | undefined; empty: string }) {
  return (
    <div className="flex h-9 items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 text-sm">
      <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <span className={cn("truncate", name ? "text-foreground" : "text-muted-foreground")}>{name || empty}</span>
    </div>
  );
}

const YES_NO = [
  { value: "tak", label: "Tak" },
  { value: "nie", label: "Nie" },
] as const;
type YesNo = (typeof YES_NO)[number]["value"];
const yesNo = (v: boolean | null): YesNo | null => (v == null ? null : v ? "tak" : "nie");

/** `dense` — trzy kolumny w jednej linii (wariant B, sekcja zwykle już kompletna). */
export function GenSourceFields({ d, dense }: { d: GenDraft; dense?: boolean }) {
  return (
    <div
      className={cn(
        "grid gap-x-3.5 gap-y-3",
        dense ? "grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)_auto]" : "grid-cols-2",
      )}
    >
      <GField label="Kandydat" htmlFor="mk-gen-cand" required>
        <PickerButton id="mk-gen-cand" value={d.candidateName} placeholder="Wybierz kandydata…" />
      </GField>
      <GField label="Rekrutacja" htmlFor="mk-gen-job" required missing={!d.recruitment}>
        <Select value={d.jobValue} onValueChange={d.setJobChoice} disabled={d.recruitments.length === 0}>
          <SelectTrigger id="mk-gen-job" className="h-9 [&>span]:truncate [&>span]:text-left" title={d.recruitment?.job_title}>
            <SelectValue placeholder={d.recruitmentsLoading ? "Wczytuję rekrutacje…" : "Wybierz rekrutację…"} />
          </SelectTrigger>
          <SelectContent>
            {d.recruitments.map((r) => (
              <SelectItem key={r.job_id} value={String(r.job_id)}>
                {r.job_title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </GField>
      <GField
        label="Język umowy"
        full={!dense}
        hint={dense ? null : "Rekrutacja wiąże umowę z kontraktem po podpisie — bez zgadywania po nazwisku i nazwie klienta."}
      >
        <SegmentedRadio<"pl" | "en">
          label="Język umowy"
          size="sm"
          value={d.language}
          onChange={d.setLanguage}
          options={[
            { value: "pl", label: "Polski" },
            { value: "en", label: "English" },
          ]}
        />
      </GField>
    </div>
  );
}

export function GenAdminFields({ d, dense }: { d: GenDraft; dense?: boolean }) {
  return (
    <div className={cn("grid gap-x-3.5 gap-y-3", dense ? "grid-cols-3" : "grid-cols-2")}>
      <GField label="Rekruter (premia za placement)" hint={d.recruiter?.source_label ?? "z rekrutacji"}>
        <ReadOnlyPerson name={d.recruiter?.name} empty={d.adminLoading ? "Wczytuję…" : "Uzupełni się po wybraniu rekrutacji"} />
      </GField>
      <GField label="Delivery Lead (premia DL)" hint={d.deliveryLead?.source_label ?? "z rekrutacji"}>
        <ReadOnlyPerson name={d.deliveryLead?.name} empty={d.adminLoading ? "Wczytuję…" : "Brak Delivery Leada u klienta"} />
      </GField>
      <GField label="Replacement" required missing={d.replacement === null}>
        <SegmentedRadio<YesNo>
          label="Replacement"
          size="sm"
          value={yesNo(d.replacement)}
          onChange={(v) => d.setReplacement(v === "tak")}
          options={YES_NO}
        />
      </GField>
      <GField label="Wymiar FTE" required missing={d.fte === null}>
        <SegmentedRadio<AgreementFte> label="Wymiar FTE" size="sm" value={d.fte} onChange={d.setFte} options={FTE_OPTIONS} />
      </GField>
      <GField
        label="Kandydat wskazany przez klienta"
        full
        hint="„Tak” — premii z placementu nie dostaje ani rekruter, ani Delivery Lead."
      >
        <SegmentedRadio<YesNo>
          label="Kandydat wskazany przez klienta"
          size="sm"
          value={yesNo(d.clientReferral)}
          onChange={(v) => d.setClientReferral(v === "tak")}
          options={YES_NO}
        />
      </GField>
    </div>
  );
}

export function GenPartnerFields({ d }: { d: GenDraft }) {
  const company = d.variant === "company";
  return (
    <div className="grid grid-cols-2 gap-x-3.5 gap-y-2.5">
      <div className="col-span-2 flex flex-wrap items-center gap-2">
        <SegmentedRadio<"jdg" | "company">
          label="Wariant umowy"
          size="sm"
          value={d.variant}
          onChange={d.setVariant}
          options={[
            { value: "jdg", label: "Umowa JDG" },
            { value: "company", label: "Umowa spółka" },
          ]}
        />
        <SegmentedRadio<"m" | "k">
          label={company ? "Płeć osoby reprezentującej" : "Płeć Partnera"}
          size="sm"
          value={d.gender}
          onChange={d.setGender}
          options={[
            { value: "m", label: "Mężczyzna" },
            { value: "k", label: "Kobieta" },
          ]}
        />
      </div>
      {company ? (
        <p className="col-span-2 rounded-lg bg-muted/70 px-3 py-2 text-[12px] leading-4 text-muted-foreground">
          Umowa spółka dokłada pola z KRS: numer KRS, siedzibę, sąd rejestrowy, kapitał zakładowy i osobę reprezentującą
          (makieta pokazuje pola JDG).
        </p>
      ) : null}
      <GField label="Imię i nazwisko" htmlFor="mk-gen-name" required missing={!d.partnerName.trim()}>
        <Input id="mk-gen-name" value={d.partnerName} onChange={(e) => d.setPartnerName(e.target.value)} className="h-9" />
      </GField>
      <GField
        label="W umowie (narzędnik)"
        htmlFor="mk-gen-instr"
        required
        missing={!d.instrumental.trim()}
        tag={
          d.instrumentalAuto
            ? { text: "· auto", title: "Odmienione samo z imienia i nazwiska — popraw przy nietypowym nazwisku." }
            : { text: "· ręcznie", title: "Odmiana poprawiona ręcznie." }
        }
      >
        <Input
          id="mk-gen-instr"
          value={d.instrumental}
          onChange={(e) => d.setInstrumental(e.target.value)}
          className="h-9"
        />
      </GField>
      <GField label="NIP" htmlFor="mk-gen-nip" required missing={d.nip.replace(/\D/g, "").length !== 10}>
        <Input
          id="mk-gen-nip"
          value={d.nip}
          onChange={(e) => d.setNip(e.target.value)}
          placeholder="10 cyfr — reszta z rejestru"
          inputMode="numeric"
          className="h-9 tabular-nums"
        />
      </GField>
      <GField label="REGON" htmlFor="mk-gen-regon" required missing={!d.regon.trim()}>
        <Input
          id="mk-gen-regon"
          value={d.regon}
          onChange={(e) => d.setRegon(e.target.value)}
          placeholder="uzupełni się po NIP"
          className="h-9 tabular-nums"
        />
      </GField>
      <GField label="Nazwa firmy" htmlFor="mk-gen-legal" required full missing={!d.legalName.trim()}>
        <Input
          id="mk-gen-legal"
          value={d.legalName}
          onChange={(e) => d.setLegalName(e.target.value)}
          placeholder="uzupełni się po NIP"
          className="h-9"
        />
      </GField>
      <GField
        label={company ? "Adres siedziby" : "Adres z CEIDG"}
        htmlFor="mk-gen-addr"
        required
        full
        missing={!d.address.trim()}
        action={
          d.correspondenceOpen ? null : (
            <button
              type="button"
              onClick={() => d.setCorrespondenceOpen(true)}
              className="font-medium text-primary hover:underline"
            >
              + adres do korespondencji
            </button>
          )
        }
        hint={
          company ? null : (
            <span>
              W umowie „pod adresem{d.addressForService ? " do doręczeń" : ""}: …” ·{" "}
              <button
                type="button"
                onClick={() => d.setAddressForService(!d.addressForService)}
                className="font-medium text-primary hover:underline"
              >
                {d.addressForService ? "to stałe miejsce działalności" : "to tylko adres do doręczeń"}
              </button>
            </span>
          )
        }
      >
        <Input
          id="mk-gen-addr"
          value={d.address}
          onChange={(e) => d.setAddress(e.target.value)}
          placeholder="uzupełni się po NIP"
          className="h-9"
        />
      </GField>
      <GField label="E-mail" htmlFor="mk-gen-email" required missing={!d.email.trim()}>
        <Input id="mk-gen-email" type="email" value={d.email} onChange={(e) => d.setEmail(e.target.value)} className="h-9" />
      </GField>
      <GField label="Telefon" htmlFor="mk-gen-phone" required missing={!d.phone.trim()}>
        <div className="flex gap-1.5">
          <Select value={d.phonePrefix} onValueChange={d.setPhonePrefix}>
            <SelectTrigger className="h-9 w-[78px] shrink-0 px-2.5" aria-label="Kierunkowy">
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
            id="mk-gen-phone"
            value={d.phone}
            onChange={(e) => d.setPhone(e.target.value)}
            inputMode="tel"
            className="h-9 tabular-nums"
          />
        </div>
      </GField>
      {d.correspondenceOpen ? (
        <GField label="Adres do korespondencji (opcjonalnie)" htmlFor="mk-gen-corr" full>
          <Input
            id="mk-gen-corr"
            value={d.correspondence}
            onChange={(e) => d.setCorrespondence(e.target.value)}
            className="h-9"
          />
        </GField>
      ) : null}
    </div>
  );
}

export function GenClientFields({ d }: { d: GenDraft }) {
  return (
    <div className="grid grid-cols-2 gap-x-3.5 gap-y-3">
      <GField label="Pełna nazwa Klienta" htmlFor="mk-gen-client" required missing={!d.clientName.trim()} hint="z rekrutacji">
        <PickerButton id="mk-gen-client" value={d.clientName} placeholder="Wybierz lub wpisz klienta…" />
      </GField>
      <GField
        label="Miasto Klienta"
        htmlFor="mk-gen-city"
        required
        missing={!d.city.trim()}
        hint={d.cityFromJob ? "z rekrutacji" : null}
      >
        <Input id="mk-gen-city" value={d.city} onChange={(e) => d.setCity(e.target.value)} placeholder="np. Warszawa" className="h-9" />
      </GField>
      <GField
        label="Opis projektu i zakres usług"
        htmlFor="mk-gen-desc"
        required
        full
        missing={!d.description.trim()}
        hint={
          d.descriptionFromArea
            ? "Wpisany z obszaru usług — możesz go zmienić."
            : d.description.trim()
              ? null
              : "Wpisze się sam po wyborze obszaru usług — albo wpisz własny."
        }
      >
        <Textarea
          id="mk-gen-desc"
          rows={3}
          value={d.description}
          onChange={(e) => d.setDescription(e.target.value)}
          className="min-h-[72px] text-[13px]"
        />
      </GField>
      <div className="col-span-2">
        <Button type="button" variant="outline" size="sm" disabled={!d.description.trim()}>
          <Sparkles className="size-3.5" aria-hidden />
          Sprawdź opis pod kątem umowy o pracę (AI)
        </Button>
      </div>
    </div>
  );
}

export function GenAreaFields({ d }: { d: GenDraft }) {
  const groups = new Map<string, B2BRole[]>();
  for (const r of d.roles) {
    const key = d.language === "pl" ? r.category_label_pl : r.category_label_en;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return (
    <div className="grid grid-cols-2 gap-x-3.5 gap-y-3">
      <GField
        label="Obszar usług (§ 1 umowy)"
        htmlFor="mk-gen-role"
        required
        full
        missing={!d.role}
        hint="Wpisze obszar specjalizacji do § 1 i gotowy opis projektu, jeśli opisu nie zmieniano ręcznie."
      >
        <Select value={d.roleId} onValueChange={d.setRoleId}>
          <SelectTrigger id="mk-gen-role" className="h-9">
            <SelectValue placeholder={d.roles.length ? `Wybierz obszar (${d.roles.length})…` : "Wczytuję obszary…"} />
          </SelectTrigger>
          <SelectContent>
            {[...groups.entries()].map(([label, items]) => (
              <SelectGroup key={label}>
                <SelectLabel>{label}</SelectLabel>
                {items.map((r) => (
                  <SelectItem key={r.id} value={String(r.id)}>
                    {d.language === "pl" ? r.name_pl : r.name_en}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </GField>
    </div>
  );
}

export function GenTermsFields({ d }: { d: GenDraft }) {
  return (
    <div className="grid grid-cols-2 gap-x-3.5 gap-y-3">
      <GField
        label="Numer umowy"
        htmlFor="mk-gen-number"
        required
        missing={!d.number.trim()}
        hint="Kolejny wolny numer; zajmie go dopiero pobranie."
      >
        <Input id="mk-gen-number" value={d.number} onChange={(e) => d.setNumber(e.target.value)} className="h-9 tabular-nums" />
      </GField>
      <GField label="Data podpisania" htmlFor="mk-gen-sign" required missing={!d.signingDate}>
        <Input
          id="mk-gen-sign"
          type="date"
          value={d.signingDate}
          onChange={(e) => d.setSigningDate(e.target.value)}
          className="h-9 tabular-nums"
        />
      </GField>
      <GField
        label="Rozpoczęcie usług"
        htmlFor="mk-gen-start"
        required
        full
        missing={!d.startDate}
        hint={d.availability ? `Dostępność ze screeningu: ${d.availability}` : null}
      >
        <div className="flex gap-1.5">
          <Select value={d.startMode} onValueChange={(v) => d.setStartMode(v as StartMode)}>
            <SelectTrigger className="h-9 w-[170px] shrink-0" aria-label="Tryb daty rozpoczęcia">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {START_MODES.map((m) => (
                <SelectItem key={m.value} value={m.value}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            id="mk-gen-start"
            type="date"
            value={d.startDate}
            onChange={(e) => d.setStartDate(e.target.value)}
            className="h-9 tabular-nums"
          />
        </div>
      </GField>
      <GField
        label="Stawka godzinowa netto"
        htmlFor="mk-gen-rate"
        required
        missing={!(Number(d.rate.replace(",", ".")) > 0)}
        hint={d.rateHint ? `Stawka ${d.rateHint}` : "Słownie policzy się sama."}
      >
        <Input
          id="mk-gen-rate"
          value={d.rate}
          onChange={(e) => d.setRate(e.target.value)}
          inputMode="decimal"
          className="h-9 tabular-nums"
          trailingIcon={<span className="text-xs">{d.currency === "PLN" ? "zł/h" : `${d.currency}/h`}</span>}
        />
      </GField>
      <GField label="Waluta" htmlFor="mk-gen-cur">
        <Select value={d.currency} onValueChange={d.setCurrency}>
          <SelectTrigger id="mk-gen-cur" className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["PLN", "EUR", "USD", "GBP"].map((cur) => (
              <SelectItem key={cur} value={cur}>
                {cur}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </GField>
      <div className="col-span-2 flex items-center gap-3">
        <Button type="button" variant="outline" size="sm">
          <Plus className="size-3.5" aria-hidden />
          Dodaj etap stawki
        </Button>
        <span className="text-[11.5px] text-muted-foreground">Stawka progresywna: każdy etap z okresem obowiązywania.</span>
      </div>
    </div>
  );
}

export const GEN_FIELDS: Record<GenSectionKey, (props: { d: GenDraft; dense?: boolean }) => React.ReactNode> = {
  zrodlo: GenSourceFields,
  admin: GenAdminFields,
  partner: GenPartnerFields,
  klient: GenClientFields,
  obszar: GenAreaFields,
  warunki: GenTermsFields,
};

export const GEN_SECTION_INTRO: Record<GenSectionKey, string> = {
  zrodlo: "Kandydat i jego rekrutacja — z nich zaciągają się dane i po podpisie powstaje kontrakt.",
  admin: "Kto dostanie placement i premię po 168 h. Rekruter i DL wynikają z rekrutacji.",
  partner: "Wpisz NIP — nazwę firmy, REGON i adres pobierzemy z rejestru.",
  klient: "Klient i opis projektu trafiają do Załącznika nr 3.",
  obszar: "Obszar specjalizacji Partnera w § 1 umowy.",
  warunki: "Numer, daty i stawka do § 6 i § 13.",
};

function Gap({ children }: { children: string }) {
  return (
    <mark className="rounded-[3px] bg-warning-muted px-1 py-px text-[10.5px] font-semibold text-warning-muted-foreground">
      [{children}]
    </mark>
  );
}

function Val({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[3px] bg-primary/8 px-0.5">{children}</span>;
}

const FORMS = {
  m: { pan: "Panem", prowadzacy: "prowadzącym", zwany: "zwany" },
  k: { pan: "Panią", prowadzacy: "prowadzącą", zwany: "zwana" },
} as const;

/** Pierwszy akapit umowy (komparycja) z szablonu, wypełniany na żywo. */
export function PaperPreview({ d }: { d: GenDraft }) {
  const g = FORMS[d.gender];
  const company = d.variant === "company";
  const gaps = missingIn(d, "partner").length + (d.number.trim() ? 0 : 1);
  const v = (value: string, gap: string) => (value.trim() ? <Val>{value}</Val> : <Gap>{gap}</Gap>);
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-[12.5px] font-semibold text-foreground">Podgląd na żywo</p>
        <p className={cn("text-[11.5px]", gaps ? "text-warning-muted-foreground" : "text-success")}>
          {gaps ? `${plural(gaps, BRAKI)} w tym akapicie` : "akapit kompletny"}
        </p>
      </div>
      <article
        aria-label="Podgląd pierwszego akapitu umowy"
        className="relative overflow-hidden rounded-[3px] border border-border bg-card px-5 pb-8 pt-5 text-[11.5px] leading-[1.6] text-foreground shadow-md"
      >
        <p className="text-center text-[12.5px] font-bold">Umowa o współpracę B2B</p>
        <p className="mb-2 text-center text-[12px] font-semibold tabular-nums">nr {v(d.number, "numer")}</p>
        <p>
          zawarta w dniu {d.signingDate ? <Val>{fmtDate(d.signingDate)}</Val> : <Gap>data podpisania</Gap>} roku
          w Warszawie pomiędzy:
        </p>
        <p className="mt-1.5 text-muted-foreground">
          <span className="font-semibold text-foreground">B2B.net S.A.</span> z siedzibą w Warszawie (…), dalej jako
          „Spółka” lub „B2BNET”
        </p>
        <p className="mt-1.5">a</p>
        {company ? (
          <p className="mt-1.5">
            <span className="font-semibold">{v(d.legalName, "nazwa spółki")}</span> z siedzibą <Gap>siedziba</Gap>, pod
            adresem {v(d.address, "adres siedziby")}, wpisaną do Rejestru Przedsiębiorców KRS, prowadzonego przez{" "}
            <Gap>sąd rejestrowy</Gap>, pod numerem KRS: <Gap>KRS</Gap>, NIP: {v(d.nip, "NIP")}, REGON:{" "}
            {v(d.regon, "REGON")}, o kapitale zakładowym <Gap>kapitał</Gap>, reprezentowaną przez{" "}
            <Gap>reprezentacja</Gap>,
          </p>
        ) : (
          <p className="mt-1.5">
            <span className="font-semibold">
              {g.pan} {v(d.instrumental, "imię i nazwisko")}
            </span>{" "}
            {g.prowadzacy} działalność gospodarczą pod firmą: {v(d.legalName, "nazwa firmy")}, zarejestrowaną
            w Centralnej Ewidencji i Informacji o Działalności Gospodarczej pod adresem
            {d.addressForService ? " do doręczeń" : ""}: {v(d.address, "adres z CEIDG")}, NIP: {v(d.nip, "NIP")},
            REGON: {v(d.regon, "REGON")},
            {d.correspondence.trim() ? (
              <>
                {" "}
                adres do korespondencji: <Val>{d.correspondence}</Val>,
              </>
            ) : null}
          </p>
        )}
        <p className="mt-1.5">Dane kontaktowe:</p>
        <p>
          Tel. {d.phone.trim() ? <Val>{`${d.phonePrefix} ${d.phone}`}</Val> : <Gap>telefon</Gap>}; Adres e-mail:{" "}
          {v(d.email, "e-mail")}
        </p>
        <p className="mt-1.5">{g.zwany} w dalszej części umowy „Partnerem”</p>
        <p className="mt-1.5 text-muted-foreground">Preambuła: Zważywszy, że: 1) Spółka realizuje usługi…</p>
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-linear-to-b from-transparent to-card" />
      </article>
      {d.language === "en" ? (
        <p className="mt-1.5 text-[11.5px] text-muted-foreground">Umowa po angielsku — makieta pokazuje akapit po polsku.</p>
      ) : null}
    </div>
  );
}

// ── Wariant A ────────────────────────────────────────────────────────────────

type StepKey = GenSectionKey | "pobierz";
const STEP_KEYS: StepKey[] = ["zrodlo", "admin", "partner", "klient", "obszar", "warunki", "pobierz"];

const TABS_A = [
  { key: "nowa", label: "Nowa umowa" },
  { key: "aneks", label: "Nowy aneks" },
  { key: "umowy", label: "Umowy" },
  { key: "dokumenty", label: "Dokumenty" },
  { key: "zakresy", label: "Zakresy ról" },
] as const;
type TabKey = (typeof TABS_A)[number]["key"];

function stepLabel(key: StepKey): string {
  return key === "pobierz" ? "Pobierz" : (GEN_SECTIONS.find((s) => s.key === key)?.label ?? key);
}

function StepList({ d, step, onGo }: { d: GenDraft; step: StepKey; onGo: (s: StepKey) => void }) {
  const ready = d.missing.length === 0;
  return (
    <nav aria-label="Kroki umowy">
      <ol>
        {STEP_KEYS.map((key, i) => {
          const current = key === step;
          const isDownload = key === "pobierz";
          const gaps = isDownload ? d.missing.length : missingIn(d, key).length;
          const done = !isDownload && gaps === 0 && !(key === "obszar" && !d.role);
          const note = isDownload ? (ready ? "gotowe do pobrania" : `brakuje ${plural(gaps, POLA)}`) : sectionNote(d, key);
          return (
            <li key={key} className="relative">
              {i < STEP_KEYS.length - 1 ? (
                <span aria-hidden className="absolute bottom-[-6px] left-[19px] top-[34px] w-px bg-border" />
              ) : null}
              <button
                type="button"
                onClick={() => onGo(key)}
                aria-current={current ? "step" : undefined}
                className={cn(
                  "relative flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors",
                  current ? "bg-card shadow-xs ring-1 ring-border" : "hover:bg-muted/60",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 shrink-0 place-items-center rounded-full text-[11.5px] font-semibold tabular-nums",
                    current
                      ? "bg-primary text-primary-foreground"
                      : done
                        ? "bg-success-muted text-success-muted-foreground"
                        : "border border-border bg-card text-muted-foreground",
                  )}
                >
                  {done && !current ? (
                    <Check className="size-3.5" aria-label="komplet" />
                  ) : isDownload && !ready ? (
                    <Lock className="size-3" aria-label="zablokowane" />
                  ) : (
                    i + 1
                  )}
                </span>
                <span className="min-w-0 pt-px">
                  <span className={cn("block text-[13px] leading-4 text-foreground", current ? "font-semibold" : "font-medium")}>
                    {stepLabel(key)}
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 line-clamp-2 break-words text-[11.5px] leading-4",
                      gaps > 0 || (key === "obszar" && !d.role) ? "text-warning-muted-foreground" : "text-muted-foreground",
                    )}
                    title={note}
                  >
                    {note}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function DownloadStep({ d, onGo }: { d: GenDraft; onGo: (s: StepKey) => void }) {
  const bySection = GEN_SECTIONS.map((s) => ({ ...s, items: missingIn(d, s.key) })).filter((s) => s.items.length > 0);
  const ready = bySection.length === 0;
  return (
    <div className="space-y-3">
      {ready ? (
        <p className="rounded-lg bg-success-muted px-3 py-2 text-[13px] text-success-muted-foreground">
          Wszystko uzupełnione — umowę można pobrać.
        </p>
      ) : (
        <div>
          <p className="mb-1.5 text-[13px] font-semibold text-foreground">{missingCountLabel(d.missing.length)}</p>
          <ul className="divide-y divide-border/60 rounded-lg border border-border">
            {bySection.map((s) => (
              <li key={s.key} className="flex items-center gap-3 px-3 py-2 text-[12.5px] leading-5">
                <span className="w-[120px] shrink-0 font-medium text-foreground">{s.label}</span>
                <span className="min-w-0 flex-1 text-muted-foreground">{s.items.map((m) => m.label).join(", ")}</span>
                <button type="button" onClick={() => onGo(s.key)} className="shrink-0 font-medium text-primary hover:underline">
                  Uzupełnij
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[12px] leading-4 text-muted-foreground">
        Pobranie zajmuje numer {d.number || "umowy"} w rejestrze — każde kolejne pobranie to nowy numer. Podgląd numeru
        nie zajmuje.
      </p>
    </div>
  );
}

function TabPlaceholder({ tab, rolesCount }: { tab: Exclude<TabKey, "nowa">; rolesCount: number }) {
  const [phase, setPhase] = useState<"current" | "no-project" | "closed">("current");
  const text: Record<Exclude<TabKey, "nowa">, string> = {
    aneks: "Generator aneksów i rejestr aneksów — poza zakresem tej makiety.",
    umowy:
      "Jedna lista umów z rejestru zamiast trzech zakładek „Umowy bieżące”, „Umowy bez projektu”, „Zakończone umowy” — faza to filtr. Sama lista poza zakresem tej makiety.",
    dokumenty: "Rozwiązania, wypowiedzenia i umowy przedwstępne — poza zakresem tej makiety.",
    zakresy: `Katalog obszarów usług (${rolesCount}) z zakresem usług PL / EN — edytuje admin. Poza zakresem tej makiety.`,
  };
  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-xs">
      {tab === "umowy" ? (
        <SegmentedRadio<"current" | "no-project" | "closed">
          label="Faza umowy"
          size="sm"
          value={phase}
          onChange={setPhase}
          options={[
            { value: "current", label: "Bieżące" },
            { value: "no-project", label: "Bez projektu" },
            { value: "closed", label: "Zakończone" },
          ]}
        />
      ) : null}
      <p className="text-[13px] text-muted-foreground">{text[tab]}</p>
    </div>
  );
}

function initialStep(raw: string | null): StepKey {
  return STEP_KEYS.find((k) => k === raw) ?? "partner";
}

export function GeneratorA() {
  const params = useSearchParams();
  const d = useGeneratorDraft();
  const [kind, setKind] = useState<"b2b" | "mandate">("b2b");
  const [tab, setTab] = useState<TabKey>("nowa");
  const [step, setStep] = useState<StepKey>(initialStep(params.get("krok")));

  if (d.loading) return <p className="text-sm text-muted-foreground">Ładowanie danych ze stagingu…</p>;
  if (d.error) return <p className="text-sm text-destructive">Nie udało się pobrać danych ze stagingu.</p>;

  const index = STEP_KEYS.indexOf(step);
  const next = STEP_KEYS[index + 1];
  const prev = STEP_KEYS[index - 1];
  const Fields = step === "pobierz" ? null : GEN_FIELDS[step];
  const ready = d.missing.length === 0;

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3">
          <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">Generator umów</h1>
          <SegmentedRadio<"b2b" | "mandate">
            label="Rodzaj umowy"
            size="sm"
            value={kind}
            onChange={setKind}
            options={[
              { value: "b2b", label: "Umowa B2B" },
              { value: "mandate", label: "Umowa zlecenia" },
            ]}
          />
        </div>
        <p className="text-[12.5px] text-muted-foreground">
          Numer <span className="font-medium tabular-nums text-foreground">{d.number || "—"}</span> zajmie się przy
          pobraniu
        </p>
      </header>

      <nav aria-label="Generator umów" className="flex gap-1 border-b border-border">
        {TABS_A.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors",
                active
                  ? "border-primary font-semibold text-foreground"
                  : "border-transparent font-medium text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </nav>

      {tab !== "nowa" ? (
        <TabPlaceholder tab={tab} rolesCount={d.roles.length} />
      ) : (
        <>
          {kind === "mandate" ? (
            <p className="rounded-lg bg-info-muted px-3 py-2 text-[12.5px] text-info-muted-foreground">
              Umowa zlecenia ma ten sam układ z krótszą listą kroków — makieta pokazuje umowę B2B.
            </p>
          ) : null}
          <div className="grid grid-cols-[176px_minmax(0,1fr)_312px] items-start gap-5">
            <StepList d={d} step={step} onGo={setStep} />

            <section className="rounded-xl border border-border bg-card shadow-xs">
              <header className="border-b border-border/70 px-4 py-2">
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="text-[15px] font-semibold text-foreground">{stepLabel(step)}</h2>
                  <span className="text-[12px] tabular-nums text-muted-foreground">
                    Krok {index + 1} z {STEP_KEYS.length}
                  </span>
                </div>
                <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">
                  {step === "pobierz" ? "Sprawdź braki i pobierz umowę." : GEN_SECTION_INTRO[step]}
                </p>
              </header>
              <div className="px-4 py-2.5">{Fields ? <Fields d={d} /> : <DownloadStep d={d} onGo={setStep} />}</div>
              <footer className="flex items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5">
                {prev ? (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setStep(prev)}>
                    Wstecz
                  </Button>
                ) : (
                  <span />
                )}
                {next ? (
                  <Button type="button" size="sm" onClick={() => setStep(next)}>
                    Dalej: {stepLabel(next)}
                    <ArrowRight className="size-3.5" aria-hidden />
                  </Button>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <Button type="button" variant="ghost" size="sm">
                      <Eye className="size-3.5" aria-hidden />
                      Podgląd
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!ready}
                      title={ready ? undefined : `${missingCountLabel(d.missing.length)}: ${missingLabel(d)}`}
                    >
                      Pobierz DOCX ({d.language === "pl" ? "PL" : "EN"})
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      disabled={!ready}
                      title={ready ? undefined : `${missingCountLabel(d.missing.length)}: ${missingLabel(d)}`}
                    >
                      <Download className="size-3.5" aria-hidden />
                      Pobierz PDF
                    </Button>
                  </div>
                )}
              </footer>
            </section>

            <aside className="sticky top-4">
              <PaperPreview d={d} />
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
