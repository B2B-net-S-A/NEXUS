"use client";

/**
 * Legacy modal bundle — housed in AppShell.tsx historically; after Phase 11
 * decommission this file keeps only the Add/Edit modals used across the app
 * (AddCandidate, EditCandidate, AddJob, EditJob, AddClient, AddMeeting) plus
 * their internal helpers. The old `<AppShell>` wrapper was replaced by
 * `<AppShellV2>` in `components/v2/shell/`.
 */

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  X, Loader2, Sparkles, ChevronRight, Plus,
  UserPlus, Briefcase, Building2, CalendarPlus,
} from "lucide-react";
import api, {
  aiWriterApi,
  phase5Api,
  pipelineTemplatesApi,
  requestHistoryApi,
} from "@/lib/api";
import type { RequestHistoryResponse } from "@/lib/api";
import { CompetenceCategoryPicker } from "@/components/jobs/CompetenceCategoryPicker";
import { AutoAssignedCollaborators } from "@/components/jobs/AutoAssignedCollaborators";

// ── Breadcrumb helper ────────────────────────────────────────────────────────

const SEGMENT_LABELS: Record<string, string> = {
  "": "Dashboard",
  candidates: "Kandydaci",
  jobs: "Oferty pracy",
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
    <div className={`fixed bottom-6 right-6 z-[200] flex items-center gap-3 px-5 py-3.5 rounded-xl shadow-xl text-white text-sm font-medium ${type === "success" ? "bg-green-600" : "bg-red-600"}`}>
      {message}
      <button onClick={onClose} className="ml-1 opacity-70 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ── Generic Modal Shell ────────────────────────────────────────────────────────

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-end sm:items-center justify-center sm:p-4 overflow-y-auto">
      <div className={`bg-card dark:bg-muted rounded-2xl sm:rounded-2xl rounded-b-none sm:rounded-b-2xl shadow-2xl w-full sm:my-4 ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"}`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
          <h2 className="text-lg font-bold text-foreground dark:text-foreground">{title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FieldGroup({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
        {label} {required && <span className="text-destructive">*</span>}
      </label>
      {children}
    </div>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="h-10 w-full px-3 border border-border dark:border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground placeholder:text-muted-foreground dark:placeholder:text-muted-foreground"
    />
  );
}

function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring resize-y bg-card dark:bg-muted dark:text-foreground placeholder:text-muted-foreground dark:placeholder:text-muted-foreground"
    />
  );
}

function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { children: React.ReactNode }) {
  return (
    <select
      {...props}
      className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted dark:text-foreground"
    >
      {children}
    </select>
  );
}

function SaveButton({ saving, label = "Zapisz" }: { saving: boolean; label?: string }) {
  return (
    <button
      type="submit"
      disabled={saving}
      aria-label={label}
      className="flex items-center gap-2 h-10 px-4 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white rounded-lg text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {saving && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
      {label}
    </button>
  );
}

function ErrorBanner({ error }: { error: string }) {
  return <div className="text-sm text-destructive dark:text-destructive bg-destructive/10 dark:bg-red-900/30 rounded-lg px-4 py-2">{error}</div>;
}

// ── Modal: Dodaj / Edytuj kandydata ───────────────────────────────────────────

interface CandidateFormData {
  name: string;
  lastname: string;
  email: string;
  phone: string;
  location: string;
  source: string;
  linkedin: string;
  salary_expectation: string;
  salary_currency: string;
  availability_date: string;
  notice_period: string;
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
  pref_remote_modes: string[]; // ['remote','hybrid','on_site']
  pref_rate_min: string;
  pref_rate_max: string;
  pref_industries: string; // comma separated
  pref_contract_types: string[]; // ['b2b','uop','zlecenie']
  pref_excluded_clients: string; // comma separated client ids
}

const EMPTY_CANDIDATE: CandidateFormData = {
  name: "", lastname: "", email: "", phone: "", location: "",
  source: "manual", linkedin: "", salary_expectation: "", salary_currency: "PLN",
  availability_date: "", notice_period: "", status: "active", availability_status: "unknown", tags: "", notes: "",
  years_it_experience: "", champion: false, verifier_id: "", verified_tech: "",
  pref_remote_modes: [], pref_rate_min: "", pref_rate_max: "",
  pref_industries: "", pref_contract_types: [], pref_excluded_clients: "",
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
    location: c.location ?? "",
    source: c.source ?? "manual",
    linkedin: c.linkedin ?? "",
    salary_expectation: c.salary_expectation ? String(c.salary_expectation) : "",
    salary_currency: c.salary_currency ?? "PLN",
    availability_date: c.availability_date ? c.availability_date.slice(0, 10) : "",
    notice_period: c.notice_period != null ? String(c.notice_period) : "",
    status: c.status ?? "active",
    availability_status: c.availability_status ?? "unknown",
    tags: Array.isArray(c.tags) ? c.tags.join(", ") : (c.tags ?? ""),
    notes: "",
    years_it_experience: c.years_it_experience != null ? String(c.years_it_experience) : "",
    champion: !!c.champion,
    verifier_id: c.verifier_id != null ? String(c.verifier_id) : "",
    verified_tech: _verifiedTechToString(c.verified_tech),
    pref_remote_modes: Array.isArray(prefs.remote_modes) ? prefs.remote_modes : [],
    pref_rate_min: prefs.rate_min != null ? String(prefs.rate_min) : "",
    pref_rate_max: prefs.rate_max != null ? String(prefs.rate_max) : "",
    pref_industries: Array.isArray(prefs.industries) ? prefs.industries.join(", ") : "",
    pref_contract_types: Array.isArray(prefs.contract_types) ? prefs.contract_types : [],
    pref_excluded_clients: Array.isArray(prefs.excluded_clients)
      ? prefs.excluded_clients.join(", ")
      : "",
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

  const preferences: Record<string, unknown> = {};
  if (form.pref_remote_modes.length) preferences.remote_modes = form.pref_remote_modes;
  if (form.pref_rate_min) preferences.rate_min = Number(form.pref_rate_min);
  if (form.pref_rate_max) preferences.rate_max = Number(form.pref_rate_max);
  if (industries.length) preferences.industries = industries;
  if (form.pref_contract_types.length) preferences.contract_types = form.pref_contract_types;
  if (excluded.length) preferences.excluded_clients = excluded;

  return {
    name: form.name,
    lastname: form.lastname,
    email: form.email || undefined,
    phone: form.phone || undefined,
    location: form.location || undefined,
    source: form.source,
    linkedin: form.linkedin || undefined,
    salary_expectation: form.salary_expectation ? Number(form.salary_expectation) : undefined,
    salary_currency: form.salary_currency,
    availability_date: form.availability_date || undefined,
    notice_period: form.notice_period ? Number(form.notice_period) : undefined,
    status: form.status,
    availability_status: form.availability_status || undefined,
    tags: tags.length ? tags : undefined,
    years_it_experience: form.years_it_experience ? Number(form.years_it_experience) : undefined,
    champion: form.champion,
    verifier_id: form.verifier_id ? Number(form.verifier_id) : undefined,
    verified_tech: verifiedTech.length ? verifiedTech : undefined,
    preferences: Object.keys(preferences).length ? preferences : undefined,
  };
}

function CandidateFormFields({
  form,
  onChange,
  onToggle,
  onMulti,
  users,
  clients,
}: {
  form: CandidateFormData;
  onChange: (k: keyof CandidateFormData, v: string) => void;
  onToggle: (k: "champion", v: boolean) => void;
  onMulti: (k: "pref_remote_modes" | "pref_contract_types", v: string, on: boolean) => void;
  users: { id: number; full_name?: string; email?: string }[];
  clients: { id: number; name: string }[];
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
        <FieldGroup label="Lokalizacja">
          <Input value={form.location} onChange={e => onChange("location", e.target.value)} placeholder="Warszawa" />
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
      <div className="grid grid-cols-3 gap-3">
        <FieldGroup label="Oczekiwania finansowe">
          <Input type="number" value={form.salary_expectation} onChange={e => onChange("salary_expectation", e.target.value)} placeholder="20000" />
        </FieldGroup>
        <FieldGroup label="Waluta">
          <Select value={form.salary_currency} onChange={e => onChange("salary_currency", e.target.value)}>
            <option value="PLN">PLN</option>
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Okres wypowiedzenia (dni)">
          <Input type="number" value={form.notice_period} onChange={e => onChange("notice_period", e.target.value)} placeholder="30" />
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
            Oznacz w zakładce <strong>Konflikty</strong> w profilu —
            typ <code>current_employment</code>. Dzięki temu karta dostanie
            burgundowy alert „U KLIENTA”.
          </div>
        </FieldGroup>
      </div>
      <FieldGroup label="Tagi (rozdzielone przecinkami)">
        <Input value={form.tags} onChange={e => onChange("tags", e.target.value)} placeholder="React, TypeScript, Remote..." />
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
            <CB field="pref_remote_modes" value="on_site" label="On-site" />
          </div>
        </FieldGroup>
        <FieldGroup label="Typ kontraktu">
          <div className="flex flex-wrap gap-2">
            <CB field="pref_contract_types" value="b2b" label="B2B" />
            <CB field="pref_contract_types" value="uop" label="UoP" />
            <CB field="pref_contract_types" value="zlecenie" label="Zlecenie" />
          </div>
        </FieldGroup>
        <div className="grid grid-cols-2 gap-3">
          <FieldGroup label="Stawka min (PLN)">
            <Input
              type="number"
              value={form.pref_rate_min}
              onChange={e => onChange("pref_rate_min", e.target.value)}
              placeholder="12000"
            />
          </FieldGroup>
          <FieldGroup label="Stawka max (PLN)">
            <Input
              type="number"
              value={form.pref_rate_max}
              onChange={e => onChange("pref_rate_max", e.target.value)}
              placeholder="20000"
            />
          </FieldGroup>
        </div>
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
}

interface DuplicateCandidateHit {
  candidate_id: number;
  name: string;
  lastname: string;
  email: string | null;
  match_score: number;
  match_reasons: string[];
}

export function AddCandidateModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  const [form, setForm] = useState<CandidateFormData>(EMPTY_CANDIDATE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [duplicates, setDuplicates] = useState<DuplicateCandidateHit[]>([]);
  const [dupeChecked, setDupeChecked] = useState(false);

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

  const checkDuplicates = async () => {
    if (!form.email && !form.phone && !form.linkedin && !(form.name && form.lastname)) return;
    try {
      const res = await api.post("/api/candidates/check-duplicates", {
        email: form.email || undefined,
        phone: form.phone || undefined,
        linkedin: form.linkedin || undefined,
        name: form.name || undefined,
        lastname: form.lastname || undefined,
      });
      setDuplicates(Array.isArray(res.data) ? res.data : []);
      setDupeChecked(true);
    } catch (err) {
      console.error("Duplicate check failed: ", err);
      setDupeChecked(true); // Fail-open: don't block save on service error
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name || !form.lastname) { setError("Imię i nazwisko są wymagane"); return; }
    setSaving(true); setError("");
    try {
      await api.post("/api/candidates", candidateFormToPayload(form));
      onSuccess("Kandydat dodany pomyślnie");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Dodaj kandydata" onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
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
        />
        <div className="flex justify-between items-center pt-1">
          <button
            type="button"
            onClick={checkDuplicates}
            className="h-9 px-3 text-xs text-primary dark:text-primary hover:bg-primary/10 dark:hover:bg-primary/15 rounded-md transition-colors"
          >
            {dupeChecked ? "Sprawdź duplikaty ponownie" : "Sprawdź duplikaty"}
          </button>
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
            <SaveButton saving={saving} label="Dodaj kandydata" />
          </div>
        </div>
      </form>
    </Modal>
  );
}

export function EditCandidateModal({ candidate, onClose, onSuccess }: { candidate: any; onClose: () => void; onSuccess: (msg: string) => void }) {
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
      await api.patch(`/api/candidates/${candidate.id}`, candidateFormToPayload(form));
      onSuccess("Kandydat zaktualizowany");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally { setSaving(false); }
  };

  return (
    <Modal title={`Edytuj: ${candidate.name} ${candidate.lastname}`} onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <CandidateFormFields
          form={form}
          onChange={onChange}
          onToggle={onToggle}
          onMulti={onMulti}
          users={users}
          clients={clients}
        />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Zapisz zmiany" />
        </div>
      </form>
    </Modal>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Lightweight `useDebouncedValue` — kept inline because we don't want to
 * pull in a new shared hook for one call site. 500ms is enough to avoid
 * banging the preview endpoint on every keystroke.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

// ── Modal: Dodaj / Edytuj ofertę ─────────────────────────────────────────────

interface JobFormData {
  title: string;
  client_id: string;
  recruitment_type: string;
  status: string;
  description: string;
  requirements: string;
  location: string;
  remote_policy: string;
  salary_min: string;
  salary_max: string;
  priority: string;
  deadline: string;
  recruiter_id: string;
  // TAC + Delivery Lead — auto-fill z primary TAC / head DL klienta po wyborze
  // klienta (endpoint /api/clients/{id}/team). Jawna zmiana = override.
  tac_id: string;
  delivery_lead_id: string;
  // Hiring manager po stronie klienta — Contact w firmie klienta odpowiedzialny
  // za rekrutację (migracja 0097, 2026-05-11). Autocomplete z Contacts klienta.
  hiring_manager_contact_id: string;
  pipeline_template_id: string;
  // AI CC matching (migracja 0041)
  competence_category_id: string;
  // Phase 15 / Phase D: programme / Agile Release Train tag — opcjonalne.
  // Auto-extract z JD w backendzie gdy DL nie wpisze; możliwy manual override.
  train_name: string;
}

const EMPTY_JOB: JobFormData = {
  title: "", client_id: "", recruitment_type: "body_leasing", status: "draft",
  description: "", requirements: "", location: "", remote_policy: "hybrid",
  salary_min: "", salary_max: "", priority: "medium", deadline: "", recruiter_id: "",
  tac_id: "", delivery_lead_id: "", hiring_manager_contact_id: "",
  pipeline_template_id: "", competence_category_id: "", train_name: "",
};

function jobToForm(j: any): JobFormData {
  return {
    title: j.title ?? "",
    client_id: j.client_id ? String(j.client_id) : "",
    recruitment_type: j.recruitment_type ?? "body_leasing",
    status: j.status ?? "draft",
    description: j.description ?? "",
    requirements: j.requirements ?? "",
    location: j.location ?? "",
    remote_policy: j.remote_policy ?? "hybrid",
    salary_min: j.salary_min ? String(j.salary_min) : "",
    salary_max: j.salary_max ? String(j.salary_max) : "",
    priority: j.priority ?? "medium",
    deadline: j.deadline ? j.deadline.slice(0, 10) : "",
    recruiter_id: j.recruiter_id ? String(j.recruiter_id) : "",
    tac_id: j.tac_id ? String(j.tac_id) : "",
    delivery_lead_id: j.delivery_lead_id ? String(j.delivery_lead_id) : "",
    hiring_manager_contact_id: j.hiring_manager_contact_id
      ? String(j.hiring_manager_contact_id)
      : "",
    pipeline_template_id: j.pipeline_template_id ? String(j.pipeline_template_id) : "",
    competence_category_id: j.competence_category_id ? String(j.competence_category_id) : "",
    train_name: j.train_name ?? "",
  };
}

function JobFormFields({
  form,
  onChange,
  clients,
  users,
  templates,
  autoCollaboratorIds,
  onAutoCollaboratorsChange,
}: {
  form: JobFormData;
  onChange: (k: keyof JobFormData, v: string) => void;
  clients: any[];
  users: any[];
  templates: { id: number; name: string; is_default?: boolean; archived?: boolean }[];
  autoCollaboratorIds?: number[];
  onAutoCollaboratorsChange?: (ids: number[]) => void;
}) {
  const ccId = form.competence_category_id ? Number(form.competence_category_id) : null;
  // Phase 15 / Phase D: podpowiedzi `train_name` zawężone do klienta.
  // Fallback na globalną listę gdy klient nie wybrany. Pomijamy fetch gdy
  // input jest jeszcze pusty (brak potrzeby).
  const clientIdNum = form.client_id ? Number(form.client_id) : null;
  const { data: trainNamesData } = useQuery<{ items: string[] }>({
    queryKey: ["jobs-train-names", clientIdNum],
    queryFn: async () => {
      const params = clientIdNum !== null ? { client_id: clientIdNum } : {};
      const res = await api.get<{ items: string[] }>("/api/jobs/train-names", {
        params,
      });
      return res.data;
    },
    staleTime: 60_000,
  });
  const trainNameSuggestions = trainNamesData?.items ?? [];

  // Auto-assign TAC + Delivery Lead wg client_tac_assignments + delivery_lead_client_assignments.
  // Endpoint zwraca cały team klienta; primary TAC / head DL są highlightowane
  // w dropdownie (zielony badge) a pola TAC/DL są auto-pre-fillowane gdy puste.
  const { data: clientTeam } = useQuery<{
    tacs: Array<{ id: number; user_id: number; name: string; email: string; role?: string; is_primary: boolean }>;
    delivery_leads: Array<{ id: number; user_id: number; name: string; email: string; role?: string; is_head: boolean }>;
  }>({
    queryKey: ["client-team", clientIdNum],
    queryFn: async () => {
      if (clientIdNum === null) return { tacs: [], delivery_leads: [] };
      const res = await api.get(`/api/clients/${clientIdNum}/team`);
      return res.data;
    },
    enabled: clientIdNum !== null,
    staleTime: 30_000,
  });
  const primaryTac = clientTeam?.tacs.find(t => t.is_primary);
  const headDl = clientTeam?.delivery_leads.find(d => d.is_head);

  // Hiring manager autocomplete — fetch Contacts klienta (2026-05-11).
  // Key relationships first (gwiazdka), potem alfabetycznie.
  const { data: clientContacts = [] } = useQuery<Array<{
    id: number;
    name: string;
    position: string | null;
    is_decision_maker: boolean;
    is_key_relationship: boolean;
    relationship_strength: string | null;
  }>>({
    queryKey: ["client-contacts-for-hiring-manager", clientIdNum],
    queryFn: async () => {
      if (clientIdNum === null) return [];
      const res = await api.get(`/api/clients/${clientIdNum}/contacts`);
      return res.data;
    },
    enabled: clientIdNum !== null,
    staleTime: 30_000,
  });
  const sortedContactsForHM = [...clientContacts].sort((a, b) => {
    if (a.is_key_relationship !== b.is_key_relationship)
      return a.is_key_relationship ? -1 : 1;
    if (a.is_decision_maker !== b.is_decision_maker)
      return a.is_decision_maker ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  // Auto-fill — tylko gdy pole jest puste (użytkownik nie nadpisał).
  useEffect(() => {
    if (!clientTeam) return;
    if (!form.tac_id && primaryTac) {
      onChange("tac_id", String(primaryTac.user_id));
    }
    if (!form.delivery_lead_id && headDl) {
      onChange("delivery_lead_id", String(headDl.user_id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientTeam?.tacs.length, clientTeam?.delivery_leads.length, clientIdNum]);

  const tacAssignableUsers = users.filter((u: any) =>
    ["tac", "delivery_lead", "admin", "head_of_recruitment"].includes(u.role ?? "")
  );
  const dlAssignableUsers = users.filter((u: any) =>
    ["delivery_lead", "admin", "head_of_recruitment"].includes(u.role ?? "")
  );
  return (
    <>
      <FieldGroup label="Tytuł stanowiska" required>
        <Input value={form.title} onChange={e => onChange("title", e.target.value)} placeholder="Senior Java Developer" />
      </FieldGroup>
      <FieldGroup label="Klient">
        <Select value={form.client_id} onChange={e => onChange("client_id", e.target.value)}>
          <option value="">— wybierz klienta —</option>
          {clients.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </FieldGroup>
      <FieldGroup label="Program / Train (opcjonalne)">
        <Input
          list="job-train-names-autocomplete"
          value={form.train_name}
          onChange={e => onChange("train_name", e.target.value)}
          placeholder="np. ART Payments, CIB Mortgages, TRAIN-X"
        />
        <datalist id="job-train-names-autocomplete">
          {trainNameSuggestions.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <p className="text-[11px] text-muted-foreground mt-1">
          Programme / Agile Release Train. Pomaga Champion Profile znaleźć
          podobne historyczne role z tego samego programu. Zostaw puste,
          a AI spróbuje wyekstrahować z opisu.
        </p>
      </FieldGroup>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Typ rekrutacji">
          <Select value={form.recruitment_type} onChange={e => onChange("recruitment_type", e.target.value)}>
            <option value="body_leasing">Body Leasing</option>
            <option value="sales_project">Sprzedaż</option>
            <option value="tender">Przetarg</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Status">
          <Select value={form.status} onChange={e => onChange("status", e.target.value)}>
            <option value="draft">Draft</option>
            <option value="published">Opublikowana</option>
            <option value="closed">Zamknięta</option>
          </Select>
        </FieldGroup>
      </div>
      <FieldGroup label="Opis">
        <Textarea value={form.description} onChange={e => onChange("description", e.target.value)} rows={3} placeholder="Opis stanowiska..." />
      </FieldGroup>
      <FieldGroup label="Wymagania">
        <Textarea value={form.requirements} onChange={e => onChange("requirements", e.target.value)} rows={3} placeholder="Wymagania techniczne..." />
      </FieldGroup>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Lokalizacja">
          <Input value={form.location} onChange={e => onChange("location", e.target.value)} placeholder="Warszawa / Remote" />
        </FieldGroup>
        <FieldGroup label="Remote policy">
          <Select value={form.remote_policy} onChange={e => onChange("remote_policy", e.target.value)}>
            <option value="on_site">On-site</option>
            <option value="hybrid">Hybrid</option>
            <option value="remote">Remote</option>
            <option value="flexible">Elastyczny</option>
          </Select>
        </FieldGroup>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Widełki min (PLN)">
          <Input type="number" value={form.salary_min} onChange={e => onChange("salary_min", e.target.value)} placeholder="15000" />
        </FieldGroup>
        <FieldGroup label="Widełki max (PLN)">
          <Input type="number" value={form.salary_max} onChange={e => onChange("salary_max", e.target.value)} placeholder="25000" />
        </FieldGroup>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Priorytet">
          <Select value={form.priority} onChange={e => onChange("priority", e.target.value)}>
            <option value="low">Niski</option>
            <option value="medium">Średni</option>
            <option value="high">Wysoki</option>
            <option value="critical">Krytyczny</option>
          </Select>
        </FieldGroup>
        <FieldGroup label="Deadline">
          <Input type="date" value={form.deadline} onChange={e => onChange("deadline", e.target.value)} />
        </FieldGroup>
      </div>
      <FieldGroup label="Rekruter (primary owner)">
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
      {clientIdNum !== null && clientTeam && !primaryTac && (
        <div className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-900/20 dark:text-amber-300 rounded-lg px-3 py-2">
          ⚠️ Klient nie ma przypisanego primary TAC. Projekt zostanie zapisany bez TAC — head_of_recruitment może uzupełnić w zakładce „Opiekunowie" klienta.
        </div>
      )}
      <FieldGroup label="TAC (opiekun klienta)">
        <Select value={form.tac_id} onChange={e => onChange("tac_id", e.target.value)}>
          <option value="">— brak TAC —</option>
          {tacAssignableUsers.map((u: any) => (
            <option key={u.id} value={u.id}>
              {u.name || u.full_name || u.email}
              {u.role ? ` (${u.role})` : ""}
            </option>
          ))}
        </Select>
        {form.tac_id && primaryTac && Number(form.tac_id) === primaryTac.user_id && (
          <p className="text-[11px] text-emerald-600 mt-1">
            ✓ Domyślny TAC klienta
          </p>
        )}
        {form.tac_id && primaryTac && Number(form.tac_id) !== primaryTac.user_id && (
          <p className="text-[11px] text-primary mt-1">
            Nadpisane (primary TAC klienta: {primaryTac.name})
          </p>
        )}
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
      <FieldGroup label="Hiring manager (osoba zatrudniająca u klienta)">
        <Select
          value={form.hiring_manager_contact_id}
          onChange={e => onChange("hiring_manager_contact_id", e.target.value)}
          disabled={!form.client_id}
        >
          <option value="">— brak hiring managera —</option>
          {sortedContactsForHM.map((c) => (
            <option key={c.id} value={c.id}>
              {c.is_key_relationship ? "★ " : ""}
              {c.name}
              {c.position ? ` · ${c.position}` : ""}
              {c.is_decision_maker ? " (decydent)" : ""}
              {c.relationship_strength ? ` · ${c.relationship_strength}` : ""}
            </option>
          ))}
        </Select>
        {!form.client_id && (
          <p className="text-[11px] text-muted-foreground mt-1">
            Najpierw wybierz klienta, żeby zobaczyć listę kontaktów.
          </p>
        )}
        {form.client_id && sortedContactsForHM.length === 0 && (
          <p className="text-[11px] text-amber-700 mt-1">
            Brak kontaktów u tego klienta. Dodaj kontakt w zakładce Zespół klienta.
          </p>
        )}
      </FieldGroup>
      <FieldGroup label="Szablon procesu rekrutacyjnego">
        <Select
          value={form.pipeline_template_id}
          onChange={e => onChange("pipeline_template_id", e.target.value)}
        >
          <option value="">— domyślny szablon —</option>
          {templates
            .filter(t => !t.archived)
            .map(t => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.is_default ? " (domyślny)" : ""}
              </option>
            ))}
        </Select>
        <p className="text-[11px] text-muted-foreground mt-1">
          Definiuje etapy kanbana i powody odrzucenia. Zmień w{" "}
          <a href="/settings/pipeline-templates" target="_blank" className="text-primary underline">
            Ustawieniach →
          </a>
        </p>
      </FieldGroup>
      <CompetenceCategoryPicker
        value={ccId}
        onChange={(v) => onChange("competence_category_id", v !== null ? String(v) : "")}
        jobTitle={form.title}
        description={form.description}
        requirements={form.requirements}
      />
      {autoCollaboratorIds !== undefined && onAutoCollaboratorsChange && (
        <AutoAssignedCollaborators
          competenceCategoryId={ccId}
          selectedUserIds={autoCollaboratorIds}
          onChange={onAutoCollaboratorsChange}
        />
      )}
    </>
  );
}

export function AddJobModal({
  onClose,
  onSuccess,
  fromJobId = null,
}: {
  onClose: () => void;
  onSuccess: (msg: string) => void;
  /**
   * "Skopiuj jako template" handoff — gdy ustawione, modal startuje
   * z prefilled polami z source jobu. Backend dokonuje finalnego
   * zoznaczenia w POST /api/jobs (przekazujemy `from_job_id`), więc
   * tutaj prefill jest tylko visualnym preview formularza.
   */
  fromJobId?: number | null;
}) {
  const router = useRouter();
  const [form, setForm] = useState<JobFormData>(EMPTY_JOB);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState("");
  // auto_cc collaborators: undefined = not initialised (all auto-add), otherwise
  // the explicit set user chose (may exclude some backend would add).
  const [autoCollaboratorIds, setAutoCollaboratorIds] = useState<number[] | null>(null);

  // Prefill form from source job when fromJobId is provided.
  useEffect(() => {
    if (fromJobId == null) return;
    let cancelled = false;
    api
      .get(`/api/jobs/${fromJobId}`)
      .then((r) => {
        if (cancelled) return;
        const src = r.data;
        const prefilled = jobToForm(src);
        // User świadomie wybiera klienta i nadaje nową nazwę roli — nie
        // kopiujemy `client_id` ani `title` (zmuszamy DL do potwierdzenia).
        prefilled.client_id = "";
        prefilled.title = "";
        setForm(prefilled);
      })
      .catch(() => {
        // Cichy fallback — DL może wypełnić ręcznie.
      });
    return () => {
      cancelled = true;
    };
  }, [fromJobId]);

  // Banner z siostrzanymi requestami — pokazujemy gdy klient wybrany
  // i tytuł >=5 znaków. Debounced przez staleTime + enabled gate.
  const debouncedTitle = useDebouncedValue(form.title, 500);
  const clientIdNum = form.client_id ? Number(form.client_id) : null;
  const previewQuery = useQuery<RequestHistoryResponse>({
    queryKey: [
      "request-history-preview",
      clientIdNum,
      debouncedTitle,
      form.train_name,
    ],
    queryFn: async () => {
      const r = await requestHistoryApi.preview({
        title: debouncedTitle,
        client_id: clientIdNum,
        train_name: form.train_name || null,
        raw_description: form.description || null,
        top_k: 5,
        cross_client: false,
        include_open: true,
      });
      return r.data;
    },
    enabled:
      fromJobId == null && // banner zbędny gdy już mamy template — DL widział historię
      clientIdNum !== null &&
      debouncedTitle.length >= 5,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const previewTotal =
    (previewQuery.data?.closed.length ?? 0) +
    (previewQuery.data?.in_progress.length ?? 0);

  const { data: clientsData } = useQuery({
    queryKey: ["clients-list-qa"],
    queryFn: () => api.get("/api/clients", { params: { page_size: 200 } }).then(r => r.data),
  });
  const { data: usersData } = useQuery({
    queryKey: ["users-list-qa"],
    queryFn: () => api.get("/api/users").then(r => r.data),
  });
  const { data: templatesData } = useQuery({
    queryKey: ["pipeline-templates-list"],
    queryFn: () => pipelineTemplatesApi.list(false).then(r => r.data),
  });
  const clients = clientsData?.items ?? [];
  const users = usersData ?? [];
  const templates = templatesData ?? [];

  const onChange = (k: keyof JobFormData, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleGenerateAI = async () => {
    if (!form.title.trim()) { setAiError("Wpisz najpierw tytuł stanowiska"); return; }
    setAiGenerating(true);
    setAiError("");
    try {
      const clientName = clients.find((c: any) => String(c.id) === form.client_id)?.name;
      const skills = form.requirements
        ? form.requirements.split(/[\n,]/).map(s => s.trim().replace(/^[-•*]/, "").trim()).filter(Boolean)
        : [];
      const { data } = await aiWriterApi.generateJob({
        title: form.title,
        client: clientName,
        seniority: form.priority === "urgent" ? "lead" : ["low"].includes(form.priority) ? "junior" : "senior",
        skills,
        description_hint: form.description || undefined,
      });
      setForm(f => ({
        ...f,
        description: data.description + (data.nice_to_have ? `\n\n**Mile widziane:**\n${data.nice_to_have}` : ""),
        requirements: data.requirements,
        salary_min: f.salary_min || (data.salary_range_suggestion?.match(/(\d[\d\s]+)/)?.[1]?.replace(/\s/g, "") || ""),
      }));
    } catch (e: any) {
      setAiError(e?.response?.data?.detail || "Błąd generowania AI");
    } finally {
      setAiGenerating(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title) { setError("Tytuł jest wymagany"); return; }
    setSaving(true); setError("");
    try {
      const { data: newJob } = await api.post<{ id: number; competence_category_id?: number }>("/api/jobs", {
        title: form.title,
        client_id: form.client_id ? Number(form.client_id) : undefined,
        recruitment_type: form.recruitment_type,
        status: form.status,
        description: form.description || undefined,
        requirements: form.requirements || undefined,
        location: form.location || undefined,
        remote_policy: form.remote_policy,
        salary_min: form.salary_min ? Number(form.salary_min) : undefined,
        salary_max: form.salary_max ? Number(form.salary_max) : undefined,
        priority: form.priority,
        deadline: form.deadline || undefined,
        recruiter_id: form.recruiter_id ? Number(form.recruiter_id) : undefined,
        tac_id: form.tac_id ? Number(form.tac_id) : undefined,
        delivery_lead_id: form.delivery_lead_id ? Number(form.delivery_lead_id) : undefined,
        hiring_manager_contact_id: form.hiring_manager_contact_id
          ? Number(form.hiring_manager_contact_id)
          : undefined,
        pipeline_template_id: form.pipeline_template_id ? Number(form.pipeline_template_id) : undefined,
        competence_category_id: form.competence_category_id
          ? Number(form.competence_category_id)
          : undefined,
        auto_suggest_cc: !form.competence_category_id,
        // Phase 15 / Phase D: opcjonalne, auto-extract z opisu po stronie
        // backendu gdy puste (regex w `train_name_extractor`).
        train_name: form.train_name.trim() || undefined,
        // "Skopiuj jako template" handoff — backend kopiuje brakujące pola
        // i pinned interview questions (idempotent, same-client champion only).
        from_job_id: fromJobId ?? undefined,
        copy_questions: fromJobId != null ? true : undefined,
      });
      // Reconcile auto_cc collaborators: if user de-selected any after backend
      // already auto-added, we DELETE them here. Hits the same endpoint the
      // JobOwnershipPanel uses post-creation (idempotent soft-delete).
      if (newJob?.id && autoCollaboratorIds !== null) {
        try {
          const { data: jobDetail } = await api.get<{ collaborators?: Array<{ id: number }> }>(
            `/api/jobs/${newJob.id}`,
          );
          const current = (jobDetail.collaborators ?? []).map((c) => c.id);
          const toRemove = current.filter((uid) => !autoCollaboratorIds.includes(uid));
          await Promise.all(
            toRemove.map((uid) =>
              api.delete(`/api/jobs/${newJob.id}/collaborators/${uid}`),
            ),
          );
        } catch (e) {
          // Non-fatal: user can still edit collaborators on the job page.
        }
      }
      onSuccess("Projekt utworzony — AI szuka kandydatów…");
      onClose();
      // Phase 13: redirect to the job detail page with AI proposals section
      // highlighted so the recruiter sees the snapshot load progress.
      if (newJob?.id) {
        router.push(`/jobs/${newJob.id}?highlight=ai-proposals`);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally { setSaving(false); }
  };

  return (
    <Modal
      title={fromJobId != null ? "Skopiuj jako template" : "Dodaj ofertę pracy"}
      onClose={onClose}
      wide
    >
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        {fromJobId != null && (
          <div className="rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
            Tworzysz kopię z roli #{fromJobId}. Pola opisu, wymagań, skills,
            seniority i train zostały prefillowane. Wybierz klienta i nadaj
            tytuł — Champion Profile zostanie skopiowany tylko gdy zachowasz
            tego samego klienta.
          </div>
        )}
        {/* AI Generate button */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleGenerateAI}
            disabled={aiGenerating || !form.title.trim()}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-gradient-to-r from-blue-600 to-violet-600 text-white rounded-lg hover:from-blue-700 hover:to-violet-700 disabled:opacity-50 transition-all font-medium shadow-sm"
          >
            {aiGenerating ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Generuję AI...</>
            ) : (
              <><Sparkles className="w-4 h-4" /> ✨ Generuj AI</>
            )}
          </button>
          <span className="text-xs text-muted-foreground">Wypełni opis i wymagania automatycznie</span>
        </div>
        {aiError && <div className="text-xs text-destructive bg-destructive/10 rounded-lg px-3 py-2">{aiError}</div>}
        {previewTotal > 0 && previewQuery.data && (
          <div
            className="rounded-lg bg-primary/10 dark:bg-primary/10 border border-primary/20 dark:border-primary/30 px-3 py-2 text-xs"
            data-testid="request-history-banner"
          >
            <div className="flex items-center gap-1.5 text-primary dark:text-primary font-medium">
              <Sparkles className="inline w-4 h-4" />
              U tego klienta było już {previewTotal}{" "}
              {previewTotal === 1 ? "podobny request" : "podobnych requestów"}
              {" "}({previewQuery.data.in_progress.length} w toku,{" "}
              {previewQuery.data.closed.length} zamkniętych)
            </div>
            <ul className="mt-1.5 space-y-0.5 pl-5 list-disc text-primary dark:text-primary">
              {[...previewQuery.data.in_progress, ...previewQuery.data.closed]
                .slice(0, 3)
                .map((r) => (
                  <li key={r.job_id}>
                    <a
                      href={`/jobs/${r.job_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="underline hover:text-primary/80"
                    >
                      {r.title}
                    </a>{" "}
                    <span className="text-primary dark:text-primary">
                      ({r.is_in_progress ? "w toku" : r.outcome ?? "zamknięty"}
                      {r.tth_days != null ? `, ${r.tth_days}d` : ""})
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}
        <JobFormFields
          form={form}
          onChange={onChange}
          clients={clients}
          users={users}
          templates={templates}
          autoCollaboratorIds={autoCollaboratorIds ?? []}
          onAutoCollaboratorsChange={setAutoCollaboratorIds}
        />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Dodaj ofertę" />
        </div>
      </form>
    </Modal>
  );
}

export function EditJobModal({ job, onClose, onSuccess }: { job: any; onClose: () => void; onSuccess: (msg: string) => void }) {
  const [form, setForm] = useState<JobFormData>(() => jobToForm(job));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { data: clientsData } = useQuery({
    queryKey: ["clients-list-qa"],
    queryFn: () => api.get("/api/clients", { params: { page_size: 200 } }).then(r => r.data),
  });
  const { data: usersData } = useQuery({
    queryKey: ["users-list-qa"],
    queryFn: () => api.get("/api/users").then(r => r.data),
  });
  const { data: templatesData } = useQuery({
    queryKey: ["pipeline-templates-list"],
    queryFn: () => pipelineTemplatesApi.list(false).then(r => r.data),
  });
  const clients = clientsData?.items ?? [];
  const users = usersData ?? [];
  const templates = templatesData ?? [];

  const onChange = (k: keyof JobFormData, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title) { setError("Tytuł jest wymagany"); return; }
    setSaving(true); setError("");
    try {
      await api.patch(`/api/jobs/${job.id}`, {
        title: form.title,
        client_id: form.client_id ? Number(form.client_id) : undefined,
        recruitment_type: form.recruitment_type,
        status: form.status,
        description: form.description || undefined,
        requirements: form.requirements || undefined,
        location: form.location || undefined,
        remote_policy: form.remote_policy,
        salary_min: form.salary_min ? Number(form.salary_min) : undefined,
        salary_max: form.salary_max ? Number(form.salary_max) : undefined,
        priority: form.priority,
        deadline: form.deadline || undefined,
        recruiter_id: form.recruiter_id ? Number(form.recruiter_id) : undefined,
        // Override TAC / DL w PATCH. `undefined` jest pomijane (zachowa DB);
        // jeśli form.tac_id == "" oznacza to, że user jawnie chce "nieprzypisany"
        // i musimy wysłać null — inaczej zostanie stary auto-assign.
        tac_id: form.tac_id ? Number(form.tac_id) : null,
        delivery_lead_id: form.delivery_lead_id ? Number(form.delivery_lead_id) : null,
        hiring_manager_contact_id: form.hiring_manager_contact_id
          ? Number(form.hiring_manager_contact_id)
          : null,
        pipeline_template_id: form.pipeline_template_id ? Number(form.pipeline_template_id) : null,
        competence_category_id: form.competence_category_id
          ? Number(form.competence_category_id)
          : null,
        // Phase 15 / Phase D: pusty string → null (clear); non-empty → value.
        // `undefined` pominąłby pole w PATCH i zachował wartość DB.
        train_name: form.train_name.trim() ? form.train_name.trim() : null,
      });
      onSuccess("Oferta zaktualizowana");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally { setSaving(false); }
  };

  return (
    <Modal title={`Edytuj: ${job.title}`} onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <JobFormFields form={form} onChange={onChange} clients={clients} users={users} templates={templates} />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
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

function ClientFormFields({ form, onChange, onCheckbox }: {
  form: ClientFormData;
  onChange: (k: keyof ClientFormData, v: string) => void;
  onCheckbox: (k: keyof ClientFormData, v: boolean) => void;
}) {
  return (
    <>
      <FieldGroup label="Nazwa firmy" required>
        <Input value={form.name} onChange={e => onChange("name", e.target.value)} placeholder="Acme Sp. z o.o." />
      </FieldGroup>
      <div className="grid grid-cols-2 gap-3">
        <FieldGroup label="Branża">
          <Input value={form.industry} onChange={e => onChange("industry", e.target.value)} placeholder="IT / Finance..." />
        </FieldGroup>
        <FieldGroup label="Status">
          <Select value={form.status} onChange={e => onChange("status", e.target.value)}>
            <option value="prospect">Prospect</option>
            <option value="active">Aktywny</option>
            <option value="inactive">Nieaktywny</option>
          </Select>
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

export function AddClientModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
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
      await api.post("/api/clients", {
        name: form.name,
        industry: form.industry || undefined,
        website: form.website || undefined,
        address: form.address || undefined,
        status: form.status,
        nda_signed: form.nda_signed,
        contract_type: form.contract_type || undefined,
        notes: form.notes || undefined,
      });
      onSuccess("Firma dodana pomyślnie");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Dodaj firmę" onClose={onClose} wide>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
        {error && <ErrorBanner error={error} />}
        <ClientFormFields form={form} onChange={onChange} onCheckbox={onCheckbox} />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Dodaj firmę" />
        </div>
      </form>
    </Modal>
  );
}

// ── Modal: Zaplanuj spotkanie ─────────────────────────────────────────────────

export function AddMeetingModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const defaultStart = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours() + 1)}:00`;
  const defaultEnd = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours() + 2)}:00`;

  const [form, setForm] = useState({ title: "", event_type: "meeting", start_time: defaultStart, end_time: defaultEnd, candidate_id: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { data: candidatesData } = useQuery({
    queryKey: ["candidates-list-qa"],
    queryFn: () => api.get("/api/candidates", { params: { page_size: 200 } }).then(r => r.data),
  });
  const candidates = candidatesData?.items ?? [];
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title || !form.start_time) { setError("Tytuł i czas rozpoczęcia są wymagane"); return; }
    setSaving(true); setError("");
    try {
      await api.post("/api/calendar/events", {
        title: form.title,
        event_type: form.event_type,
        start_time: new Date(form.start_time).toISOString(),
        end_time: form.end_time ? new Date(form.end_time).toISOString() : undefined,
        candidate_id: form.candidate_id ? Number(form.candidate_id) : undefined,
      });
      onSuccess("Spotkanie zaplanowane pomyślnie");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
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
            <option value="call">Rozmowa telefoniczna</option>
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
        <FieldGroup label="Kandydat">
          <Select value={form.candidate_id} onChange={e => set("candidate_id", e.target.value)}>
            <option value="">— opcjonalnie —</option>
            {candidates.map((c: any) => (
              <option key={c.id} value={c.id}>{c.name} {c.lastname}</option>
            ))}
          </Select>
        </FieldGroup>
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="h-10 px-4 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 rounded-lg transition-colors">Anuluj</button>
          <SaveButton saving={saving} label="Zaplanuj" />
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

  // Handle external modal trigger (from keyboard shortcuts)
  useEffect(() => {
    if (externalModal) {
      setModal(externalModal);
      onExternalModalClear?.();
    }
  }, [externalModal, onExternalModalClear]);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
    queryClient.invalidateQueries({ queryKey: ["candidates"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["clients"] });
    queryClient.invalidateQueries({ queryKey: ["contacts"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
  };

  const QUICK_ACTIONS: { label: string; icon: React.ComponentType<{ className?: string }>; modal: ModalType }[] = [
    { label: "Dodaj kandydata", icon: UserPlus, modal: "candidate" },
    { label: "Dodaj ofertę", icon: Briefcase, modal: "job" },
    { label: "Dodaj firmę", icon: Building2, modal: "client" },
    { label: "Zaplanuj spotkanie", icon: CalendarPlus, modal: "meeting" },
  ];

  return (
    <>
      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 bg-primary hover:bg-primary/90 active:scale-95 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150 shadow-sm"
        >
          <Plus className="w-4 h-4" />
          <span className="hidden sm:inline">Dodaj</span>
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-2 w-52 bg-card dark:bg-muted border border-border dark:border-border rounded-xl shadow-lg py-1.5 z-50">
            {QUICK_ACTIONS.map(({ label, icon: Icon, modal: m }) => (
              <button
                key={m}
                onClick={() => { setOpen(false); setModal(m); }}
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
      {modal === "job" && <AddJobModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "client" && <AddClientModal onClose={() => setModal(null)} onSuccess={showToast} />}
      {modal === "meeting" && <AddMeetingModal onClose={() => setModal(null)} onSuccess={showToast} />}

      {/* Toast */}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </>
  );
}
