"use client";

import * as React from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
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
  FilePen,
  FileSignature,
  Loader2,
  History,
  PauseCircle,
  Pencil,
  Plus,
  Printer,
  Save,
  Search,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  type B2BClosureReason,
  type B2BConfirmFullySignedResult,
  type B2BContractStatus,
  type B2BGeneratedContractRow,
  type B2BGeneratedContractUpdate,
  type B2BGeneratedListParams,
  type B2BRenderPayload,
  type B2BRole,
  type B2BUopCheckResult,
} from "@/lib/api";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { hasActionAccess } from "@/lib/action-access";
import { hasSectionAccess } from "@/lib/section-access";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { hasRole, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { countPl } from "@/lib/plural-pl";
import { positiveIntParam } from "@/lib/client-tab";
import {
  B2B_CURRENCIES,
  B2B_REGISTER_PAGE_SIZE,
  canCorrectInForm,
  contractStatusOptions,
  existingContractFor,
  generatedIdFromHeaders,
  generatorEditHref,
  generatorTabFromParam,
  mergeRegisterPages,
  nextRegisterOffset,
  registerRowWarnings,
  registerSearchHref,
  type GeneratorTab,
} from "@/lib/b2b-generator-register";

// Router generatora ma szeroką bramkę Sourcing, ale operacje na dokumentach
// ze stawką mają osobne, konfigurowalne uprawnienie. Poziom `view` dostaje
// wyłącznie bezpieczny, pozbawiony finansów rejestr.
function isForbidden(error: unknown): boolean {
  return (
    (error as { response?: { status?: number } } | null)?.response?.status === 403
  );
}

const NO_ACCESS_TITLE = "Brak uprawnień do Generatora Umów B2B";
const NO_ACCESS_DESC =
  "Ta operacja wymaga dodatkowych uprawnień do dokumentów umownych. " +
  "Poproś administratora o nadanie dostępu — " +
  "wygenerowane wcześniej umowy nie zostały usunięte, są tylko niewidoczne " +
  "bez uprawnień.";

type ContractConflict = {
  message: string;
  contractIds: number[];
  /** Etykiety PL różniących się pól — z 409 automatyzacji podpisu. */
  conflicts: string[];
  /**
   * Serwer dopuszcza ponowne potwierdzenie z `keep_existing_contract_terms`.
   * Tylko konflikt WARUNKÓW to ma; duplikaty kontraktorów, inny klient czy
   * umowa już podpisana zostają twardą odmową bez tej podpowiedzi.
   */
  canKeepExistingTerms: boolean;
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
  const rawConflicts = (detail as { conflicts?: unknown }).conflicts;
  const canKeep = (detail as { can_keep_existing_terms?: unknown })
    .can_keep_existing_terms;
  if (typeof message !== "string") return null;
  return {
    message,
    contractIds: Array.isArray(rawIds)
      ? rawIds.filter(
          (id): id is number => typeof id === "number" && Number.isFinite(id),
        )
      : [],
    conflicts: Array.isArray(rawConflicts)
      ? rawConflicts.filter(
          (label): label is string =>
            typeof label === "string" && label.trim().length > 0,
        )
      : [],
    canKeepExistingTerms: canKeep === true,
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
  // `id`/`title` przychodzą też z listy `/api/jobs` (katalog projektów przy
  // przywracaniu zawieszonej umowy), gdzie ten sam kształt jest elementem
  // tablicy, a nie odpowiedzią `/api/jobs/{id}`.
  id?: number;
  title?: string | null;
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
  return warsawToday();
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
/**
 * Data i godzina w formacie DD.MM.RRRR GG:MM (czas lokalny przeglądarki).
 * Wcześniej `created_at.slice(0, 16)` pokazywało surowe ISO i godzinę UTC.
 */
export function formatDateTimePl(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${formatIsoDatePl(value)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

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

/** Imię i nazwisko Partnera po odpytaniu rejestru o NIP.
 *
 * Nazwisko należy do KANDYDATA ze „Źródła danych" (prefill) albo do ręcznej
 * poprawki — rejestr może je UZUPEŁNIĆ tylko wtedy, gdy pole jest puste, i NIGDY
 * nie kasuje wartości, która już tam jest. NIP kandydata bywa cudzy (błąd
 * w profilu) albo należy do spółki, więc `person` z rejestru potrafił wstawić
 * inne nazwisko niż wybrany kandydat (regresja: wybrany „Rafał Korecki", w polu
 * „RAFAŁ WASILEWSKI" — właściciel JDG z NIP-u firmy NERTHUS). `name` firmy,
 * REGON i adres to dane rejestrowe i nadpisują się osobno, bez tej ochrony. */
export function partnerNameAfterLookup(
  currentName: string,
  registryPerson: string | null | undefined,
): string {
  const current = currentName.trim();
  if (current) return currentName;
  // Pole bez realnej treści (puste albo same białe znaki) i rejestr bez nazwiska
  // → normalizujemy do "", nie zostawiamy surowych spacji (spójnie z gałęzią
  // wypełniającą, która białe znaki traktuje jak pustkę).
  return registryPerson?.trim() ? registryPerson : current;
}

/** Needle'e wpisów rejestru klauzul, które NIE dają modyfikacji umowy.
 *
 * „BNP Paribas Cardif" to odrębny Klient (ubezpieczyciel), nie Bank BNP Paribas
 * Polska — dostaje zwykły szablon. Musi być sprawdzane PRZED listą pozytywną,
 * spójnie z kolejnością wpisów w backendowym CLIENT_OVERRIDES (needle jest
 * podciągiem, pierwsze trafienie wygrywa). */
export const CLAUSE_OVERRIDE_NEEDLES_NONE = [
  "bnp paribas cardif",
  "bnp cardif",
];

/** Needle'e Klientów z niestandardowymi zapisami umowy — LUSTRO backendu
 * (clause_override_content.CLIENT_OVERRIDES).
 *
 * Ta lista rozjechała się już raz w praktyce: commit poszerzający needle
 * „e-zdrowia" o warianty „e-zdrowie"/„ezdrowie" zaktualizował inne lustro
 * (ContractRegisterDialog) i pominął to, więc backend podmieniał cały § 10
 * (zakaz konkurencji + kary umowne), a baner ostrzegawczy milczał. Pilnuje tego
 * teraz test kontraktowy po stronie backendu (`test_b2b_clause_needle_mirror`),
 * który parsuje TĘ tablicę i porównuje ją z rejestrem — rozjazd wywala CI. */
export const CLAUSE_OVERRIDE_NEEDLES = [
  "pfron",
  "rehabilitacji osób niepełnosprawnych",
  "centrum e-zdrowia",
  "e-zdrowia",
  "e-zdrowie",
  "ezdrowie",
  "bnp paribas",
  "alior",
  "credit agricole",
  "biuro informacji kredytowej",
  "bik",
];

/** Klienci z niestandardowymi zapisami umowy — zwraca true gdy wybrany klient
 * wymaga modyfikacji. PL i EN. */
export function hasSpecialClauses(clientName: string): boolean {
  // Lustro backendowego `_norm`: NFC + zwinięcie ciągów białych znaków.
  // NFC, bo needle „rehabilitacji osób niepełnosprawnych" ma znaki rozkładalne,
  // a nazwa wklejona (macOS, komórka arkusza) bywa w NFD — wizualnie identyczna,
  // bajtowo niedopasowalna. `\s+`, bo nazwy z importu miewają podwójne spacje.
  const n = clientName
    .normalize("NFC")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
  if (CLAUSE_OVERRIDE_NEEDLES_NONE.some((needle) => n.includes(needle)))
    return false;
  return CLAUSE_OVERRIDE_NEEDLES.some((needle) => n.includes(needle));
}

/** Memo współdzielone przez akcje, które muszą mieć kontrakt PRZED zapisem.
 *
 * Od 09.2026 generator nie ma już takiej akcji: umowy podpisujemy offline
 * (decyzja 17.09.2026), a jedyną drogą do kontraktu jest „Oznacz jako
 * podpisaną" w rejestrze (`confirm-fully-signed`). Helper i `POST /generate`
 * zostają — chronią endpoint przed podwójnym zapisem, gdyby wróciła akcja
 * tworząca kontrakt przed podpisem — ale w tym komponencie nikt ich nie woła.
 */
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
  const canView = hasActionAccess(
    user,
    "b2b_contract_generator",
    "view",
  );
  const canGenerate =
    hasSectionAccess(user, "sourcing", "write") &&
    hasActionAccess(user, "b2b_contract_generator", "generate");

  // Zakładka, fraza rejestru i para (kandydat, rekrutacja) żyją w adresie:
  // link z kroku „Umowa” rekrutacji i ostrzeżenie „popraw ją w rejestrze”
  // prowadzą wprost na miejsce, a F5 nie wraca na „Generator”.
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const tabParam = searchParams?.get("tab") ?? null;
  const qParam = searchParams?.get("q") ?? null;
  const candidateParam = positiveIntParam(searchParams?.get("candidate") ?? null);
  const jobParam = positiveIntParam(searchParams?.get("job") ?? null);
  // `?edit=<id>` — „Popraw umowę” z wiersza rejestru: formularz wczytuje
  // zapisany payload i poprawia ten sam wiersz pod tym samym numerem.
  const editParam = positiveIntParam(searchParams?.get("edit") ?? null);
  const defaultTab: GeneratorTab = canGenerate ? "generator" : "generated";
  const allowedTab = (tab: GeneratorTab | null): GeneratorTab | null => {
    if (!tab) return null;
    if (tab === "generator" && !canGenerate) return null;
    if (tab === "roles" && !isAdmin) return null;
    return tab;
  };
  const requestedTab = allowedTab(generatorTabFromParam(tabParam));
  const [activeTab, setActiveTab] = useState<GeneratorTab>(
    requestedTab ?? defaultTab,
  );
  // Efekt na WARTOŚCI parametru — sam inicjalizator useState nie zobaczy
  // miękkiej nawigacji (link na tej samej stronie nie odmontowuje komponentu).
  useEffect(() => {
    if (requestedTab) setActiveTab(requestedTab);
  }, [requestedTab]);
  const selectTab = (value: string) => {
    const tab = allowedTab(generatorTabFromParam(value));
    if (!tab) return;
    setActiveTab(tab);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", tab);
    // Fraza dotyczy zakładki, z której przyszła — w innej zawęziłaby listę
    // po cichu. Para (kandydat, rekrutacja) należy do formularza i zostaje.
    params.delete("q");
    router.replace(`${pathname ?? ""}?${params.toString()}`, { scroll: false });
  };

  return (
    // max-w-7xl (nie 4xl): zakładka „Wygenerowane umowy" ma szeroką tabelę
    // (9 kolumn + akcje: status podpisu / status umowy / Edytuj / Pobierz /
    // Usuń). Przy 4xl kolumna akcji wychodziła poza wąski kontener i „Usuń"
    // było ucięte poza ekranem — użytkownik nie widział opcji usunięcia.
    // Kolumna „Status umowy" (PR: status + wyszukiwarka) dołożyła szerokości,
    // stąd 6xl → 7xl. Szerszy kontener mieści wszystkie akcje w widocznym
    // obszarze.
    // `p-0 md:p-6`: shell daje już `p-4` — na telefonie podwójny margines
    // zostawiał ~295 px na treść.
    <div className="mx-auto max-w-7xl p-0 md:p-6">
      <div className="mb-6 flex items-center gap-3">
        <FileSignature className="h-7 w-7 shrink-0 text-primary" />
        <div>
          <h1 className="text-2xl font-semibold">Generator Umów B2B</h1>
          <p className="text-sm text-muted-foreground">
            Wpisz dane ręcznie lub zaciągnij z kandydata/rekrutacji, wybierz rolę
            z gotowym zakresem usług → pobierz DOCX / PDF.
          </p>
        </div>
      </div>

      {!canView ? (
        <Alert title={NO_ACCESS_TITLE} description={NO_ACCESS_DESC} />
      ) : (
        <div className="space-y-4">
          {!canGenerate ? (
            <Alert
              variant="info"
              title="Dostęp tylko do rejestru"
              description="Możesz przeglądać umowy bez danych finansowych. Generowanie wymaga poziomu „Generowanie” oraz prawa zapisu w sekcji Sourcing."
            />
          ) : null}

          <Tabs value={activeTab} onValueChange={selectTab}>
            <TabsList className="mb-4 overflow-x-auto">
              {canGenerate ? (
                <TabsTrigger value="generator" className="shrink-0 whitespace-nowrap">Generator</TabsTrigger>
              ) : null}
              {/* „Umowy bieżące", nie „aktywne i w trakcie podpisu": od 0328
                  siedzą tu także umowy anulowane (wiersz zostaje pod ręką, żeby
                  dało się go cofnąć na „W trakcie", gdy Partner wróci).
                  Nagłówek wyliczający statusy przestałby być prawdziwy. */}
              <TabsTrigger value="generated" className="shrink-0 whitespace-nowrap">Umowy bieżące</TabsTrigger>
              <TabsTrigger value="no-project" className="shrink-0 whitespace-nowrap">Umowy bez projektu</TabsTrigger>
              <TabsTrigger value="closed" className="shrink-0 whitespace-nowrap">Zakończone umowy</TabsTrigger>
              {isAdmin ? (
                <TabsTrigger value="roles" className="shrink-0 whitespace-nowrap">Zakresy ról (admin)</TabsTrigger>
              ) : null}
            </TabsList>
            {/* forceMount: nie odmontowuj formularza przy przejściu na inną
                zakładkę — inaczej wpisane dane znikają (zgłoszone przez Artura). */}
            {canGenerate ? (
              <TabsContent
                value="generator"
                forceMount
                className="data-[state=inactive]:hidden"
              >
                <GeneratorForm
                  prefillCandidateId={candidateParam}
                  prefillJobId={jobParam}
                  editGeneratedId={editParam}
                  onEditConsumed={() => {
                    // Po wczytaniu (albo odmowie) parametr znika — F5 nie może
                    // nadpisać poprawek wczytanym ponownie stanem z serwera.
                    const params = new URLSearchParams(
                      searchParams?.toString() ?? "",
                    );
                    if (!params.has("edit")) return;
                    params.delete("edit");
                    const query = params.toString();
                    router.replace(
                      query ? `${pathname ?? ""}?${query}` : (pathname ?? ""),
                      { scroll: false },
                    );
                  }}
                  onClearPrefill={() => {
                    if (!candidateParam && !jobParam) return;
                    const params = new URLSearchParams(
                      searchParams?.toString() ?? "",
                    );
                    params.delete("candidate");
                    params.delete("job");
                    const query = params.toString();
                    router.replace(
                      query ? `${pathname ?? ""}?${query}` : (pathname ?? ""),
                      { scroll: false },
                    );
                  }}
                />
              </TabsContent>
            ) : null}
            <TabsContent value="generated">
              <GeneratedContractsTab
                searchParam={activeTab === "generated" ? qParam : null}
                canCorrect={canGenerate}
              />
            </TabsContent>
            <TabsContent value="no-project">
              <NoProjectContractsTab
                searchParam={activeTab === "no-project" ? qParam : null}
              />
            </TabsContent>
            <TabsContent value="closed">
              <ClosedContractsTab
                searchParam={activeTab === "closed" ? qParam : null}
              />
            </TabsContent>
            {isAdmin ? (
              <TabsContent value="roles">
                <RoleScopeEditor />
              </TabsContent>
            ) : null}
          </Tabs>
        </div>
      )}
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
  // Zaznaczane dopiero PO 409 z listą różnic — drugi, jawny krok. Bez niego
  // „Potwierdź podpisanie" wysyłałoby flagę w ciemno i konflikt warunków
  // (stawka dzienna w kontrakcie vs godzinowa w dokumencie) nigdy nie
  // dotarłby do operatora.
  const [keepExistingTerms, setKeepExistingTerms] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCandidate(null);
    setCandidateOpen(false);
    setCandidateQuery("");
    setStageId("");
    setSubmitError(null);
    setKeepExistingTerms(false);
  }, [open, row.id]);

  const effectiveCandidateId = row.candidate_id ?? candidate?.id ?? null;
  // Debounce jak w szukajce rejestru — bez niego każda litera to zapytanie.
  const debouncedCandidateQuery = useDebouncedValue(candidateQuery, 300);

  const candidatesQuery = useQuery({
    queryKey: ["b2b-signature-candidates", debouncedCandidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: debouncedCandidateQuery, limit: 20 },
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

  // Zgoda dotyczy KONKRETNEJ pary (kandydat, rekrutacja) — tej, dla której
  // serwer wyliczył różnice. W wierszu historycznym parę wybiera się w tym
  // samym dialogu, więc jej zmiana musi skasować i listę różnic, i zgodę;
  // inaczej flaga poleciałaby dla pary, której konfliktów nikt nie widział.
  useEffect(() => {
    setSubmitError(null);
    setKeepExistingTerms(false);
  }, [effectiveCandidateId, effectiveJobId]);

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
        // Klucz dopiero po świadomym zaznaczeniu — `false` nie leci wcale,
        // żeby zwykłe potwierdzenie było bajt w bajt tym samym żądaniem co
        // przed tą zmianą. Czytamy WYŁĄCZNIE stan checkboxa: `onMutate`
        // czyści `submitError` przed wywołaniem `mutationFn`, więc warunek
        // na błędzie w tym miejscu widziałby już `null` i gubił flagę.
        ...(keepExistingTerms ? { keep_existing_contract_terms: true } : {}),
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
        conflicts: [],
        canKeepExistingTerms: false,
      };
      setSubmitError(normalized);
      // Zaznaczenie ma sens tylko przy odmowie, która je oferuje; inna
      // odmowa (np. dwa kontrakty naraz) chowa checkbox, więc i flaga musi
      // zniknąć — inaczej kolejne kliknięcie wysłałoby ją w ciemno.
      if (!normalized.canKeepExistingTerms) setKeepExistingTerms(false);
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
            <Alert
              variant={submitError.canKeepExistingTerms ? "warning" : "error"}
              title={
                submitError.canKeepExistingTerms
                  ? "Istniejący kontrakt ma inne warunki niż dokument"
                  : "Nie można zakończyć automatyzacji"
              }
            >
              <p className="mt-0.5 text-xs opacity-90">{submitError.message}</p>
              {submitError.conflicts.length > 0 ? (
                <ul className="mt-1.5 list-disc pl-4 text-xs">
                  {submitError.conflicts.map((label) => (
                    <li key={label}>{label}</li>
                  ))}
                </ul>
              ) : null}
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
              {submitError.canKeepExistingTerms ? (
                <div className="mt-3 flex items-start gap-2">
                  <Checkbox
                    id="b2b-keep-existing-terms"
                    checked={keepExistingTerms}
                    onCheckedChange={(value) =>
                      setKeepExistingTerms(value === true)
                    }
                    className="mt-0.5"
                  />
                  <Label
                    htmlFor="b2b-keep-existing-terms"
                    className="text-xs font-normal leading-snug"
                  >
                    Zachowaj dotychczasowe warunki kontraktu
                    {submitError.contractIds.length === 1
                      ? ` #${submitError.contractIds[0]}`
                      : ""}{" "}
                    i potwierdź podpisanie mimo różnic. Umowa zostanie
                    powiązana z kontraktem, ale stawka, jednostka, harmonogram
                    ani daty w kontrakcie nie zmienią się — podpisany dokument
                    pozostaje zapisem tego, co strony podpisały; kontrakt
                    popraw ręcznie, jeśli trzeba.
                  </Label>
                </div>
              ) : null}
            </Alert>
          ) : null}

          <div className="rounded-lg border border-border p-4">
            <p className="text-sm font-medium text-foreground">
              System wykona atomowo:
            </p>
            <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
              <li>
                • utworzy albo powiąże kontraktora jako <strong>aktywny</strong>{" "}
                kontrakt (start z umowy → bezterminowo, stawka godzinowa z umowy),
              </li>
              <li>• zapewni szkic zamówienia klienta,</li>
              <li>
                • okres zamówienia i stawka przychodowa trafią do kontraktu po
                uzupełnieniu zamówienia,
              </li>
              <li>
                • przesunie kandydata w pipeline tej rekrutacji na „Zatrudniony”
                (chyba że kandydat nie ma w niej procesu, a nowy blokuje
                Priority Work — wtedy etap uzupełnia Head of Recruitment),
              </li>
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
            {/* Sam stan checkboxa: `onMutate` czyści `submitError` na czas
                żądania, a etykieta nie może mrugać na „Potwierdź podpisanie",
                gdy flaga właśnie leci. Checkbox istnieje tylko po 409
                z podpowiedzią i jest zerowany przy każdej innej odmowie oraz
                przy zmianie pary, więc `true` zawsze znaczy świadomą zgodę. */}
            {keepExistingTerms ? "Potwierdź mimo różnic" : "Potwierdź podpisanie"}
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
  cancelled: "Anulowana",
  suspended: "Zawieszona",
  // „Zamknięta" → „Zakończona": tak nazywa ten stan proces i tak brzmi
  // zakładka, do której wiersz trafia. Wartość w bazie zostaje `closed`.
  closed: "Zakończona",
};

/**
 * Warianty badge'a statusu umowy.
 *
 * „Zakończona" przeszła z `warning` (pomarańcz) na `neutral` (szary), żeby
 * zwolnić pomarańcz dla „W trakcie". Nie jest to tylko przetasowanie kolorów:
 * stan terminalny nie jest ostrzeżeniem, a umowa w drodze do podpisu wymaga
 * uwagi. Dwa pomarańczowe statusy obok siebie byłyby nierozróżnialne.
 *
 * „Zawieszona" dostaje `soft` — czyta się jako wstrzymanie, a nie awarię ani
 * stan terminalny. Umowa dalej obowiązuje, więc czerwień byłaby kłamstwem.
 *
 * „Anulowana" dostaje `danger` (czerwień) — i to jest JEDYNY status, któremu
 * ona przysługuje: umowa nie doszła do skutku, więc wiersz jest martwy mimo
 * tego, że siedzi w zakładce z żywymi. Bez czerwieni niczym nie różniłby się
 * wzrokowo od umowy czekającej na podpis.
 */
export const B2B_CONTRACT_STATUS_VARIANT: Record<
  B2BContractStatus,
  "info" | "warning" | "neutral" | "soft" | "danger"
> = {
  active: "info",
  in_progress: "warning",
  cancelled: "danger",
  suspended: "soft",
  closed: "neutral",
};

/** Ikona statusu — para z wariantem wyżej. */
function StatusIcon({ status }: { status: B2BContractStatus }) {
  const cls = "h-3.5 w-3.5";
  if (status === "closed") return <CircleSlash className={cls} />;
  if (status === "cancelled") return <XCircle className={cls} />;
  if (status === "suspended") return <PauseCircle className={cls} />;
  if (status === "in_progress") return <CircleDashed className={cls} />;
  return <CircleDot className={cls} />;
}

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
            "hit-area rounded p-0.5 transition-colors",
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
  no_client_budget: "Brak budżetu u klienta",
  contractor_found_other_project: "Kontraktor znalazł inny projekt",
  contractor_health_reasons: "Względy zdrowotne kontraktora",
  contractor_underperformance:
    "Kontraktor nie wywiązywał się z obowiązków projektowych",
  project_completed: "Zakończenie projektu",
  internalization: "Internalizacja",
  other: "Inny",
  // Katalog sprzed migracji 0226 — opisywał ROZSTANIE Z PARTNEREM, nie koniec
  // projektu. Zniknął z pickera niżej, ale etykiety ZOSTAJĄ: produkcja ma
  // zamknięte umowy z tymi powodami, a bez etykiety kolumna „Powód zakończenia
  // projektu" pokazywałaby im surowy klucz albo puste miejsce.
  resignation_before_signing: "Rezygnacja przed podpisaniem umowy",
  termination: "Wypowiedzenie",
  mutual_agreement: "Porozumienie o rozwiązaniu umowy",
};

// Kolejność w liście rozwijanej „Powód zakończenia projektu" — jak w zgłoszeniu.
// JEDNA lista dla „Zakończona" i „Zawieszona": to samo zdarzenie (projekt się
// skończył) kończy albo zawiesza umowę, w zależności od tego, czy szukamy
// kontraktorowi kolejnego zlecenia.
const CLOSURE_REASONS: B2BClosureReason[] = [
  "no_client_budget",
  "contractor_found_other_project",
  "contractor_health_reasons",
  "contractor_underperformance",
  "project_completed",
  "internalization",
  "other",
];

/** Czytelny powód: własny tekst dla „Inny", inaczej etykieta z katalogu. */
export function closureReasonText(
  reason: B2BClosureReason | null | undefined,
  reasonOther: string | null | undefined,
): string | null {
  if (!reason) return null;
  if (reason === "other") return reasonOther?.trim() || "Inny";
  return B2B_CLOSURE_REASON_LABEL[reason] ?? reason;
}

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
          ? "Umowa zakończona — wpis przeszedł do „Zakończone umowy”."
          : updated.contract_status === "suspended"
            ? "Umowa zawieszona — kontraktor jest teraz w „Umowy bez projektu”."
            : updated.contract_status === "cancelled"
              ? "Umowa anulowana — wpis zostaje w rejestrze, numer nie wraca do puli."
              : updated.contract_status === "in_progress"
                ? row.contract_status === "closed"
                  ? "Zakończenie cofnięte — umowa wróciła do „Umowy bieżące” jako „W trakcie”."
                  : "Umowa wróciła do podpisu — możesz ją oznaczyć jako podpisaną."
                : "Umowa oznaczona jako aktywna.",
      );
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      queryClient.invalidateQueries({ queryKey: ["b2b-status-history", row.id] });
      onOpenChange(false);
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  // Oba statusy wymagają tego samego kompletu pól; różni się TYLKO to, co się
  // kończy — przy zawieszeniu projekt (umowa trwa), przy zakończeniu umowa.
  const closing = status === "closed" || status === "suspended";
  const subject = status === "suspended" ? "projektu" : "umowy";
  // Backend odrzuca niedozwolone przejścia 422/409; ukrycie opcji oszczędza
  // użytkownikowi wysyłki, która i tak nie ma prawa się udać.
  const statusOptions = contractStatusOptions(row);
  // Ręczny wybór „W trakcie": powrót z „Anulowanej" (Partner jednak wraca do
  // podpisu) albo cofnięcie pomyłkowego zakończenia NIEPODPISANEJ umowy.
  const canReturnToProgress = statusOptions.some(
    (o) => o.value === "in_progress" && !o.disabled,
  );
  const submit = () => {
    if (!closing) {
      // `status`, nie sztywne „active": ten sam przycisk obsługuje teraz
      // anulowanie i powrót na „W trakcie".
      mut.mutate({ contract_status: status });
      return;
    }
    // Te same reguły egzekwuje backend (422) i CHECK w bazie — tu tylko po to,
    // żeby użytkownik zobaczył powód od razu, bez round-tripu.
    if (!reason) {
      toast.showError(`Wybierz powód zakończenia ${subject}.`);
      return;
    }
    if (reason === "other" && !reasonOther.trim()) {
      toast.showError(`Wpisz własny powód zakończenia ${subject}.`);
      return;
    }
    if (!closureDate) {
      toast.showError(`Podaj datę zakończenia ${subject}.`);
      return;
    }
    mut.mutate({
      contract_status: status,
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
            Żadna z tych zmian nie usuwa umowy z systemu — wpis przechodzi do
            innej zakładki wraz z powodem i datą zakończenia.
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
                {/* Pozycje liczy `contractStatusOptions` — lustro reguł PATCH-a.
                    Opcja, która zawsze kończy się błędem, jest gorsza niż jej
                    brak: „Aktywna" tylko dla podpisanej obustronnie (zawieszona
                    wraca „Przywróć", bo wymaga projektu). Bieżący status zostaje
                    na liście zawsze, inaczej Radix wyrenderowałby pusty trigger. */}
                {statusOptions.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    disabled={option.disabled}
                  >
                    {B2B_CONTRACT_STATUS_LABEL[option.value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {status === "suspended" ? (
              <p className="text-xs text-muted-foreground">
                Umowa nadal obowiązuje — kontraktor tylko nie ma przypisanego
                projektu. Wpis przejdzie do zakładki „Umowy bez projektu”.
              </p>
            ) : null}
            {status === "cancelled" ? (
              <p className="text-xs text-muted-foreground">
                Umowa nie doszła do skutku — Partner wycofał się przed
                podpisem. Wpis zostaje na tej liście (numer jest już zużyty
                i nie wraca do puli), ale nie da się go oznaczyć jako
                podpisanego. Jeśli Partner wróci, ustaw status „W trakcie”.
              </p>
            ) : null}
            {status === "in_progress" && canReturnToProgress ? (
              <p className="text-xs text-muted-foreground">
                {row.contract_status === "closed"
                  ? "Cofa pomyłkowe zakończenie niepodpisanej umowy — wpis wróci do „Umowy bieżące”, a powód i data zakończenia zostaną wyczyszczone (zostają w historii statusów)."
                  : "Umowa wraca do podpisu — przycisk „Oznacz jako podpisaną” pojawi się ponownie."}
              </p>
            ) : null}
          </div>

          {closing ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="b2b-closure-reason">
                  Powód zakończenia {subject}
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
                    placeholder={`Opisz powód zakończenia ${subject}`}
                  />
                </div>
              ) : null}

              <div className="space-y-1.5">
                <Label htmlFor="b2b-closure-date">
                  Data zakończenia {subject}
                </Label>
                {/* type="date" = wpisanie z klawiatury ORAZ natywny kalendarz. */}
                <Input
                  id="b2b-closure-date"
                  type="date"
                  value={closureDate}
                  onChange={(e) => setClosureDate(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Pole obowiązkowe dla statusu „
                  {B2B_CONTRACT_STATUS_LABEL[status]}".
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

/**
 * Przywrócenie zawieszonej umowy do gry: wybór projektu, klient dociągany.
 *
 * Klient jest READ-ONLY i wyprowadzany z projektu — dokładnie jak w generatorze
 * przy tworzeniu umowy. Ręczne pole pozwoliłoby zapisać parę projekt/klient,
 * która w bazie do siebie nie należy; backend i tak wyprowadza klienta sam,
 * więc dwa źródła prawdy tylko by się rozjeżdżały.
 */
export function ReactivateContractDialog({
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
  const [jobId, setJobId] = useState("");
  // Rekrutacje kandydata to węższy i pewniejszy zbiór (kontraktor jest w nich
  // realnie w pipelinie), ale bywa pusty — wtedy bez przełącznika na pełny
  // katalog użytkownik zostaje w ślepym zaułku.
  const [browseAll, setBrowseAll] = useState(false);
  const [jobQuery, setJobQuery] = useState("");
  const debouncedJobQuery = useDebouncedValue(jobQuery, 300);

  useEffect(() => {
    if (!open) return;
    setJobId("");
    setBrowseAll(false);
    setJobQuery("");
  }, [open, row]);

  const recruitments = useQuery({
    queryKey: ["b2b-reactivate-recruitments", row.candidate_id],
    queryFn: () =>
      api
        .get<RecruitmentOption[]>(
          `/api/cv-generator/candidates/${row.candidate_id}/recruitments`,
        )
        .then((r) => r.data),
    enabled: open && !!row.candidate_id && !browseAll,
  });

  const catalog = useQuery({
    queryKey: ["b2b-reactivate-jobs", debouncedJobQuery],
    queryFn: () =>
      api
        .get<{ items?: JobDetail[] } | JobDetail[]>("/api/jobs", {
          params: {
            open_only: true,
            page_size: 50,
            ...(debouncedJobQuery.trim() ? { q: debouncedJobQuery.trim() } : {}),
          },
        })
        .then((r) => (Array.isArray(r.data) ? r.data : (r.data.items ?? []))),
    enabled: open && browseAll,
  });

  const selectedJob = useQuery({
    queryKey: ["b2b-reactivate-job", jobId],
    queryFn: () =>
      api.get<JobDetail>(`/api/jobs/${jobId}`).then((r) => r.data),
    enabled: open && !!jobId,
  });

  const mut = useMutation({
    mutationFn: () =>
      b2bGeneratorApi.updateGenerated(row.id, {
        contract_status: "active",
        job_id: Number(jobId),
      }),
    onSuccess: () => {
      toast.showSuccess(
        "Umowa wróciła do zakładki „Umowy bieżące”. Notatkę " +
          "o poprzednim projekcie dopisano w Kontraktach.",
      );
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      queryClient.invalidateQueries({ queryKey: ["b2b-status-history", row.id] });
      onOpenChange(false);
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const options: { value: string; label: string }[] = browseAll
    ? (catalog.data ?? []).map((j) => ({
        value: String(j.id),
        label: j.title ?? `Projekt #${j.id}`,
      }))
    : (recruitments.data ?? []).map((r) => ({
        value: String(r.job_id),
        label: r.job_title,
      }));
  const listQuery = browseAll ? catalog : recruitments;
  const clientLabel =
    selectedJob.data?.client_name ?? row.canonical_client_name ?? "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Przywróć umowę {row.contract_number}</DialogTitle>
          <DialogDescription>
            Kontraktor wraca do pracy. Wskaż projekt — klient dociągnie się
            z niego automatycznie, a data i powód zakończenia poprzedniego
            projektu trafią jako notatka do powiązanego kontraktu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="b2b-reactivate-job">Projekt</Label>
            {listQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">Ładowanie…</p>
            ) : listQuery.isError ? (
              /* Awaria NIE może wyrenderować się jako pusta lista — „brak
                 projektów" czyta się jako fakt o świecie, a projekt jest tu
                 polem obowiązkowym, więc user zostałby z zablokowanym
                 przyciskiem i zerową wskazówką. */
              <div className="space-y-2">
                <Alert
                  variant="warning"
                  title="Nie udało się wczytać listy projektów"
                  description="Sprawdź połączenie i spróbuj ponownie."
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => listQuery.refetch()}
                >
                  Ponów
                </Button>
              </div>
            ) : options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {browseAll
                  ? "Brak otwartych projektów pasujących do wyszukiwania."
                  : "Kandydat nie jest w żadnej rekrutacji."}
              </p>
            ) : (
              <Select value={jobId} onValueChange={setJobId}>
                <SelectTrigger id="b2b-reactivate-job">
                  <SelectValue placeholder="Wybierz projekt…" />
                </SelectTrigger>
                <SelectContent>
                  {options.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <button
              type="button"
              className="text-xs text-primary hover:underline"
              onClick={() => {
                setBrowseAll((v) => !v);
                setJobId("");
              }}
            >
              {browseAll
                ? "← Wróć do rekrutacji kandydata"
                : "Szukaj w innych projektach →"}
            </button>
          </div>

          {browseAll ? (
            <div className="space-y-1.5">
              <Label htmlFor="b2b-reactivate-search">Szukaj projektu</Label>
              <Input
                id="b2b-reactivate-search"
                value={jobQuery}
                onChange={(e) => setJobQuery(e.target.value)}
                placeholder="Nazwa projektu…"
              />
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="b2b-reactivate-client">Klient</Label>
            <Input
              id="b2b-reactivate-client"
              value={selectedJob.isLoading && jobId ? "Ładowanie…" : clientLabel}
              readOnly
              disabled
            />
            <p className="text-xs text-muted-foreground">
              Uzupełniany automatycznie na podstawie wybranego projektu.
            </p>
          </div>
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
          <Button
            type="button"
            disabled={mut.isPending || !jobId}
            onClick={() => mut.mutate()}
          >
            {mut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Przywróć umowę
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Dziennik zmian statusu — jedyne miejsce, w którym data i powód zakończenia
 * poprzedniego projektu przetrwały powrót umowy na „Aktywna" (na wierszu pola
 * te MUSZĄ zostać wyczyszczone, wymusza to CHECK spójności w bazie).
 */
export function StatusHistoryDialog({
  row,
  open,
  onOpenChange,
}: {
  row: B2BGeneratedContractRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const q = useQuery({
    queryKey: ["b2b-status-history", row.id],
    queryFn: () => b2bGeneratorApi.statusHistory(row.id),
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Historia statusów {row.contract_number}</DialogTitle>
          <DialogDescription>
            Zapis wszystkich zmian statusu tej umowy wraz z datą i powodem
            zakończenia projektu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {q.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : q.isError ? (
            <div className="space-y-2">
              <Alert
                variant="warning"
                title="Nie udało się wczytać historii"
                description={extractErrorMsg(q.error)}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => q.refetch()}
              >
                Ponów
              </Button>
            </div>
          ) : (q.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Status tej umowy nie był jeszcze zmieniany.
            </p>
          ) : (
            <ol className="space-y-3">
              {(q.data ?? []).map((e) => (
                <li key={e.id} className="border-l-2 border-border pl-3">
                  <p className="text-sm font-medium">
                    {e.from_status
                      ? `${
                          B2B_CONTRACT_STATUS_LABEL[
                            e.from_status as B2BContractStatus
                          ] ?? e.from_status
                        } → `
                      : ""}
                    {B2B_CONTRACT_STATUS_LABEL[
                      e.to_status as B2BContractStatus
                    ] ?? e.to_status}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {[
                      e.effective_date
                        ? `Zakończenie: ${formatIsoDatePl(e.effective_date)}`
                        : null,
                      closureReasonText(
                        e.reason as B2BClosureReason | null,
                        e.reason_other,
                      ),
                      e.job_title ? `Projekt: ${e.job_title}` : null,
                      e.client_name ? `Klient: ${e.client_name}` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {[
                      e.changed_by_name,
                      e.created_at ? formatDateTimePl(e.created_at) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Stopka rejestru: ile wierszy widać i „Pokaż więcej”. Do 23.09.2026 rejestr
 * cicho kończył się na 100 najnowszych umowach — bez licznika lista przycięta
 * limitem czytała się jak komplet.
 */
export function RegisterPager({
  shown,
  hasMore,
  loading,
  failed = false,
  onMore,
}: {
  shown: number;
  hasMore: boolean;
  loading: boolean;
  failed?: boolean;
  onMore: () => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>Pokazano {countPl(shown, "umowę", "umowy", "umów")}</span>
      {failed ? (
        <span className="text-destructive" role="alert">
          Nie udało się wczytać kolejnych umów.
        </span>
      ) : null}
      {hasMore ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loading}
          onClick={onMore}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {failed ? "Ponów" : "Pokaż więcej"}
        </Button>
      ) : null}
    </div>
  );
}

/** Plakietki rozjazdu rejestru z modułem Kontrakty — patrz `registerRowWarnings`. */
function RegisterRowWarnings({ row }: { row: B2BGeneratedContractRow }) {
  const warnings = registerRowWarnings(row);
  if (warnings.length === 0) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      {warnings.map((w) => (
        // `h-auto` + `whitespace-normal`: zdanie z datą nie mieści się w jednej
        // linii wąskiej kolumny statusu, a stała wysokość badge'a ucinała je.
        <Badge
          key={w.text}
          variant={w.tone}
          size="md"
          className="h-auto max-w-56 whitespace-normal rounded-md text-left leading-snug"
        >
          {w.text}
        </Badge>
      ))}
    </div>
  );
}

export function GeneratedContractsTab({
  searchParam = null,
  canCorrect = true,
}: {
  /** `?q=` z adresu — link „popraw ją w rejestrze” z formularza. */
  searchParam?: string | null;
  /**
   * „Popraw umowę” otwiera zakładkę Generator — bez prawa generowania tej
   * zakładki nie ma, więc akcja prowadziłaby donikąd.
   */
  canCorrect?: boolean;
} = {}) {
  const toast = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [signatureRow, setSignatureRow] =
    useState<B2BGeneratedContractRow | null>(null);
  const [statusRow, setStatusRow] = useState<B2BGeneratedContractRow | null>(
    null,
  );
  const [historyRow, setHistoryRow] = useState<B2BGeneratedContractRow | null>(
    null,
  );
  const [search, setSearch] = useState(searchParam ?? "");
  // Efekt na WARTOŚCI parametru, nie sam inicjalizator: link z formularza to
  // miękka nawigacja, a zakładka bywa już zamontowana.
  useEffect(() => {
    if (searchParam) setSearch(searchParam);
  }, [searchParam]);
  // „all" w TEJ zakładce znaczy „bieżące" (aktywne, w trakcie podpisu
  // i anulowane), nie „wszystkie umowy w systemie": zamknięte i zawieszone mają
  // własne zakładki i nie mogą się tu pojawić, inaczej wiersz byłby widoczny
  // w dwóch miejscach naraz.
  const [statusFilter, setStatusFilter] = useState<
    "active" | "in_progress" | "cancelled" | "all"
  >("all");
  // Zakres daty ROZPOCZĘCIA USŁUG. Trzy tryby panelu (zakres / cały miesiąc /
  // konkretny dzień) sprowadzają się do jednej pary granic: miesiąc to pierwszy
  // i ostatni dzień, dzień to ta sama data w obu polach. `""` = brak granicy.
  const [startFrom, setStartFrom] = useState("");
  const [startTo, setStartTo] = useState("");
  const dateFilterActive = Boolean(startFrom || startTo);
  // Debounce, żeby nie strzelać zapytaniem na każdą literę wpisaną w szukajkę.
  const debouncedSearch = useDebouncedValue(search, 300);
  const q = useInfiniteQuery({
    // Filtr daty MUSI być w kluczu — bez tego react-query oddaje wynik
    // poprzedniego zakresu z cache i zmiana granic „nic nie robi". Filtry
    // w kluczu resetują też stronicowanie: nowy klucz = od pierwszej strony.
    // „register" odróżnia ten kształt (strony) od listy rekrutacji
    // (`["b2b-generated", "job", id]`, zwykła tablica) pod tym samym prefiksem.
    queryKey: [
      "b2b-generated",
      "register",
      debouncedSearch,
      statusFilter,
      startFrom,
      startTo,
    ],
    initialPageParam: 0,
    getNextPageParam: (
      lastPage: B2BGeneratedContractRow[],
      allPages: B2BGeneratedContractRow[][],
    ) => nextRegisterOffset(lastPage, allPages.length),
    queryFn: ({ pageParam }: { pageParam: number }) =>
      b2bGeneratorApi.generated(B2B_REGISTER_PAGE_SIZE, {
        q: debouncedSearch,
        // „Wszystkie" w tej zakładce znaczy „bieżące": trzy statusy sprzed
        // zakładek terminalnych. `cancelled` zostaje tutaj świadomie — wiersz
        // ma być pod ręką, żeby dało się go cofnąć na „W trakcie".
        contractStatus:
          statusFilter === "all"
            ? ["active", "in_progress", "cancelled"]
            : [statusFilter],
        startFrom: startFrom || undefined,
        startTo: startTo || undefined,
        ...(pageParam ? { offset: pageParam } : {}),
      }),
    staleTime: 10_000,
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => b2bGeneratorApi.deleteGenerated(id),
    onSuccess: () => {
      // Od 23.09.2026 numer usuniętej umowy NIE wraca do puli — usunięty
      // DOCX mógł już trafić do Partnera (1518 i 1522/2026 wydane dwa razy).
      toast.showSuccess(
        "Umowa usunięta z rejestru — jej numer nie wraca do puli.",
      );
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
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
  const rows = useMemo(
    () => mergeRegisterPages(q.data?.pages ?? []),
    [q.data],
  );

  const handleConfirmed = (result: B2BConfirmFullySignedResult) => {
    const fallbackMessage =
      result.outcome === "created"
        ? "Umowa podpisana — utworzono aktywny kontrakt."
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
        `Usunąć umowę „${label}” z listy? Tej operacji nie można cofnąć, a numer nie wróci do puli.`,
      )
    ) {
      deleteMut.mutate(r.id);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Umowy bieżące</CardTitle>
        <CardDescription>
          Umowy obowiązujące, czekające na podpis obu stron oraz anulowane (te,
          które nie doszły do skutku — numer został zużyty, więc wpis zostaje) —
          sprawdź, czy sugerowany / wpisany numer nie powtarza istniejącego.
          Umowę można pobrać ponownie, a nazwę Klienta poprawić („Edytuj").
          Potwierdzenie podpisania uruchamia jednorazowo proces zatrudnienia.
          Niepodpisany wpis może edytować lub usunąć osoba, która go
          wygenerowała, albo administrator. Zawieszenie lub zakończenie umowy
          („Zmień status") nie usuwa jej z systemu — przenosi ją do zakładki
          „Umowy bez projektu" albo „Zakończone umowy".
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isForbidden(q.error) ? null : (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative w-full min-w-0 flex-1 sm:w-auto sm:min-w-[18rem]">
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
                setStatusFilter(
                  v as "active" | "in_progress" | "cancelled" | "all",
                )
              }
            >
              <SelectTrigger className="w-full sm:w-56" aria-label="Filtr statusu umowy">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* Bez „Zakończona" i „Zawieszona": te wiersze mają własne
                    zakładki. Zostawienie ich tutaj pokazywałoby tę samą umowę
                    w dwóch miejscach naraz i psuło obietnicę nazwy zakładki.
                    „Anulowana" JEST tutaj, bo własnej zakładki nie ma — jej
                    miejsce jest obok umów, z których powstała. */}
                <SelectItem value="all">Wszystkie statusy</SelectItem>
                <SelectItem value="in_progress">
                  {B2B_CONTRACT_STATUS_LABEL.in_progress}
                </SelectItem>
                <SelectItem value="active">
                  {B2B_CONTRACT_STATUS_LABEL.active}
                </SelectItem>
                <SelectItem value="cancelled">
                  {B2B_CONTRACT_STATUS_LABEL.cancelled}
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
        ) : q.error && !q.data ? (
          /* Awaria ≠ pustka — lustro zakładek „bez projektu” i „zakończone”.
             Bez tej gałęzi padnięte zapytanie wpadało w `rows = q.data ?? []`
             i renderowało się jako „Brak umów bieżących”, czyli jako fakt. */
          <div className="space-y-2">
            <Alert
              variant="warning"
              title="Nie udało się wczytać listy"
              description={extractErrorMsg(q.error)}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => q.refetch()}
            >
              Ponów
            </Button>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {/* Pustka po wyszukaniu ≠ brak umów w systemie — inaczej czyta się
                to jak utratę danych (ten sam błąd co przy 403 wyżej).
                Filtr daty MUSI być w tym warunku: bez niego odfiltrowana lista
                twierdziłaby „Brak wygenerowanych umów", czyli awaria
                wyrenderowałaby się jako utrata danych. */}
            {debouncedSearch.trim() || statusFilter !== "all" || dateFilterActive
              ? "Brak umów pasujących do wyszukiwania."
              : "Brak umów bieżących."}
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
                  {/* „Wygenerowano" niesie datę I autora (druga linia) —
                      jedna kolumna zamiast dwóch. Kontener jest przycięty do
                      `max-w-7xl`, więc rejestr o 10 kolumnach przelewał się
                      na KAŻDYM monitorze, a przyklejona kolumna akcji
                      zasłaniała wtedy to, co pod nią leżało: „Status podpisu"
                      z uciętym „Oznacz jako…". */}
                  <th className="py-2 pr-4 font-medium">Wygenerowano</th>
                  {/* `sticky right-0`: przy tylu kolumnach tabela przelewa się
                      w poziomy scroll i akcje lądowały za prawą krawędzią —
                      ucięty przycisk czyta się jak brak możliwości („nie da
                      się usunąć"), więc kolumna akcji musi być widoczna bez
                      przewijania. Przyklejona kolumna ZASŁANIA jednak wszystko,
                      co pod nią, dopóki użytkownik nie przewinie — dlatego
                      akcje są ikonowe (z `aria-label` i `title`): trzy
                      przyciski z tekstem miały 283 px i zakrywały pół
                      „Status podpisu". */}
                  <th className="bg-card py-2 pl-2 text-right font-medium shadow-[inset_1px_0_0_hsl(var(--border))] md:sticky md:right-0 md:z-10">
                    Akcje
                  </th>
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
                  const cancelled = r.contract_status === "cancelled";
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
                      <td className="py-2 pr-4 tabular-nums">{formatIsoDatePl(r.start_date)}</td>
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
                            className="h-8 min-w-[12rem] md:min-w-[16rem]"
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
                                    closureReasonText(
                                      r.closure_reason,
                                      r.closure_reason_other,
                                    )
                                      ? `Powód: ${closureReasonText(
                                          r.closure_reason,
                                          r.closure_reason_other,
                                        )}`
                                      : null,
                                    r.closure_date
                                      ? `Zakończenie: ${formatIsoDatePl(r.closure_date)}`
                                      : null,
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                : r.contract_status === "in_progress"
                                  ? "Wygenerowana, czeka na podpis obu stron"
                                  : cancelled
                                    ? "Umowa nie doszła do skutku — Partner wycofał się przed podpisem. Numer został zużyty, więc wpis zostaje w rejestrze."
                                    : "Umowa podpisana i obowiązująca"
                            }
                          >
                            <StatusIcon status={r.contract_status} />
                            {B2B_CONTRACT_STATUS_LABEL[r.contract_status]}
                          </Badge>

                          {closed ? (
                            <span className="max-w-56 text-xs text-muted-foreground">
                              {closureReasonText(
                                r.closure_reason,
                                r.closure_reason_other,
                              )}
                              {r.closure_date ? ` · ${formatIsoDatePl(r.closure_date)}` : ""}
                            </span>
                          ) : null}
                          <RegisterRowWarnings row={r} />

                          <div className="flex items-center gap-1">
                            {r.can_change_status ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                onClick={() => setStatusRow(r)}
                                title="Zmień status umowy"
                                aria-label={`Zmień status umowy ${r.contract_number}`}
                              >
                                <Pencil className="h-4 w-4" />
                                <span className="ml-1">Zmień status</span>
                              </Button>
                            ) : null}
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2"
                              onClick={() => setHistoryRow(r)}
                              title="Historia statusów"
                              aria-label="Historia statusów"
                            >
                              <History className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex flex-col items-start gap-1.5">
                          {/* Anulowana umowa NIE zmienia etykiety — podpisu
                              nadal nie ma, więc „Niepodpisana" jest prawdą.
                              Zmienia się kolor: badge nie ma osobnego elementu
                              kropki, ikona dziedziczy jego wariant, więc
                              `danger` jest sposobem na czerwony wskaźnik.
                              Szary `outline` obok czerwonego statusu umowy
                              sugerowałby, że ta umowa wciąż na coś czeka. */}
                          <Badge
                            variant={
                              signed
                                ? "success"
                                : cancelled
                                  ? "danger"
                                  : "outline"
                            }
                            size="md"
                            title={
                              signed
                                ? [
                                    r.signed_by_name
                                      ? `Potwierdził: ${r.signed_by_name}`
                                      : null,
                                    r.signed_at
                                      ? `Data: ${formatDateTimePl(r.signed_at)}`
                                      : null,
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                : cancelled
                                  ? "Umowa anulowana — nie doszła do skutku i nie może zostać podpisana"
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
                      <td className="py-2 pr-4">
                        <div className="flex flex-col gap-0.5">
                          <span className="whitespace-nowrap text-muted-foreground">
                            {formatDateTimePl(r.created_at)}
                          </span>
                          <span className="text-muted-foreground">
                            {r.created_by_name || "—"}
                          </span>
                        </div>
                      </td>
                      <td className="bg-card py-2 pl-2 text-right shadow-[inset_1px_0_0_hsl(var(--border))] md:sticky md:right-0 md:z-10">
                        <div className="flex items-center justify-end gap-1">
                          {editing ? (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10"
                                disabled={saving}
                                onClick={() => saveEdit(r.id)}
                                title="Zapisz nazwę Klienta"
                                aria-label="Zapisz nazwę Klienta"
                              >
                                {saving ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Save className="h-4 w-4" />
                                )}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10"
                                disabled={saving}
                                onClick={() => setEditingId(null)}
                                title="Anuluj edycję"
                                aria-label="Anuluj edycję"
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </>
                          ) : (
                            <>
                              {canCorrect && canCorrectInForm(r) ? (
                                // Poprawka treści pod tym samym numerem. Do
                                // 23.09.2026 działała tylko w karcie, w której
                                // umowę pobrano; po odświeżeniu zostawało
                                // „Usuń”, a usunięcie trwale zużywa numer.
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10"
                                  onClick={() =>
                                    router.replace(generatorEditHref(r.id), {
                                      scroll: false,
                                    })
                                  }
                                  title="Popraw umowę (ten sam numer)"
                                  aria-label={`Popraw umowę ${r.contract_number}`}
                                >
                                  <FilePen className="h-4 w-4" />
                                </Button>
                              ) : null}
                              {!signed && r.can_edit ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10"
                                  onClick={() => startEdit(r)}
                                  title="Edytuj nazwę Klienta"
                                  aria-label="Edytuj nazwę Klienta"
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                              ) : null}
                              {r.can_download ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10"
                                  disabled={downloading}
                                  onClick={() => downloadMut.mutate(r)}
                                  title="Pobierz DOCX ponownie"
                                  aria-label="Pobierz DOCX ponownie"
                                >
                                  {downloading ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Download className="h-4 w-4" />
                                  )}
                                </Button>
                              ) : null}
                              {!signed && r.can_delete ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0 pointer-coarse:h-10 pointer-coarse:w-10 text-destructive hover:text-destructive"
                                  disabled={deleting}
                                  onClick={() => confirmDelete(r)}
                                  title="Usuń umowę z listy"
                                  aria-label="Usuń umowę z listy"
                                >
                                  {deleting ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-4 w-4" />
                                  )}
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
        {/* `!(error && !data)`, nie `!error`: nieudane „Pokaż więcej” ustawia
            `error`, a pierwsza strona zostaje — bez stopki 100 wierszy
            wyglądałoby na komplet, a komunikat i „Ponów” by znikły. */}
        {rows.length > 0 && !(q.error && !q.data) ? (
          <RegisterPager
            shown={rows.length}
            hasMore={q.hasNextPage}
            loading={q.isFetchingNextPage}
            failed={q.isFetchNextPageError}
            onMore={() => void q.fetchNextPage()}
          />
        ) : null}
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
      {historyRow ? (
        <StatusHistoryDialog
          row={historyRow}
          open
          onOpenChange={(open) => {
            if (!open) setHistoryRow(null);
          }}
        />
      ) : null}
    </Card>
  );
}

/**
 * Zakładki „Umowy bez projektu" i „Zakończone umowy".
 *
 * Jeden komponent dla obu, bo różnią je wyłącznie: filtrowany status, etykieta
 * kolumny z datą (projekt vs umowa) i obecność akcji. Dwie kopie rozjechałyby
 * się przy pierwszej zmianie kolumn — a to ten sam rejestr, tylko w innej fazie
 * życia.
 */
function LifecycleContractsTab({
  status,
  title,
  description,
  dateColumnLabel,
  allowActions,
  allowStatusChange = allowActions,
  emptyLabel,
  searchParam = null,
}: {
  status: Extract<B2BContractStatus, "suspended" | "closed">;
  title: string;
  description: string;
  dateColumnLabel: string;
  /** „Przywróć” — tylko umowa zawieszona wraca do gry z nowym projektem. */
  allowActions: boolean;
  /**
   * „Zmień status” — w „Zakończonych” po to, żeby dało się cofnąć pomyłkowe
   * zakończenie (niepodpisana → „W trakcie”). Do 23.09.2026 zakładka była
   * tylko do odczytu i taki wiersz utykał w niej na zawsze.
   */
  allowStatusChange?: boolean;
  emptyLabel: string;
  /** `?q=` z adresu — link do umowy z formularza generatora. */
  searchParam?: string | null;
}) {
  const [search, setSearch] = useState(searchParam ?? "");
  useEffect(() => {
    if (searchParam) setSearch(searchParam);
  }, [searchParam]);
  const [reasonFilter, setReasonFilter] = useState<B2BClosureReason | "all">(
    "all",
  );
  const [startFrom, setStartFrom] = useState("");
  const [startTo, setStartTo] = useState("");
  const [statusRow, setStatusRow] = useState<B2BGeneratedContractRow | null>(
    null,
  );
  const [reactivateRow, setReactivateRow] =
    useState<B2BGeneratedContractRow | null>(null);
  const [historyRow, setHistoryRow] = useState<B2BGeneratedContractRow | null>(
    null,
  );
  const debouncedSearch = useDebouncedValue(search, 300);
  const dateFilterActive = Boolean(startFrom || startTo);

  const params: B2BGeneratedListParams = {
    q: debouncedSearch,
    contractStatus: [status],
    closureReason: reasonFilter === "all" ? undefined : reasonFilter,
    startFrom: startFrom || undefined,
    startTo: startTo || undefined,
  };
  const q = useInfiniteQuery({
    // Filtry w kluczu = zmiana filtra zaczyna stronicowanie od początku.
    queryKey: [
      "b2b-generated",
      "lifecycle",
      status,
      debouncedSearch,
      reasonFilter,
      startFrom,
      startTo,
    ],
    initialPageParam: 0,
    getNextPageParam: (
      lastPage: B2BGeneratedContractRow[],
      allPages: B2BGeneratedContractRow[][],
    ) => nextRegisterOffset(lastPage, allPages.length),
    queryFn: ({ pageParam }: { pageParam: number }) =>
      b2bGeneratorApi.generated(B2B_REGISTER_PAGE_SIZE, {
        ...params,
        ...(pageParam ? { offset: pageParam } : {}),
      }),
    staleTime: 10_000,
  });
  const rows = useMemo(
    () => mergeRegisterPages(q.data?.pages ?? []),
    [q.data],
  );
  const showActionsColumn = allowActions || allowStatusChange;
  const filtersActive =
    Boolean(debouncedSearch.trim()) || reasonFilter !== "all" || dateFilterActive;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {isForbidden(q.error) ? null : (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative w-full min-w-0 flex-1 sm:w-auto sm:min-w-[18rem]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
                placeholder="Szukaj: numer umowy, firma, NIP, kandydat…"
                aria-label={`Szukaj — ${title}`}
              />
            </div>
            {/* Filtr statusu byłby tu bez sensu (z definicji jeden), więc
                „Filtruj" to powód zakończenia + zakres daty rozpoczęcia. */}
            <Select
              value={reasonFilter}
              onValueChange={(v) =>
                setReasonFilter(v as B2BClosureReason | "all")
              }
            >
              <SelectTrigger
                className="w-full sm:w-72"
                aria-label="Filtr powodu zakończenia"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Wszystkie powody</SelectItem>
                {CLOSURE_REASONS.map((key) => (
                  <SelectItem key={key} value={key}>
                    {B2B_CLOSURE_REASON_LABEL[key]}
                  </SelectItem>
                ))}
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
        ) : q.error && !q.data ? (
          /* Awaria ≠ pustka. Bez tej gałęzi padnięte zapytanie renderowałoby
             się jako „brak umów", czyli jako fakt o świecie. */
          <div className="space-y-2">
            <Alert
              variant="warning"
              title="Nie udało się wczytać listy"
              description={extractErrorMsg(q.error)}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => q.refetch()}
            >
              Ponów
            </Button>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {filtersActive ? "Brak umów pasujących do wyszukiwania." : emptyLabel}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Numer umowy</th>
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
                  <th className="py-2 pr-4 font-medium">{dateColumnLabel}</th>
                  <th className="py-2 pr-4 font-medium">Klient</th>
                  <th className="py-2 pr-4 font-medium">Status umowy</th>
                  <th className="py-2 pr-4 font-medium">
                    Powód zakończenia projektu
                  </th>
                  {showActionsColumn ? (
                    <th className="bg-card py-2 pl-2 text-right font-medium shadow-[inset_1px_0_0_hsl(var(--border))] md:sticky md:right-0 md:z-10">
                      Akcje
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b">
                    <td className="py-2 pr-4 font-medium">
                      {r.contract_number}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex flex-col gap-0.5">
                        <span>
                          {r.partner_display_name || r.partner_name || "—"}
                        </span>
                        {r.partner_secondary_line ? (
                          <span className="text-xs text-muted-foreground">
                            {r.partner_secondary_line}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {r.partner_nip || "—"}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {formatIsoDatePl(r.start_date)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {formatIsoDatePl(r.closure_date)}
                    </td>
                    <td className="py-2 pr-4">{r.client_name || "—"}</td>
                    <td className="py-2 pr-4">
                      <div className="flex flex-col items-start gap-1">
                        <Badge
                          variant={B2B_CONTRACT_STATUS_VARIANT[r.contract_status]}
                          size="md"
                        >
                          <StatusIcon status={r.contract_status} />
                          {B2B_CONTRACT_STATUS_LABEL[r.contract_status]}
                        </Badge>
                        <RegisterRowWarnings row={r} />
                      </div>
                    </td>
                    <td className="py-2 pr-4">
                      {closureReasonText(
                        r.closure_reason,
                        r.closure_reason_other,
                      ) || "—"}
                    </td>
                    {showActionsColumn ? (
                      <td className="bg-card py-2 pl-2 text-right shadow-[inset_1px_0_0_hsl(var(--border))] md:sticky md:right-0 md:z-10">
                        <div className="flex items-center justify-end gap-1">
                          {r.can_change_status && allowActions ? (
                            <>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-8"
                                onClick={() => setReactivateRow(r)}
                              >
                                <CircleDot className="h-4 w-4" />
                                Przywróć
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                onClick={() => setStatusRow(r)}
                                title="Zakończ umowę"
                                aria-label={`Zakończ umowę ${r.contract_number}`}
                              >
                                <CircleSlash className="h-4 w-4" />
                              </Button>
                            </>
                          ) : r.can_change_status && allowStatusChange ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2"
                              onClick={() => setStatusRow(r)}
                              title="Zmień status umowy"
                              aria-label={`Zmień status umowy ${r.contract_number}`}
                            >
                              <Pencil className="h-4 w-4" />
                              <span className="ml-1">Zmień status</span>
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-8 px-2"
                            onClick={() => setHistoryRow(r)}
                            title="Historia statusów"
                            aria-label="Historia statusów"
                          >
                            <History className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > 0 && !(q.error && !q.data) ? (
          <RegisterPager
            shown={rows.length}
            hasMore={q.hasNextPage}
            loading={q.isFetchingNextPage}
            failed={q.isFetchNextPageError}
            onMore={() => void q.fetchNextPage()}
          />
        ) : null}
      </CardContent>

      {statusRow ? (
        <ContractStatusDialog
          row={statusRow}
          open
          onOpenChange={(open) => {
            if (!open) setStatusRow(null);
          }}
        />
      ) : null}
      {reactivateRow ? (
        <ReactivateContractDialog
          row={reactivateRow}
          open
          onOpenChange={(open) => {
            if (!open) setReactivateRow(null);
          }}
        />
      ) : null}
      {historyRow ? (
        <StatusHistoryDialog
          row={historyRow}
          open
          onOpenChange={(open) => {
            if (!open) setHistoryRow(null);
          }}
        />
      ) : null}
    </Card>
  );
}

export function NoProjectContractsTab({
  searchParam = null,
}: { searchParam?: string | null } = {}) {
  return (
    <LifecycleContractsTab
      searchParam={searchParam}
      status="suspended"
      title="Umowy bez projektu"
      description={
        "Umowy, które nadal obowiązują, ale kontraktor nie ma aktualnie " +
        "przypisanego projektu. Przywrócenie do gry wymaga wskazania nowego " +
        "projektu — klient dociągnie się z niego, a informacja o poprzednim " +
        "projekcie trafi jako notatka do powiązanego kontraktu."
      }
      dateColumnLabel="Data zakończenia projektu"
      allowActions
      emptyLabel="Brak umów bez przypisanego projektu."
    />
  );
}

export function ClosedContractsTab({
  searchParam = null,
}: { searchParam?: string | null } = {}) {
  return (
    <LifecycleContractsTab
      searchParam={searchParam}
      status="closed"
      title="Zakończone umowy"
      description={
        "Umowy, które przestały obowiązywać. Pomyłkowo zakończoną, " +
        "niepodpisaną umowę cofniesz na „W trakcie” przyciskiem „Zmień status”."
      }
      dateColumnLabel="Data zakończenia umowy"
      allowActions={false}
      allowStatusChange
      emptyLabel="Brak zakończonych umów."
    />
  );
}

// ── Generator form ──────────────────────────────────────────────────────────

/**
 * Stan listy rekrutacji kandydata pod selectem generatora (UAT M08-B07).
 * Awaria nie może wyglądać jak pustka, a pusta lista potrzebuje zdania —
 * rozwinięty, pusty select nie mówi, co zrobić dalej.
 */
export function RecruitmentOptionsNotice({
  hasCandidate,
  isError,
  isEmpty,
  onRetry,
}: {
  hasCandidate: boolean;
  isError: boolean;
  isEmpty: boolean;
  onRetry: () => void;
}) {
  if (!hasCandidate) return null;
  if (isError) {
    return (
      <p className="mt-1.5 text-xs text-destructive" role="alert">
        Nie udało się wczytać rekrutacji kandydata.{" "}
        <button
          type="button"
          className="underline underline-offset-2"
          onClick={onRetry}
        >
          Ponów
        </button>
      </p>
    );
  }
  if (isEmpty) {
    return (
      <p className="mt-1.5 text-xs text-muted-foreground">
        Kandydat nie jest w żadnej rekrutacji — dodaj go do rekrutacji, aby
        wygenerować umowę.
      </p>
    );
  }
  return null;
}

/**
 * Umowa, którą formularz właśnie opisuje — po pierwszym „Pobierz DOCX”.
 * Dopóki jest ustawiona, pobranie POPRAWIA ten wiersz rejestru pod tym samym
 * numerem (`/rerender`) zamiast zakładać kolejny: do 23.09.2026 każda
 * poprawka literówki albo zmiana języka dawała nowy numer (15 usunięć na
 * ~104 generacje).
 */
type SavedContract = {
  id: number;
  number: string;
  candidateId: number | null;
  jobId: number | null;
};

/** Telefon z payloadu („+48 600 100 200”) → prefiks z listy + numer. */
function splitPhone(value: string | null | undefined): {
  prefix: string;
  number: string;
} {
  const v = (value ?? "").trim();
  const prefix = PHONE_PREFIXES.find((p) => v.startsWith(`${p} `));
  // Numer bez znanego prefiksu zostaje w całości — `buildPayload` wysyła
  // wartość zaczynającą się od „+” bez doklejania prefiksu z listy.
  return prefix
    ? { prefix, number: v.slice(prefix.length + 1).trim() }
    : { prefix: "+48", number: v };
}

export function GeneratorForm({
  prefillCandidateId = null,
  prefillJobId = null,
  editGeneratedId = null,
  onClearPrefill,
  onEditConsumed,
}: {
  /** `?candidate=` z adresu — link „Otwórz w Generatorze” z kroku „Umowa”. */
  prefillCandidateId?: number | null;
  /** `?job=` — rekrutacja do wybrania, gdy kandydat w niej jest. */
  prefillJobId?: number | null;
  /** `?edit=` — zapisana umowa do wczytania i poprawy pod tym samym numerem. */
  editGeneratedId?: number | null;
  /** „Nowa umowa” zdejmuje parę z adresu, żeby F5 nie wypełnił jej znowu. */
  onClearPrefill?: () => void;
  /** Zdejmuje `?edit=` z adresu po wczytaniu albo odmowie. */
  onEditConsumed?: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const currencyId = useId();
  const clientPickerId = useId();
  const phoneId = useId();
  const startDateId = useId();
  const candidatePickerId = useId();
  const recruitmentId = useId();
  const roleSelectId = useId();

  const [language, setLanguage] = useState<Lang>("pl");

  // Źródło danych — wymagane powiązanie kandydata z rekrutacją.
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");
  // Debounce jak w rejestrze — bez niego każda litera to osobne zapytanie.
  const debouncedCandidateQuery = useDebouncedValue(candidateQuery, 300);
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
  // Lista punktów zakresu z zapisanej umowy. Formularz jej nie edytuje, ale
  // poprawka wczytanej umowy nie może jej po cichu zgubić.
  const [scopeItemsOverride, setScopeItemsOverride] = useState<string[] | null>(
    null,
  );
  // NIP wczytany z zapisanej umowy — lookup rejestru go pomija, bo nadpisałby
  // zapisaną nazwę firmy, REGON i adres danymi z dziś (a to tylko poprawka).
  const nipLookupSkip = useRef<string | null>(null);
  const [partnerEntityType, setPartnerEntityType] = useState<
    "sole_trader" | "company" | null
  >(null);

  const [previewHtml, setPreviewHtml] = useState<string>("");
  const [savedContract, setSavedContract] = useState<SavedContract | null>(
    null,
  );

  // Pre-fill „raz na kandydata / ofertę" — nie nadpisuje ręcznych zmian.
  const prefilledCand = useRef<number | null>(null);
  const prefilledJob = useRef<number | null>(null);
  // Użytkownik ręcznie zmienił opis → nie nadpisuj smart-prefillem.
  const descTouched = useRef(false);
  // Użytkownik ręcznie poprawił narzędnik → nie nadpisuj auto-odmianą.
  const instrTouched = useRef(false);
  // Pola klienta/projektu pochodzą z rekrutacji — kolejna rekrutacja podmienia
  // je w całości, także na puste (inaczej miasto z poprzedniej zostawało).
  const jobFieldsFromJob = useRef(false);
  // Rekrutacja z adresu, wybierana, gdy dojdzie lista rekrutacji kandydata.
  // Para z kandydatem, bo lista rekrutacji poprzedniej osoby nie może jej
  // „zużyć”, zanim dojdzie lista nowej.
  const [pendingPrefill, setPendingPrefill] = useState<{
    candidateId: number;
    jobId: number;
    /** Wczytana umowa — brak jej rekrutacji na liście trzeba powiedzieć. */
    fromSaved?: boolean;
  } | null>(null);

  const candidatesQuery = useQuery({
    queryKey: ["b2b-gen-candidates", debouncedCandidateQuery],
    queryFn: async () => {
      const res = await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
        params: { q: debouncedCandidateQuery, limit: 20 },
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
    // Pierwsza rekrutacja uzupełnia tylko to, co ma; każda KOLEJNA podmienia
    // pola w całości — pusta wartość nowej rekrutacji czyści pole po starej,
    // inaczej umowa dostawała miasto i klienta z poprzednio wybranej.
    const replace = jobFieldsFromJob.current;
    jobFieldsFromJob.current = true;
    if (j.description) {
      setProjectDescription(j.description);
      descTouched.current = true; // opis z rekrutacji ma priorytet nad smart-prefillem
    } else if (replace) {
      descTouched.current = false;
      setProjectDescription(
        areaPrefillDescription({
          role: selectedRole,
          language,
          clientName: j.client_name ?? "",
          descTouched: false,
        }) ?? "",
      );
    }
    if (j.location) setProjectCity(j.location);
    else if (replace) setProjectCity("");
    if (j.client_name) setClientName(j.client_name);
    else if (replace) setClientName("");
  }, [jobQuery.data, selectedRecruitment, selectedRole, language]);

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
    if (nipLookupSkip.current !== null && nipLookupSkip.current === nip) {
      setPartnerLookup("idle");
      return;
    }
    nipLookupSkip.current = null;
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
        // JDG → `person` = imię i nazwisko właściciela; `name` = nazwa firmy
        // (pełna z CEIDG, lub nazwisko z Białej Listy). Nazwisko UZUPEŁNIAMY
        // tylko gdy puste — rejestr nie może nadpisać nazwiska kandydata ze
        // „Źródła danych" (jego NIP bywa cudzy/spółkowy → `person` był inną
        // osobą). Updater funkcyjny czyta świeży stan bez dokładania
        // `partnerName` do zależności efektu (inaczej lookup leciałby na każdy
        // znak nazwiska). Reszta pól to dane rejestrowe — nadpisują się.
        setPartnerName((prev) => partnerNameAfterLookup(prev, d.person));
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

  /**
   * Wybór innego kandydata to inna osoba w umowie: pola Partnera z profilu
   * poprzedniego kandydata nie mogą przetrwać (prefill nowego nadpisuje tylko
   * to, co ma w profilu — reszta zostawała po starym), a flagi „dotknięcia”
   * blokowałyby auto-odmianę narzędnika i opis dla nowej osoby.
   * Zmiana pary kończy też poprawianie zapisanej umowy — to już nowa umowa.
   */
  const selectCandidate = (next: CandidateOption | null) => {
    const changed = (candidate?.id ?? null) !== (next?.id ?? null);
    setCandidate(next);
    setStageId("");
    if (!changed) return;
    prefilledCand.current = null;
    prefilledJob.current = null;
    instrTouched.current = false;
    descTouched.current = false;
    if (candidate) {
      setPartnerName("");
      setPartnerInstrumental("");
      setPartnerLegalName("");
      setPartnerNip("");
      setPartnerRegon("");
      setPartnerBusinessAddress("");
      setPartnerCorrespondenceAddress("");
      setPartnerEmail("");
      setPartnerPhone("");
      setPartnerEntityType(null);
    }
    setScopeItemsOverride(null);
    nipLookupSkip.current = null;
    leaveSavedContract();
  };

  const selectStage = (value: string) => {
    if (value !== stageId) leaveSavedContract();
    setStageId(value);
  };

  /** Koniec poprawiania zapisanej umowy — następne pobranie to nowy numer. */
  const leaveSavedContract = () => {
    if (!savedContract) return;
    setSavedContract(null);
    void nextNumberQuery.refetch().then((r) => {
      if (r.data) setContractNumber(r.data.contract_number);
    });
  };

  // Para (kandydat, rekrutacja) z adresu — link z kroku „Umowa” rekrutacji.
  // Efekt na WARTOŚCI parametrów: miękka nawigacja nie odmontowuje formularza.
  useEffect(() => {
    if (!prefillCandidateId) return;
    let cancelled = false;
    const pending = prefillJobId
      ? { candidateId: prefillCandidateId, jobId: prefillJobId }
      : null;
    if (candidate?.id === prefillCandidateId) {
      setPendingPrefill(pending);
      return;
    }
    api
      .get<CandidateDetail>(`/api/candidates/${prefillCandidateId}`)
      .then((res) => {
        if (cancelled) return;
        const d = res.data;
        const fullName =
          d.full_name || `${d.name ?? ""} ${d.lastname ?? ""}`.trim();
        selectCandidate({
          id: prefillCandidateId,
          name: d.name ?? "",
          lastname: d.lastname ?? "",
          full_name: fullName || `Kandydat #${prefillCandidateId}`,
          email: d.email ?? null,
        });
        // selectCandidate czyści etap — rekrutację wybierze efekt niżej.
        setPendingPrefill(pending);
      })
      .catch((e: unknown) => {
        if (!cancelled) toast.showError(extractErrorMsg(e));
      });
    return () => {
      cancelled = true;
    };
    // Tylko na zmianę parametrów adresu — reszta to stan chwili wyboru.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillCandidateId, prefillJobId]);

  useEffect(() => {
    if (
      !pendingPrefill ||
      candidate?.id !== pendingPrefill.candidateId ||
      !recruitmentsQuery.data
    )
      return;
    const match = recruitmentsQuery.data.find(
      (r) => r.job_id === pendingPrefill.jobId,
    );
    setPendingPrefill(null);
    if (match) setStageId(String(match.stage_id));
    else if (pendingPrefill.fromSaved) {
      // Bez rekrutacji formularz nie przejdzie walidacji, a poprawka wymaga
      // tej samej pary — cisza zostawiłaby zablokowany przycisk bez powodu.
      toast.showError(
        "Rekrutacji tej umowy nie ma już na liście rekrutacji kandydata — " +
          "poprawka pod tym samym numerem wymaga tej samej rekrutacji.",
      );
    }
    // `toast` ze stabilnego kontekstu — nie jest sygnałem do ponownego wyboru.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingPrefill, candidate?.id, recruitmentsQuery.data]);

  // `?edit=<id>` — „Popraw umowę” z wiersza rejestru albo z ostrzeżenia
  // o istniejącej umowie. Efekt na WARTOŚCI parametru (miękka nawigacja nie
  // odmontowuje formularza). Wczytuje zapisany payload do KAŻDEGO pola
  // i przełącza w tryb poprawki: pobranie idzie do `/rerender` tego wiersza.
  useEffect(() => {
    if (!editGeneratedId) return;
    let cancelled = false;
    (async () => {
      try {
        const { id, contract_number, form } =
          await b2bGeneratorApi.generatedForm(editGeneratedId);
        let candidateOption: CandidateOption | null = null;
        if (form.candidate_id) {
          const res = await api.get<CandidateDetail>(
            `/api/candidates/${form.candidate_id}`,
          );
          const d = res.data;
          const fullName =
            d.full_name || `${d.name ?? ""} ${d.lastname ?? ""}`.trim();
          candidateOption = {
            id: form.candidate_id,
            name: d.name ?? "",
            lastname: d.lastname ?? "",
            full_name: fullName || `Kandydat #${form.candidate_id}`,
            email: d.email ?? null,
          };
        }
        if (cancelled) return;
        applySavedForm(id, contract_number, form, candidateOption);
      } catch (e: unknown) {
        if (!cancelled) toast.showError(extractErrorMsg(e));
      } finally {
        if (!cancelled) onEditConsumed?.();
      }
    })();
    return () => {
      cancelled = true;
    };
    // Tylko na zmianę parametru — reszta to stan chwili wczytania.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editGeneratedId]);

  // Żywa umowa tej osoby w tej rekrutacji — ostrzeżenie przed drugą. Ten sam
  // klucz i kształt co krok „Umowa” rekrutacji (`JobContractTab`), więc
  // unieważnienie `["b2b-generated"]` po pobraniu odświeża oba miejsca.
  const selectedJobId = selectedRecruitment?.job_id ?? null;
  const jobContractsQuery = useQuery({
    queryKey: ["b2b-generated", "job", selectedJobId],
    queryFn: () =>
      b2bGeneratorApi.generated(50, { jobId: selectedJobId ?? undefined }),
    enabled: !!candidate && !!selectedJobId,
    staleTime: 60_000,
  });
  // Zapisana umowa obowiązuje tylko dla tej samej pary — inna osoba albo
  // rekrutacja to nowa umowa (backend i tak odrzuciłby poprawkę 422).
  const activeSaved =
    savedContract &&
    savedContract.candidateId === (candidate?.id ?? null) &&
    savedContract.jobId === selectedJobId
      ? savedContract
      : null;
  const existingContract = existingContractFor(
    jobContractsQuery.data ?? [],
    candidate?.id,
    savedContract?.id ?? null,
  );

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
    ...(scopeItemsOverride ? { scope_items_override: scopeItemsOverride } : {}),
  });

  // Podgląd opisuje dane z chwili kliknięcia — po każdej zmianie formularza
  // znika, zamiast udawać aktualny dokument.
  const previewKey = JSON.stringify(buildPayload(language));
  useEffect(() => {
    setPreviewHtml("");
  }, [previewKey]);

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
    mutationFn: async () => {
      const payload = buildPayload(language);
      // Formularz opisuje zapisaną umowę → poprawka tego samego wiersza pod
      // tym samym numerem. Inaczej — nowy wpis w rejestrze.
      const saved = activeSaved;
      const res = saved
        ? await b2bGeneratorApi.rerenderGenerated(saved.id, payload)
        : await b2bGeneratorApi.renderDocx(payload);
      const number = saved?.number ?? contractNumber.trim();
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa B2B ${number.replaceAll("/", "-")}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
      return {
        id: generatedIdFromHeaders(res.headers) ?? saved?.id ?? null,
        number,
        rerender: !!saved,
      };
    },
    onSuccess: (result) => {
      toast.showSuccess(
        result.rerender
          ? `Umowa ${result.number} poprawiona i pobrana (ten sam numer).`
          : `Umowa ${result.number} pobrana (DOCX) i zapisana w rejestrze.`,
      );
      if (result.id !== null) {
        setSavedContract({
          id: result.id,
          number: result.number,
          candidateId: candidate?.id ?? null,
          jobId: selectedRecruitment?.job_id ?? null,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      // Podpowiedź „następny wolny numer” w polu numeru; samego numeru nie
      // podmieniamy — formularz nadal opisuje właśnie zapisaną umowę.
      void nextNumberQuery.refetch();
    },
    onError: (e) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      // 409 przy PIERWSZYM pobraniu = numer zajęty. Nie podmieniamy go po
      // cichu: komunikat mówi, jaki numer podstawiono, i prosi o ponowne
      // kliknięcie — użytkownik musi wiedzieć, pod jakim numerem wyjdzie umowa.
      if (status === 409 && !activeSaved) {
        const taken = contractNumber.trim();
        void nextNumberQuery.refetch().then((r) => {
          const next = r.data?.contract_number;
          if (next && next !== taken) {
            setContractNumber(next);
            toast.showError(
              `${extractErrorMsg(e)} Podstawiono numer ${next} — sprawdź go i kliknij „Pobierz DOCX” ponownie.`,
            );
          } else {
            toast.showError(extractErrorMsg(e));
          }
        });
        return;
      }
      toast.showError(extractErrorMsg(e));
    },
  });

  /**
   * Zapisany payload umowy → pola formularza + tryb poprawki. Flagi prefillu
   * i „dotknięcia” są ustawiane PRZED renderem, żeby żaden efekt (profil
   * kandydata, oferta, obszar, auto-odmiana, lookup NIP-u) nie nadpisał
   * wczytanych wartości tym, co jest w bazie dziś.
   */
  const applySavedForm = (
    id: number,
    number: string,
    form: B2BRenderPayload,
    candidateOption: CandidateOption | null,
  ) => {
    const candidateId = candidateOption?.id ?? null;
    const jobId = form.job_id ?? null;
    prefilledCand.current = candidateId;
    prefilledJob.current = jobId;
    jobFieldsFromJob.current = true;
    descTouched.current = true;
    instrTouched.current = true;
    const nipDigits = (form.partner_nip ?? "").replace(/\D/g, "");
    nipLookupSkip.current = nipDigits || null;

    setCandidate(candidateOption);
    setCandidateQuery("");
    setStageId("");
    setPendingPrefill(
      candidateId && jobId ? { candidateId, jobId, fromSaved: true } : null,
    );
    setLanguage(form.language === "en" ? "en" : "pl");
    setGender(form.gender === "k" ? "k" : "m");
    setRoleId(form.role_id ? String(form.role_id) : "");
    setPartnerName(form.partner_name ?? "");
    setPartnerInstrumental(form.partner_instrumental ?? "");
    setPartnerLegalName(form.partner_legal_name ?? "");
    setPartnerNip(form.partner_nip ?? "");
    setPartnerRegon(form.partner_regon ?? "");
    setPartnerBusinessAddress(form.partner_business_address ?? "");
    setPartnerCorrespondenceAddress(form.partner_correspondence_address ?? "");
    setPartnerEntityType(form.partner_entity_type ?? null);
    setPartnerEmail(form.partner_email ?? "");
    const phone = splitPhone(form.partner_phone);
    setPhonePrefix(phone.prefix);
    setPartnerPhone(phone.number);
    setClientName(form.client_name ?? "");
    setClientQuery("");
    setProjectCity(form.project_city ?? "");
    setProjectDescription(form.project_description ?? "");
    setContractNumber(number);
    setSigningDate(form.signing_date ?? "");
    setStartDate(form.start_date ?? "");
    setStartDateMode(
      form.start_date_mode === "not_earlier" ||
        form.start_date_mode === "not_later"
        ? form.start_date_mode
        : "exact",
    );
    const stages = form.rate_stages ?? [];
    setRateStages(
      stages.length > 1
        ? stages.map((st) => ({
            rate: String(st.rate),
            from: st.effective_from ?? "",
            to: st.effective_to ?? "",
          }))
        : [
            {
              rate:
                form.rate_candidate != null ? String(form.rate_candidate) : "",
              from: "",
              to: "",
            },
          ],
    );
    setCurrency(form.currency || "PLN");
    setScopeItemsOverride(form.scope_items_override ?? null);
    setUop(null);
    setPreviewHtml("");
    setSavedContract({ id, number, candidateId, jobId });
  };

  /** „Nowa umowa” — pusty formularz i kolejny wolny numer. */
  const resetForm = () => {
    setSavedContract(null);
    setCandidate(null);
    setCandidateQuery("");
    setStageId("");
    setPendingPrefill(null);
    setRoleId("");
    setPartnerName("");
    setPartnerLegalName("");
    setPartnerNip("");
    setPartnerRegon("");
    setPartnerBusinessAddress("");
    setPartnerCorrespondenceAddress("");
    setPartnerEmail("");
    setPartnerPhone("");
    setPhonePrefix("+48");
    setClientName("");
    setClientQuery("");
    setProjectCity("");
    setProjectDescription("");
    setSigningDate(todayISO());
    setStartDate(todayISO());
    setStartDateMode("exact");
    setRateStages([emptyRateStage()]);
    setCurrency("PLN");
    setUop(null);
    setGender("m");
    setPartnerInstrumental("");
    setPartnerEntityType(null);
    setScopeItemsOverride(null);
    nipLookupSkip.current = null;
    setPreviewHtml("");
    prefilledCand.current = null;
    prefilledJob.current = null;
    descTouched.current = false;
    instrTouched.current = false;
    jobFieldsFromJob.current = false;
    setContractNumber("");
    void nextNumberQuery.refetch().then((r) => {
      if (r.data) setContractNumber(r.data.contract_number);
    });
    onClearPrefill?.();
  };

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

  const onDocx = () => {
    if (validate()) docxMut.mutate();
  };
  const onPreview = () => {
    if (validate()) previewMut.mutate();
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
      {activeSaved ? (
        <Alert
          variant="success"
          title={`Umowa ${activeSaved.number} zapisana w rejestrze (W trakcie)`}
        >
          <p className="mt-0.5 text-xs opacity-90">
            Poprawki zapiszesz pod tym samym numerem — także w drugim języku
            (przełącz „Język umowy”). Zmiana kandydata albo rekrutacji zaczyna
            nową umowę.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={docxMut.isPending}
              onClick={onDocx}
            >
              {docxMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Popraw i pobierz ponownie
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={docxMut.isPending}
              onClick={resetForm}
            >
              <Plus className="h-4 w-4" />
              Nowa umowa
            </Button>
          </div>
        </Alert>
      ) : null}

      {existingContract ? (
        /* Nie blokuje generowania: druga umowa bywa świadoma (aneks, nowy
           zakres). Mówi tylko, że poprawka pierwszej jest w rejestrze. */
        <Alert
          variant="warning"
          title={`Ta osoba ma już umowę ${existingContract.contract_number} (${
            B2B_CONTRACT_STATUS_LABEL[existingContract.contract_status]
          }) w tej rekrutacji`}
        >
          <p className="mt-0.5 text-xs opacity-90">
            {canCorrectInForm(existingContract)
              ? "Popraw ją pod tym samym numerem zamiast generować nową — każde pobranie tutaj zajmuje kolejny numer."
              : "Sprawdź ją w rejestrze, zanim wygenerujesz nową — każde pobranie tutaj zajmuje kolejny numer."}{" "}
            {/* Link obiecuje tylko to, co da się zrobić: poprawkę w formularzu
                dla autora/admina i umowy „W trakcie”, w innym razie rejestr
                z wyszukaną umową. */}
            <Link
              href={
                canCorrectInForm(existingContract)
                  ? generatorEditHref(existingContract.id)
                  : registerSearchHref(
                      existingContract.contract_number,
                      existingContract.contract_status,
                    )
              }
              className="font-semibold underline underline-offset-2"
            >
              {canCorrectInForm(existingContract)
                ? `Popraw umowę ${existingContract.contract_number}`
                : `Otwórz umowę ${existingContract.contract_number} w rejestrze`}
            </Link>
          </p>
        </Alert>
      ) : null}

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
              <Label className="mb-1.5 block" htmlFor={candidatePickerId}>
                Kandydat <span className="text-destructive">*</span>
              </Label>
              <div className="flex gap-2">
                <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      id={candidatePickerId}
                      variant="outline"
                      role="combobox"
                      aria-expanded={candidateOpen}
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
                                selectCandidate(c);
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
                    aria-label="Wyczyść kandydata"
                    onClick={() => selectCandidate(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            </div>

            <div>
              <Label className="mb-1.5 block" htmlFor={recruitmentId}>
                Rekrutacja (klient z rekrutacji){" "}
                <span className="text-destructive">*</span>
              </Label>
              <Select
                value={stageId}
                onValueChange={selectStage}
                disabled={
                  !candidate ||
                  !recruitmentsQuery.isSuccess ||
                  recruitmentsQuery.data.length === 0
                }
              >
                <SelectTrigger id={recruitmentId}>
                  <SelectValue
                    placeholder={
                      !candidate
                        ? "Najpierw wybierz kandydata"
                        : recruitmentsQuery.isLoading
                          ? "Wczytywanie rekrutacji…"
                          : "Wybierz rekrutację…"
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
              <RecruitmentOptionsNotice
                hasCandidate={!!candidate}
                isError={recruitmentsQuery.isError}
                isEmpty={
                  recruitmentsQuery.isSuccess &&
                  recruitmentsQuery.data.length === 0
                }
                onRetry={() => void recruitmentsQuery.refetch()}
              />
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
                  aria-pressed={language === l}
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
                  aria-pressed={gender === v}
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
          <Field label="Telefon" required htmlFor={phoneId}>
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
                id={phoneId}
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
          <Field label="Pełna nazwa Klienta" required htmlFor={clientPickerId}>
            <Popover open={clientOpen} onOpenChange={setClientOpen}>
              <PopoverTrigger asChild>
                <Button
                  id={clientPickerId}
                  variant="outline"
                  role="combobox"
                  aria-expanded={clientOpen}
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
          <Label className="mb-1.5 block" htmlFor={roleSelectId}>
            Obszar *
          </Label>
          <Select value={roleId} onValueChange={setRoleId}>
            <SelectTrigger id={roleSelectId}>
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
              value={activeSaved ? activeSaved.number : contractNumber}
              onChange={(e) => setContractNumber(e.target.value)}
              placeholder="np. 1435/2026"
              // Numer zapisanej umowy jest już wydany — poprawka idzie pod
              // ten sam numer, więc edycja pola nic by nie zmieniła.
              readOnly={!!activeSaved}
              disabled={!!activeSaved}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {activeSaved
                ? "Numer zapisanej umowy — nowy numer dostaniesz przyciskiem „Nowa umowa”."
                : `Format: liczba/rok. System podpowiada kolejny wolny numer${
                    nextNumberQuery.data?.contract_number
                      ? ` (${nextNumberQuery.data.contract_number})`
                      : ""
                  }; ten sam numer nie może być użyty dwa razy, także po usunięciu umowy.`}
            </p>
          </Field>
          <Field label="Data podpisania" required>
            <Input
              type="date"
              value={signingDate}
              onChange={(e) => setSigningDate(e.target.value)}
            />
          </Field>
          <Field label="Data rozpoczęcia usług" required htmlFor={startDateId}>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Select
                value={startDateMode}
                onValueChange={(v) =>
                  setStartDateMode(v as "exact" | "not_earlier" | "not_later")
                }
              >
                <SelectTrigger className="w-full sm:w-[150px] sm:shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="exact">z dniem</SelectItem>
                  <SelectItem value="not_earlier">nie wcześniej niż</SelectItem>
                  <SelectItem value="not_later">nie później niż</SelectItem>
                </SelectContent>
              </Select>
              <Input
                id={startDateId}
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
          </Field>
          <div className="space-y-3 sm:col-span-2">
            {rateStages.length === 1 ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Stawka godz. (netto)" required>
                  <Input
                    type="number"
                    value={rateStages[0]?.rate ?? ""}
                    onChange={(e) => setRateStage(0, { rate: e.target.value })}
                    placeholder="np. 150"
                  />
                </Field>
                <Field label="Waluta" htmlFor={currencyId}>
                  <CurrencySelect
                    id={currencyId}
                    value={currency}
                    onChange={setCurrency}
                  />
                </Field>
              </div>
            ) : (
              <>
                {rateStages.map((stage, i) => (
                  <div key={i} className="flex items-end gap-2">
                    <div className="grid min-w-0 flex-1 grid-cols-1 gap-3 sm:grid-cols-3">
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
                      aria-label={`Usuń etap stawki ${i + 1}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field label="Waluta" htmlFor={currencyId}>
                    <CurrencySelect
                      id={currencyId}
                      value={currency}
                      onChange={setCurrency}
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
        {/* Jeden przycisk w języku z „Język umowy”. Dwa (PL/EN) zakładały dwa
            wiersze rejestru i dwa numery dla jednej umowy; teraz druga wersja
            językowa to poprawka zapisanej umowy pod tym samym numerem. */}
        <Button disabled={docxMut.isPending} onClick={onDocx}>
          {docxMut.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Download className="mr-2 h-4 w-4" />
          )}
          {activeSaved
            ? "Popraw i pobierz ponownie"
            : `Pobierz DOCX (${language === "pl" ? "PL" : "EN"})`}
        </Button>
        {activeSaved ? (
          <Button
            type="button"
            variant="outline"
            disabled={docxMut.isPending}
            onClick={resetForm}
          >
            <Plus className="mr-2 h-4 w-4" />
            Nowa umowa
          </Button>
        ) : null}
      </div>

      {/* Podgląd */}
      {previewHtml ? (
        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            {/* Podgląd nie zapisuje umowy — numer w nim to tylko propozycja,
                a wydruk nie jest dokumentem z rejestru. */}
            <CardTitle className="text-base">
              Podgląd (bez numeru w rejestrze)
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => printHtml(previewHtml, "Podgląd umowy B2B")}
            >
              <Printer className="mr-2 h-4 w-4" />
              Drukuj podgląd
            </Button>
          </CardHeader>
          <CardContent>
            {/* `sandbox=""`: treść idzie z danych wpisanych w formularz (opis
                projektu, nazwy), więc ramka nie wykonuje skryptów ani nie ma
                dostępu do strony. Style inline działają i bez uprawnień. */}
            <iframe
              title="Podgląd umowy"
              sandbox=""
              className="h-[60dvh] min-h-[420px] w-full rounded-lg border bg-white"
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
          className="hit-area h-6 w-6 shrink-0"
          onClick={onClose}
          aria-label="Zamknij wynik sprawdzenia AI"
          title="Zamknij"
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

/**
 * Etykieta pola powiązana z kontrolką (`htmlFor`) — bez tego czytnik ekranu
 * ogłaszał „pole edycji” bez nazwy, a klik w etykietę nie ustawiał kursora.
 *
 * Pojedyncze `Input`/`Textarea` dostaje id automatycznie; złożone pola (select
 * z prefiksem, wybór klienta) przekazują `htmlFor` i same nadają id kontrolce.
 */
function Field({
  label,
  full,
  required,
  htmlFor,
  children,
}: {
  label: string;
  full?: boolean;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  const autoId = useId();
  let linkedId = htmlFor;
  let assigned = false;
  const content = htmlFor
    ? children
    : React.Children.map(children, (child) => {
        if (
          assigned ||
          !React.isValidElement<{ id?: string }>(child) ||
          (child.type !== Input && child.type !== Textarea)
        ) {
          return child;
        }
        assigned = true;
        linkedId = child.props.id ?? autoId;
        return child.props.id ? child : React.cloneElement(child, { id: autoId });
      });
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <Label className="mb-1.5 block" htmlFor={linkedId}>
        {label}
        {required ? <span className="text-destructive"> *</span> : null}
      </Label>
      {content}
    </div>
  );
}

/** Waluta stawki — zamknięta lista zamiast wolnego tekstu („pln”, „zł”). */
function CurrencySelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const options = (B2B_CURRENCIES as readonly string[]).includes(value)
    ? B2B_CURRENCIES
    : [...B2B_CURRENCIES, value];
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((code) => (
          <SelectItem key={code} value={code}>
            {code}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
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
