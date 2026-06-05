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

      {isAdmin ? (
        <Tabs defaultValue="generator">
          <TabsList className="mb-4">
            <TabsTrigger value="generator">Generator</TabsTrigger>
            <TabsTrigger value="roles">Zakresy ról (admin)</TabsTrigger>
          </TabsList>
          <TabsContent value="generator">
            <GeneratorForm />
          </TabsContent>
          <TabsContent value="roles">
            <RoleScopeEditor />
          </TabsContent>
        </Tabs>
      ) : (
        <GeneratorForm />
      )}
    </div>
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
  const [scopeText, setScopeText] = useState("");

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
  const [projectCity, setProjectCity] = useState("");
  const [projectDescription, setProjectDescription] = useState("");

  // Warunki
  const [contractNumber, setContractNumber] = useState("");
  const [signingDate, setSigningDate] = useState(todayISO());
  const [startDate, setStartDate] = useState(todayISO());
  const [rateCandidate, setRateCandidate] = useState("");
  const [currency, setCurrency] = useState("PLN");

  const [clientNip, setClientNip] = useState("");
  const [partnerLookup, setPartnerLookup] = useState<LookupStatus>("idle");
  const [clientLookup, setClientLookup] = useState<LookupStatus>("idle");

  const [previewHtml, setPreviewHtml] = useState<string>("");

  // Pre-fill „raz na kandydata / ofertę" — nie nadpisuje ręcznych zmian.
  const prefilledCand = useRef<number | null>(null);
  const prefilledJob = useRef<number | null>(null);

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
    if (j.description) setProjectDescription(j.description);
    if (j.location) setProjectCity(j.location);
    if (j.client_name) setClientName(j.client_name);
  }, [jobQuery.data, selectedRecruitment]);

  // Zakres z roli/języka.
  useEffect(() => {
    if (!selectedRole) {
      setScopeText("");
      return;
    }
    const bullets =
      language === "pl" ? selectedRole.scope_pl : selectedRole.scope_en;
    setScopeText(bullets.join("\n"));
  }, [selectedRole, language]);

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

  // Auto-uzupełnianie nazwy Klienta z rejestru po NIP (debounced).
  useEffect(() => {
    const nip = clientNip.replace(/\D/g, "");
    if (nip.length !== 10) {
      setClientLookup("idle");
      return;
    }
    let cancelled = false;
    setClientLookup("loading");
    const timer = setTimeout(async () => {
      try {
        const d = await b2bGeneratorApi.companyLookup({ nip });
        if (cancelled) return;
        if (d.name) setClientName(d.name);
        setClientLookup("ok");
      } catch {
        if (!cancelled) setClientLookup("none");
      }
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [clientNip]);

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

  const scopeItems = useMemo(
    () =>
      scopeText
        .split("\n")
        .map((l) => l.replace(/^[•\-*]\s*/, "").trim())
        .filter(Boolean),
    [scopeText],
  );

  const buildPayload = (lang: Lang): B2BRenderPayload => ({
    role_id: selectedRole ? selectedRole.id : null,
    language: lang,
    partner_name: partnerName.trim() || null,
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
    rate_candidate: rateCandidate ? Number(rateCandidate) : null,
    currency: currency.trim() || "PLN",
    scope_items_override: scopeItems.length ? scopeItems : null,
  });

  const validate = (): boolean => {
    if (!selectedRole) {
      toast.showError("Wybierz rolę / stanowisko.");
      return false;
    }
    if (!partnerName.trim() && !partnerLegalName.trim()) {
      toast.showError(
        "Uzupełnij dane Partnera (imię i nazwisko lub nazwę firmy).",
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
            Wpisz NIP → dane firmy zaciągną się z rejestru (Biała Lista MF).
            Pre-fill też z profilu kandydata. Wszystko edytowalne.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Imię i nazwisko">
            <Input
              value={partnerName}
              onChange={(e) => setPartnerName(e.target.value)}
              placeholder="np. Jan Kowalski"
            />
          </Field>
          <Field label="Nazwa Firmy">
            <Input
              value={partnerLegalName}
              onChange={(e) => setPartnerLegalName(e.target.value)}
              placeholder="np. JK Software Jan Kowalski"
            />
          </Field>
          <Field label="NIP (auto z rejestru)">
            <Input
              value={partnerNip}
              onChange={(e) => setPartnerNip(e.target.value)}
              placeholder="10 cyfr → auto-pobranie"
            />
            <div className="mt-1 h-4">{lookupHint(partnerLookup)}</div>
          </Field>
          <Field label="REGON">
            <Input
              value={partnerRegon}
              onChange={(e) => setPartnerRegon(e.target.value)}
            />
          </Field>
          <Field label="Adres siedziby firmy" full>
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
          <Field label="E-mail">
            <Input
              value={partnerEmail}
              onChange={(e) => setPartnerEmail(e.target.value)}
            />
          </Field>
          <Field label="Telefon">
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
          <Field label="NIP Klienta (auto z rejestru)">
            <Input
              value={clientNip}
              onChange={(e) => setClientNip(e.target.value)}
              placeholder="10 cyfr → pobierze nazwę"
            />
            <div className="mt-1 h-4">{lookupHint(clientLookup)}</div>
          </Field>
          <Field label="Pełna nazwa Klienta">
            <Input
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="np. ACME Bank S.A."
            />
          </Field>
          <Field label="Miasto Klienta">
            <Input
              value={projectCity}
              onChange={(e) => setProjectCity(e.target.value)}
              placeholder="np. Warszawa"
            />
          </Field>
          <Field label="Opis projektu i zakres usług" full>
            <Textarea
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              rows={3}
              placeholder="3–4 zdania o projekcie (auto z oferty, jeśli wybrana)…"
            />
          </Field>
        </CardContent>
      </Card>

      {/* Rola i zakres usług */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Rola i zakres usług</CardTitle>
          <CardDescription>
            Zakres trafia do Załącznika nr 3. Możesz go edytować (1 punkt na linię).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="mb-1.5 block">Rola / Stanowisko *</Label>
            <Select value={roleId} onValueChange={setRoleId}>
              <SelectTrigger>
                <SelectValue placeholder="Wybierz rolę…" />
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
          </div>
          {selectedRole ? (
            <div>
              <Label className="mb-1.5 block">
                Zakres usług ({language.toUpperCase()})
              </Label>
              <Textarea
                value={scopeText}
                onChange={(e) => setScopeText(e.target.value)}
                rows={8}
                className="font-mono text-xs"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {scopeItems.length} punktów.
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Warunki */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Warunki umowy</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Numer umowy (auto)">
            <Input
              value={contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="np. 1/2026"
            />
          </Field>
          <Field label="Data podpisania">
            <Input
              type="date"
              value={signingDate}
              onChange={(e) => setSigningDate(e.target.value)}
            />
          </Field>
          <Field label="Data rozpoczęcia usług">
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Stawka godz. (netto)">
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

function Field({
  label,
  full,
  children,
}: {
  label: string;
  full?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <Label className="mb-1.5 block">{label}</Label>
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
