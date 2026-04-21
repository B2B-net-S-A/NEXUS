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
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { DeleteButton } from "@/components/ConfirmDialog";
import { RateCardsTab } from "@/components/RateCardsTab";
import { MaterialsTab } from "./MaterialsTab";
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
  inactive: "bg-gray-100 text-gray-600",
  prospect: "bg-blue-100 text-blue-700",
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
    color: "text-blue-600",
    bg: "bg-blue-50",
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
    color: "text-gray-600",
    bg: "bg-gray-100",
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
        <p className="text-sm text-gray-500">Baza wiedzy o kliencie</p>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj wiedzę
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-blue-900">Nowy wpis</h3>
            <button onClick={() => setShowAdd(false)} className="text-blue-400 hover:text-blue-600">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Kategoria</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as KnowledgeCategory })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {KNOWLEDGE_CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-600 block mb-1">Źródło</label>
              <input
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="np. rozmowa z HM 2025-11"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-600 block mb-1">Treść *</label>
            <textarea
              required
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={4}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="Wprowadź wiedzę o kliencie..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900">
              Anuluj
            </button>
            <button
              onClick={() => addMutation.mutate(form)}
              disabled={!form.content || addMutation.isPending}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50"
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
              <div key={entry.id} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 group">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-gray-700 whitespace-pre-line leading-relaxed flex-1">
                    {entry.content}
                  </p>
                  <DeleteButton
                    onConfirm={() => deleteMutation.mutate(entry.id)}
                    className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-all flex-shrink-0"
                  />
                </div>
                {entry.source && (
                  <p className="text-xs text-gray-400 mt-2 italic">Źródło: {entry.source}</p>
                )}
                <p className="text-xs text-gray-300 mt-1">
                  {new Date(entry.created_at).toLocaleDateString("pl-PL")}
                </p>
              </div>
            ))}
          </div>
        )
      )}

      {entries.length === 0 && !showAdd && (
        <div className="text-center py-12 text-gray-400">
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
          <label className="text-xs font-semibold text-gray-600 block mb-1">Imię i nazwisko *</label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Jan Kowalski"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-1">Stanowisko</label>
          <input
            value={form.position}
            onChange={(e) => setForm({ ...form, position: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="IT Procurement Manager"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-1">Email</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-1">Telefon</label>
          <input
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-gray-600 block mb-1">Dział</label>
          <input
            value={form.department}
            onChange={(e) => setForm({ ...form, department: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
            <span className="text-sm text-gray-700">Decydent</span>
          </label>
        </div>
      </div>
      <div>
        <label className="text-xs font-semibold text-gray-600 block mb-1">Notatki</label>
        <textarea
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          rows={2}
          className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900">
          Anuluj
        </button>
        <button
          onClick={onSubmit}
          disabled={!form.name || isLoading}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {isLoading ? "Zapisuję..." : "Zapisz"}
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">Osoby kontaktowe</p>
        <button
          onClick={() => { setShowAdd(true); setEditContact(null); }}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj kontakt
        </button>
      </div>

      {showAdd && !editContact && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-blue-900">Nowy kontakt</h3>
            <button onClick={() => setShowAdd(false)} className="text-blue-400 hover:text-blue-600">
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
        <div className="text-center py-12 text-gray-400">
          <Users className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Brak kontaktów dla tego klienta</p>
        </div>
      ) : (
        <div className="space-y-3">
          {contacts.map((contact) => (
            <div key={contact.id} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl">
              {editContact?.id === contact.id ? (
                <div className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-gray-900">Edytuj kontakt</h3>
                    <button onClick={() => setEditContact(null)} className="text-gray-400 hover:text-gray-600">
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
                      <div className="w-9 h-9 bg-gray-100 rounded-full flex items-center justify-center flex-shrink-0">
                        <span className="text-sm font-semibold text-gray-600">
                          {contact.name.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-gray-900">{contact.name}</span>
                          {contact.is_decision_maker && (
                            <span className="flex items-center gap-0.5 px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-full text-xs font-semibold">
                              <Crown className="w-3 h-3" />
                              Decydent
                            </span>
                          )}
                        </div>
                        {contact.position && (
                          <p className="text-xs text-gray-500 mt-0.5">
                            {contact.position}
                            {contact.department && ` · ${contact.department}`}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-3 mt-2">
                          {contact.email && (
                            <a
                              href={`mailto:${contact.email}`}
                              className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                            >
                              <Mail className="w-3 h-3" />
                              {contact.email}
                            </a>
                          )}
                          {contact.phone && (
                            <a
                              href={`tel:${contact.phone}`}
                              className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
                            >
                              <Phone className="w-3 h-3" />
                              {contact.phone}
                            </a>
                          )}
                        </div>
                        {contact.notes && (
                          <p className="text-xs text-gray-500 mt-2 italic">{contact.notes}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        onClick={() => openEdit(contact)}
                        className="text-gray-300 hover:text-blue-500 transition-colors"
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
      <div className="flex items-center gap-2 text-gray-400 text-sm py-8 justify-center">
        <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
        Ładowanie projektów...
      </div>
    );

  if (!jobs.length)
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
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
          className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl hover:border-purple-300 transition-colors group"
        >
          <div className="w-8 h-8 bg-purple-50 dark:bg-purple-900/30 rounded-lg flex items-center justify-center flex-shrink-0">
            <Briefcase className="w-4 h-4 text-purple-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">{job.title}</p>
            {job.location && (
              <p className="text-xs text-gray-400 truncate">{job.location}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              job.status === "published" ? "bg-green-100 text-green-700" :
              job.status === "draft" ? "bg-gray-100 text-gray-600" : "bg-red-100 text-red-600"
            }`}>
              {job.status === "published" ? "Aktywna" : job.status === "draft" ? "Szkic" : "Zamknięta"}
            </span>
            <ExternalLink className="w-3.5 h-3.5 text-gray-300 group-hover:text-purple-500 transition-colors" />
          </div>
        </a>
      ))}
    </div>
  );
}

// ── Contracts Tab ─────────────────────────────────────────────────────────────

function ContractsTab({ clientId }: { clientId: number }) {
  const { data: contracts = [], isLoading } = useQuery({
    queryKey: ["client-contracts", clientId],
    queryFn: () =>
      api.get("/api/contracts", { params: { client_id: clientId, limit: 50 } }).then((r) =>
        Array.isArray(r.data) ? r.data : r.data?.items ?? []
      ),
  });

  if (isLoading)
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-8 justify-center">
        <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
        Ładowanie kontraktów...
      </div>
    );

  if (!contracts.length)
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
        <FileText className="w-10 h-10 mb-3 opacity-40" />
        <p className="text-sm">Brak kontraktów dla tego klienta</p>
      </div>
    );

  return (
    <div className="space-y-2">
      {contracts.map((contract: any) => (
        <div
          key={contract.id}
          className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl"
        >
          <div className="w-8 h-8 bg-orange-50 dark:bg-orange-900/20 rounded-lg flex items-center justify-center flex-shrink-0">
            <FileText className="w-4 h-4 text-orange-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 dark:text-gray-200 truncate">
              {contract.title || contract.candidate_name || `Kontrakt #${contract.id}`}
            </p>
            <div className="flex gap-3 mt-0.5">
              {contract.start_date && (
                <p className="text-xs text-gray-400">
                  Od: {new Date(contract.start_date).toLocaleDateString("pl-PL")}
                </p>
              )}
              {contract.end_date && (
                <p className="text-xs text-gray-400">
                  Do: {new Date(contract.end_date).toLocaleDateString("pl-PL")}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {contract.monthly_rate && (
              <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                {Number(contract.monthly_rate).toLocaleString("pl-PL")} PLN
              </span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              contract.status === "active" ? "bg-green-100 text-green-700" :
              contract.status === "completed" ? "bg-blue-100 text-blue-700" :
              "bg-gray-100 text-gray-600"
            }`}>
              {contract.status === "active" ? "Aktywny" :
               contract.status === "completed" ? "Zakończony" : contract.status ?? "—"}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type Tab = "info" | "projekty" | "wiedza" | "kontakty" | "kontrakty" | "materialy" | "cennik";

export default function ClientDetailPage() {
  const { id } = useParams();
  const [activeTab, setActiveTab] = useState<Tab>("info");
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
      <div className="flex items-center justify-center h-64 text-gray-400">
        <div className="w-6 h-6 border-2 border-purple-400 border-t-transparent rounded-full animate-spin mr-3" />
        Ładowanie klienta...
      </div>
    );
  if (!client)
    return <div className="p-6 text-red-500">Nie znaleziono klienta</div>;

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "info", label: "Informacje", icon: <Building2 className="w-4 h-4" /> },
    { key: "projekty", label: "Projekty", icon: <Briefcase className="w-4 h-4" /> },
    { key: "wiedza", label: "Wiedza", icon: <BookOpen className="w-4 h-4" /> },
    { key: "kontakty", label: "Kontakty", icon: <Users className="w-4 h-4" /> },
    { key: "kontrakty", label: "Kontrakty", icon: <FileText className="w-4 h-4" /> },
    { key: "materialy", label: "Materiały", icon: <FolderOpen className="w-4 h-4" /> },
    { key: "cennik", label: "Cennik", icon: <DollarSign className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4 max-w-4xl">
      <Link
        href="/clients"
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Wróć do klientów
      </Link>

      <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="h-1.5 bg-gradient-to-r from-purple-600 via-violet-500 to-purple-400" />

        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 bg-purple-100 rounded-2xl flex items-center justify-center flex-shrink-0">
              <Building2 className="w-7 h-7 text-purple-600" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">{client.name}</h1>
                  {client.industry && (
                    <p className="text-sm text-purple-600 font-medium mt-0.5">{client.industry}</p>
                  )}
                </div>
                {client.status && (
                  <span
                    className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_COLORS[client.status] || "bg-gray-100 text-gray-600"}`}
                  >
                    {STATUS_LABELS[client.status] || client.status}
                  </span>
                )}
              </div>

              <div className="flex flex-wrap gap-4 mt-3 text-sm text-gray-600">
                {client.contact_email && (
                  <a
                    href={`mailto:${client.contact_email}`}
                    className="flex items-center gap-1.5 hover:text-blue-600 transition-colors"
                  >
                    <Mail className="w-3.5 h-3.5 text-gray-400" />
                    {client.contact_email}
                  </a>
                )}
                {client.contact_phone && (
                  <a
                    href={`tel:${client.contact_phone}`}
                    className="flex items-center gap-1.5 hover:text-emerald-600 transition-colors"
                  >
                    <Phone className="w-3.5 h-3.5 text-gray-400" />
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
                    <Globe className="w-3.5 h-3.5 text-gray-400" />
                    {client.website}
                  </a>
                )}
              </div>

              <div className="flex items-center gap-3 mt-3">
                <span className="flex items-center gap-1.5 text-xs text-gray-500">
                  {client.nda_signed ? (
                    <CheckCircle className="w-4 h-4 text-green-500" />
                  ) : (
                    <XCircle className="w-4 h-4 text-gray-300" />
                  )}
                  NDA {client.nda_signed ? "podpisane" : "niepodpisane"}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-t border-gray-100">
          <div className="flex gap-0 px-6 pt-0">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                  activeTab === tab.key
                    ? "border-purple-600 text-purple-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
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
          {activeTab === "info" && (
            <div className="space-y-4">
              {client.notes && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Notatki</p>
                  <p className="text-sm text-gray-700 whitespace-pre-line">{client.notes}</p>
                </div>
              )}
              {!client.notes && (
                <p className="text-sm text-gray-400 italic">Brak dodatkowych notatek.</p>
              )}
            </div>
          )}

          {activeTab === "projekty" && <ProjectsTab clientId={Number(id)} />}
          {activeTab === "wiedza" && <KnowledgeTab clientId={Number(id)} />}
          {activeTab === "kontakty" && <ContactsTab clientId={Number(id)} />}
          {activeTab === "kontrakty" && <ContractsTab clientId={Number(id)} />}
          {activeTab === "materialy" && <MaterialsTab clientId={Number(id)} />}
          {activeTab === "cennik" && <RateCardsTab clientId={Number(id)} />}
        </div>
      </div>
    </div>
  );
}
