"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronsUpDown,
  Download,
  ExternalLink,
  FileSignature,
  Loader2,
  Printer,
  Save,
  Search,
} from "lucide-react";
import Link from "next/link";
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
  contractsApi,
  extractErrorMsg,
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

type Lang = "pl" | "en";

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
            Wypełnij jednolitą umowę B2B (PL/EN) danymi kandydata i rekrutacji,
            wybierz rolę z gotowym zakresem usług → pobierz DOCX / PDF.
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
  const queryClient = useQueryClient();

  const [language, setLanguage] = useState<Lang>("pl");
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [stageId, setStageId] = useState<string>("");
  const [roleId, setRoleId] = useState<string>("");
  const [scopeText, setScopeText] = useState("");

  const [contractNumber, setContractNumber] = useState("");
  const [signingDate, setSigningDate] = useState(todayISO());
  const [startDate, setStartDate] = useState("");
  const [projectCity, setProjectCity] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [correspondenceAddress, setCorrespondenceAddress] = useState("");
  const [rateCandidate, setRateCandidate] = useState("");
  const [rateInWords, setRateInWords] = useState("");
  const [currency, setCurrency] = useState("PLN");

  const [generatedContractId, setGeneratedContractId] = useState<number | null>(
    null,
  );

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

  const draftQuery = useQuery({
    queryKey: ["b2b-gen-draft", generatedContractId],
    queryFn: async () => {
      if (!generatedContractId) return null;
      const res = await contractsApi.draft.get(generatedContractId);
      return res.data;
    },
    enabled: !!generatedContractId,
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

  // Populate editable scope when role / language changes.
  useEffect(() => {
    if (!selectedRole) {
      setScopeText("");
      return;
    }
    const bullets =
      language === "pl" ? selectedRole.scope_pl : selectedRole.scope_en;
    setScopeText(bullets.join("\n"));
  }, [selectedRole, language]);

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

  const canSubmit =
    !!candidate && !!selectedRecruitment && !!selectedRole && !!startDate;

  const generateMut = useMutation({
    mutationFn: () =>
      b2bGeneratorApi.generate({
        candidate_id: candidate!.id,
        job_id: selectedRecruitment!.job_id,
        role_id: selectedRole!.id,
        language,
        contract_number: contractNumber.trim() || null,
        signing_date: signingDate || null,
        start_date: startDate,
        project_city: projectCity.trim() || null,
        project_description: projectDescription.trim() || null,
        correspondence_address: correspondenceAddress.trim() || null,
        rate_candidate: rateCandidate ? Number(rateCandidate) : null,
        currency: currency.trim() || "PLN",
        rate_in_words: rateInWords.trim() || null,
        scope_items_override: scopeItems.length ? scopeItems : null,
      }),
    onSuccess: (res) => {
      setGeneratedContractId(res.contract_id);
      queryClient.invalidateQueries({
        queryKey: ["b2b-gen-draft", res.contract_id],
      });
      toast.showSuccess("Umowa wygenerowana — podgląd poniżej.");
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const docxMut = useMutation({
    mutationFn: async (lang: Lang) => {
      if (!generatedContractId) throw new Error("Brak umowy");
      const res = await b2bGeneratorApi.docxBlob(generatedContractId, lang);
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa_B2B_${lang}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const draftHtml = draftQuery.data?.content_html ?? "";

  return (
    <div className="space-y-4">
      {/* Krok 1 — kandydat + rekrutacja + język */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. Kandydat i rekrutacja</CardTitle>
          <CardDescription>
            Dane firmowe (NIP, REGON, adres) zaciągane są z profilu kandydata —
            uzupełnij profil, jeśli puste.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label className="mb-1.5 block">Kandydat</Label>
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
                <PopoverContent align="start" className="w-[--radix-popover-trigger-width] p-0">
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
                                candidate?.id === c.id ? "opacity-100" : "opacity-0",
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
            </div>

            <div>
              <Label className="mb-1.5 block">Rekrutacja (klient z oferty)</Label>
              <Select value={stageId} onValueChange={setStageId} disabled={!candidate}>
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      candidate ? "Wybierz rekrutację…" : "Najpierw kandydat"
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

      {/* Krok 2 — rola + zakres usług */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. Rola i zakres usług</CardTitle>
          <CardDescription>
            Zakres trafia do Załącznika nr 3. Możesz go edytować dla tej umowy
            (1 punkt na linię).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="mb-1.5 block">Rola / Stanowisko</Label>
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
                {scopeItems.length} punktów · brzmienione punkty zapisują się
                tylko dla tej umowy.
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Krok 3 — dane umowy */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">3. Dane umowy</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Numer umowy">
            <Input
              value={contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="np. 42/2026"
            />
          </Field>
          <Field label="Data podpisania">
            <Input
              type="date"
              value={signingDate}
              onChange={(e) => setSigningDate(e.target.value)}
            />
          </Field>
          <Field label="Data rozpoczęcia usług *">
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
          <Field label="Miasto Klienta">
            <Input
              value={projectCity}
              onChange={(e) => setProjectCity(e.target.value)}
              placeholder="np. Warszawa"
            />
          </Field>
          <Field label="Stawka godzinowa (netto)">
            <Input
              type="number"
              value={rateCandidate}
              onChange={(e) => setRateCandidate(e.target.value)}
              placeholder="np. 150"
            />
          </Field>
          <Field label="Waluta">
            <Input
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            />
          </Field>
          <Field label="Stawka słownie" full>
            <Input
              value={rateInWords}
              onChange={(e) => setRateInWords(e.target.value)}
              placeholder="np. sto pięćdziesiąt"
            />
          </Field>
          <Field label="Opis projektu i zakres usług" full>
            <Textarea
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              rows={3}
              placeholder="3–4 zdania o projekcie (z procesu rekrutacyjnego)…"
            />
          </Field>
          <Field label="Adres do korespondencji (opcjonalnie)" full>
            <Input
              value={correspondenceAddress}
              onChange={(e) => setCorrespondenceAddress(e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">* pola wymagane</p>
        <Button
          size="lg"
          disabled={!canSubmit || generateMut.isPending}
          onClick={() => generateMut.mutate()}
        >
          {generateMut.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Generuję…
            </>
          ) : (
            <>
              <FileSignature className="mr-2 h-4 w-4" />
              Generuj umowę
            </>
          )}
        </Button>
      </div>

      {/* Wynik */}
      {generatedContractId ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Wygenerowano umowę #{generatedContractId}
            </CardTitle>
            <CardDescription>
              Pobierz DOCX (formatowanie prawne) lub PDF, albo dopracuj w profilu
              kandydata (edytor + e-podpis Autenti).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={docxMut.isPending}
                onClick={() => docxMut.mutate("pl")}
              >
                <Download className="mr-2 h-4 w-4" />
                DOCX (PL)
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={docxMut.isPending}
                onClick={() => docxMut.mutate("en")}
              >
                <Download className="mr-2 h-4 w-4" />
                DOCX (EN)
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!draftHtml}
                onClick={() =>
                  printHtml(draftHtml, `Umowa B2B #${generatedContractId}`)
                }
              >
                <Printer className="mr-2 h-4 w-4" />
                Drukuj / PDF
              </Button>
              {candidate ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/candidates/${candidate.id}`}>
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Otwórz w profilu kandydata
                  </Link>
                </Button>
              ) : null}
            </div>
            {draftHtml ? (
              <iframe
                title="Podgląd umowy"
                className="h-[520px] w-full rounded-lg border bg-white"
                srcDoc={`<style>${PREVIEW_STYLE}</style>${draftHtml}`}
              />
            ) : (
              <div className="p-6 text-sm text-muted-foreground">
                Ładowanie podglądu…
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
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
