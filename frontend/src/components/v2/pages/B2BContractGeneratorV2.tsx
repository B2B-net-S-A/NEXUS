"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  ChevronsUpDown,
  Download,
  Eye,
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
  type B2BGeneratedContractRow,
  type B2BGeneratePayload,
  type B2BRenderPayload,
  type B2BRole,
  type B2BUopCheckResult,
} from "@/lib/api";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
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

/** Klienci z niestandardowymi zapisami umowy — zwraca true gdy wybrany klient
 * wymaga modyfikacji. Musi być zgodne z backendem
 * (clause_override_content.CLIENT_OVERRIDES). PL i EN. */
function hasSpecialClauses(clientName: string): boolean {
  const n = clientName.trim().toLowerCase();
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
    // max-w-6xl (nie 4xl): zakładka „Wygenerowane umowy" ma szeroką tabelę
    // (7 kolumn + 3 akcje: Edytuj / Pobierz / Usuń). Przy 4xl kolumna akcji
    // wychodziła poza wąski kontener i „Usuń" było ucięte poza ekranem —
    // użytkownik nie widział opcji usunięcia. Szerszy kontener mieści wszystkie
    // akcje w widocznym obszarze.
    <div className="mx-auto max-w-6xl p-6">
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
  const toast = useToast();
  const queryClient = useQueryClient();
  const q = useQuery({
    queryKey: ["b2b-generated"],
    queryFn: () => b2bGeneratorApi.generated(100),
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

  const startEdit = (r: B2BGeneratedContractRow) => {
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
          Klienta poprawić („Edytuj"); wpis może edytować lub usunąć („Usuń")
          osoba, która wygenerowała umowę, lub administrator. Usunięcie zwalnia
          numer — najniższy wolny numer wraca do podpowiedzi w generatorze.
        </CardDescription>
      </CardHeader>
      <CardContent>
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
                  <th className="py-2 pr-4 font-medium">Wygenerowano</th>
                  <th className="py-2 pr-4 font-medium">Wygenerował</th>
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
                  return (
                    <tr key={r.id} className="border-b">
                      <td className="py-2 pr-4 font-medium">
                        {r.contract_number}
                      </td>
                      <td className="py-2 pr-4">{r.partner_name || "—"}</td>
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
                      <td className="py-2 pr-4 uppercase">
                        {r.language || "—"}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground">
                        {r.created_at
                          ? r.created_at.slice(0, 16).replace("T", " ")
                          : "—"}
                      </td>
                      <td className="py-2 pr-4">{r.created_by_name || "—"}</td>
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
                              {r.can_edit ? (
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
                              {r.can_delete ? (
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
                              {!r.can_edit && !r.can_download && !r.can_delete ? (
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
    // Lista jest już kuratorska (featured=true → ~17 nazw); cap wysoki, żeby
    // nigdy nie ucinać w pół alfabetu (wcześniej slice(0,50) gubił > litery „D").
    return list.slice(0, 200);
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
      nextNumberQuery.refetch().then((r) => {
        if (r.data) setContractNumber(r.data.contract_number);
      });
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

  const sendSignMut = useMutation({
    mutationFn: async () => {
      const gp = buildGeneratePayload();
      if (!gp) {
        throw new Error(
          "Wybierz kandydata, rekrutację, rolę i datę startu, aby wysłać do podpisu.",
        );
      }
      // 1. Promocja do realnego Contract z treścią (draft_content_html).
      const gen = await b2bGeneratorApi.generate(gp);
      // 2. Wyślij do podpisu → zwraca publiczny link /sign/{token}.
      const res = await signingApi.sendForSignature(gen.contract_id, {
        provider: "upload_validate",
        signature_type: "QES",
      });
      return res.sign_url;
    },
    onSuccess: (url) => {
      setSignLink(url);
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
      const gp = buildGeneratePayload();
      if (!gp) {
        throw new Error(
          "Wybierz kandydata, rekrutację, rolę i datę startu, aby oznaczyć wysłaną.",
        );
      }
      const gen = await b2bGeneratorApi.generate(gp);
      await signingApi.markSentOffline(gen.contract_id);
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
      const gp = buildGeneratePayload();
      if (!gp) {
        throw new Error(
          "Wybierz kandydata, rekrutację, rolę i datę startu, aby wgrać podpisaną umowę.",
        );
      }
      const gen = await b2bGeneratorApi.generate(gp);
      return signingApi.uploadSigned(gen.contract_id, file);
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
          disabled={sendSignMut.isPending}
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
          disabled={markSentMut.isPending}
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
          disabled={uploadSignedMut.isPending}
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
