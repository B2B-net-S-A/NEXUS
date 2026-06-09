"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronsUpDown,
  Download,
  Eye,
  FileSignature,
  Loader2,
  Printer,
  Save,
  Search,
  Sparkles,
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
  type B2BRenderPayload,
  type B2BRole,
  type B2BUopCheckResult,
} from "@/lib/api";
import { hasRole, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

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
  description?: string | null;
  location?: string | null;
  client_name?: string | null;
};

type Lang = "pl" | "en";
type LookupStatus = "idle" | "loading" | "ok" | "none";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function parseDispositionFilename(disposition: string, fallback: string): string {
  const match = disposition.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
}

/** Smart-prefill „Opis projektu" z roli (gdy brak oferty z rekrutacji). */
function smartDescription(role: B2BRole, lang: Lang, clientName: string): string {
  const area = lang === "pl" ? role.area_label_pl : role.area_label_en;
  const scope = (lang === "pl" ? role.scope_pl : role.scope_en).slice(0, 3);
  const client = clientName.trim();
  if (lang === "en") {
    const lead = `Provision of services in the area of ${area}${
      client ? ` for the Client ${client}` : ""
    }.`;
    return scope.length
      ? `${lead} The scope includes, among others: ${scope.join("; ")}.`
      : lead;
  }
  const lead = `Świadczenie usług w obszarze: ${area}${
    client ? ` na rzecz Klienta ${client}` : ""
  }.`;
  return scope.length
    ? `${lead} Zakres obejmuje m.in.: ${scope.join("; ")}.`
    : lead;
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
  "table{border-collapse:collapse;width:100%;margin:1em 0}" +
  "th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}";

export function B2BContractGeneratorV2() {
  const { user } = useAuthStore();
  const isAdmin = hasRole(user, "admin");

  return (
    <div className="mx-auto max-w-4xl p-6">
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

function GeneratedContractsTab() {
  const q = useQuery({
    queryKey: ["b2b-generated"],
    queryFn: () => b2bGeneratorApi.generated(100),
    staleTime: 10_000,
  });
  const rows = q.data ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Wygenerowane umowy</CardTitle>
        <CardDescription>
          Numery dotąd wygenerowanych umów — sprawdź, czy sugerowany / wpisany
          numer nie powtarza istniejącego.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Brak wygenerowanych umów.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Numer</th>
                  <th className="py-2 pr-4 font-medium">Partner</th>
                  <th className="py-2 pr-4 font-medium">Klient</th>
                  <th className="py-2 pr-4 font-medium">Język</th>
                  <th className="py-2 font-medium">Wygenerowano</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.contract_number}-${i}`} className="border-b">
                    <td className="py-2 pr-4 font-medium">
                      {r.contract_number}
                    </td>
                    <td className="py-2 pr-4">{r.partner_name || "—"}</td>
                    <td className="py-2 pr-4">{r.client_name || "—"}</td>
                    <td className="py-2 pr-4 uppercase">{r.language || "—"}</td>
                    <td className="py-2 text-muted-foreground">
                      {r.created_at ? r.created_at.slice(0, 16).replace("T", " ") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Generator form ──────────────────────────────────────────────────────────

function GeneratorForm() {
  const toast = useToast();

  const [language, setLanguage] = useState<Lang>("pl");

  // Źródło danych (opcjonalne) — pre-fill z kandydata + rekrutacji.
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
  const [rateCandidate, setRateCandidate] = useState("");
  const [currency, setCurrency] = useState("PLN");

  // AI-sprawdzenie opisu pod kątem znamion umowy o pracę (#3).
  const [uop, setUop] = useState<B2BUopCheckResult | null>(null);

  // Płeć Partnera — steruje formami gramatycznymi w umowie (Panem/ią,
  // prowadzącym/cą, zwany/a, zapoznałem/am).
  const [gender, setGender] = useState<"m" | "k">("m");
  // Imię i nazwisko w narzędniku do komparycji (auto-odmiana, edytowalne) (#7).
  const [partnerInstrumental, setPartnerInstrumental] = useState("");
  const [partnerLookup, setPartnerLookup] = useState<LookupStatus>("idle");

  const [previewHtml, setPreviewHtml] = useState<string>("");

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
      descTouched.current = true; // opis z oferty ma priorytet nad smart-prefillem
    }
    if (j.location) setProjectCity(j.location);
    if (j.client_name) setClientName(j.client_name);
  }, [jobQuery.data, selectedRecruitment]);

  // Smart-prefill opisu projektu z roli (gdy brak oferty z rekrutacji i user
  // nie edytował ręcznie) — sensowny start także w trybie standalone.
  useEffect(() => {
    if (!selectedRole || selectedRecruitment || descTouched.current) return;
    setProjectDescription(smartDescription(selectedRole, language, clientName));
  }, [selectedRole, language, clientName, selectedRecruitment]);

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
    return list.slice(0, 50);
  }, [clientsQuery.data, clientQuery]);

  const buildPayload = (lang: Lang): B2BRenderPayload => ({
    role_id: selectedRole ? selectedRole.id : null,
    language: lang,
    gender,
    partner_name: partnerName.trim() || null,
    partner_instrumental: partnerInstrumental.trim() || null,
    partner_legal_name: partnerLegalName.trim() || null,
    partner_business_address: partnerBusinessAddress.trim() || null,
    partner_correspondence_address: partnerCorrespondenceAddress.trim() || null,
    partner_nip: partnerNip.trim() || null,
    partner_regon: partnerRegon.trim() || null,
    partner_email: partnerEmail.trim() || null,
    partner_phone: partnerPhone.trim() || null,
    client_name: clientName.trim() || null,
    project_city: projectCity.trim() || null,
    project_description: projectDescription.trim() || null,
    contract_number: contractNumber.trim() || null,
    signing_date: signingDate || null,
    start_date: startDate || null,
    start_date_mode: startDateMode,
    rate_candidate: rateCandidate ? Number(rateCandidate) : null,
    currency: currency.trim() || "PLN",
  });

  const validate = (): boolean => {
    const missing: string[] = [];
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
    if (!rateCandidate.trim() || Number(rateCandidate) <= 0)
      missing.push("Stawka godzinowa");
    if (missing.length) {
      toast.showError(`Uzupełnij wymagane pola: ${missing.join(", ")}.`);
      return false;
    }
    return true;
  };

  const docxMut = useMutation({
    mutationFn: async (lang: Lang) => {
      const res = await b2bGeneratorApi.renderDocx(buildPayload(lang));
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa_B2B_${lang}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    },
    onSuccess: () => {
      toast.showSuccess("Umowa pobrana (DOCX).");
      nextNumberQuery.refetch().then((r) => {
        if (r.data) setContractNumber(r.data.contract_number);
      });
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const previewMut = useMutation({
    mutationFn: () => b2bGeneratorApi.renderHtml(buildPayload(language)),
    onSuccess: (d) => setPreviewHtml(d.html),
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const uopMut = useMutation({
    mutationFn: () =>
      b2bGeneratorApi.checkUop({ text: projectDescription, language }),
    onSuccess: (d) => setUop(d),
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const onDocx = (lang: Lang) => {
    if (validate()) docxMut.mutate(lang);
  };
  const onPreview = () => {
    if (validate()) previewMut.mutate();
  };

  return (
    <div className="space-y-4">
      {/* Źródło danych (opcjonalne) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Źródło danych (opcjonalne)</CardTitle>
          <CardDescription>
            Wybierz kandydata i rekrutację, by zaciągnąć dane — albo wpisz
            wszystko ręcznie w polach poniżej (tryb standalone).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label className="mb-1.5 block">Kandydat (opcjonalnie)</Label>
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
                    className="w-[--radix-popover-trigger-width] p-0"
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
              <Label className="mb-1.5 block">Rekrutacja (klient z oferty)</Label>
              <Select
                value={stageId}
                onValueChange={setStageId}
                disabled={!candidate}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      candidate ? "Wybierz rekrutację…" : "Opcjonalne — najpierw kandydat"
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
            <Input
              value={partnerPhone}
              onChange={(e) => setPartnerPhone(e.target.value)}
            />
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
                className="w-[--radix-popover-trigger-width] p-0"
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
                if (uop) setUop(null);
              }}
              rows={4}
              placeholder="Auto z obszaru/oferty — możesz nadpisać. Po wklejeniu sprawdź AI…"
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
              placeholder="np. 1/2026"
            />
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Stawka godz. (netto)" required>
              <Input
                type="number"
                value={rateCandidate}
                onChange={(e) => setRateCandidate(e.target.value)}
                placeholder="np. 150"
              />
            </Field>
            <Field label="Waluta">
              <Input value={currency} onChange={(e) => setCurrency(e.target.value)} />
            </Field>
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            „Stawka słownie" liczy się automatycznie z kwoty.
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
      </div>

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
