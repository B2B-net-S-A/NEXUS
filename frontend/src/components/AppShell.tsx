"use client";

/**
 * Legacy modal bundle — housed in AppShell.tsx historically; after Phase 11
 * decommission this file keeps only the Add/Edit modals used across the app
 * (AddCandidate, EditCandidate, AddJob, EditJob, AddClient, AddMeeting) plus
 * their internal helpers. The old `<AppShell>` wrapper was replaced by
 * `<AppShellV2>` in `components/v2/shell/`.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Children,
  cloneElement,
  isValidElement,
  useState,
  useRef,
  useEffect,
  useId,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  X, Loader2, ChevronRight, Plus,
  UserPlus, Briefcase, Building2, CalendarPlus,
} from "lucide-react";
import api, {
  candidateProfileApi,
  clientTeamApi,
  microsoft365Api,
  phase5Api,
} from "@/lib/api";
import type {
  ClientDirectoryCategory,
  ClientTeamResponse,
} from "@/lib/api";
import { useCapability } from "@/hooks/useCapability";
import { editableTagText, mergeEditedTags, structuredTagLabels } from "@/lib/candidate-tags";
import { useClickOutside } from "@/lib/use-click-outside";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { defaultMeetingWindow } from "@/lib/meeting-defaults";
import { newClientRequestId } from "@/lib/client-request-id";
import {
  jobNamesDraft,
  jobNamesPatch,
  type JobNames,
  type JobNamesDraft,
} from "@/lib/job-names";
import {
  invalidAttendeeEmails,
  splitAttendeeEmails,
} from "@/components/calendar/attendee-emails";
import {
  CandidateCombobox,
  type CandidateChoice,
} from "@/components/calendar/CandidateCombobox";
import { HiringManagerCombobox } from "@/components/jobs/HiringManagerCombobox";
import {
  sameChoice,
  saveHiringManager,
  type HiringManagerChoice,
} from "@/lib/hiring-manager";

// ── Breadcrumb helper ────────────────────────────────────────────────────────

const SEGMENT_LABELS: Record<string, string> = {
  "": "Dashboard",
  candidates: "Kandydaci",
  jobs: "Rekrutacje",
  clients: "Klienci",
  contacts: "Kontakty",
  contracts: "Kontrakty",
  talents: "Talenty",
  analytics: "Analityka",
  reports: "Raporty",
  calendar: "Kalendarz",
  settings: "Ustawienia",
  templates: "Szablony email",
  admin: "Admin",
  profile: "Profil",
};

// Maps entity type -> API endpoint to fetch name
const ENTITY_NAME_FETCHERS: Record<string, (id: string) => Promise<string>> = {
  candidates: async (id) => {
    const r = await api.get(`/api/candidates/${id}`);
    return `${r.data.name} ${r.data.lastname}`.trim();
  },
  jobs: async (id) => {
    const r = await api.get(`/api/jobs/${id}`);
    return r.data.title;
  },
  clients: async (id) => {
    const r = await api.get(`/api/clients/${id}`);
    return r.data.name;
  },
};

function isNumeric(s: string) {
  return /^\d+$/.test(s);
}

function DynamicLabel({ entityType, id }: { entityType: string; id: string }) {
  const fetcher = ENTITY_NAME_FETCHERS[entityType];
  const { data: label, isLoading } = useQuery({
    queryKey: ["breadcrumb", entityType, id],
    queryFn: () => fetcher(id),
    enabled: !!fetcher,
    staleTime: 60_000,
  });

  if (!fetcher) return <span>{id}</span>;
  if (isLoading) return <span className="opacity-50">…</span>;
  return <span>{label ?? id}</span>;
}

function Breadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) {
    return <span className="text-sm text-muted-foreground dark:text-muted-foreground font-medium">Dashboard</span>;
  }

  const crumbs: { label: React.ReactNode; href: string }[] = [
    { label: "Dashboard", href: "/" },
  ];

  let path = "";
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    path += "/" + seg;
    const prevSeg = segments[i - 1];

    if (isNumeric(seg) && prevSeg && ENTITY_NAME_FETCHERS[prevSeg]) {
      // This is an ID segment — show dynamic entity name
      crumbs.push({
        label: <DynamicLabel entityType={prevSeg} id={seg} />,
        href: path,
      });
    } else if (!isNumeric(seg)) {
      const label = SEGMENT_LABELS[seg] ?? (seg.length > 14 ? seg.slice(0, 12) + "…" : seg);
      crumbs.push({ label, href: path });
    }
  }

  return (
    <nav className="flex items-center gap-1 text-sm" aria-label="Breadcrumb">
      {crumbs.map((c, i) => (
        <span key={c.href} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-muted-foreground dark:text-muted-foreground" />}
          {i < crumbs.length - 1 ? (
            <Link
              href={c.href}
              className="text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground transition-colors"
            >
              {c.label}
            </Link>
          ) : (
            <span className="text-foreground dark:text-foreground font-medium">
              {c.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={`fixed bottom-6 right-6 z-200 flex items-center gap-3 px-5 py-3.5 rounded-xl shadow-xl text-white text-sm font-medium ${type === "success" ? "bg-green-600" : "bg-red-600"}`}>
      {message}
      <button onClick={onClose} className="ml-1 opacity-70 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ── Generic Modal Shell ────────────────────────────────────────────────────────

/**
 * Shell 8 modali eksportowanych z tego pliku (AddCandidate, EditCandidate,
 * AddJob, EditJob, AddClient, EditClient, AddMeeting, AddContact).
 *
 * Wnętrze stoi na `@radix-ui/react-dialog` (ten sam primitive co
 * `components/ui/dialog.tsx`), bo ręczna wersja miała TYLKO obsługę Escape:
 * brakowało `role="dialog"`/`aria-modal`, powiązania nagłówka przez
 * `aria-labelledby`, pułapki fokusu i przywrócenia fokusu do elementu
 * wyzwalającego po zamknięciu, a przycisk zamknięcia (sama ikona) czytnik
 * ekranu ogłaszał jako „button".
 *
 * API komponentu (`title` / `onClose` / `children` / `wide`) oraz klasy tokenowe
 * są zachowane 1:1 — konsumenci i wygląd bez zmian.
 */
function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  // Element, który miał fokus tuż przed otwarciem — czytany w renderze, zanim
  // radix zdąży przenieść fokus do treści modala (efekty lecą po renderze).
  const [opener] = useState<Element | null>(() =>
    typeof document !== "undefined" ? document.activeElement : null
  );

  return (
    <DialogPrimitive.Root
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        {/* Overlay jest jednocześnie kontenerem przewijania (wzorzec „scrollable
            overlay" z dokumentacji radix) — dzięki temu zostaje sheet-on-mobile
            / center-on-desktop z wersji ręcznej. */}
        <DialogPrimitive.Overlay className="fixed inset-0 bg-black/50 z-100 flex items-end sm:items-center justify-center sm:p-4 overflow-y-auto">
          <DialogPrimitive.Content
            // Radix woli `hideOthers()` (aria-hidden na rodzeństwie) i sam nie
            // wystawia `aria-modal`; dokładamy je jawnie, bo to element kontraktu.
            aria-modal="true"
            // Brak `<DialogDescription>` — jawne `undefined` wycisza warning radix.
            aria-describedby={undefined}
            // Wersja ręczna zamykała się WYŁĄCZNIE przez Escape i „X"; klik w tło
            // nie gubił wypełnionego formularza. Zachowujemy to zachowanie.
            onPointerDownOutside={(e) => e.preventDefault()}
            onInteractOutside={(e) => e.preventDefault()}
            onCloseAutoFocus={(e) => {
              // Domyślnie radix oddaje fokus do `<Dialog.Trigger>`, którego tu nie
              // ma — te modale montują zewnętrzne przyciski (QuickActions, akcje
              // w wierszach). Bez tego fokus po zamknięciu przepadał na <body>.
              e.preventDefault();
              if (opener instanceof HTMLElement && document.contains(opener)) {
                opener.focus();
              }
            }}
            className={`bg-card dark:bg-muted rounded-2xl sm:rounded-2xl rounded-b-none sm:rounded-b-2xl shadow-2xl w-full sm:my-4 focus:outline-hidden ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"}`}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
              <DialogPrimitive.Title className="text-lg font-bold text-foreground dark:text-foreground">{title}</DialogPrimitive.Title>
              <DialogPrimitive.Close
                aria-label="Zamknij"
                className="text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </DialogPrimitive.Close>
            </div>
            {children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * Podpis pola + kontrolka. `<label>` jest RODZEŃSTWEM kontrolki, więc bez pary
 * `htmlFor`/`id` przeglądarka nie ma czego powiązać: klik w podpis nie ustawia
 * fokusu, czytnik ekranu czyta „edycja, puste", a sterowanie głosem („kliknij
 * Imię") nie ma celu. Dotyczyło to wszystkich 60 pól modali Dodaj/Edytuj w tym
 * pliku — dla `<select>` najboleśniej, bo tam nawet placeholder nie podstawia
 * się pod brakującą nazwę.
 *
 * `id` nadajemy WYŁĄCZNIE lokalnym kontrolkom (Input/Textarea/Select) i tylko
 * pierwszej z nich. Gdy w środku jest grupa (dwie kontrolki w `<div>`, np.
 * „Okres wypowiedzenia" — te mają własne `aria-label`) albo sam tekst
 * objaśniający, `htmlFor` wskazywałby w próżnię, a martwe powiązanie jest
 * gorsze od jego braku: czytnik ekranu ogłasza nazwę, po której nie da się
 * nawigować.
 */
function FieldGroup({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  const generatedId = useId();
  let controlId: string | undefined;

  const labelled = Children.map(children, (child) => {
    if (controlId !== undefined || !isValidElement(child)) return child;
    if (!LABELLABLE_CONTROLS.includes(child.type)) return child;
    const own = (child.props as { id?: string }).id;
    const nextId = own ?? generatedId;
    controlId = nextId;
    if (own) return child;
    return cloneElement(child as React.ReactElement<{ id?: string }>, {
      id: nextId,
    });
  });

  return (
    <div>
      <label
        htmlFor={controlId}
        className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1"
      >
        {label} {required && <span className="text-destructive">*</span>}
      </label>
      {labelled}
    </div>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="h-10 w-full px-3 border border-border dark:border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground placeholder:text-muted-foreground dark:placeholder:text-muted-foreground"
    />
  );
}

function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring resize-y bg-card dark:bg-muted dark:text-foreground placeholder:text-muted-foreground dark:placeholder:text-muted-foreground"
    />
  );
}

function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { children: React.ReactNode }) {
  return (
    <select
      {...props}
      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground"
    >
      {children}
    </select>
  );
}

// Kontrolki, którym `FieldGroup` potrafi nadać `id` i spiąć je z `<label>`.
// Deklaracje funkcji są hoistowane, więc ta stała może stać po nich, a
// `FieldGroup` (wyżej) i tak ją widzi w czasie renderu.
const LABELLABLE_CONTROLS: readonly unknown[] = [Input, Textarea, Select];

function SaveButton({ saving, label = "Zapisz" }: { saving: boolean; label?: string }) {
  return (
    <button
      type="submit"
      disabled={saving}
      aria-label={label}
      className="flex items-center gap-2 h-10 px-4 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white rounded-lg text-sm font-medium transition-all focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {saving && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
      {label}
    </button>
  );
}

function ErrorBanner({ error }: { error: string }) {
  return <div className="text-sm text-destructive dark:text-destructive bg-destructive/10 dark:bg-red-900/30 rounded-lg px-4 py-2">{error}</div>;
}

/**
 * Komunikat błędu do stanu typu string. Handlery w tym pliku czytały wprost
 * `err.response.data.detail`, a `detail` bywa NIE-STRINGIEM:
 *   - obiektem `{feature, reason, used, limit}` — 503 o wyczerpanej kwocie AI
 *     (`ai_writer.py`, jedno kliknięcie admina w Ustawienia → AI od tego stanu),
 *   - obiektem `{message, ...}` — konflikty domenowe,
 *   - tablicą `{msg, loc}` — 422 z Pydantica.
 * Taka wartość trafiała do stanu i była renderowana jako dziecko Reacta, co
 * rzuca „Objects are not valid as a React child" W TRAKCIE RENDERU: error
 * boundary App Routera podmieniał całą stronę, a wypełniony do połowy formularz
 * (tytuł, klient, TAC, DL, wymagania) przepadał. Zwykły błąd zapisu kasował
 * więc pracę użytkownika.
 *
 * Zwracana wartość jest ZAWSZE stringiem. `reason` czytamy zaraz po `message`,
 * bo dla kwot AI jest jedynym polem pisanym po polsku do użytkownika. Z 422
 * bierzemy wyłącznie błędy z `body` — tylko one opisują to, co użytkownik
 * wpisał; `query`/`path` ustawia kod aplikacji i surowy `loc` byłby wyciekiem
 * wewnętrznego kontraktu (ta sama zasada co w `extractErrorMsg`; logika jest
 * tu powtórzona świadomie, żeby ten plik nie zyskał zależności, której nie
 * pokrywają istniejące mocki `@/lib/api` w testach modali).
 */
function formErrorMsg(error: unknown, fallback: string): string {
  const detail = (
    error as { response?: { data?: { detail?: unknown } } } | null | undefined
  )?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) return detail;

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { message, reason } = detail as { message?: unknown; reason?: unknown };
    if (typeof message === "string" && message.trim()) return message;
    if (typeof reason === "string" && reason.trim()) return reason;
  }

  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown; loc?: unknown } | undefined;
    const loc = Array.isArray(first?.loc) ? first.loc : [];
    if (typeof first?.msg === "string" && first.msg.trim() && loc[0] === "body") {
      return `${loc.slice(1).join(".") || "pole"}: ${first.msg}`;
    }
  }

  return fallback;
}

// ── Modal: Dodaj / Edytuj kandydata ───────────────────────────────────────────

interface CandidateFormData {
  name: string;
  lastname: string;
  email: string;
  phone: string;
  city: string;
  country: string;
  source: string;
  linkedin: string;
  availability_date: string;
  notice_period: string;
  notice_period_unit: string; // "days" | "weeks" | "months"
  status: string;
  availability_status: string;
  tags: string;
  notes: string;
  // Structured (Phase 1 – Sprint 3)
  years_it_experience: string;
  champion: boolean;
  verifier_id: string;
  verified_tech: string; // comma separated
  // Preferences JSONB
  pref_remote_modes: string[]; // ['remote','hybrid','onsite']
  pref_industries: string; // comma separated
  pref_contract_types: string[]; // ['b2b','uop','zlecenie']
  pref_excluded_clients: string; // comma separated client ids
  pref_office_cities: string; // comma separated — preferences.office_cities (0278)
  // Trzecia rubryka rekrutacji (0278). KOLUMNA, nie preferences — backend
  // odrzuca ten klucz W preferences (drugie źródło prawdy o tej samej rubryce).
  max_onsite_days_per_week: string;
}

const EMPTY_CANDIDATE: CandidateFormData = {
  name: "", lastname: "", email: "", phone: "", city: "", country: "",
  source: "manual", linkedin: "",
  availability_date: "", notice_period: "", notice_period_unit: "days", status: "active", availability_status: "unknown", tags: "", notes: "",
  years_it_experience: "", champion: false, verifier_id: "", verified_tech: "",
  pref_remote_modes: [],
  pref_industries: "", pref_contract_types: [], pref_excluded_clients: "",
  pref_office_cities: "", max_onsite_days_per_week: "",
};

type VerifiedTechItem = string | { name?: string; skill?: string } | null;

function _verifiedTechToString(v: unknown): string {
  if (!Array.isArray(v)) return "";
  return v
    .map((it: VerifiedTechItem) => {
      if (!it) return "";
      if (typeof it === "string") return it;
      if (typeof it === "object") return it.name ?? it.skill ?? "";
      return "";
    })
    .filter(Boolean)
    .join(", ");
}

function candidateToForm(c: any): CandidateFormData {
  const prefs = (c.preferences && typeof c.preferences === "object") ? c.preferences : {};
  return {
    name: c.name ?? "",
    lastname: c.lastname ?? "",
    email: c.email ?? "",
    phone: c.phone ?? "",
    city: c.city ?? c.location ?? "",
    country: c.country ?? "",
    source: c.source ?? "manual",
    linkedin: c.linkedin ?? "",
    availability_date: c.availability_date ? c.availability_date.slice(0, 10) : "",
    notice_period: c.notice_period != null ? String(c.notice_period) : "",
    notice_period_unit: c.notice_period_unit ?? (c.notice_period != null ? "days" : "days"),
    status: c.status ?? "active",
    availability_status: c.availability_status ?? "unknown",
    tags: editableTagText(c.tags),
    notes: "",
    years_it_experience: c.years_it_experience != null ? String(c.years_it_experience) : "",
    champion: !!c.champion,
    verifier_id: c.verifier_id != null ? String(c.verifier_id) : "",
    verified_tech: _verifiedTechToString(c.verified_tech),
    pref_remote_modes: Array.isArray(prefs.remote_modes) ? prefs.remote_modes : [],
    pref_industries: Array.isArray(prefs.industries) ? prefs.industries.join(", ") : "",
    pref_contract_types: Array.isArray(prefs.contract_types) ? prefs.contract_types : [],
    pref_excluded_clients: Array.isArray(prefs.excluded_clients)
      ? prefs.excluded_clients.join(", ")
      : "",
    pref_office_cities: Array.isArray(prefs.office_cities)
      ? prefs.office_cities.join(", ")
      : "",
    max_onsite_days_per_week:
      c.max_onsite_days_per_week != null ? String(c.max_onsite_days_per_week) : "",
  };
}

function candidateFormToPayload(form: CandidateFormData) {
  const tags = form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [];
  const verifiedTech = form.verified_tech
    ? form.verified_tech.split(",").map(t => t.trim()).filter(Boolean)
    : [];
  const industries = form.pref_industries
    ? form.pref_industries.split(",").map(t => t.trim()).filter(Boolean)
    : [];
  const excluded = form.pref_excluded_clients
    ? form.pref_excluded_clients
        .split(",")
        .map(t => t.trim())
        .filter(Boolean)
        .map(n => Number(n))
        .filter(n => !Number.isNaN(n))
    : [];
  const officeCities = form.pref_office_cities
    ? form.pref_office_cities.split(",").map(t => t.trim()).filter(Boolean)
    : [];

  // ZAWSZE wysyłamy `preferences` — z jawnym `null` dla wyczyszczonych pól
  // (0278). Backend scala PŁYTKO (PATCH /api/candidates/{id}): brak klucza w
  // ogóle zostawia go nietkniętym, ale pusty formularz musi mieć jak wysłać
  // "wyczyściłem to pole" — inaczej odznaczenie ostatniego checkboxa "Remote"
  // nie dałoby się zapisać. Create ignoruje `null`, bo nie ma czego usuwać
  // (walidator z `allow_null_values=False` w schemas/candidate.py).
  const preferences: Record<string, unknown> = {
    remote_modes: form.pref_remote_modes.length ? form.pref_remote_modes : null,
    industries: industries.length ? industries : null,
    contract_types: form.pref_contract_types.length ? form.pref_contract_types : null,
    excluded_clients: excluded.length ? excluded : null,
    office_cities: officeCities.length ? officeCities : null,
  };

  return {
    name: form.name,
    lastname: form.lastname,
    email: form.email || undefined,
    phone: form.phone || undefined,
    city: form.city || undefined,
    country: form.country.trim().toUpperCase() || undefined,
    source: form.source,
    linkedin: form.linkedin || undefined,
    // Wyczyszczone pole = jawne `null` (PATCH z exclude_unset: brak klucza
    // zostawiał starą wartość, więc „Dostępny od” i wypowiedzenia nie dało się usunąć).
    availability_date: form.availability_date || null,
    notice_period: form.notice_period ? Number(form.notice_period) : null,
    notice_period_unit: form.notice_period ? (form.notice_period_unit || "days") : null,
    status: form.status,
    availability_status: form.availability_status || undefined,
    tags: tags.length ? tags : undefined,
    years_it_experience: form.years_it_experience ? Number(form.years_it_experience) : undefined,
    champion: form.champion,
    verifier_id: form.verifier_id ? Number(form.verifier_id) : undefined,
    verified_tech: verifiedTech.length ? verifiedTech : undefined,
    preferences,
    // Trzecia rubryka rekrutacji (0278) — kolumna kandydata, nie preferences.
    max_onsite_days_per_week:
      form.max_onsite_days_per_week === "" ? null : Number(form.max_onsite_days_per_week),
  };
}

function CandidateFormFields({
  form,
  onChange,
  onToggle,
  onMulti,
  users,
  clients,
  importedTagLabels = [],
  collapseSecondary = false,
}: {
  form: CandidateFormData;
  onChange: (k: keyof CandidateFormData, v: string) => void;
  onToggle: (k: "champion", v: boolean) => void;
  onMulti: (k: "pref_remote_modes" | "pref_contract_types", v: string, on: boolean) => void;
  users: { id: number; full_name?: string; email?: string }[];
  clients: { id: number; name: string }[];
  /** Tagi z importu (np. źródło z Traffita) — zapis ich nie zmienia (UAT B60). */
  importedTagLabels?: string[];
  /**
   * Ręczne dodanie: widoczne tylko Imię, Nazwisko, E-mail, Telefon i Miasto,
   * reszta pod „Więcej danych”. Edycja profilu pokazuje wszystko jak dotąd.
   */
  collapseSecondary?: boolean;
}) {
  const CB = ({
    field,
    value,
    label,
  }: {
    field: "pref_remote_modes" | "pref_contract_types";
    value: string;
    label: string;
  }) => {
    const arr = form[field];
    const checked = arr.includes(value);
    return (
      <label className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-border dark:border-border cursor-pointer hover:bg-muted dark:hover:bg-muted">
        <input
          type="checkbox"
          checked={checked}
          onChange={e => onMulti(field, value, e.target.checked)}
          className="w-3.5 h-3.5 accent-blue-600"
        />
        <span>{label}</span>
      </label>
    );
  };

  const secondaryFields = (
    <>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Kraj (ISO)">
          <Input
            value={form.country}
            onChange={e => onChange("country", e.target.value.slice(0, 2).toUpperCase())}
            placeholder="PL"
            maxLength={2}
          />
        </FieldGroup>
        <FieldGroup label="Źródło">
          <Select value={form.source} onChange={e => onChange("source", e.target.value)}>
            <option value="manual">Manualny</option>
            <option value="linkedin">LinkedIn</option>
            <option value="pracuj">Pracuj.pl</option>
            <option value="jjit">JustJoin.it</option>
            <option value="referral">Polecenie</option>
            <option value="database">Baza ATS</option>
          </Select>
        </FieldGroup>
      </div>
      <FieldGroup label="LinkedIn URL">
        <Input value={form.linkedin} onChange={e => onChange("linkedin", e.target.value)} placeholder="https://linkedin.com/in/..." />
      </FieldGroup>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FieldGroup label="Okres wypowiedzenia">
          <div className="grid grid-cols-[1fr_1.2fr] gap-2">
            <Input
              type="number"
              min={0}
              value={form.notice_period}
              onChange={e => onChange("notice_period", e.target.value)}
              placeholder="30"
              aria-label="Okres wypowiedzenia — wartość"
            />
            <Select
              value={form.notice_period_unit || "days"}
              onChange={e => onChange("notice_period_unit", e.target.value)}
              aria-label="Okres wypowiedzenia — jednostka"
            >
              <option value="days">dni</option>
              <option value="weeks">tygodnie</option>
              <option value="months">miesiące</option>
            </Select>
          </div>
        </FieldGroup>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Dostępność">
          <Input type="date" value={form.availability_date} onChange={e => onChange("availability_date", e.target.value)} />
        </FieldGroup>
        <FieldGroup label="Status">
          <Select value={form.status} onChange={e => onChange("status", e.target.value)}>
            <option value="active">Aktywny</option>
            <option value="passive">Pasywny</option>
            <option value="blacklisted">Zablokowany</option>
          </Select>
        </FieldGroup>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Dyspozycyjność">
          <Select
            value={form.availability_status}
            onChange={e => onChange("availability_status", e.target.value)}
          >
            <option value="unknown">Nie wiemy</option>
            <option value="actively_looking">Aktywnie szuka pracy</option>
            <option value="open_to_offers">Otwarty na dodatkowe projekty</option>
            <option value="not_looking">Nie szuka</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Aktualnie u klienta (opcjonalnie)">
          <div className="text-xs text-muted-foreground dark:text-muted-foreground px-3 py-2 bg-muted dark:bg-card/40 rounded-lg">
            W profilu kandydata: <strong>Podsumowanie → Dane handlowe → Dodaj konflikt</strong>,
            typ <strong>Obecne zatrudnienie</strong> (albo „Oznacz jako zatrudnionego”
            w szybkim podglądzie). Dzięki temu karta dostanie burgundowy alert „U KLIENTA”.
          </div>
        </FieldGroup>
      </div>
      <FieldGroup label="Tagi (rozdzielone przecinkami)">
        <Input value={form.tags} onChange={e => onChange("tags", e.target.value)} placeholder="React, TypeScript, Remote..." />
        {importedTagLabels.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            Tagi z importu zostają bez zmian: {importedTagLabels.join(", ")}
          </p>
        )}
      </FieldGroup>
      <FieldGroup label="Notatki">
        <Textarea value={form.notes} onChange={e => onChange("notes", e.target.value)} rows={3} placeholder="Dodatkowe informacje..." />
      </FieldGroup>

      {/* ── Dane strukturalne ───────────────────────────────────────────── */}
      <div className="pt-2 border-t border-border dark:border-border">
        <h4 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-2">
          Dane strukturalne
        </h4>
        <div className="grid grid-cols-3 gap-3">
          <FieldGroup label="Lata doświadczenia IT">
            <Input
              type="number"
              value={form.years_it_experience}
              onChange={e => onChange("years_it_experience", e.target.value)}
              placeholder="8"
            />
          </FieldGroup>
          <FieldGroup label="Weryfikator (recruiter)">
            <Select
              value={form.verifier_id}
              onChange={e => onChange("verifier_id", e.target.value)}
            >
              <option value="">— brak —</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </Select>
          </FieldGroup>
          <label className="flex items-center gap-2 mt-6 cursor-pointer">
            <input
              type="checkbox"
              checked={form.champion}
              onChange={e => onToggle("champion", e.target.checked)}
              className="w-4 h-4 accent-yellow-500"
            />
            <span className="text-sm text-foreground dark:text-muted-foreground">
              Champion (ulubieniec)
            </span>
          </label>
        </div>
        <FieldGroup label="Zweryfikowane technologie (rozdzielone przecinkami)">
          <Input
            value={form.verified_tech}
            onChange={e => onChange("verified_tech", e.target.value)}
            placeholder="Python, AWS, Kubernetes"
          />
        </FieldGroup>
      </div>

      {/* ── Preferencje kontraktowe ─────────────────────────────────────── */}
      <div className="pt-2 border-t border-border dark:border-border">
        <h4 className="text-sm font-semibold text-foreground dark:text-muted-foreground mb-2">
          Preferencje kontraktowe
        </h4>
        <FieldGroup label="Tryb pracy">
          <div className="flex flex-wrap gap-2">
            <CB field="pref_remote_modes" value="remote" label="Remote" />
            <CB field="pref_remote_modes" value="hybrid" label="Hybrid" />
            <CB field="pref_remote_modes" value="onsite" label="Stacjonarnie" />
          </div>
        </FieldGroup>
        {/* Trzecia rubryka rekrutacji (obok must-have i stawki, 0278) —
            KOLUMNA `max_onsite_days_per_week`, nie `preferences`. */}
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Maks. dni w biurze / tydzień">
            <Input
              type="number"
              min={0}
              max={7}
              value={form.max_onsite_days_per_week}
              onChange={e => onChange("max_onsite_days_per_week", e.target.value)}
              placeholder="np. 2 — 0 = tylko zdalnie"
            />
          </FieldGroup>
          <FieldGroup label="Lokalizacje biura (miasta, po przecinku)">
            <Input
              value={form.pref_office_cities}
              onChange={e => onChange("pref_office_cities", e.target.value)}
              placeholder="Warszawa, Kraków"
            />
          </FieldGroup>
        </div>
        <FieldGroup label="Typ kontraktu">
          <div className="flex flex-wrap gap-2">
            <CB field="pref_contract_types" value="b2b" label="B2B" />
            <CB field="pref_contract_types" value="uop" label="UoP" />
            <CB field="pref_contract_types" value="zlecenie" label="Zlecenie" />
          </div>
        </FieldGroup>
        <FieldGroup label="Preferowane branże (rozdzielone przecinkami)">
          <Input
            value={form.pref_industries}
            onChange={e => onChange("pref_industries", e.target.value)}
            placeholder="Fintech, E-commerce"
          />
        </FieldGroup>
        <FieldGroup label="Wykluczeni klienci">
          <Select
            multiple
            value={
              form.pref_excluded_clients
                ? form.pref_excluded_clients.split(",").map(s => s.trim()).filter(Boolean)
                : []
            }
            onChange={e => {
              const opts = Array.from(e.target.selectedOptions, o => o.value);
              onChange("pref_excluded_clients", opts.join(", "));
            }}
          >
            {clients.map(c => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <p className="text-[11px] text-muted-foreground mt-1">
            Ctrl/⌘+klik aby zaznaczyć wielu klientów.
          </p>
        </FieldGroup>
      </div>
    </>
  );

  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Imię" required>
          <Input value={form.name} onChange={e => onChange("name", e.target.value)} placeholder="Jan" />
        </FieldGroup>
        <FieldGroup label="Nazwisko" required>
          <Input value={form.lastname} onChange={e => onChange("lastname", e.target.value)} placeholder="Kowalski" />
        </FieldGroup>
        <FieldGroup label="Email">
          <Input type="email" value={form.email} onChange={e => onChange("email", e.target.value)} placeholder="jan@mail.pl" />
        </FieldGroup>
        <FieldGroup label="Telefon">
          <Input type="tel" value={form.phone} onChange={e => onChange("phone", e.target.value)} placeholder="+48 500..." />
        </FieldGroup>
        <FieldGroup label="Miasto">
          <Input value={form.city} onChange={e => onChange("city", e.target.value)} placeholder="Warszawa" />
        </FieldGroup>
      </div>
      {collapseSecondary ? (
        <details className="group rounded-lg border border-border">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-foreground">
            Więcej danych
          </summary>
          <div className="space-y-4 border-t border-border p-3">{secondaryFields}</div>
        </details>
      ) : (
        secondaryFields
      )}
    </>
  );
}

interface DuplicateCandidateHit {
  candidate_id: number;
  name: string;
  lastname: string;
  email: string | null;
  match_score: number;
  match_reasons: string[];
}

type DuplicateIdentityFields = Pick<CandidateFormData, "email" | "phone" | "linkedin" | "name" | "lastname">;

/**
 * Tożsamość sprawdzana automatycznie — te same pola, po których dopasowuje
 * backend (`dedup_service`: e-mail, telefon, LinkedIn, imię+nazwisko). Zmiana
 * któregokolwiek = nowe sprawdzenie; inaczej zapis użyłby wyniku sprzed
 * wpisania nazwiska albo profilu LinkedIn istniejącej osoby.
 */
function duplicateIdentityKey(form: DuplicateIdentityFields): string {
  return JSON.stringify([
    form.email.trim().toLowerCase(),
    form.phone.trim(),
    form.linkedin.trim().toLowerCase(),
    form.name.trim().toLowerCase(),
    form.lastname.trim().toLowerCase(),
  ]);
}

/** Czy jest z czym porównać: kontakt, LinkedIn albo pełne imię i nazwisko. */
function hasDuplicateIdentity(form: DuplicateIdentityFields): boolean {
  return Boolean(
    form.email.trim() ||
      form.phone.trim() ||
      form.linkedin.trim() ||
      (form.name.trim() && form.lastname.trim()),
  );
}

const DUPLICATE_CHECK_DEBOUNCE_MS = 400;

export function AddCandidateModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  const [form, setForm] = useState<CandidateFormData>(EMPTY_CANDIDATE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [duplicates, setDuplicates] = useState<DuplicateCandidateHit[]>([]);
  // Klucz tożsamości (e-mail, telefon, LinkedIn, imię i nazwisko), dla którego `duplicates` jest aktualne.
  const [checkedKey, setCheckedKey] = useState<string>(() => duplicateIdentityKey(EMPTY_CANDIDATE));
  // Zapis zatrzymany na trafieniach — rekruter wybiera „Otwórz istniejącego” albo „Zapisz mimo to”.
  const [decisionPending, setDecisionPending] = useState(false);
  const checkSeqRef = useRef(0);
  const formRef = useRef(form);
  formRef.current = form;

  const { data: usersData } = useQuery({
    queryKey: ["users-list-for-candidate"],
    queryFn: () => api.get("/api/users").then(r => r.data),
  });
  const { data: clientsData } = useQuery({
    queryKey: ["clients-lookup-for-candidate"],
    queryFn: () => phase5Api.clientsLookup().then(r => r.data),
  });
  const users = usersData ?? [];
  const clients = clientsData ?? [];

  const onChange = (k: keyof CandidateFormData, v: string) => setForm(f => ({ ...f, [k]: v }));
  const onToggle = (k: "champion", v: boolean) => setForm(f => ({ ...f, [k]: v }));
  const onMulti = (
    k: "pref_remote_modes" | "pref_contract_types",
    v: string,
    on: boolean,
  ) =>
    setForm(f => {
      const current = f[k];
      const next = on ? Array.from(new Set([...current, v])) : current.filter(x => x !== v);
      return { ...f, [k]: next };
    });

  /**
   * Sprawdza duplikaty dla migawki formularza. Każde wywołanie unieważnia
   * wcześniejsze w locie (licznik), więc spóźniona odpowiedź dla starego
   * e-maila nie nadpisze wyniku dla bieżącego. Zwraca trafienia tego
   * wywołania (fail-open: błąd usługi = brak trafień, nie blokada zapisu).
   */
  const checkDuplicates = async (snapshot: CandidateFormData): Promise<DuplicateCandidateHit[]> => {
    const seq = ++checkSeqRef.current;
    const key = duplicateIdentityKey(snapshot);
    if (!hasDuplicateIdentity(snapshot)) {
      setDuplicates([]);
      setCheckedKey(key);
      return [];
    }
    let hits: DuplicateCandidateHit[] = [];
    try {
      const res = await api.post("/api/candidates/check-duplicates", {
        email: snapshot.email || undefined,
        phone: snapshot.phone || undefined,
        linkedin: snapshot.linkedin || undefined,
        name: snapshot.name || undefined,
        lastname: snapshot.lastname || undefined,
      });
      hits = Array.isArray(res?.data) ? res.data : [];
    } catch (err) {
      console.error("Duplicate check failed: ", err);
    }
    if (seq === checkSeqRef.current) {
      setDuplicates(hits);
      setCheckedKey(key);
    }
    return hits;
  };

  const debouncedIdentityKey = useDebouncedValue(duplicateIdentityKey(form), DUPLICATE_CHECK_DEBOUNCE_MS);
  useEffect(() => {
    const snapshot = formRef.current;
    // Pierwszy render z pustym formularzem — nic do sprawdzenia.
    if (!hasDuplicateIdentity(snapshot) && duplicates.length === 0) return;
    // Klucz się zmienił w trakcie opóźnienia — kolejne wywołanie efektu sprawdzi świeży stan.
    if (duplicateIdentityKey(snapshot) !== debouncedIdentityKey) return;
    void checkDuplicates(snapshot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedIdentityKey]);

  const currentKey = duplicateIdentityKey(form);
  const showDecision = decisionPending && duplicates.length > 0 && currentKey === checkedKey;

  const saveCandidate = async (force: boolean) => {
    if (!form.name || !form.lastname) { setError("Imię i nazwisko są wymagane"); return; }
    setSaving(true); setError("");
    try {
      if (!force) {
        // Szybki zapis przed końcem debounce: sprawdź to, co jest w polach teraz.
        const hits = currentKey === checkedKey ? duplicates : await checkDuplicates(form);
        if (hits.length > 0) {
          setDecisionPending(true);
          return;
        }
      }
      await api.post("/api/candidates", candidateFormToPayload(form));
      onSuccess("Kandydat dodany pomyślnie");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await saveCandidate(false);
  };

  return (
    <Modal title="Dodaj kandydata" onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80dvh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        {duplicates.length > 0 && (
          <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-900/20 p-3 space-y-2">
            <div className="flex items-start gap-2">
              <span className="text-amber-700 dark:text-amber-300 font-medium text-sm">
                ⚠️ Znaleziono {duplicates.length} podobnego kandydata w bazie:
              </span>
            </div>
            <ul className="space-y-1 text-sm">
              {duplicates.slice(0, 5).map((d) => (
                <li key={d.candidate_id} className="flex items-center justify-between">
                  <span className="text-foreground dark:text-muted-foreground">
                    {d.name} {d.lastname}
                    {d.email ? ` (${d.email})` : ""}
                    <span className="ml-2 text-xs text-amber-700">
                      score {d.match_score} · {d.match_reasons.join(", ")}
                    </span>
                  </span>
                  <a
                    href={`/candidates/${d.candidate_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary hover:underline text-xs"
                  >
                    Otwórz profil ↗
                  </a>
                </li>
              ))}
            </ul>
            <p className="text-xs text-amber-800">
              Możesz kontynuować, jeśli masz pewność że to inny kandydat.
            </p>
          </div>
        )}
        <CandidateFormFields
          form={form}
          onChange={onChange}
          onToggle={onToggle}
          onMulti={onMulti}
          users={users}
          clients={clients}
          collapseSecondary
        />
        {showDecision ? (
          <div
            role="alert"
            className="space-y-3 rounded-md border border-amber-300 bg-amber-50 p-3 dark:bg-amber-900/20"
          >
            <p className="text-sm font-medium text-foreground">
              Ten kandydat może już być w bazie: {duplicates[0].name} {duplicates[0].lastname}
              {duplicates[0].email ? ` (${duplicates[0].email})` : ""}.
            </p>
            <div className="flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => setDecisionPending(false)}
                className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground rounded-lg transition-colors"
              >
                Wróć do formularza
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => void saveCandidate(true)}
                className="h-10 px-4 text-sm font-medium rounded-lg border border-border bg-card hover:bg-muted disabled:opacity-60 transition-colors"
              >
                Zapisz mimo to
              </button>
              <Link
                href={`/candidates/${duplicates[0].candidate_id}`}
                onClick={onClose}
                className="inline-flex h-10 items-center px-4 bg-primary hover:bg-primary/90 text-white rounded-lg text-sm font-medium transition-all"
              >
                Otwórz istniejącego
              </Link>
            </div>
          </div>
        ) : (
          <div className="flex justify-end items-center gap-3 pt-1">
            <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
            <SaveButton saving={saving} label="Dodaj kandydata" />
          </div>
        )}
      </form>
    </Modal>
  );
}

export function EditCandidateModal({ candidate, onClose, onSuccess }: { candidate: any; onClose: () => void; onSuccess: (msg: string) => void }) {
  const [initialIdentity] = useState(() => ({
    name: candidate.name ?? "",
    lastname: candidate.lastname ?? "",
  }));
  const [form, setForm] = useState<CandidateFormData>(() => candidateToForm(candidate));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { data: usersData } = useQuery({
    queryKey: ["users-list-for-candidate"],
    queryFn: () => api.get("/api/users").then(r => r.data),
  });
  const { data: clientsData } = useQuery({
    queryKey: ["clients-lookup-for-candidate"],
    queryFn: () => phase5Api.clientsLookup().then(r => r.data),
  });
  const users = usersData ?? [];
  const clients = clientsData ?? [];

  const onChange = (k: keyof CandidateFormData, v: string) => setForm(f => ({ ...f, [k]: v }));
  const onToggle = (k: "champion", v: boolean) => setForm(f => ({ ...f, [k]: v }));
  const onMulti = (
    k: "pref_remote_modes" | "pref_contract_types",
    v: string,
    on: boolean,
  ) =>
    setForm(f => {
      const current = f[k];
      const next = on ? Array.from(new Set([...current, v])) : current.filter(x => x !== v);
      return { ...f, [k]: next };
    });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name || !form.lastname) { setError("Imię i nazwisko są wymagane"); return; }
    setSaving(true); setError("");
    try {
      const {
        city: _city,
        country: _country,
        name: nextName,
        lastname: nextLastname,
        ...nonIdentityPayload
      } =
        candidateFormToPayload(form);
      const profilePayload: Omit<typeof nonIdentityPayload, "tags"> & {
        name?: string;
        lastname?: string;
        tags?: unknown[];
      } = { ...nonIdentityPayload, tags: mergeEditedTags(form.tags, candidate.tags) };
      // Niezmienione tagi nie jadą w PATCH (backend zastępuje całą listę).
      if (profilePayload.tags === undefined) delete profilePayload.tags;
      // Nie wysyłaj pól tożsamości tylko dlatego, że pełny modal zawsze je
      // renderuje. W przeciwnym razie nocny sync między otwarciem a zapisem
      // telefonu zamieniłby starą wartość formularza w fałszywy manual lock.
      if (nextName !== initialIdentity.name) profilePayload.name = nextName;
      if (nextLastname !== initialIdentity.lastname) {
        profilePayload.lastname = nextLastname;
      }
      await api.patch(`/api/candidates/${candidate.id}`, profilePayload);

      const nextCity = form.city.trim();
      const nextCountry = form.country.trim().toUpperCase();
      const currentCity = String(candidate.city ?? candidate.location ?? "").trim();
      const currentCountry = String(candidate.country ?? "").trim().toUpperCase();
      if (nextCity !== currentCity || nextCountry !== currentCountry) {
        await candidateProfileApi.updateLocation(candidate.id, {
          city: nextCity || null,
          country: nextCountry || null,
        });
      }
      onSuccess("Kandydat zaktualizowany");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  return (
    <Modal title={`Edytuj: ${candidate.name} ${candidate.lastname}`} onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80dvh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <CandidateFormFields
          form={form}
          onChange={onChange}
          onToggle={onToggle}
          onMulti={onMulti}
          users={users}
          clients={clients}
          importedTagLabels={structuredTagLabels(candidate.tags)}
        />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Zapisz zmiany" />
        </div>
      </form>
    </Modal>
  );
}

// ── Modal: Dodaj / Edytuj ofertę ─────────────────────────────────────────────

interface JobFormData {
  title: string;
  client_id: string;
  status: string;
  description: string;
  requirements: string;
  location: string;
  remote_policy: string;
  // Trzecia rubryka rekrutacji (0278) — obok must-have i rate_budget_hourly.
  onsite_days_per_week: string;
  salary_min: string;
  salary_max: string;
  rate_budget_hourly: string;
  priority: string;
  deadline: string;
  recruiter_id: string;
  // Owner requestu (TAC) + Delivery Lead. Jedyny TAC klienta może być
  // podpowiedziany; przy kilku równorzędnych TAC-ach wybór musi być jawny.
  tac_id: string;
  delivery_lead_id: string;
  pipeline_template_id: string;
  // AI CC matching (migracja 0041)
  competence_category_id: string;
  // Phase 15 / Phase D: programme / Agile Release Train tag — opcjonalne.
  // Auto-extract z JD w backendzie gdy DL nie wpisze; możliwy manual override.
  train_name: string;
}

function jobToForm(j: any): JobFormData {
  return {
    title: j.title ?? "",
    client_id: j.client_id ? String(j.client_id) : "",
    status: j.status ?? "draft",
    description: j.description ?? "",
    requirements: j.requirements ?? "",
    location: j.location ?? "",
    remote_policy: j.remote_policy ?? "",
    onsite_days_per_week: j.onsite_days_per_week != null ? String(j.onsite_days_per_week) : "",
    salary_min: j.salary_min ? String(j.salary_min) : "",
    salary_max: j.salary_max ? String(j.salary_max) : "",
    rate_budget_hourly: j.rate_budget_hourly ? String(j.rate_budget_hourly) : "",
    priority: j.priority ?? "medium",
    deadline: j.deadline ? j.deadline.slice(0, 10) : "",
    recruiter_id: j.recruiter_id ? String(j.recruiter_id) : "",
    tac_id: j.tac_id ? String(j.tac_id) : "",
    delivery_lead_id: j.delivery_lead_id ? String(j.delivery_lead_id) : "",
    pipeline_template_id: j.pipeline_template_id ? String(j.pipeline_template_id) : "",
    competence_category_id: j.competence_category_id ? String(j.competence_category_id) : "",
    train_name: j.train_name ?? "",
  };
}

// Hiring manager po stronie klienta (migracja 0097) — osobny stan formularza,
// bo zapisuje go `PUT /api/jobs/{id}/hiring-manager`, która umie też założyć
// nową osobę jako kontakt klienta (25.09.2026).
function jobHiringManager(j: any): HiringManagerChoice | null {
  return j.hiring_manager_contact_id && j.hiring_manager_name
    ? { kind: "contact", id: j.hiring_manager_contact_id, name: j.hiring_manager_name }
    : null;
}

function JobFormFields({
  form,
  onChange,
  clients,
  users,
  hiringManager,
  onHiringManagerChange,
}: {
  form: JobFormData;
  onChange: (k: keyof JobFormData, v: string) => void;
  clients: any[];
  users: any[];
  hiringManager: HiringManagerChoice | null;
  onHiringManagerChange: (value: HiringManagerChoice | null) => void;
}) {
  const hiringManagerLabelId = useId();
  // 22.09.2026 (strona `/jobs/new`): TAC, Program/Train, typ rekrutacji,
  // widełki PLN/mies., priorytet, szablon procesu i kategoria kompetencji
  // zniknęły z tworzenia I z edycji — ustawia je backend, dane zostają.
  const clientIdNum = form.client_id ? Number(form.client_id) : null;
  // Zespół klienta — tylko po head DL (podpowiedź przy Delivery Leadzie).
  const { data: clientTeam } = useQuery<ClientTeamResponse>({
    queryKey: ["client-team", clientIdNum],
    queryFn: async () => {
      if (clientIdNum === null) return { tacs: [], delivery_leads: [] };
      const res = await clientTeamApi.get(clientIdNum);
      return res.data;
    },
    enabled: clientIdNum !== null,
    staleTime: 30_000,
  });
  const headDl = clientTeam?.delivery_leads.find(d => d.is_head);

  // Auto-fill Delivery Leada z head DL klienta, gdy pole puste.
  useEffect(() => {
    if (!clientTeam) return;
    if (!form.delivery_lead_id && headDl) {
      onChange("delivery_lead_id", String(headDl.user_id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientTeam?.delivery_leads.length, clientIdNum]);

  const dlAssignableUsers = users.filter((u: any) =>
    ["delivery_lead", "admin", "head_of_recruitment"].includes(u.role ?? "")
  );
  return (
    <>
      <FieldGroup label="Tytuł stanowiska" required>
        <Input value={form.title} onChange={e => onChange("title", e.target.value)} placeholder="Senior Java Developer" />
      </FieldGroup>
      <FieldGroup label="Klient" required>
        <Select value={form.client_id} onChange={e => onChange("client_id", e.target.value)}>
          <option value="">— wybierz klienta —</option>
          {clients.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </FieldGroup>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <FieldGroup label="Status">
          <Select value={form.status} onChange={e => onChange("status", e.target.value)}>
            <option value="draft">Draft</option>
            <option value="published">Opublikowana</option>
            <option value="closed">Zamknięta</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Deadline">
          <Input type="date" value={form.deadline} onChange={e => onChange("deadline", e.target.value)} />
        </FieldGroup>
      </div>
      <FieldGroup label="Opis">
        <Textarea value={form.description} onChange={e => onChange("description", e.target.value)} rows={3} placeholder="Opis stanowiska..." />
      </FieldGroup>
      <FieldGroup label="Wymagania">
        <Textarea value={form.requirements} onChange={e => onChange("requirements", e.target.value)} rows={3} placeholder="Wymagania techniczne..." />
      </FieldGroup>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <FieldGroup label="Miasto biura">
          {/* Rubryka biura oferty (0278) — miasto, DO KTÓREGO trzeba dojechać
              przy trybie hybrydowym/stacjonarnym. Kolumna `location` czytana
              przez dealbreaker `office_city_mismatch` i bramkę handoffu. */}
          <Input value={form.location} onChange={e => onChange("location", e.target.value)} placeholder="np. Warszawa" />
        </FieldGroup>
        <FieldGroup label="Tryb pracy (remote policy)">
          {/* Values MUST match backend RemotePolicy enum (onsite|hybrid|remote).
              "on_site"/"flexible" were rejected server-side (422) — SEARCH-P0-02.
              Puste = "nieznane" (0278, bez domyślnej "hybrid" po stronie DB —
              importer Traffita przestał stemplować, więc realny brak wyboru
              zostaje wreszcie odróżnialny od "chce biura"). */}
          <Select value={form.remote_policy} onChange={e => onChange("remote_policy", e.target.value)}>
            <option value="">— nie ustawiono —</option>
            <option value="onsite">On-site</option>
            <option value="hybrid">Hybrid</option>
            <option value="remote">Remote</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Dni w biurze / tydzień">
          <Input
            type="number"
            min={0}
            max={7}
            value={form.onsite_days_per_week}
            onChange={e => onChange("onsite_days_per_week", e.target.value)}
            placeholder="np. 2"
          />
        </FieldGroup>
      </div>
      {/* Budżet dla kandydata (dealbreaker-switch). Osobne pole, bo
          salary_min/max ma niejednoznaczną jednostkę: formularz podpisuje je
          PLN/h, ale importy/seed trzymają tam PLN/mies. — scoring odmawia tej
          kolumny właśnie przez to. To pole jest ZAWSZE PLN/h. */}
      <FieldGroup label="Budżet PLN/h dla kandydata (switch „poza budżetem”)">
        <Input type="number" value={form.rate_budget_hourly} onChange={e => onChange("rate_budget_hourly", e.target.value)} placeholder="np. 150 — puste = użyjemy stawki Championa" />
      </FieldGroup>
      <FieldGroup label="Rekruter prowadzący">
        <Select value={form.recruiter_id} onChange={e => onChange("recruiter_id", e.target.value)}>
          <option value="">— nieprzypisany —</option>
          {users.map((u: any) => (
            <option key={u.id} value={u.id}>
              {u.name || u.full_name || u.email}
              {u.role ? ` (${u.role})` : ""}
            </option>
          ))}
        </Select>
      </FieldGroup>
      <FieldGroup label="Delivery Lead">
        <Select value={form.delivery_lead_id} onChange={e => onChange("delivery_lead_id", e.target.value)}>
          <option value="">— brak DL —</option>
          {dlAssignableUsers.map((u: any) => (
            <option key={u.id} value={u.id}>
              {u.name || u.full_name || u.email}
              {u.role ? ` (${u.role})` : ""}
            </option>
          ))}
        </Select>
        {form.delivery_lead_id && headDl && Number(form.delivery_lead_id) === headDl.user_id && (
          <p className="text-[11px] text-emerald-600 mt-1">
            ✓ Head DL klienta
          </p>
        )}
        {form.delivery_lead_id && headDl && Number(form.delivery_lead_id) !== headDl.user_id && (
          <p className="text-[11px] text-primary mt-1">
            Nadpisane (head DL klienta: {headDl.name})
          </p>
        )}
      </FieldGroup>
      {/* Nie `FieldGroup`: wiąże etykietę tylko z Input/Select/Textarea,
          a combobox dostaje nazwę przez `aria-labelledby`. */}
      <div>
        <span
          id={hiringManagerLabelId}
          className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1"
        >
          Hiring manager (osoba zatrudniająca u klienta)
        </span>
        <HiringManagerCombobox
          clientId={clientIdNum}
          value={hiringManager}
          onChange={onHiringManagerChange}
          labelledBy={hiringManagerLabelId}
        />
      </div>
    </>
  );
}

/**
 * `scope="content"` (22.09.2026) — rekruter prowadzący i współpracownicy
 * (`can_edit` z `GET /api/jobs/{id}`, bez capability `job.update`) zmieniają
 * wyłącznie treść: opis i wymagania. Klient, budżet, właściciele, hiring
 * manager, termin i status zostają w rękach Delivery Leada — nie renderujemy
 * ich i NIE wysyłamy w PATCH (backend czyta `model_fields_set`, więc wartości
 * w bazie zostają nietknięte). Patrz `lib/job-edit-access.ts`.
 */
/**
 * Numer u klienta i tytuł dla rekrutera (0380). „Tytuł stanowiska” wyżej
 * zostaje nazwą od klienta — to ona idzie do klienta w CV i do Cpro.
 */
function JobNamesFields({
  job,
  names,
  onChange,
}: {
  job: JobNames;
  names: JobNamesDraft;
  onChange: (next: JobNamesDraft) => void;
}) {
  const shown = names.workingTitleManual ? names.workingTitle : (job.working_title ?? "");
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <FieldGroup label="Numer u klienta">
        <Input
          value={names.clientReference}
          maxLength={120}
          onChange={(e) => onChange({ ...names, clientReference: e.target.value })}
          placeholder="np. ZOB 48213"
        />
      </FieldGroup>
      <div className="sm:col-span-2">
        <FieldGroup label="Tytuł dla rekrutera">
          <Input
            value={shown}
            maxLength={255}
            onChange={(e) =>
              onChange({ ...names, workingTitle: e.target.value, workingTitleManual: true })
            }
            placeholder="składa się sam z roli, must-have i lat doświadczenia"
          />
        </FieldGroup>
        <p className="mt-1 text-xs text-muted-foreground">
          {names.workingTitleManual ? (
            <button
              type="button"
              className="font-medium text-primary hover:underline"
              onClick={() => onChange({ ...names, workingTitle: "", workingTitleManual: false })}
            >
              Przywróć automatyczny
            </button>
          ) : (
            "Automatyczny — zmieni się po zmianie profilu. Widzi go tylko zespół."
          )}
        </p>
      </div>
    </div>
  );
}

export function EditJobModal({
  job,
  onClose,
  onSuccess,
  scope = "full",
}: {
  job: any;
  onClose: () => void;
  onSuccess: (msg: string) => void;
  scope?: "full" | "content";
}) {
  const [form, setForm] = useState<JobFormData>(() => jobToForm(job));
  const [hiringManager, setHiringManager] = useState<HiringManagerChoice | null>(
    () => jobHiringManager(job),
  );
  // 0380: numer u klienta i tytuł dla rekrutera — osobny szkic, bo PATCH
  // wysyła je tylko po zmianie (pusty tytuł = powrót do automatu).
  const [names, setNames] = useState<JobNamesDraft>(() => jobNamesDraft(job));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const contentOnly = scope === "content";

  const { data: clientsData } = useQuery({
    queryKey: ["clients-list-qa"],
    queryFn: () => phase5Api.clientsLookup().then(r => r.data),
    enabled: !contentOnly,
  });
  const { data: usersData } = useQuery({
    queryKey: ["users-list-qa"],
    queryFn: () => api.get("/api/users").then(r => r.data),
    enabled: !contentOnly,
  });
  const clients = clientsData ?? [];
  const users = usersData ?? [];

  const onChange = (k: keyof JobFormData, v: string) =>
    setForm((current) => {
      if (k === "client_id" && current.client_id !== v) {
        // Hiring manager to osoba z firmy klienta — przy zmianie klienta
        // znika (serwer robi to samo, `update_job`).
        setHiringManager(null);
        return {
          ...current,
          client_id: v,
          delivery_lead_id: "",
        };
      }
      return { ...current, [k]: v };
    });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title) { setError("Tytuł jest wymagany"); return; }
    setSaving(true); setError("");
    try {
      if (contentOnly) {
        await api.patch(`/api/jobs/${job.id}`, {
          description: form.description || undefined,
          requirements: form.requirements || undefined,
          ...jobNamesPatch(job, names),
        });
        onSuccess("Rekrutacja zaktualizowana");
        onClose();
        return;
      }
      await api.patch(`/api/jobs/${job.id}`, {
        title: form.title,
        client_id: form.client_id ? Number(form.client_id) : undefined,
        status: form.status,
        description: form.description || undefined,
        requirements: form.requirements || undefined,
        location: form.location || undefined,
        // 0278: pusty select → jawny `null` (czyści tryb), nie `undefined`
        // (zachowałoby stary, wybrany wcześniej tryb w PATCH — patrz tac_id
        // niżej po ten sam wzorzec).
        remote_policy: form.remote_policy || null,
        onsite_days_per_week:
          form.onsite_days_per_week === "" ? null : Number(form.onsite_days_per_week),
        // Czyszczalne (`null`, nie `undefined`): PATCH z pustym polem musi
        // móc zdjąć wcześniej ustawiony budżet, np. gdy DL chce z powrotem
        // polegać na stawce z Profilu Championa (`resolve_job_budget_hourly`
        // preferuje kolumnę, więc bez tego budżetu nie dałoby się cofnąć).
        rate_budget_hourly: form.rate_budget_hourly ? Number(form.rate_budget_hourly) : null,
        deadline: form.deadline || undefined,
        recruiter_id: form.recruiter_id ? Number(form.recruiter_id) : undefined,
        // Pola usunięte z formularza 22.09.2026 (TAC, typ, widełki, priorytet,
        // szablon, kategoria, Program/Train) NIE są wysyłane — PATCH czyta
        // `model_fields_set`, więc wartości w bazie zostają nietknięte.
        delivery_lead_id: form.delivery_lead_id ? Number(form.delivery_lead_id) : null,
        ...jobNamesPatch(job, names),
      });
      if (!sameChoice(hiringManager, jobHiringManager(job))) {
        try {
          await saveHiringManager(job.id, hiringManager);
        } catch (err: any) {
          setError(
            `Rekrutacja zapisana, ale hiring manager nie: ${formErrorMsg(err, "błąd zapisu")}`,
          );
          return;
        }
      }
      onSuccess("Rekrutacja zaktualizowana");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  return (
    <Modal title={`Edytuj: ${job.title}`} onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80dvh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        {contentOnly ? (
          <>
            <JobNamesFields job={job} names={names} onChange={setNames} />
            <FieldGroup label="Opis">
              <Textarea value={form.description} onChange={e => onChange("description", e.target.value)} rows={6} placeholder="Opis stanowiska..." />
            </FieldGroup>
            <FieldGroup label="Wymagania">
              <Textarea value={form.requirements} onChange={e => onChange("requirements", e.target.value)} rows={4} placeholder="Wymagania techniczne..." />
            </FieldGroup>
            <p className="text-xs text-muted-foreground">
              Klienta, budżet, zespół, termin i status rekrutacji zmienia Delivery Lead.
            </p>
          </>
        ) : (
          <>
            <JobFormFields
              form={form}
              onChange={onChange}
              clients={clients}
              users={users}
              hiringManager={hiringManager}
              onHiringManagerChange={setHiringManager}
            />
            <JobNamesFields job={job} names={names} onChange={setNames} />
          </>
        )}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Zapisz zmiany" />
        </div>
      </form>
    </Modal>
  );
}

// ── Modal: Dodaj firmę ────────────────────────────────────────────────────────

interface ClientFormData {
  name: string;
  industry: string;
  website: string;
  address: string;
  status: string;
  nda_signed: boolean;
  contract_type: string;
  notes: string;
}

const EMPTY_CLIENT: ClientFormData = {
  name: "", industry: "", website: "", address: "", status: "prospect",
  nda_signed: false, contract_type: "", notes: "",
};

function clientToForm(c: any): ClientFormData {
  return {
    name: c.name ?? "",
    industry: c.industry ?? "",
    website: c.website ?? "",
    address: c.address ?? "",
    status: c.status ?? "prospect",
    nda_signed: c.nda_signed ?? false,
    contract_type: c.contract_type ?? "",
    notes: c.notes ?? "",
  };
}

function ClientFormFields({ form, onChange, onCheckbox, nameRequired = true }: {
  form: ClientFormData;
  onChange: (k: keyof ClientFormData, v: string) => void;
  onCheckbox: (k: keyof ClientFormData, v: boolean) => void;
  /** Edycja pozwala wyczyścić nazwę (powrót do nazwy źródłowej z Traffita) —
      tworzenie nadal jej wymaga. */
  nameRequired?: boolean;
}) {
  return (
    <>
      <FieldGroup label="Nazwa firmy" required={nameRequired}>
        <Input value={form.name} onChange={e => onChange("name", e.target.value)} placeholder="Acme Sp. z o.o." />
        {!nameRequired && (
          <p className="mt-1 text-xs text-muted-foreground">
            Wyczyść pole, aby przywrócić nazwę źródłową (np. z Traffita).
          </p>
        )}
      </FieldGroup>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Branża">
          <Input value={form.industry} onChange={e => onChange("industry", e.target.value)} placeholder="IT / Finance..." />
        </FieldGroup>
        <FieldGroup label="Status handlowy">
          <Select value={form.status} onChange={e => onChange("status", e.target.value)}>
            <option value="prospect">Prospect</option>
            <option value="active">Aktywny</option>
            <option value="inactive">Nieaktywny</option>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">
            Etykieta handlowa. Nie przenosi między zakładkami — o zakładce
            (Aktywni / Relacyjni / Nieaktywni) decyduje kategoria portfela na
            liście klientów.
          </p>
        </FieldGroup>
      </div>
      <FieldGroup label="Strona WWW">
        <Input type="url" value={form.website} onChange={e => onChange("website", e.target.value)} placeholder="https://firma.pl" />
      </FieldGroup>
      <FieldGroup label="Typ kontraktu">
        <Input value={form.contract_type} onChange={e => onChange("contract_type", e.target.value)} placeholder="B2B / Umowa..." />
      </FieldGroup>
      <FieldGroup label="Adres">
        <Input value={form.address} onChange={e => onChange("address", e.target.value)} placeholder="ul. Przykładowa 1, Warszawa" />
      </FieldGroup>
      <FieldGroup label="Notatki">
        <Textarea value={form.notes} onChange={e => onChange("notes", e.target.value)} rows={3} placeholder="Dodatkowe informacje..." />
      </FieldGroup>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.nda_signed}
          onChange={e => onCheckbox("nda_signed", e.target.checked)}
          className="w-4 h-4 rounded accent-blue-600"
        />
        <span className="text-sm text-foreground dark:text-muted-foreground">NDA podpisane</span>
      </label>
    </>
  );
}

export function AddClientModal({
  onClose,
  onSuccess,
  category,
}: {
  onClose: () => void;
  onSuccess: (msg: string) => void;
  category?: ClientDirectoryCategory;
}) {
  const [form, setForm] = useState<ClientFormData>(EMPTY_CLIENT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const onChange = (k: keyof ClientFormData, v: string) => setForm(f => ({ ...f, [k]: v }));
  const onCheckbox = (k: keyof ClientFormData, v: boolean) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name) { setError("Nazwa firmy jest wymagana"); return; }
    setSaving(true); setError("");
    try {
      await api.post(
        "/api/clients",
        {
          name: form.name,
          industry: form.industry || undefined,
          website: form.website || undefined,
          address: form.address || undefined,
          status: form.status,
          nda_signed: form.nda_signed,
          contract_type: form.contract_type || undefined,
          notes: form.notes || undefined,
        },
        {
          params: {
            portfolio_category: category ?? "active",
          },
        },
      );
      onSuccess("Firma dodana pomyślnie");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Dodaj firmę" onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80dvh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <ClientFormFields form={form} onChange={onChange} onCheckbox={onCheckbox} />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Dodaj firmę" />
        </div>
      </form>
    </Modal>
  );
}

export function EditClientModal({ client, onClose, onSuccess }: { client: any; onClose: () => void; onSuccess: (msg: string) => void }) {
  // Reguły CV prowadzi Delivery Lead (DeliveryLeadPlus), a kartę klienta
  // edytuje też TAC (TacPlus). Bez tej bramki TAC widziałby formularz reguł
  // i dostawał 403 dopiero na zapisie.
  const canManageCvRules = useCapability("cv_rule.manage");
  const [form, setForm] = useState<ClientFormData>(() => clientToForm(client));
  // Nazwa z chwili otwarcia (GET zwraca nazwę EFEKTYWNĄ = display_name ?? name)
  // — dirty-check decyduje, czy w ogóle wysyłamy display_name.
  const [initialName] = useState<string>(() => clientToForm(client).name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const onChange = (k: keyof ClientFormData, v: string) => setForm(f => ({ ...f, [k]: v }));
  const onCheckbox = (k: keyof ClientFormData, v: boolean) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      const payload: Record<string, unknown> = {
        industry: form.industry || null,
        website: form.website || null,
        address: form.address || null,
        status: form.status,
        nda_signed: form.nda_signed,
        contract_type: form.contract_type || null,
        notes: form.notes || null,
      };
      // Edycja nazwy pisze do sync-odpornego `display_name` — Traffit nadpisuje
      // `name` przy każdym daily sync, a wyświetlanie i tak robi
      // coalesce(display_name, name). Wysyłamy TYLKO gdy pole faktycznie
      // zmienione (bezwarunkowy zapis przy edycji np. branży zamroziłby nazwę
      // względem Traffita na stałe). Wyczyszczenie pola → null → powrót do
      // nazwy źródłowej. `name` celowo NIE jest już wysyłane.
      if (form.name.trim() !== initialName.trim()) {
        payload.display_name = form.name.trim() || null;
      }
      await api.patch(`/api/clients/${client.id}`, payload);
      onSuccess("Firma zaktualizowana");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  return (
    <Modal title={`Edytuj: ${client.name}`} onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80dvh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <ClientFormFields form={form} onChange={onChange} onCheckbox={onCheckbox} nameRequired={false} />
        {/* Reguły CV mają WŁASNĄ tabelę i własny zapis — celowo poza payloadem
            PATCH klienta i poza `ClientFormFields`, który jest współdzielony
            z oknem DODAWANIA klienta. Zakładanie reguł przy tworzeniu firmy
            dawałoby regułę bez świadomej decyzji. */}
        {/* Reguły CV (nazwa pliku, język, instrukcje, blokady, polityka treści,
            interaktywne CV) mają WŁASNY edytor w Ustawieniach — jeden ekran
            prowadzi całą politykę CV klienta. Tu tylko odsyłacz. */}
        <p className="text-xs text-muted-foreground">
          Reguły CV tego klienta (nazwa pliku, język, instrukcje dla generatora,
          interaktywne CV) prowadzi Delivery Lead albo admin w{" "}
          {canManageCvRules ? (
            <a
              href={`/settings/cv-rules?client=${client.id}`}
              className="text-primary hover:underline"
            >
              Ustawienia → Reguły CV per klient
            </a>
          ) : (
            <span>Ustawienia → Reguły CV per klient</span>
          )}
          .
        </p>
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Zapisz zmiany" />
        </div>
      </form>
    </Modal>
  );
}

// ── Modal: Zaplanuj spotkanie ─────────────────────────────────────────────────

export function AddMeetingModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  // Pełna godzina + 1 h liczona przez `Date` — po 23:00 przewija się na
  // następny dzień zamiast dawać „T24:00" (FE-12).
  const [defaults] = useState(() => defaultMeetingWindow());
  const [form, setForm] = useState({ title: "", event_type: "meeting", start_time: defaults.start, end_time: defaults.end });
  // Kandydat szukany po stronie serwera — dawny `<select>` z `page_size: 100`
  // nie pozwalał wskazać nikogo spoza pierwszej setki (FE-11).
  const [candidate, setCandidate] = useState<CandidateChoice | null>(null);
  const [createInOutlook, setCreateInOutlook] = useState(false);
  const [addTeamsMeeting, setAddTeamsMeeting] = useState(true);
  const [inviteCandidate, setInviteCandidate] = useState(false);
  const [attendees, setAttendees] = useState("");
  const [clientRequestId] = useState(newClientRequestId);
  const candidateLabelId = useId();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title || !form.start_time) { setError("Tytuł i czas rozpoczęcia są wymagane"); return; }
    if (createInOutlook && !form.end_time) { setError("Podaj godzinę zakończenia spotkania w Outlooku."); return; }
    const extraAttendees = splitAttendeeEmails(attendees);
    if (createInOutlook && invalidAttendeeEmails(extraAttendees).length > 0) {
      setError("Sprawdź adresy e-mail uczestników.");
      return;
    }
    setSaving(true); setError("");
    try {
      if (createInOutlook) {
        await microsoft365Api.createInvite({
          title: form.title,
          event_type: form.event_type,
          start: new Date(form.start_time).toISOString(),
          end: new Date(form.end_time).toISOString(),
          candidate_id: candidate?.id ?? null,
          invite_candidate: Boolean(candidate && inviteCandidate),
          extra_attendees: extraAttendees,
          add_teams_meeting: addTeamsMeeting,
          client_request_id: clientRequestId,
        });
        onSuccess("Spotkanie utworzone w Outlooku" + (addTeamsMeeting ? " z linkiem Teams" : ""));
      } else {
        await api.post("/api/calendar/events", {
          title: form.title,
          event_type: form.event_type,
          start_time: new Date(form.start_time).toISOString(),
          end_time: form.end_time ? new Date(form.end_time).toISOString() : undefined,
          candidate_id: candidate?.id,
        });
        onSuccess("Spotkanie zaplanowane pomyślnie");
      }
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Zaplanuj spotkanie" onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        {error && <ErrorBanner error={error} />}
        <FieldGroup label="Tytuł" required>
          <Input value={form.title} onChange={e => set("title", e.target.value)} placeholder="Screening call — Jan Kowalski" />
        </FieldGroup>
        <FieldGroup label="Typ spotkania">
          <Select value={form.event_type} onChange={e => set("event_type", e.target.value)}>
            <option value="meeting">Spotkanie</option>
            <option value="interview">Rozmowa kwalifikacyjna</option>
            <option value="screening">Screening</option>
            <option value="prep_call">Rozmowa telefoniczna</option>
            <option value="deadline">Deadline</option>
          </Select>
        </FieldGroup>
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Początek" required>
            <Input type="datetime-local" value={form.start_time} onChange={e => set("start_time", e.target.value)} />
          </FieldGroup>
          <FieldGroup label="Koniec">
            <Input type="datetime-local" value={form.end_time} onChange={e => set("end_time", e.target.value)} />
          </FieldGroup>
        </div>
        <div>
          <span
            id={candidateLabelId}
            className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1"
          >
            Kandydat (opcjonalnie)
          </span>
          <CandidateCombobox
            value={candidate}
            onChange={setCandidate}
            labelledBy={candidateLabelId}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={createInOutlook} onChange={e => setCreateInOutlook(e.target.checked)} />
          Utwórz też w moim Outlooku
        </label>
        {createInOutlook && (
          <div className="space-y-3 rounded-lg border border-border p-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={addTeamsMeeting} onChange={e => setAddTeamsMeeting(e.target.checked)} />
              Dodaj link Teams
            </label>
            {candidate && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={inviteCandidate} onChange={e => setInviteCandidate(e.target.checked)} />
                Wyślij zaproszenie kandydatowi
              </label>
            )}
            <FieldGroup label="Inni uczestnicy (adresy e-mail)">
              <Input value={attendees} onChange={e => setAttendees(e.target.value)} placeholder="osoba@firma.pl, druga@firma.pl" />
            </FieldGroup>
            <p className="text-xs text-muted-foreground">Zaproszenia wyśle Outlook po zapisaniu spotkania.</p>
          </div>
        )}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label={createInOutlook ? "Utwórz w Outlooku" : "Zaplanuj"} />
        </div>
      </form>
    </Modal>
  );
}

// ── Modal: Dodaj osobę kontaktową u klienta ──────────────────────────────────

export function AddContactModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  const [form, setForm] = useState({
    client_id: "",
    name: "",
    position: "",
    email: "",
    phone: "",
    department: "",
    is_decision_maker: false,
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();

  const { data: clientsData } = useQuery({
    queryKey: ["clients-list-qa"],
    queryFn: () => phase5Api.clientsLookup().then(r => r.data),
  });
  const clients = clientsData ?? [];

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.client_id) { setError("Wybierz klienta"); return; }
    if (!form.name.trim()) { setError("Imię i nazwisko jest wymagane"); return; }
    setSaving(true); setError("");
    try {
      const clientIdNum = Number(form.client_id);
      await api.post("/api/contacts", {
        client_id: clientIdNum,
        name: form.name.trim(),
        position: form.position.trim() || undefined,
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
        department: form.department.trim() || undefined,
        is_decision_maker: form.is_decision_maker,
        notes: form.notes.trim() || undefined,
      });
      queryClient.invalidateQueries({ queryKey: ["client-contacts", clientIdNum] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      onSuccess("Osoba kontaktowa dodana pomyślnie");
      onClose();
    } catch (err: any) {
      setError(formErrorMsg(err, "Błąd podczas zapisywania"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Dodaj osobę kontaktową" onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        {error && <ErrorBanner error={error} />}
        <FieldGroup label="Klient" required>
          <Select value={form.client_id} onChange={e => set("client_id", e.target.value)}>
            <option value="">— wybierz klienta —</option>
            {clients.map((c: any) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </FieldGroup>
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Imię i nazwisko" required>
            <Input value={form.name} onChange={e => set("name", e.target.value)} placeholder="Jan Kowalski" />
          </FieldGroup>
          <FieldGroup label="Stanowisko">
            <Input value={form.position} onChange={e => set("position", e.target.value)} placeholder="IT Procurement Manager" />
          </FieldGroup>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Email">
            <Input type="email" value={form.email} onChange={e => set("email", e.target.value)} placeholder="jan@firma.pl" />
          </FieldGroup>
          <FieldGroup label="Telefon">
            <Input value={form.phone} onChange={e => set("phone", e.target.value)} placeholder="+48 500..." />
          </FieldGroup>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Dział">
            <Input value={form.department} onChange={e => set("department", e.target.value)} placeholder="IT / HR" />
          </FieldGroup>
          <div className="flex items-end pb-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_decision_maker}
                onChange={e => set("is_decision_maker", e.target.checked)}
                className="w-4 h-4 rounded accent-primary"
              />
              <span className="text-sm text-foreground">Decydent</span>
            </label>
          </div>
        </div>
        <FieldGroup label="Notatki">
          <Textarea value={form.notes} onChange={e => set("notes", e.target.value)} rows={2} />
        </FieldGroup>
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Dodaj kontakt" />
        </div>
      </form>
    </Modal>
  );
}

// ── Quick actions dropdown ───────────────────────────────────────────────────

type ModalType = "candidate" | "job" | "client" | "meeting" | null;

function QuickActionsButton({
  externalModal,
  onExternalModalClear,
}: {
  externalModal?: ModalType;
  onExternalModalClear?: () => void;
} = {}) {
  const [open, setOpen] = useState(false);
  const [modal, setModal] = useState<ModalType>(null);
  const router = useRouter();

  // Handle external modal trigger (from keyboard shortcuts)
  useEffect(() => {
    if (externalModal) {
      if (externalModal === "job") router.push("/jobs/new");
      else setModal(externalModal);
      onExternalModalClear?.();
    }
  }, [externalModal, onExternalModalClear, router]);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);

  useClickOutside(ref, () => setOpen(false));

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
    // Aktywne listy V2 używają kluczy z sufiksem `-v2` / `calendar-events`.
    // Stare (bezsufiksowe) klucze zostawiamy — są nieszkodliwe, a niektóre
    // ekrany V1 nadal ich używają. Bez kluczy V2 świeżo dodany rekord nie
    // pojawiał się na liście bez ręcznego odświeżenia strony.
    queryClient.invalidateQueries({ queryKey: ["candidates"] });
    queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
    queryClient.invalidateQueries({ queryKey: ["clients"] });
    queryClient.invalidateQueries({ queryKey: ["clients-v2"] });
    queryClient.invalidateQueries({ queryKey: ["contacts"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
    queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
  };

  const QUICK_ACTIONS: { label: string; icon: React.ComponentType<{ className?: string }>; modal: ModalType }[] = [
    { label: "Dodaj kandydata", icon: UserPlus, modal: "candidate" },
    { label: "Dodaj rekrutację", icon: Briefcase, modal: "job" },
    { label: "Dodaj firmę", icon: Building2, modal: "client" },
    { label: "Zaplanuj spotkanie", icon: CalendarPlus, modal: "meeting" },
  ];

  return (
    <>
      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 bg-primary hover:bg-primary/90 active:scale-95 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150 shadow-xs"
        >
          <Plus className="w-4 h-4" />
          <span className="hidden sm:inline">Dodaj</span>
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-2 w-52 bg-card dark:bg-muted border border-border dark:border-border rounded-xl shadow-lg py-1.5 z-50">
            {QUICK_ACTIONS.map(({ label, icon: Icon, modal: m }) => (
              <button
                key={m}
                onClick={() => {
                  setOpen(false);
                  // Nowa rekrutacja to strona, nie okno (22.09.2026).
                  if (m === "job") router.push("/jobs/new");
                  else setModal(m);
                }}
                className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted transition-colors"
              >
                <Icon className="w-4 h-4 text-muted-foreground" />
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Modals */}
      {modal === "candidate" && <AddCandidateModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "client" && <AddClientModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "meeting" && <AddMeetingModal onClose={() => setModal(null)} onSuccess={showToast} />}

      {/* Toast */}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </>
  );
}
