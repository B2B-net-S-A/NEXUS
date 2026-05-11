"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  ArrowLeft,
  Building2,
  Mail,
  Phone,
  Globe,
  CheckCircle,
  XCircle,
  BookOpen,
  Bell,
  Users,
  Plus,
  Trash2,
  X,
  Star,
  Code,
  HelpCircle,
  Lightbulb,
  Info,
  Crown,
  Pencil,
  Briefcase,
  FileText,
  ExternalLink,
  DollarSign,
  FolderOpen,
  LayoutDashboard,
  UserCog,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { DeleteButton } from "@/components/ConfirmDialog";
import { RateCardsTab } from "@/components/RateCardsTab";
import { MaterialsTab } from "./MaterialsTab";
import { OwnersTab } from "./OwnersTab";
import { ProfileTab } from "./ProfileTab";
import { NotificationsTab } from "./NotificationsTab";
import { FrameworkContractsTab } from "@/components/FrameworkContractsTab";
import { OrdersAndContractsTab } from "@/components/OrdersAndContractsTab";
import { AnalyticsTab } from "@/components/AnalyticsTab";
import Link from "next/link";
import { useTabsStore } from "@/store/tabs";
import { cn } from "@/lib/utils";

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
}

type KnowledgeCategory = "selling_points" | "interview_questions" | "tech_stack" | "culture" | "general";

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  inactive: "bg-muted text-muted-foreground",
  prospect: "bg-primary/15 text-primary",
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
    color: "text-amber-600",
    bg: "bg-amber-50",
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
    color: "text-violet-600",
    bg: "bg-violet-50",
  },
  {
    key: "culture",
    label: "Kultura pracy",
    icon: <Lightbulb className="w-4 h-4" />,
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    key: "general",
    label: "Ogólne",
    icon: <Info className="w-4 h-4" />,
    color: "text-muted-foreground",
    bg: "bg-muted",
  },
];

// ── Knowledge Tab ─────────────────────────────────────────────────────────────

function KnowledgeTab({ clientId }: { clientId: number }) {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ category: "general" as KnowledgeCategory, content: "", source: "" });
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const { data: entries = [] } = useQuery<ClientKnowledge[]>({
    queryKey: ["client-knowledge", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/knowledge`).then((r) => r.data),
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
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary/90 text-white text-xs font-semibold rounded-lg transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj wiedzę
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="bg-primary/10 border border-primary/20 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-primary">Nowy wpis</h3>
            <button onClick={() => setShowAdd(false)} className="text-primary hover:text-primary">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-muted-foreground block mb-1">Kategoria</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as KnowledgeCategory })}
                className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
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
                className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
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
              className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring resize-none"
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
              className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50"
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
                  <DeleteButton
                    onConfirm={() => deleteMutation.mutate(entry.id)}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all flex-shrink-0"
                  />
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

      {entries.length === 0 && !showAdd && (
        <div className="text-center py-12 text-muted-foreground">
          <BookOpen className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak wpisów wiedzy o tym kliencie</p>
          <p className="text-xs mt-1">Kliknij "Dodaj wiedzę" aby začąć</p>
        </div>
      )}
    </div>
  );
}

// ── Contacts Tab ──────────────────────────────────────────────────────────────

function ContactsTab({ clientId }: { clientId: number }) {
  const [showAdd, setShowAdd] = useState(false);
  const [editContact, setEditContact] = useState<Contact | null>(null);
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

  const { data: contacts = [] } = useQuery<Contact[]>({
    queryKey: ["client-contacts", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/contacts`).then((r) => r.data),
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

  const ContactForm = ({ onSubmit, onCancel, isLoading }: { onSubmit: () => void; onCancel: () => void; isLoading: boolean }) => (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Imię i nazwisko *</label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            placeholder="Jan Kowalski"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Stanowisko</label>
          <input
            value={form.position}
            onChange={(e) => setForm({ ...form, position: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            placeholder="IT Procurement Manager"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Email</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Telefon</label>
          <input
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-muted-foreground block mb-1">Dział</label>
          <input
            value={form.department}
            onChange={(e) => setForm({ ...form, department: e.target.value })}
            className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            placeholder="IT / HR"
          />
        </div>
        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_decision_maker}
              onChange={(e) => setForm({ ...form, is_decision_maker: e.target.checked })}
              className="w-4 h-4 rounded accent-blue-600"
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
          className="w-full border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring resize-none"
        />
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground">
          Anuluj
        </button>
        <button
          onClick={onSubmit}
          disabled={!form.name || isLoading}
          className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-white text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {isLoading ? "Zapisuję..." : "Zapisz"}
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Osoby kontaktowe</p>
        <button
          onClick={() => { setShowAdd(true); setEditContact(null); }}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary/90 text-white text-xs font-semibold rounded-lg transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj kontakt
        </button>
      </div>

      {showAdd && !editContact && (
        <div className="bg-primary/10 border border-primary/20 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-primary">Nowy kontakt</h3>
            <button onClick={() => setShowAdd(false)} className="text-primary hover:text-primary">
              <X className="w-4 h-4" />
            </button>
          </div>
          <ContactForm
            onSubmit={() => createMutation.mutate(form)}
            onCancel={() => setShowAdd(false)}
            isLoading={createMutation.isPending}
          />
        </div>
      )}

      {/* Contacts list */}
      {contacts.length === 0 && !showAdd ? (
        <div className="text-center py-12 text-muted-foreground">
          <Users className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak kontaktów dla tego klienta</p>
        </div>
      ) : (
        <div className="space-y-3">
          {contacts.map((contact) => (
            <div key={contact.id} className="bg-card dark:bg-muted border border-border dark:border-border rounded-xl">
              {editContact?.id === contact.id ? (
                <div className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-foreground">Edytuj kontakt</h3>
                    <button onClick={() => setEditContact(null)} className="text-muted-foreground hover:text-muted-foreground">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <ContactForm
                    onSubmit={() => updateMutation.mutate({ id: contact.id, data: form })}
                    onCancel={() => setEditContact(null)}
                    isLoading={updateMutation.isPending}
                  />
                </div>
              ) : (
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-9 h-9 bg-muted rounded-full flex items-center justify-center flex-shrink-0">
                        <span className="text-sm font-semibold text-muted-foreground">
                          {contact.name.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-foreground">{contact.name}</span>
                          {contact.is_decision_maker && (
                            <span className="flex items-center gap-0.5 px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-full text-xs font-semibold">
                              <Crown className="w-3 h-3" />
                              Decydent
                            </span>
                          )}
                        </div>
                        {contact.position && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {contact.position}
                            {contact.department && ` · ${contact.department}`}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-3 mt-2">
                          {contact.email && (
                            <a
                              href={`mailto:${contact.email}`}
                              className="flex items-center gap-1 text-xs text-primary hover:underline"
                            >
                              <Mail className="w-3 h-3" />
                              {contact.email}
                            </a>
                          )}
                          {contact.phone && (
                            <a
                              href={`tel:${contact.phone}`}
                              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                            >
                              <Phone className="w-3 h-3" />
                              {contact.phone}
                            </a>
                          )}
                        </div>
                        {contact.notes && (
                          <p className="text-xs text-muted-foreground mt-2 italic">{contact.notes}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        onClick={() => openEdit(contact)}
                        className="text-muted-foreground hover:text-primary transition-colors"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <DeleteButton onConfirm={() => deleteMutation.mutate(contact.id)} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Projects Tab ──────────────────────────────────────────────────────────────

function ProjectsTab({ clientId }: { clientId: number }) {
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["client-jobs", clientId],
    queryFn: () =>
      api.get("/api/jobs", { params: { client_id: clientId, limit: 50 } }).then((r) =>
        Array.isArray(r.data) ? r.data : r.data?.items ?? []
      ),
  });

  if (isLoading)
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm py-8 justify-center">
        <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
        Ładowanie projektów...
      </div>
    );

  if (!jobs.length)
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Briefcase className="w-10 h-10 mb-3 opacity-40" />
        <p className="text-sm">Brak powiązanych ofert pracy</p>
      </div>
    );

  return (
    <div className="space-y-2">
      {jobs.map((job: any) => (
        <a
          key={job.id}
          href={`/jobs/${job.id}`}
          className="flex items-center gap-3 p-3 bg-card dark:bg-muted border border-border dark:border-border rounded-xl hover:border-purple-300 transition-colors group"
        >
          <div className="w-8 h-8 bg-purple-50 dark:bg-purple-900/30 rounded-lg flex items-center justify-center flex-shrink-0">
            <Briefcase className="w-4 h-4 text-purple-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground dark:text-muted-foreground truncate">{job.title}</p>
            {job.location && (
              <p className="text-xs text-muted-foreground truncate">{job.location}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              job.status === "published" ? "bg-green-100 text-green-700" :
              job.status === "draft" ? "bg-muted text-muted-foreground" : "bg-destructive/15 text-destructive"
            }`}>
              {job.status === "published" ? "Aktywna" : job.status === "draft" ? "Szkic" : "Zamknięta"}
            </span>
            <ExternalLink className="w-3.5 h-3.5 text-muted-foreground group-hover:text-purple-500 transition-colors" />
          </div>
        </a>
      ))}
    </div>
  );
}

// Kontrakty Tab — usunięty w refaktorze DL portal Order:Contract M:N → 1:N
// (2026-05-11). Wszystkie kontrakty kandydackie są teraz wyświetlane w tabie
// "Zamówienia & Kontrakty" (OrdersAndContractsTab) jako karta per Contract
// z historią Orderów. Globalna lista `/contracts` zostaje dla admin view.

// ── Main Page ─────────────────────────────────────────────────────────────────

type Tab =
  | "profil"
  | "info"
  | "projekty"
  | "opiekunowie"
  | "powiadomienia"
  | "wiedza"
  | "kontakty"
  | "umowy-ramowe"
  | "zamowienia"
  | "analityka"
  | "materialy"
  | "cennik";

export default function ClientDetailPage() {
  const { id } = useParams();
  const [activeTab, setActiveTab] = useState<Tab>("profil");
  const openTab = useTabsStore((s) => s.openTab);

  const { data: client, isLoading } = useQuery({
    queryKey: ["client", id],
    queryFn: () => api.get(`/api/clients/${id}`).then((r) => r.data),
  });

  useEffect(() => {
    if (client) {
      openTab("client", Number(id), client.name);
    }
  }, [client, id, openTab]);

  if (isLoading)
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="w-6 h-6 border-2 border-purple-400 border-t-transparent rounded-full animate-spin mr-3" />
        Ładowanie klienta...
      </div>
    );
  if (!client)
    return <div className="p-6 text-destructive">Nie znaleziono klienta</div>;

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "profil", label: "Profil", icon: <LayoutDashboard className="w-4 h-4" /> },
    { key: "info", label: "Informacje", icon: <Building2 className="w-4 h-4" /> },
    { key: "projekty", label: "Projekty", icon: <Briefcase className="w-4 h-4" /> },
    { key: "umowy-ramowe", label: "Umowy ramowe", icon: <FileText className="w-4 h-4" /> },
    { key: "zamowienia", label: "Zamówienia & Kontrakty", icon: <DollarSign className="w-4 h-4" /> },
    { key: "analityka", label: "Analityka", icon: <LayoutDashboard className="w-4 h-4" /> },
    { key: "opiekunowie", label: "Opiekunowie", icon: <UserCog className="w-4 h-4" /> },
    { key: "powiadomienia", label: "Powiadomienia", icon: <Bell className="w-4 h-4" /> },
    { key: "wiedza", label: "Wiedza", icon: <BookOpen className="w-4 h-4" /> },
    { key: "kontakty", label: "Kontakty", icon: <Users className="w-4 h-4" /> },
    { key: "materialy", label: "Materiały", icon: <FolderOpen className="w-4 h-4" /> },
    { key: "cennik", label: "Cennik", icon: <DollarSign className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4 max-w-7xl">
      <Link
        href="/clients"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Wróć do klientów
      </Link>

      <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border shadow-sm overflow-hidden">
        <div className="h-1.5 bg-gradient-to-r from-purple-600 via-violet-500 to-purple-400" />

        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 bg-purple-100 rounded-2xl flex items-center justify-center flex-shrink-0">
              <Building2 className="w-7 h-7 text-purple-600" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h1 className="text-2xl font-bold text-foreground">{client.name}</h1>
                  {client.industry && (
                    <p className="text-sm text-purple-600 font-medium mt-0.5">{client.industry}</p>
                  )}
                </div>
                {client.status && (
                  <span
                    className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_COLORS[client.status] || "bg-muted text-muted-foreground"}`}
                  >
                    {STATUS_LABELS[client.status] || client.status}
                  </span>
                )}
              </div>

              <div className="flex flex-wrap gap-4 mt-3 text-sm text-muted-foreground">
                {client.contact_email && (
                  <a
                    href={`mailto:${client.contact_email}`}
                    className="flex items-center gap-1.5 hover:text-primary transition-colors"
                  >
                    <Mail className="w-3.5 h-3.5 text-muted-foreground" />
                    {client.contact_email}
                  </a>
                )}
                {client.contact_phone && (
                  <a
                    href={`tel:${client.contact_phone}`}
                    className="flex items-center gap-1.5 hover:text-emerald-600 transition-colors"
                  >
                    <Phone className="w-3.5 h-3.5 text-muted-foreground" />
                    {client.contact_phone}
                  </a>
                )}
                {client.website && (
                  <a
                    href={client.website.startsWith("http") ? client.website : `https://${client.website}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 hover:text-purple-600 transition-colors"
                  >
                    <Globe className="w-3.5 h-3.5 text-muted-foreground" />
                    {client.website}
                  </a>
                )}
              </div>

              <div className="flex items-center gap-3 mt-3">
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {client.nda_signed ? (
                    <CheckCircle className="w-4 h-4 text-green-500" />
                  ) : (
                    <XCircle className="w-4 h-4 text-muted-foreground" />
                  )}
                  NDA {client.nda_signed ? "podpisane" : "niepodpisane"}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs — horizontal scroll prevents overflow w/ 12 tabs. min-w-0
            na flex container jest krytyczne żeby Tailwind respektował overflow
            zamiast rozciągać parent flex. */}
        <div className="border-t border-border min-w-0">
          <div className="flex gap-0 px-6 pt-0 overflow-x-auto whitespace-nowrap min-w-0">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors shrink-0",
                  activeTab === tab.key
                    ? "border-purple-600 text-purple-600"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab content */}
        <div className="p-6">
          {activeTab === "profil" && <ProfileTab clientId={Number(id)} />}

          {activeTab === "info" && (
            <div className="space-y-6">
              <CooperationStatsSection clientId={Number(id)} />
              <div>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Notatki
                </p>
                {client.notes ? (
                  <p className="text-sm text-foreground whitespace-pre-line">{client.notes}</p>
                ) : (
                  <p className="text-sm text-muted-foreground italic">Brak dodatkowych notatek.</p>
                )}
              </div>
            </div>
          )}

          {activeTab === "projekty" && <ProjectsTab clientId={Number(id)} />}
          {activeTab === "umowy-ramowe" && <FrameworkContractsTab clientId={Number(id)} />}
          {activeTab === "zamowienia" && <OrdersAndContractsTab clientId={Number(id)} />}
          {activeTab === "analityka" && <AnalyticsTab clientId={Number(id)} />}
          {activeTab === "opiekunowie" && <OwnersTab clientId={Number(id)} />}
          {activeTab === "powiadomienia" && <NotificationsTab clientId={Number(id)} />}
          {activeTab === "wiedza" && <KnowledgeTab clientId={Number(id)} />}
          {activeTab === "kontakty" && <ContactsTab clientId={Number(id)} />}
          {activeTab === "materialy" && <MaterialsTab clientId={Number(id)} />}
          {activeTab === "cennik" && <RateCardsTab clientId={Number(id)} />}
        </div>
      </div>
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
  fill_rate: number;
  active_jobs: number;
  target_achieved: boolean;
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

function CooperationStatsSection({ clientId }: { clientId: number }) {
  const { data: hitData, isLoading, isError } = useQuery<CoopStatsResponse>({
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

  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground">Ładowanie statystyk…</div>
    );
  }

  // 403 for recruiter/sourcer → hide section entirely (graceful degradation).
  if (isError) return null;

  const row = hitData?.clients.find((c) => c.client_id === clientId);

  // Empty state — new client, no data yet. Still show the header + placeholder.
  const hasData = row && (row.closed_jobs > 0 || row.active_jobs > 0);
  const tonePill = row && row.closed_jobs >= 3
    ? row.hit_ratio >= 50
      ? "bg-green-100 text-green-800"
      : row.hit_ratio >= 20
        ? "bg-amber-100 text-amber-800"
        : "bg-destructive/15 text-red-800"
    : "bg-muted text-foreground";

  const trendValues = trendData?.trend.map((p) => p.hit_ratio) ?? [];
  const trendMax = Math.max(...trendValues, 1);

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Statystyki współpracy
        </p>
        <span className="text-xs text-muted-foreground">Ostatnie 12 mies.</span>
      </div>

      {!hasData ? (
        <div className="rounded-lg border border-dashed border-border dark:border-border p-6 text-center text-sm text-muted-foreground">
          Brak zamkniętych zapytań w ostatnich 12 miesiącach.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
              <div className="text-xs text-muted-foreground mb-1">Zamknięte zapytania</div>
              <div className="text-2xl font-bold text-foreground dark:text-foreground">
                {row!.closed_jobs}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {row!.filled_jobs} obsadzonych · {row!.closed_jobs - row!.filled_jobs} przegranych
              </div>
            </div>
            <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
              <div className="text-xs text-muted-foreground mb-1">Zatrudnienia</div>
              <div className="text-2xl font-bold text-foreground dark:text-foreground">
                {row!.placements}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {row!.total_vacancies > 0
                  ? `z ${row!.total_vacancies} miejsc · fill ${row!.fill_rate.toFixed(1)}%`
                  : "—"}
              </div>
            </div>
            <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
              <div className="text-xs text-muted-foreground mb-1">Hit ratio</div>
              <div className="flex items-baseline gap-2">
                <span className={`text-2xl font-bold px-2 py-0.5 rounded ${tonePill}`}>
                  {row!.closed_jobs >= 3 ? `${row!.hit_ratio.toFixed(1)}%` : `${row!.filled_jobs} / ${row!.closed_jobs}`}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {row!.closed_jobs >= 3
                  ? row!.target_achieved
                    ? `cel ≥${hitData!.overall.hit_ratio_target_pct}% ✓`
                    : `cel ≥${hitData!.overall.hit_ratio_target_pct}%`
                  : "Za mało danych (min. 3)"}
              </div>
            </div>
            <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
              <div className="text-xs text-muted-foreground mb-1">Aktywne projekty</div>
              <div className="text-2xl font-bold text-foreground dark:text-foreground">
                {row!.active_jobs}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">opublikowane</div>
            </div>
          </div>

          {trendValues.length > 0 && (
            <div className="mt-4 bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-muted-foreground">Trend hit ratio · 6M</p>
                <span className="text-xs text-muted-foreground">
                  max {Math.round(trendMax)}% · min {Math.round(Math.min(...trendValues))}%
                </span>
              </div>
              <div className="flex items-end gap-1 h-16">
                {trendData!.trend.map((p) => {
                  const tone =
                    p.hit_ratio >= 50
                      ? "bg-green-500"
                      : p.hit_ratio >= 20
                        ? "bg-amber-500"
                        : p.hit_ratio > 0
                          ? "bg-destructive/100"
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
