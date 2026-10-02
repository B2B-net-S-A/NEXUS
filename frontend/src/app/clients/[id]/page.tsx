"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import {
  positiveIntParam,
  useClientTab,
  useForbiddenTabFallback,
  type ClientTab,
} from "@/lib/client-tab";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { useCapability } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  ArrowLeft,
  Building2,
  Globe,
  CheckCircle,
  XCircle,
  BookOpen,
  Users,
  Plus,
  X,
  Star,
  Heart,
  Code,
  HelpCircle,
  Lightbulb,
  Info,
  Crown,
  Pencil,
  DollarSign,
  FolderOpen,
  Trash2,
  AlertOctagon,
  Ellipsis,
} from "lucide-react";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { clientTeamApi, type ClientTeamResponse } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { DeleteButton } from "@/components/ConfirmDialog";
import { EditClientModal } from "@/components/AppShell";
import { RateCardsTab } from "@/components/RateCardsTab";
import { MaterialsTab } from "./MaterialsTab";
import { OwnersTab } from "./OwnersTab";
import { ProfileTab } from "./ProfileTab";
import { ProjectsTab } from "./ProjectsTab";
// NotificationsTab — usunięty po konsolidacji 12→6 tabów (2026-05-11).
// Powiadomienia per-klient zostały zlikwidowane jako tab — globalny bell w
// topbarze (NotificationsDropdown) wystarcza.
import { FrameworkContractsTab } from "@/components/FrameworkContractsTab";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import { ClientMdImportsTab } from "@/components/client-profile/orders/ClientMdImportsTab";
import { AnalyticsTab } from "@/components/AnalyticsTab";
import { KeyRelationshipDialog } from "@/components/KeyRelationshipDialog";
import { ClientPlaybookTab } from "@/components/client-playbook/ClientPlaybookTab";
import { DeleteClientDialog } from "@/components/client-profile/DeleteClientDialog";
import { ClientConflictsSection } from "@/components/client-profile/ClientConflictsSection";
import { ClientHeaderStats } from "@/components/client-profile/SummaryBar";
import {
  canEditClientLegalDocuments,
  canManageClientDelivery,
} from "@/components/client-profile/permissions";
import { TAC_UI_ENABLED } from "@/lib/tac-ui";
import {
  RELATIONSHIP_STRENGTH_COLORS,
  RELATIONSHIP_STRENGTH_LABELS,
} from "@/components/clients/KeyRelationshipsPanel";
import Link from "next/link";
import { useTabsStore } from "@/store/tabs";
import { canViewClientFinance, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";
import { useCanonicalClientRedirect } from "@/hooks/useCanonicalClientRedirect";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ClientKnowledge {
  id: number;
  client_id: number;
  category: KnowledgeCategory;
  content: string;
  added_by: number | null;
  source: string | null;
  created_at: string;
}

type RelationshipStrength = "cold" | "warm" | "strong" | "champion";

interface Contact {
  id: number;
  client_id: number;
  name: string;
  email: string | null;
  phone: string | null;
  position: string | null;
  department: string | null;
  is_decision_maker: boolean;
  notes: string | null;
  last_contacted_at: string | null;
  created_at: string;
  // Key relationship fields (2026-05-11)
  is_key_relationship: boolean;
  relationship_strength: RelationshipStrength | null;
  relationship_notes: string | null;
  key_relationship_owner_id: number | null;
  last_personal_touchpoint_at: string | null;
}

type KnowledgeCategory = "selling_points" | "interview_questions" | "tech_stack" | "culture" | "general";

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_TONES: Record<string, StatusDotTone> = {
  active: "success",
  inactive: "neutral",
  prospect: "neutral",
};

const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  inactive: "Nieaktywny",
  prospect: "Prospekt",
};

const KNOWLEDGE_CATEGORIES: {
  key: KnowledgeCategory;
  label: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
}[] = [
  {
    key: "selling_points",
    label: "Atuty klienta",
    icon: <Star className="w-4 h-4" />,
    color: "text-warning-muted-foreground",
    bg: "bg-warning-muted",
  },
  {
    key: "interview_questions",
    label: "Pytania na rozmowie",
    icon: <HelpCircle className="w-4 h-4" />,
    color: "text-primary",
    bg: "bg-primary/10",
  },
  {
    key: "tech_stack",
    label: "Stack technologiczny",
    icon: <Code className="w-4 h-4" />,
    color: "text-info-muted-foreground",
    bg: "bg-info-muted",
  },
  {
    key: "culture",
    label: "Kultura pracy",
    icon: <Lightbulb className="w-4 h-4" />,
    color: "text-success-muted-foreground",
    bg: "bg-success-muted",
  },
  {
    key: "general",
    label: "Ogólne",
    icon: <Info className="w-4 h-4" />,
    color: "text-muted-foreground",
    bg: "bg-muted",
  },
];

// ── Lazy collapsible ──────────────────────────────────────────────────────────

/**
 * Zwinięty <details> MONTUJE swoje dzieci — przeglądarka je wyłącznie ukrywa.
 * Na domyślnej zakładce "Profil" oznaczało to, że każde otwarcie profilu
 * klienta odpalało zapytania trzech paneli, których nikt nie ogląda (m.in.
 * niecache'owany raport hit-ratio i listowanie dokumentów), konkurując o
 * budżet połączeń przeglądarki z treścią faktycznie rysowaną. Delivery Leadzi
 * i TAC-e otwierają profile bez przerwy, więc to była stała wielokrotność
 * obciążenia w całości wyrzucana do kosza.
 *
 * Natywne <details> zostaje (argument z pierwotnego komentarza — brak stanu
 * Reacta na rozwijanie — jest sensowny); zabramkowane jest wyłącznie
 * MONTOWANIE dziecka. Raz otwarta sekcja zostaje zamontowana także po
 * zwinięciu: ponowne zwijanie nie ma kasować stanu formularzy ani zmuszać do
 * powtórnego pobrania danych.
 *
 * `defaultOpen` (02.10.2026): sekcje, które na makiecie są rozwiniętymi
 * kartami obok treści (informacje, materiały, konflikty, wiedza, cennik),
 * startują otwarte i montują dziecko od razu — tylko dla zakładki, na której
 * stoją. Sekcja bez `defaultOpen` zachowuje leniwe montowanie.
 *
 * Uwaga przy pisaniu testów: zdarzenie `toggle` jest ZAKOLEJKOWANE (spec HTML),
 * więc w jsdom klik w <summary> ustawia `open`, ale handler odpala się dopiero
 * w kolejnym zadaniu — asercja tuż po `fireEvent.click` zobaczy jeszcze pustkę.
 */
function LazyDetails({
  icon,
  title,
  contentClassName = "border-t border-border p-4",
  defaultOpen = false,
  children,
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  contentClassName?: string;
  /** Karta od razu rozwinięta — dziecko montuje się przy pierwszym renderze. */
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(defaultOpen);

  return (
    <details
      className="group min-w-0 rounded-lg border border-border bg-card"
      open={defaultOpen}
      onToggle={(e) => {
        if (e.currentTarget.open) setMounted(true);
      }}
    >
      <summary className="flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-semibold text-foreground hover:bg-accent/30 pointer-coarse:min-h-10">
        {icon}
        {title}
        <span className="ml-auto text-xs font-normal text-muted-foreground group-open:hidden">rozwiń</span>
        <span className="ml-auto hidden text-xs font-normal text-muted-foreground group-open:inline">zwiń</span>
      </summary>
      <div className={contentClassName}>{mounted ? children : null}</div>
    </details>
  );
}

// ── Knowledge Tab ─────────────────────────────────────────────────────────────

function KnowledgeTab({ clientId }: { clientId: number }) {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ category: "general" as KnowledgeCategory, content: "", source: "" });
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  // Dodawanie i usuwanie wiedzy = `ClientAccess.can_edit_knowledge` (admin
  // i Delivery Lead) — innym rolom przycisk kończył się 403 (audyt S11).
  const currentUser = useAuthStore((state) => state.user);
  const canEditKnowledge = canManageClientDelivery(currentUser);

  const knowledgeQuery = useQuery<ClientKnowledge[]>({
    queryKey: ["client-knowledge", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/knowledge`).then((r) => r.data),
  });
  const entries = knowledgeQuery.data ?? [];
  // Awaria ≠ pusta baza wiedzy (audyt S10).
  const knowledgeState = resolveViewState({
    isLoading: knowledgeQuery.isPending,
    isError: knowledgeQuery.isError,
    error: knowledgeQuery.error,
    isEmpty: entries.length === 0,
    isSuccess: knowledgeQuery.isSuccess,
  });

  const addMutation = useMutation({
    mutationFn: (data: object) => api.post(`/api/clients/${clientId}/knowledge`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-knowledge", clientId] });
      setShowAdd(false);
      setForm({ category: "general", content: "", source: "" });
      showSuccess("Wpis dodany pomyślnie");
    },
    onError: () => showError("Błąd podczas dodawania wpisu"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/client-knowledge/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-knowledge", clientId] });
      showSuccess("Wpis usunięty");
    },
    onError: () => showError("Błąd podczas usuwania"),
  });

  const grouped = KNOWLEDGE_CATEGORIES.map((cat) => ({
    ...cat,
    entries: entries.filter((e) => e.category === cat.key),
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Baza wiedzy o kliencie</p>
        {canEditKnowledge ? (
          <Button size="sm" variant="primary" onClick={() => setShowAdd(!showAdd)}>
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            Dodaj wiedzę
          </Button>
        ) : null}
      </div>

      {isBlockingViewState(knowledgeState) ? (
        <QueryStateNotice
          state={knowledgeState as "forbidden" | "not_found" | "error"}
          description={
            knowledgeState === "error"
              ? "Nie udało się wczytać wiedzy o kliencie."
              : undefined
          }
          onRetry={() => void knowledgeQuery.refetch()}
        />
      ) : null}

      {/* Add form */}
      {showAdd && (
        <div className="bg-primary/10 border border-primary/20 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-primary">Nowy wpis</h3>
            <button
              onClick={() => setShowAdd(false)}
              aria-label="Zamknij"
              className="hit-area text-primary hover:text-primary"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="text-xs font-semibold text-muted-foreground block mb-1">Kategoria</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as KnowledgeCategory })}
                className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              >
                {KNOWLEDGE_CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground block mb-1">Źródło</label>
              <input
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
                placeholder="np. rozmowa z HM 2025-11"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Treść *</label>
            <textarea
              required
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={4}
              className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring resize-none"
              placeholder="Wprowadź wiedzę o kliencie..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">
              Anuluj
            </button>
            <button
              onClick={() => addMutation.mutate(form)}
              disabled={!form.content || addMutation.isPending}
              className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              {addMutation.isPending ? "Zapisuję..." : "Zapisz"}
            </button>
          </div>
        </div>
      )}

      {/* Grouped entries */}
      {grouped.map((cat) =>
        cat.entries.length === 0 ? null : (
          <div key={cat.key} className="space-y-2">
            <div className={cn("flex items-center gap-2 px-3 py-1.5 rounded-lg w-fit", cat.bg)}>
              <span className={cat.color}>{cat.icon}</span>
              <span className={cn("text-xs font-bold uppercase tracking-wide", cat.color)}>
                {cat.label}
              </span>
            </div>
            {cat.entries.map((entry) => (
              <div key={entry.id} className="bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-4 group">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-foreground whitespace-pre-line leading-relaxed flex-1">
                    {entry.content}
                  </p>
                  {canEditKnowledge ? (
                    <DeleteButton
                      onConfirm={() => deleteMutation.mutate(entry.id)}
                      className="hit-area pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-within:opacity-100 focus-visible:opacity-100 text-muted-foreground hover:text-destructive transition-all shrink-0"
                    />
                  ) : null}
                </div>
                {entry.source && (
                  <p className="text-xs text-muted-foreground mt-2 italic">Źródło: {entry.source}</p>
                )}
                <p className="text-xs text-muted-foreground mt-1">
                  {new Date(entry.created_at).toLocaleDateString("pl-PL")}
                </p>
              </div>
            ))}
          </div>
        )
      )}

      {knowledgeState === "empty" && !showAdd && (
        <div className="text-center py-12 text-muted-foreground">
          <BookOpen className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak wpisów wiedzy o tym kliencie</p>
          {canEditKnowledge ? (
            <p className="text-xs mt-1">Kliknij „Dodaj wiedzę”, aby zacząć</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ── Contacts Tab ──────────────────────────────────────────────────────────────

type ContactFormData = {
  name: string;
  email: string;
  phone: string;
  position: string;
  department: string;
  is_decision_maker: boolean;
  notes: string;
};

function ContactForm({
  form,
  setForm,
  onSubmit,
  onCancel,
  isLoading,
}: {
  form: ContactFormData;
  setForm: React.Dispatch<React.SetStateAction<ContactFormData>>;
  onSubmit: () => void;
  onCancel: () => void;
  isLoading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Imię i nazwisko *</label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            placeholder="Jan Kowalski"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Stanowisko</label>
          <input
            value={form.position}
            onChange={(e) => setForm({ ...form, position: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            placeholder="IT Procurement Manager"
          />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Email</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Telefon</label>
          <input
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Dział</label>
          <input
            value={form.department}
            onChange={(e) => setForm({ ...form, department: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            placeholder="IT / HR"
          />
        </div>
        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_decision_maker}
              onChange={(e) => setForm({ ...form, is_decision_maker: e.target.checked })}
              className="w-4 h-4 rounded accent-primary"
            />
            <span className="text-sm text-foreground">Decydent</span>
          </label>
        </div>
      </div>
      <div>
        <label className="text-xs font-semibold text-muted-foreground block mb-1">Notatki</label>
        <textarea
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          rows={2}
          className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring resize-none"
        />
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">
          Anuluj
        </button>
        <button
          onClick={onSubmit}
          disabled={!form.name || isLoading}
          className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {isLoading ? "Zapisuję..." : "Zapisz"}
        </button>
      </div>
    </div>
  );
}

function ContactsTab({ clientId }: { clientId: number }) {
  const [showAdd, setShowAdd] = useState(false);
  const [editContact, setEditContact] = useState<Contact | null>(null);
  const [editingKeyRelationship, setEditingKeyRelationship] =
    useState<Contact | null>(null);
  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    position: "",
    department: "",
    is_decision_maker: false,
    notes: "",
  });
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  // POST /api/clients/{id}/contacts → ClientAccess.can_edit_contacts
  // przecięte z zapisem sekcji Delivery. Zostają Admin i Delivery Lead;
  // pozostali czytelnicy nie dostają formularza prowadzącego w 403 (F-19).
  const canCreateContact = useCapability("contact.create");

  const contactsQuery = useQuery<Contact[]>({
    queryKey: ["client-contacts", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/contacts`).then((r) => r.data),
  });
  const rawContacts = contactsQuery.data ?? [];
  // Awaria ≠ „brak kontaktów” (audyt S10).
  const contactsState = resolveViewState({
    isLoading: contactsQuery.isPending,
    isError: contactsQuery.isError,
    error: contactsQuery.error,
    isEmpty: rawContacts.length === 0,
    isSuccess: contactsQuery.isSuccess,
  });
  // Sort: key relationships first (within key — by strength), then alfabetycznie
  const contacts = [...rawContacts].sort((a, b) => {
    if (a.is_key_relationship !== b.is_key_relationship)
      return a.is_key_relationship ? -1 : 1;
    const strengthOrder: Record<string, number> = {
      champion: 0,
      strong: 1,
      warm: 2,
      cold: 3,
    };
    const sa = strengthOrder[a.relationship_strength ?? ""] ?? 99;
    const sb = strengthOrder[b.relationship_strength ?? ""] ?? 99;
    if (sa !== sb) return sa - sb;
    return a.name.localeCompare(b.name);
  });

  const createMutation = useMutation({
    mutationFn: (data: object) => api.post(`/api/contacts`, { ...data, client_id: clientId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-contacts", clientId] });
      setShowAdd(false);
      resetForm();
      showSuccess("Kontakt dodany pomyślnie");
    },
    onError: () => showError("Błąd podczas dodawania kontaktu"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => api.put(`/api/contacts/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-contacts", clientId] });
      setEditContact(null);
      showSuccess("Kontakt zaktualizowany");
    },
    onError: () => showError("Błąd podczas aktualizacji"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/contacts/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-contacts", clientId] });
      showSuccess("Kontakt usunięty");
    },
    onError: () => showError("Błąd podczas usuwania"),
  });

  const resetForm = () =>
    setForm({ name: "", email: "", phone: "", position: "", department: "", is_decision_maker: false, notes: "" });

  const openEdit = (c: Contact) => {
    setEditContact(c);
    setForm({
      name: c.name,
      email: c.email || "",
      phone: c.phone || "",
      position: c.position || "",
      department: c.department || "",
      is_decision_maker: c.is_decision_maker,
      notes: c.notes || "",
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
          Osoby kontaktowe
          {contactsState === "ready" || contactsState === "empty" ? (
            <span className="rounded-full bg-muted px-1.5 text-[11px] font-semibold leading-[18px] text-muted-foreground tabular-nums">
              {contacts.length}
            </span>
          ) : null}
        </h2>
        {canCreateContact && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => { setShowAdd(true); setEditContact(null); }}
          >
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            Dodaj kontakt
          </Button>
        )}
      </div>

      {showAdd && !editContact && (
        <div className="bg-primary/10 border border-primary/20 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-primary">Nowy kontakt</h3>
            <button
              onClick={() => setShowAdd(false)}
              aria-label="Zamknij"
              className="hit-area text-primary hover:text-primary"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <ContactForm
            form={form}
            setForm={setForm}
            onSubmit={() => createMutation.mutate(form)}
            onCancel={() => setShowAdd(false)}
            isLoading={createMutation.isPending}
          />
        </div>
      )}

      {/* Contacts list */}
      {isBlockingViewState(contactsState) ? (
        <QueryStateNotice
          state={contactsState as "forbidden" | "not_found" | "error"}
          description={
            contactsState === "error"
              ? "Nie udało się wczytać kontaktów klienta."
              : undefined
          }
          onRetry={() => void contactsQuery.refetch()}
        />
      ) : contactsState === "loading" ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Ładowanie kontaktów…
        </p>
      ) : contacts.length === 0 && !showAdd ? (
        <div className="text-center py-12 text-muted-foreground">
          <Users className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak kontaktów dla tego klienta</p>
        </div>
      ) : contacts.length === 0 ? null : (
        <Table density="compact" className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead className={CALM_HEAD}>Osoba</TableHead>
              <TableHead className={CALM_HEAD}>E-mail</TableHead>
              <TableHead className={CALM_HEAD}>Telefon</TableHead>
              <TableHead className={CALM_HEAD}>Siła relacji</TableHead>
              <TableHead className={CALM_HEAD}>Ostatni kontakt</TableHead>
              {canCreateContact ? (
                <TableHead className={cn(CALM_HEAD, "text-right")}>Akcje</TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {contacts.map((contact) => {
              if (editContact?.id === contact.id) {
                return (
                  <TableRow key={contact.id}>
                    <TableCell colSpan={canCreateContact ? 6 : 5} className="p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold text-foreground">Edytuj kontakt</h3>
                        <button
                          onClick={() => setEditContact(null)}
                          aria-label="Zamknij"
                          className="hit-area text-muted-foreground hover:text-foreground"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                      <ContactForm
                        form={form}
                        setForm={setForm}
                        onSubmit={() => updateMutation.mutate({ id: contact.id, data: form })}
                        onCancel={() => setEditContact(null)}
                        isLoading={updateMutation.isPending}
                      />
                    </TableCell>
                  </TableRow>
                );
              }
              const lastContact =
                contact.last_personal_touchpoint_at ?? contact.last_contacted_at;
              const relationshipNote =
                contact.is_key_relationship && contact.relationship_notes
                  ? contact.relationship_notes
                  : null;
              const hasNotes = Boolean(contact.notes || relationshipNote);
              return (
                <Fragment key={contact.id}>
                  <TableRow className={cn("h-[54px]", hasNotes && "border-b-0")}>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted">
                          <span className="text-[10.5px] font-semibold text-muted-foreground">
                            {contact.name.charAt(0).toUpperCase()}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                            {contact.is_key_relationship && (
                              <Star
                                className="h-3.5 w-3.5 shrink-0 fill-warning text-warning"
                                aria-hidden="true"
                              />
                            )}
                            <span className="font-semibold text-foreground">{contact.name}</span>
                            {contact.is_key_relationship && (
                              <Badge size="sm" variant="soft">
                                Kluczowa relacja
                              </Badge>
                            )}
                            {contact.is_decision_maker && (
                              <Badge size="sm" variant="warning">
                                <Crown className="h-2.5 w-2.5" aria-hidden="true" />
                                Decydent
                              </Badge>
                            )}
                          </div>
                          {contact.position || contact.department ? (
                            <span className={CALM_SUBLINE}>
                              {[contact.position, contact.department]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {contact.email ? (
                        <a
                          href={`mailto:${contact.email}`}
                          className="break-all font-medium text-primary hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-10 pointer-coarse:items-center"
                        >
                          {contact.email}
                        </a>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {contact.phone ? (
                        <a
                          href={`tel:${contact.phone}`}
                          className="hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-10 pointer-coarse:items-center"
                        >
                          {contact.phone}
                        </a>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {contact.relationship_strength ? (
                        <span
                          className={cn(
                            "inline-flex whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium",
                            RELATIONSHIP_STRENGTH_COLORS[
                              contact.relationship_strength
                            ] ?? "bg-muted text-muted-foreground",
                          )}
                        >
                          {/* Etykiety jak w „Kluczowych relacjach” zamiast
                              surowego „warm”/„champion” (audyt N9). */}
                          {RELATIONSHIP_STRENGTH_LABELS[
                            contact.relationship_strength
                          ] ?? contact.relationship_strength}
                        </span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {lastContact ? (
                        formatIsoDatePl(lastContact)
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </TableCell>
                    {/* Edycja i usunięcie = `ClientAccess.can_edit_contacts`
                        — ta sama bramka co „Dodaj kontakt” (audyt S11). */}
                    {canCreateContact ? (
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditingKeyRelationship(contact)}
                            aria-label="Edytuj relację"
                            title="Edytuj relację (klucz, siła, notatki)"
                          >
                            <Heart
                              className={cn(
                                "h-3.5 w-3.5",
                                contact.is_key_relationship && "fill-primary/30 text-primary",
                              )}
                              aria-hidden="true"
                            />
                            Relacja
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEdit(contact)}
                            aria-label="Edytuj kontakt"
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                            Edytuj
                          </Button>
                          <DeleteButton
                            onConfirm={() => deleteMutation.mutate(contact.id)}
                            iconOnly={false}
                            label="Usuń"
                            className={buttonVariants({ variant: "quiet", size: "sm" })}
                          />
                        </div>
                      </TableCell>
                    ) : null}
                  </TableRow>
                  {hasNotes ? (
                    <TableRow className="h-auto">
                      <TableCell
                        colSpan={canCreateContact ? 6 : 5}
                        className="pb-2.5 pl-[50px] pt-0 text-xs text-muted-foreground"
                      >
                        {contact.notes ? <p>{contact.notes}</p> : null}
                        {relationshipNote ? (
                          <p className="mt-0.5 border-l-2 border-primary/30 pl-2 italic">
                            {relationshipNote}
                          </p>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}

      {editingKeyRelationship && (
        <KeyRelationshipDialog
          contact={{
            id: editingKeyRelationship.id,
            name: editingKeyRelationship.name,
            client_id: editingKeyRelationship.client_id,
            is_key_relationship: editingKeyRelationship.is_key_relationship,
            relationship_strength: editingKeyRelationship.relationship_strength,
            relationship_notes: editingKeyRelationship.relationship_notes,
            last_personal_touchpoint_at:
              editingKeyRelationship.last_personal_touchpoint_at,
          }}
          onClose={() => setEditingKeyRelationship(null)}
        />
      )}
    </div>
  );
}

// Projects Tab — wyodrębniony do ./ProjectsTab.tsx (podział aktywne/zamknięte +
// wyszukiwarka). Sibling-tab pattern jak ProfileTab/MaterialsTab/OwnersTab.

// Kontrakty Tab — usunięty w refaktorze DL portal Order:Contract M:N → 1:N
// (2026-05-11). Wszystkie kontrakty kandydackie są teraz wyświetlane w tabie
// "Zamówienia & Kontrakty" (OrdersAndContractsTab) jako karta per Contract
// z historią Orderów. Globalna lista `/contracts` zostaje dla admin view.

// ── Main Page ─────────────────────────────────────────────────────────────────

// Konsolidacja UX 2026-05-11: 12 tabów → 6. Pozostałe (Informacje, Materiały,
// Cennik, Kontakty, Wiedza) wbudowane jako collapsibles w odpowiednich tabach.
// Powiadomienia per-klient skasowane (globalny bell w topbarze wystarcza).

export default function ClientDetailPage() {
  const { id } = useParams();
  const user = useAuthStore((state) => state.user);
  // Materiały sprzedażowe klienta: ta sama bramka co wiedza o kliencie
  // („Klienci: dodawanie i edycja”) — bez niej przyciski kończą się 403.
  const canEditDelivery = canManageClientDelivery(user);
  // Umowy ramowe, cennik i warunki umowy niosą stawki, więc widzi je ten, kto
  // widzi kwoty TEGO klienta („Stawki i kwoty: podgląd”; Delivery Lead —
  // u klientów z przypisania). Serwer odmawia tak samo.
  const canViewDeliveryLegal = canViewClientFinance(user, Number(id));
  // Zapis warunków kontraktowych to dokumenty prawne klienta, nie edycja
  // klienta: „Kontrakty i zamówienia” + podgląd kwot (lustro backendu).
  const canEditDeliveryLegal = canEditClientLegalDocuments(user, Number(id));
  // `?tab=` NIE jest ozdobnikiem — trzy źródła powiadomień linkują wprost do
  // zakładki, w której jest sprawa do załatwienia: skaner alertów Delivery
  // Leada (`dl_alerts_scanner.py`), skaner wygasania zamówień
  // (`dl_portal_expiry_scanner.py`) i pipeline (`pipeline.py`). Wszystkie
  // emitują `/clients/{id}?tab=zamowienia`, a strona czytała wyłącznie stan
  // początkowy "profil", więc kliknięcie powiadomienia lądowało na Profilu
  // i kazało odbiorcy szukać samodzielnie — czyli link obiecywał coś,
  // czego nie robił.
  const searchParams = useSearchParams();
  const router = useRouter();
  // Kliknięcie zakładki zapisuje ją w adresie (replace, bez nowego wpisu
  // w historii) — F5 odtwarza zakładkę, a kolejny link z powiadomienia do
  // `?tab=zamowienia` zmienia wartość parametru i naprawdę przełącza widok.
  const writeTabToUrl = useCallback(
    (tab: ClientTab) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set("tab", tab);
      router.replace(`/clients/${id}?${next.toString()}`, { scroll: false });
    },
    [router, id, searchParams],
  );
  const [activeTab, setActiveTab, selectTab] = useClientTab(
    searchParams.get("tab"),
    writeTabToUrl,
  );
  const orderMailDocParam = Number(searchParams.get("orderMailDoc"));
  const orderMailDocId =
    Number.isInteger(orderMailDocParam) && orderMailDocParam > 0
      ? orderMailDocParam
      : null;
  // Dokument z maila obsłużony albo porzucony — parametr znika z adresu, żeby
  // odświeżenie strony nie otwierało okna zamówienia drugi raz.
  const clearOrderMailDoc = useCallback(() => {
    router.replace(`/clients/${id}?tab=zamowienia`, { scroll: false });
  }, [router, id]);
  // Deep linki z panelu „Moi klienci": konkretne zamówienie (`?order=`),
  // zamówienie MD/kosztowe (`?group=`) albo umowa ramowa (`?framework=`).
  // Zakładka czyta WARTOŚĆ parametru (miękka nawigacja nie odmontowuje
  // strony), a po obsłużeniu parametr znika z adresu — F5 nie otwiera
  // okna uzupełniania drugi raz.
  // „Otwórz import →" z historii zamówienia: `?tab=importy-md&import={id}`.
  const selectedImportId = positiveIntParam(searchParams.get("import"));
  const selectImport = useCallback(
    (importId: number | null) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set("tab", "importy-md");
      if (importId == null) next.delete("import");
      else next.set("import", String(importId));
      router.replace(`/clients/${id}?${next.toString()}`, { scroll: false });
    },
    [router, id, searchParams],
  );
  const focusOrderId = positiveIntParam(searchParams.get("order"));
  const focusGroupId = positiveIntParam(searchParams.get("group"));
  const focusFrameworkId = positiveIntParam(searchParams.get("framework"));
  // `?contract=` — panel kontraktora bez zamówienia w zakładce „Zamówienia”
  // (wersja B). Zakładka sama pisze `?order=`/`?group=`/`?contract=` przy
  // wyborze wiersza, więc otwarty panel przeżywa odświeżenie strony.
  const focusContractId = positiveIntParam(searchParams.get("contract"));
  const clearFocusParams = useCallback(() => {
    const next = new URLSearchParams(searchParams.toString());
    next.delete("order");
    next.delete("group");
    next.delete("contract");
    next.delete("framework");
    router.replace(`/clients/${id}?${next.toString()}`, { scroll: false });
  }, [router, id, searchParams]);
  const [showEdit, setShowEdit] = useState(false);
  const openTab = useTabsStore((s) => s.openTab);
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  // PATCH /api/clients/{id} wymaga uprawnienia „Klienci: dodawanie i edycja”.
  // Bez bramki konto bez niego widziało "Edytuj" i dostawało 403 dopiero na
  // zapisie (czytało się jak "zapis nie działa").
  const canUpdateClient = useCapability("client.update");
  // Imienne uprawnienie (0307) — nie wynika z roli. W trybie podglądu jako
  // inny użytkownik backend i tak odmówi, więc przycisku też nie pokazujemy.
  const realUser = useAuthStore((state) => state.realUser);
  const canDeleteClient = !!user?.can_delete_clients && !realUser;
  const [showDelete, setShowDelete] = useState(false);
  const closeTab = useTabsStore((s) => s.closeTab);

  // Zakładka „Umowy” i jej treść mają JEDNĄ bramkę (`canViewDeliveryLegal`).
  // Do 24.09.2026 zakładkę chowano tylko TCM-owi, a treść pokazywano rolom
  // admin/DL/Finanse — rola z ręcznie nadaną sekcją Delivery widziała pustą
  // zakładkę (audyt N7).
  // Czeka na hydrację użytkownika — inaczej pełne wczytanie linku
  // `?tab=umowy-ramowe` zawsze lądowało na Profilu (audyt 24.09.2026).
  const authHydrated = useAuthStore((state) => state.hydrated);
  useForbiddenTabFallback(
    activeTab,
    setActiveTab,
    "umowy-ramowe",
    canViewDeliveryLegal,
    authHydrated,
  );

  const {
    data: client,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["client", id],
    queryFn: () => api.get(`/api/clients/${id}`).then((r) => r.data),
  });

  useCanonicalClientRedirect(id, client?.id);

  // Główny Delivery Lead w nagłówku — ten sam klucz co zakładka „Delivery
  // Lead” (`OwnersTab`), więc cache jest wspólny. Awaria = brak chipa,
  // nie komunikat: nagłówek to skrót, pełna informacja jest w zakładce.
  const teamQuery = useQuery<ClientTeamResponse>({
    queryKey: ["client-team", Number(id)],
    queryFn: () => clientTeamApi.get(Number(id)).then((r) => r.data),
    enabled: Number.isFinite(Number(id)),
  });
  const headDeliveryLead = (() => {
    const leads = teamQuery.data?.delivery_leads ?? [];
    const head = leads.find((lead) => lead.is_head) ?? leads[0];
    if (!head) return null;
    return leads.length > 1 ? `${head.name} +${leads.length - 1}` : head.name;
  })();

  // Pasek 8 zakładek jest na telefonie szerszy niż ekran. Wejście z
  // powiadomienia (`?tab=zamowienia`) albo klik w częściowo widoczną zakładkę
  // przewija go do aktywnej — inaczej wybrana zakładka bywa poza kadrem.
  // Przewijamy WYŁĄCZNIE pasek w poziomie (nie `scrollIntoView`), żeby zmiana
  // zakładki z wnętrza treści nie podrywała całej strony do góry.
  const activeTabRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const tab = activeTabRef.current;
    const strip = tab?.parentElement;
    if (!tab || !strip) return;
    const tabBox = tab.getBoundingClientRect();
    const stripBox = strip.getBoundingClientRect();
    if (tabBox.left < stripBox.left) {
      strip.scrollLeft -= stripBox.left - tabBox.left;
    } else if (tabBox.right > stripBox.right) {
      strip.scrollLeft += tabBox.right - stripBox.right;
    }
  }, [activeTab, client]);

  useEffect(() => {
    if (client && Number(id) === client.id) {
      openTab("client", Number(id), client.name);
    }
  }, [client, id, openTab]);

  // 403 (brak uprawnień do klienta) i 5xx NIE mogą udawać „nie znaleziono"
  // (audyt F-20) — użytkownik czytał to jako skasowanie rekordu.
  const clientViewState = resolveViewState({
    isLoading,
    isError,
    error,
    isEmpty: !client,
  });
  if (clientViewState === "loading")
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mr-3" />
        Ładowanie klienta...
      </div>
    );
  if (clientViewState !== "ready")
    return (
      <div className="p-6">
        <QueryStateNotice
          state={clientViewState === "empty" ? "not_found" : clientViewState}
          description={
            clientViewState !== "forbidden"
              ? undefined
              : user?.delivery_client_scope === "assigned"
                ? // Od 25.09.2026 DL widzi w Klientach, Kontraktach i Zamówieniach
                  // tylko klientów z przypisania; rekrutacje zostają otwarte.
                  "Ten klient jest poza Twoim portfelem. Jego rekrutacje znajdziesz w module Rekrutacje, a o przypisanie klienta poproś administratora albo Head of Recruitment."
                : "Nie masz uprawnień do tego klienta. Rekord istnieje — poproś administratora o dostęp."
          }
          onRetry={() => void refetch()}
        />
      </div>
    );

  const allTabs: { key: ClientTab; label: string }[] = [
    { key: "profil", label: "Profil" },
    // Karta klienta — bez filtra po roli: rola `user` dostanie 403 z backendu
    // i karta pokaże „Brak uprawnień", nie pustkę (zamierzone).
    { key: "zasady", label: "Zasady współpracy" },
    { key: "projekty", label: "Projekty" },
    { key: "zamowienia", label: "Zamówienia" },
    { key: "importy-md", label: "Importy MD" },
    { key: "zespol", label: "Delivery Lead" },
    { key: "kontakty", label: "Kontakty klienta" },
    { key: "umowy-ramowe", label: "Umowy" },
    { key: "analityka", label: "Analityka" },
  ];
  const TABS = allTabs.filter(
    (tab) => canViewDeliveryLegal || tab.key !== "umowy-ramowe",
  );

  return (
    <div className="space-y-3">
      <div className="bg-card dark:bg-muted rounded-xl border border-border shadow-xs overflow-hidden">
        {/* Nagłówek w jednej linii (wersja B, 29.09.2026): nazwa, status,
            Delivery Lead i menu. Do 09.2026 karta miała ~130 px (ikona 56 px,
            tytuł 24 px, osobne rzędy WWW i NDA), więc zamówienia zaczynały się
            w połowie ekranu laptopa. WWW, NDA i „Usuń klienta” są w menu „⋯”. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-5" data-client-header>
          <Link
            href="/clients"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Wróć do klientów"
            title="Wróć do klientów"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Klienci
          </Link>
          <span aria-hidden="true" className="text-xs text-muted-foreground">/</span>
          <h1 className="min-w-0 break-words font-display text-lg font-semibold text-foreground">{client.name}</h1>
          {client.status && (
            <StatusDot tone={STATUS_TONES[client.status] ?? "neutral"}>
              {STATUS_LABELS[client.status] || client.status}
            </StatusDot>
          )}
          {client.industry && (
            <span className="text-xs text-muted-foreground">{client.industry}</span>
          )}
          {headDeliveryLead && (
            <span
              className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              data-client-header-dl
            >
              DL: <span className="font-medium text-foreground">{headDeliveryLead}</span>
            </span>
          )}
          {/* Liczby klienta na KAŻDEJ zakładce (dawniej dwa kafle w zakładce
              Profil). To samo zapytanie co `ProfileTab` — jeden klucz. */}
          <ClientHeaderStats
            clientId={Number(id)}
            className="ml-auto justify-end max-sm:order-last max-sm:ml-0 max-sm:w-full max-sm:justify-start"
          />
          <div className="flex items-center gap-1.5 max-sm:ml-auto">
            {canUpdateClient && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowEdit(true)}
                title="Edytuj firmę"
              >
                <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                Edytuj
              </Button>
            )}
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label="Więcej o kliencie"
                  title="Strona WWW, NDA i więcej"
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground pointer-coarse:h-10 pointer-coarse:w-10"
                >
                  <Ellipsis className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel className="truncate">{client.name}</DropdownMenuLabel>
                {client.website ? (
                  <DropdownMenuItem asChild>
                    <a
                      href={client.website.startsWith("http") ? client.website : `https://${client.website}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Globe className="h-4 w-4 shrink-0" />
                      <span className="break-all">{client.website}</span>
                    </a>
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem disabled>
                    <Globe className="h-4 w-4" />
                    Brak strony WWW
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem disabled className="opacity-100">
                  {client.nda_signed ? (
                    <CheckCircle className="h-4 w-4 text-success" />
                  ) : (
                    <XCircle className="h-4 w-4 text-muted-foreground" />
                  )}
                  NDA {client.nda_signed ? "podpisane" : "niepodpisane"}
                </DropdownMenuItem>
                {canDeleteClient && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={() => window.setTimeout(() => setShowDelete(true), 0)}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                      Usuń klienta
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Tabs — horizontal scroll z visible scrollbar (macOS hide by default
            ukrywa scrollbar i user nie wie że można scrollować). Mniejszy
            padding px-3 (vs 4) + krótsze labele mieszczą wszystkie 12 tabów. */}
        <div className="border-t border-border min-w-0">
          <div
            role="tablist"
            aria-label="Sekcje klienta"
            className="flex gap-0.5 px-3 sm:px-5 pt-0 overflow-x-auto whitespace-nowrap min-w-0"
            style={{ scrollbarWidth: "thin" }}
          >
            {TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                id={`client-tab-${tab.key}`}
                aria-selected={activeTab === tab.key}
                aria-controls="client-tab-panel"
                ref={activeTab === tab.key ? activeTabRef : undefined}
                onClick={() => selectTab(tab.key)}
                className={cn(
                  "shrink-0 border-b-2 px-3 py-2 text-[13px] transition-colors pointer-coarse:min-h-10",
                  activeTab === tab.key
                    ? "border-primary font-semibold text-foreground"
                    : "border-transparent font-medium text-muted-foreground hover:text-foreground"
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab content — po konsolidacji 12→6 tabów reszta sekcji wbudowana
            jako collapsibles. Rozwijaniem steruje natywne <details>, ale
            dziecko montuje się dopiero po pierwszym otwarciu (LazyDetails) —
            zwinięty <details> montuje treść i odpalał zapytania paneli, których
            nikt nie ogląda. */}
        <div
          id="client-tab-panel"
          role="tabpanel"
          aria-labelledby={`client-tab-${activeTab}`}
          className="p-3 sm:p-4"
        >
          {activeTab === "profil" && (
            // Od `xl` dwie kolumny: konsultanci po lewej, po prawej rozwinięte
            // karty (informacje, materiały, konflikty). Węziej — karty pod tabelą.
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start">
              <ProfileTab clientId={Number(id)} />

              <aside className="@container grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3" aria-label="Informacje o kliencie">
                <LazyDetails
                  defaultOpen
                  icon={<Building2 className="w-4 h-4 text-muted-foreground" />}
                  title="Informacje + statystyki współpracy"
                  contentClassName="space-y-4 border-t border-border p-4"
                >
                  <CooperationStatsSection clientId={Number(id)} />
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
                      Notatki
                    </p>
                    {client.notes ? (
                      <p className="text-sm text-foreground whitespace-pre-line">{client.notes}</p>
                    ) : (
                      <p className="text-sm text-muted-foreground italic">Brak dodatkowych notatek.</p>
                    )}
                  </div>
                </LazyDetails>

                <LazyDetails
                  defaultOpen
                  icon={<FolderOpen className="w-4 h-4 text-muted-foreground" />}
                  title="Materiały sprzedażowe"
                >
                  <MaterialsTab
                    clientId={Number(id)}
                    readOnly={!canEditDelivery}
                    showContractTerms={canViewDeliveryLegal}
                    contractTermsReadOnly={!canEditDeliveryLegal}
                  />
                </LazyDetails>

                <LazyDetails
                  defaultOpen
                  icon={<AlertOctagon className="w-4 h-4 text-muted-foreground" />}
                  title="Konflikty z kandydatami"
                >
                  <ClientConflictsSection clientId={Number(id)} />
                </LazyDetails>
              </aside>
            </div>
          )}

          {activeTab === "zasady" && <ClientPlaybookTab clientId={Number(id)} />}

          {activeTab === "projekty" && <ProjectsTab clientId={Number(id)} />}

          {activeTab === "kontakty" && <ContactsTab clientId={Number(id)} />}

          {canViewDeliveryLegal && activeTab === "umowy-ramowe" && (
            <div className="space-y-4">
              <FrameworkContractsTab
                clientId={Number(id)}
                focusContractId={focusFrameworkId}
                onFocusHandled={clearFocusParams}
              />

              <LazyDetails
                defaultOpen
                icon={<DollarSign className="w-4 h-4 text-muted-foreground" />}
                title="Cennik (rate cards)"
              >
                <RateCardsTab clientId={Number(id)} />
              </LazyDetails>
            </div>
          )}

          {/* Jeden rejestr dla wszystkich klientów: tabela zamówień okresowych,
              kosztowych i MD z panelem szczegółów po prawej (wersja B). */}
          {activeTab === "zamowienia" && (
            <MultiConsultantOrdersTab
              clientId={Number(id)}
              clientName={client?.display_name || client?.name || ""}
              legacyNullOrderType={
                client?.legacy_null_order_type === "md" ? "md" : "periodic"
              }
              // „Rozstrzygnij w oknie zamówienia" z kolejki zamówień z maila.
              orderMailDocId={orderMailDocId}
              onOrderMailDocDone={clearOrderMailDoc}
              focusOrderId={focusOrderId}
              focusGroupId={focusGroupId}
              focusContractId={focusContractId}
              onFocusHandled={clearFocusParams}
            />
          )}
          {activeTab === "importy-md" && (
            <ClientMdImportsTab
              clientId={Number(id)}
              selectedImportId={selectedImportId}
              onSelectImport={selectImport}
            />
          )}
          {activeTab === "analityka" && <AnalyticsTab clientId={Number(id)} />}

          {activeTab === "zespol" && (
            <div className="space-y-4">
              <div>
                <h3 className="mb-2 text-[13px] font-semibold text-foreground">
                  {TAC_UI_ENABLED ? "Opiekunowie (TAC + Delivery Lead)" : "Delivery Lead"}
                </h3>
                <OwnersTab clientId={Number(id)} />
              </div>

              <LazyDetails
                defaultOpen
                icon={<BookOpen className="w-4 h-4 text-muted-foreground" />}
                title="Wiedza o kliencie (selling points, tech stack, kultura)"
              >
                <KnowledgeTab clientId={Number(id)} />
              </LazyDetails>
            </div>
          )}
        </div>
      </div>

      {canDeleteClient && (
        <DeleteClientDialog
          clientId={client.id}
          clientName={client.name}
          open={showDelete}
          onOpenChange={setShowDelete}
          onDeleted={(result) => {
            setShowDelete(false);
            showSuccess(
              result.result === "purged"
                ? `Klient „${result.client_name}" został usunięty trwale.`
                : `Klient „${result.client_name}" został usunięty — dane historyczne zostały zachowane.`,
            );
            closeTab(`client-${client.id}`);
            queryClient.removeQueries({ queryKey: ["client", id] });
            queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
            queryClient.invalidateQueries({ queryKey: ["clients"] });
            router.push("/clients");
          }}
        />
      )}

      {showEdit && (
        <EditClientModal
          client={client}
          onClose={() => setShowEdit(false)}
          onSuccess={(msg) => {
            queryClient.invalidateQueries({ queryKey: ["client", id] });
            queryClient.invalidateQueries({ queryKey: ["client-profile", Number(id)] });
            // Zmieniona nazwa/status musi być widoczna też na liście klientów
            // bez pełnego przeładowania (ClientsListV2 → "clients-directory").
            queryClient.invalidateQueries({ queryKey: ["clients-directory"] });
            showSuccess(msg);
          }}
        />
      )}
    </div>
  );
}

// ── Cooperation stats widget ─────────────────────────────────────────────────
//
// Surfaces /api/reports/clients hit-ratio + /clients/{id}/trend for a single
// client. 4 KPI cards (closed, hires, hit ratio, active) + 6-month sparkline.
// Silently returns null on 403 (recruiter/sourcer have no access) or when
// client has zero data in the selected period.

interface CoopStatsRow {
  client_id: number;
  closed_jobs: number;
  filled_jobs: number;
  placements: number;
  total_vacancies: number;
  hit_ratio: number;
  /** `null` = nie da się policzyć (żadna zamknięta rekrutacja nie deklaruje
   *  headcountu). NIE to samo co 0% — patrz `services/job_data_trust.py`. */
  fill_rate: number | null;
  fill_rate_source?: string;
  active_jobs: number;
  target_achieved: boolean;
  /** Odsetek zamknięć ze znanym powodem; `null` gdy brak zamknięć. */
  outcome_coverage_pct?: number | null;
}

interface CoopStatsResponse {
  clients: CoopStatsRow[];
  overall: { hit_ratio_target_pct: number };
}

interface CoopTrendPoint {
  month: string;
  month_label: string;
  closed_jobs: number;
  filled_jobs: number;
  hit_ratio: number;
}

interface CoopTrendResponse {
  client_id: number;
  months: number;
  trend: CoopTrendPoint[];
}

/** Kolor pigułki hit ratio względem CELU z backendu (`hit_ratio_target_pct`,
 *  dziś 30%) — do 24.09.2026 progi 50/20 były wpisane na sztywno i klient na
 *  celu świecił na bursztynowo (audyt N8). */
export function hitRatioTone(hitRatio: number, targetPct: number): string {
  if (hitRatio >= targetPct) return "bg-success-muted text-success-muted-foreground";
  if (hitRatio >= targetPct / 2) return "bg-warning-muted text-warning-muted-foreground";
  return "bg-destructive-muted text-destructive-muted-foreground";
}

function CooperationStatsSection({ clientId }: { clientId: number }) {
  // Raport nie przyjmuje `client_id` (backend `/api/reports/clients` liczy
  // wszystkich klientów) — filtrujemy wiersz po stronie przeglądarki. Zawężenie
  // wymaga zmiany endpointu raportów (poza modułem Klienci).
  const hitQuery = useQuery<CoopStatsResponse>({
    queryKey: ["client-coop-stats", clientId, "year"],
    queryFn: () =>
      api
        .get("/api/reports/clients", {
          params: { period: "year", min_closed: 0 },
        })
        .then((r) => r.data),
    retry: false,
  });

  const { data: trendData } = useQuery<CoopTrendResponse>({
    queryKey: ["client-coop-trend", clientId, 6],
    queryFn: () =>
      api
        .get(`/api/reports/clients/${clientId}/trend`, { params: { months: 6 } })
        .then((r) => r.data),
    retry: false,
  });

  const hitData = hitQuery.data;
  const hitState = resolveViewState({
    isLoading: hitQuery.isPending,
    isError: hitQuery.isError,
    error: hitQuery.error,
    isSuccess: hitQuery.isSuccess,
  });

  if (hitState === "loading") {
    return (
      <div className="text-sm text-muted-foreground">Ładowanie statystyk…</div>
    );
  }

  // 403 (rola bez raportów) → sekcja znika. Awaria serwera NIE może wyglądać
  // tak samo — do 24.09.2026 każdy błąd chował sekcję (audyt S10).
  if (hitState === "forbidden") return null;
  if (isBlockingViewState(hitState)) {
    return (
      <QueryStateNotice
        state={hitState as "not_found" | "error"}
        description="Nie udało się wczytać statystyk współpracy."
        onRetry={() => void hitQuery.refetch()}
        className="py-6"
      />
    );
  }

  const row = hitData?.clients.find((c) => c.client_id === clientId);

  // Empty state — new client, no data yet. Still show the header + placeholder.
  const hasData = row && (row.closed_jobs > 0 || row.active_jobs > 0);
  const tonePill = row && row.closed_jobs >= 3
    ? hitRatioTone(row.hit_ratio, hitData?.overall.hit_ratio_target_pct ?? 30)
    : "bg-muted text-foreground";

  const trendValues = trendData?.trend.map((p) => p.hit_ratio) ?? [];
  const trendMax = Math.max(...trendValues, 1);

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
          Statystyki współpracy
        </p>
        <span className="text-[11px] text-muted-foreground">Ostatnie 12 mies.</span>
      </div>

      {!hasData ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
          Brak zamkniętych zapytań w ostatnich 12 miesiącach.
        </div>
      ) : (
        <>
          {/* Trzy liczby, nie cztery: „Aktywne projekty" (`row.active_jobs`)
              zdjęte, bo było trzecim miejscem z tą samą informacją — przy
              przełączniku w zakładce Projekty i w nagłówku klienta — i to
              liczonym jeszcze inaczej (tu tylko `published`, tam `draft` +
              `published`). Zostają METRYKI skuteczności: bez „N obsadzonych ·
              N przegranych" hit ratio traci kontekst. Lista faktów w karcie
              zamiast trzech dużych kafli (makieta 02.10.2026). */}
          <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Zamknięte zapytania</dt>
            <dd className="min-w-0">
              <span className="font-semibold tabular-nums text-foreground">{row!.closed_jobs}</span>
              <span className={CALM_SUBLINE}>
                {row!.filled_jobs} obsadzonych · {row!.closed_jobs - row!.filled_jobs} przegranych
              </span>
            </dd>
            <dt className="text-muted-foreground">Zatrudnienia</dt>
            <dd className="min-w-0">
              <span className="font-semibold tabular-nums text-foreground">{row!.placements}</span>
              <span className={CALM_SUBLINE}>
                {row!.fill_rate !== null && row!.total_vacancies > 0
                  ? `z ${row!.total_vacancies} miejsc · fill ${row!.fill_rate.toFixed(1)}%`
                  : "brak zadeklarowanych etatów"}
              </span>
            </dd>
            <dt className="text-muted-foreground">Hit ratio</dt>
            <dd className="min-w-0">
              <span className={`inline-flex rounded-md px-1.5 py-0.5 text-sm font-semibold tabular-nums ${tonePill}`}>
                {row!.closed_jobs >= 3 ? `${row!.hit_ratio.toFixed(1)}%` : `${row!.filled_jobs} / ${row!.closed_jobs}`}
              </span>
              <span className={CALM_SUBLINE}>
                {row!.closed_jobs >= 3
                  ? row!.target_achieved
                    ? `cel ≥${hitData!.overall.hit_ratio_target_pct}% ✓`
                    : `cel ≥${hitData!.overall.hit_ratio_target_pct}%`
                  : "Za mało danych (min. 3)"}
              </span>
            </dd>
          </dl>

          {trendValues.length > 0 && (
            <div className="mt-3 rounded-lg bg-muted/40 p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[11px] font-semibold text-muted-foreground">Trend hit ratio · 6M</p>
                <span className="text-[11px] text-muted-foreground">
                  max {Math.round(trendMax)}% · min {Math.round(Math.min(...trendValues))}%
                </span>
              </div>
              <div className="flex items-end gap-1 h-14">
                {trendData!.trend.map((p) => {
                  const tone =
                    p.hit_ratio >= 50
                      ? "bg-success"
                      : p.hit_ratio >= 20
                        ? "bg-warning"
                        : p.hit_ratio > 0
                          ? "bg-destructive"
                          : "bg-muted";
                  const heightPct = trendMax > 0 ? Math.max((p.hit_ratio / trendMax) * 100, 4) : 4;
                  return (
                    <div
                      key={p.month}
                      className="flex-1 flex flex-col items-center justify-end gap-1"
                      title={`${p.month_label}: ${p.hit_ratio.toFixed(1)}% (${p.filled_jobs}/${p.closed_jobs})`}
                    >
                      <div
                        className={`w-full rounded-t ${tone}`}
                        style={{ height: `${heightPct}%` }}
                      />
                      <span className="text-[10px] text-muted-foreground">
                        {p.month_label.split(" ")[0]}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
