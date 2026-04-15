"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Plus,
  Pencil,
  Trash2,
  Eye,
  Mail,
  X,
  Loader2,
  AlertCircle,
  Send,
  CheckCircle2,
  FileText,
  Star,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

type EmailCategory =
  | "application_received"
  | "screening_invite"
  | "interview_invite"
  | "rejection"
  | "offer"
  | "general";

interface EmailTemplate {
  id: number;
  name: string;
  subject: string;
  body: string;
  category: EmailCategory;
  is_default: boolean;
  created_by: number | null;
  placeholders?: string[];
}

// ── Constants ────────────────────────────────────────────────────────────────

const ALL_CATEGORIES: { value: EmailCategory | "all"; label: string }[] = [
  { value: "all", label: "Wszystkie" },
  { value: "screening_invite", label: "Screening" },
  { value: "offer", label: "Oferta" },
  { value: "rejection", label: "Odmowa" },
  { value: "general", label: "Follow-up" },
  { value: "application_received", label: "Potwierdzenie" },
  { value: "interview_invite", label: "Rozmowa" },
];

const CATEGORY_LABELS: Record<EmailCategory, string> = {
  application_received: "Potwierdzenie aplikacji",
  screening_invite: "Zaproszenie na screening",
  interview_invite: "Zaproszenie na rozmowę",
  rejection: "Odrzucenie",
  offer: "Oferta współpracy",
  general: "Ogólna wiadomość",
};

const CATEGORY_COLORS: Record<EmailCategory, string> = {
  application_received: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  screening_invite: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  interview_invite: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  rejection: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
  offer: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  general: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
};

const AVAILABLE_PLACEHOLDERS = [
  { key: "{{candidate_name}}", desc: "Imię i nazwisko kandydata" },
  { key: "{{job_title}}", desc: "Tytuł stanowiska" },
  { key: "{{company_name}}", desc: "Nazwa firmy" },
  { key: "{{interview_date}}", desc: "Data rozmowy / termin" },
  { key: "{{salary}}", desc: "Wynagrodzenie / widełki" },
  { key: "{{recruiter_name}}", desc: "Imię rekrutera" },
  { key: "{{recruiter_email}}", desc: "Email rekrutera" },
  { key: "{{application_date}}", desc: "Data aplikacji" },
];

// ── Preview Modal ─────────────────────────────────────────────────────────────

function PreviewModal({ template, onClose }: { template: EmailTemplate; onClose: () => void }) {
  const { data: preview, isLoading } = useQuery({
    queryKey: ["email-preview", template.id],
    queryFn: () =>
      api.post(`/api/email-templates/${template.id}/preview`).then((r) => r.data),
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Eye className="w-5 h-5 text-violet-500" />
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
              Podgląd: {template.name}
            </h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex items-center gap-2 text-gray-400 py-8 justify-center">
              <Loader2 className="w-5 h-5 animate-spin" /> Generowanie podglądu...
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Temat</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{preview?.subject}</p>
              </div>
              <div className="bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Treść</p>
                <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
                  {preview?.body}
                </pre>
              </div>
              <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3">
                <p className="text-xs text-amber-700 dark:text-amber-400 font-medium">
                  ℹ️ Podgląd z przykładowymi danymi. Rzeczywiste wartości zostaną podstawione przy wysyłce.
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
          >
            Zamknij
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Delete Confirm Modal ──────────────────────────────────────────────────────

function DeleteConfirmModal({
  template,
  onClose,
  onConfirm,
  isDeleting,
}: {
  template: EmailTemplate;
  onClose: () => void;
  onConfirm: () => void;
  isDeleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-sm p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center">
            <Trash2 className="w-5 h-5 text-red-600" />
          </div>
          <div>
            <h3 className="font-bold text-gray-900 dark:text-gray-100">Usuń szablon</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">Tej operacji nie można cofnąć</p>
          </div>
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-300 mb-6">
          Czy na pewno chcesz usunąć szablon <span className="font-semibold">&ldquo;{template.name}&rdquo;</span>?
        </p>
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
          >
            Anuluj
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-xl hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
            Usuń
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Template Editor Panel ─────────────────────────────────────────────────────

interface EditorProps {
  template: EmailTemplate | null; // null = new
  onSave: () => void;
  onCancel: () => void;
}

function TemplateEditor({ template, onSave, onCancel }: EditorProps) {
  const queryClient = useQueryClient();
  const isEdit = !!template;

  const [form, setForm] = useState({
    name: template?.name ?? "",
    subject: template?.subject ?? "",
    body: template?.body ?? "",
    category: (template?.category ?? "general") as EmailCategory,
    is_default: template?.is_default ?? false,
  });
  const [error, setError] = useState("");
  const [sendTestSuccess, setSendTestSuccess] = useState(false);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);

  // Reset form when template changes
  useEffect(() => {
    setForm({
      name: template?.name ?? "",
      subject: template?.subject ?? "",
      body: template?.body ?? "",
      category: (template?.category ?? "general") as EmailCategory,
      is_default: template?.is_default ?? false,
    });
    setError("");
    setPreview(null);
    setShowPreview(false);
  }, [template?.id]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (isEdit) {
        return api.put(`/api/email-templates/${template!.id}`, form);
      } else {
        return api.post("/api/email-templates", form);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-templates"] });
      onSave();
    },
    onError: () => {
      setError("Błąd zapisywania szablonu. Spróbuj ponownie.");
    },
  });

  const sendTestMutation = useMutation({
    mutationFn: () => api.post(`/api/email-templates/${template!.id}/send`),
    onSuccess: () => {
      setSendTestSuccess(true);
      setTimeout(() => setSendTestSuccess(false), 3000);
    },
  });

  const handlePreview = async () => {
    if (!form.subject || !form.body) return;
    if (!template?.id) {
      // For unsaved templates, do a client-side preview
      const rendered = { subject: form.subject, body: form.body };
      for (const p of AVAILABLE_PLACEHOLDERS) {
        const sample: Record<string, string> = {
          "{{candidate_name}}": "Jan Kowalski",
          "{{job_title}}": "Senior Java Developer",
          "{{company_name}}": "B2B.net S.A.",
          "{{interview_date}}": "2025-02-15 10:00",
          "{{salary}}": "20 000 – 25 000 PLN",
          "{{recruiter_name}}": "Anna Nowak",
          "{{recruiter_email}}": "rekrutacja@b2bnet.pl",
          "{{application_date}}": "2025-02-01",
        };
        rendered.subject = rendered.subject.replaceAll(p.key, sample[p.key] ?? p.key);
        rendered.body = rendered.body.replaceAll(p.key, sample[p.key] ?? p.key);
      }
      setPreview(rendered);
      setShowPreview(true);
      return;
    }
    setLoadingPreview(true);
    try {
      const r = await api.post(`/api/email-templates/${template.id}/preview`);
      setPreview(r.data);
      setShowPreview(true);
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!form.name.trim() || !form.subject.trim() || !form.body.trim()) {
      setError("Nazwa, temat i treść są wymagane.");
      return;
    }
    saveMutation.mutate();
  };

  const insertPlaceholder = (placeholder: string) => {
    const textarea = document.getElementById("template-body") as HTMLTextAreaElement;
    if (!textarea) {
      setForm((f) => ({ ...f, body: f.body + placeholder }));
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const newBody = form.body.slice(0, start) + placeholder + form.body.slice(end);
    setForm((f) => ({ ...f, body: newBody }));
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + placeholder.length, start + placeholder.length);
    }, 0);
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col h-full">
      {/* Editor header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-blue-500" />
          <h2 className="font-bold text-gray-900 dark:text-gray-100">
            {isEdit ? "Edytuj szablon" : "Nowy szablon"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {isEdit && (
            <button
              type="button"
              onClick={() => sendTestMutation.mutate()}
              disabled={sendTestMutation.isPending}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors border",
                sendTestSuccess
                  ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800"
                  : "bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600"
              )}
              title="Wyślij testowy email na swój adres"
            >
              {sendTestSuccess ? (
                <><CheckCircle2 className="w-3.5 h-3.5" /> Wysłano!</>
              ) : (
                <><Send className="w-3.5 h-3.5" /> Wyślij test</>
              )}
            </button>
          )}
          <button
            type="button"
            onClick={handlePreview}
            disabled={loadingPreview}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800 hover:bg-violet-100 dark:hover:bg-violet-900/50 transition-colors"
          >
            {loadingPreview ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Eye className="w-3.5 h-3.5" />}
            Podgląd
          </button>
        </div>
      </div>

      {/* Form body */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {/* Name + Category */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Nazwa szablonu *
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="np. Zaproszenie na rozmowę"
              className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
              Kategoria *
            </label>
            <select
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value as EmailCategory }))}
              className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Subject */}
        <div>
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
            Temat emaila *
          </label>
          <input
            type="text"
            value={form.subject}
            onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
            placeholder="np. Zaproszenie na rozmowę — {{job_title}}"
            className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Placeholder hints */}
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-3 border border-blue-100 dark:border-blue-800">
          <p className="text-xs font-semibold text-blue-700 dark:text-blue-400 mb-2">
            Zmienne (kliknij aby wstawić w treść):
          </p>
          <div className="flex flex-wrap gap-1.5">
            {AVAILABLE_PLACEHOLDERS.map(({ key, desc }) => (
              <button
                key={key}
                type="button"
                onClick={() => insertPlaceholder(key)}
                title={desc}
                className="px-2 py-0.5 bg-white dark:bg-gray-700 border border-blue-200 dark:border-blue-700 text-blue-700 dark:text-blue-300 text-xs font-mono rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors"
              >
                {key}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div>
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
            Treść emaila *
          </label>
          <textarea
            id="template-body"
            value={form.body}
            onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
            placeholder="Wpisz treść emaila..."
            rows={14}
            className="w-full px-3 py-2.5 border border-gray-200 dark:border-gray-600 rounded-xl text-sm resize-y bg-white dark:bg-gray-700 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono leading-relaxed"
          />
          <p className="text-xs text-gray-400 mt-1">{form.body.length} znaków</p>
        </div>

        {/* Default checkbox */}
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
            className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div className="flex items-center gap-1.5">
            <Star className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-sm text-gray-700 dark:text-gray-300">Szablon domyślny</span>
          </div>
        </label>

        {error && (
          <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
        >
          Anuluj
        </button>
        <button
          type="submit"
          disabled={saveMutation.isPending}
          className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
        >
          {saveMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Mail className="w-4 h-4" />
          )}
          {isEdit ? "Zapisz zmiany" : "Utwórz szablon"}
        </button>
      </div>

      {/* Preview Modal */}
      {showPreview && preview && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-center gap-2">
                <Eye className="w-5 h-5 text-violet-500" />
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Podgląd szablonu</h2>
              </div>
              <button
                type="button"
                onClick={() => setShowPreview(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              <div className="bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Temat</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{preview.subject}</p>
              </div>
              <div className="bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Treść</p>
                <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
                  {preview.body}
                </pre>
              </div>
              <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3">
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  ℹ️ Podgląd z przykładowymi danymi (Jan Kowalski, B2B.net S.A. itp.)
                </p>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
              <button
                type="button"
                onClick={() => setShowPreview(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl hover:bg-gray-50 transition-colors"
              >
                Zamknij
              </button>
            </div>
          </div>
        </div>
      )}
    </form>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function EmailTemplatesPage() {
  const queryClient = useQueryClient();

  const [activeCategory, setActiveCategory] = useState<EmailCategory | "all">("all");
  const [selectedTemplate, setSelectedTemplate] = useState<EmailTemplate | null | undefined>(undefined);
  // undefined = none selected, null = create new, EmailTemplate = edit
  const [deleteTarget, setDeleteTarget] = useState<EmailTemplate | null>(null);
  const [seedStatus, setSeedStatus] = useState<string | null>(null);

  const { data: allTemplates = [], isLoading } = useQuery<EmailTemplate[]>({
    queryKey: ["email-templates"],
    queryFn: () => api.get("/api/email-templates").then((r) => r.data),
  });

  const filteredTemplates = activeCategory === "all"
    ? allTemplates
    : allTemplates.filter((t) => t.category === activeCategory);

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/email-templates/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-templates"] });
      setDeleteTarget(null);
      if (selectedTemplate && deleteTarget && selectedTemplate.id === deleteTarget.id) {
        setSelectedTemplate(undefined);
      }
    },
  });

  const handleSeedTemplates = async () => {
    try {
      const r = await api.post("/api/email-templates/seed");
      setSeedStatus(r.data.message);
      queryClient.invalidateQueries({ queryKey: ["email-templates"] });
      setTimeout(() => setSeedStatus(null), 4000);
    } catch {
      setSeedStatus("Błąd podczas dodawania szablonów");
    }
  };

  const handleEditorSave = () => {
    setSelectedTemplate(undefined);
  };

  const handleEditorCancel = () => {
    setSelectedTemplate(undefined);
  };

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col space-y-4 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Szablony emaili</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Zarządzaj szablonami komunikacji z kandydatami
          </p>
        </div>
        <div className="flex items-center gap-2">
          {allTemplates.length === 0 && !isLoading && (
            <button
              onClick={handleSeedTemplates}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
            >
              <Copy className="w-4 h-4" />
              Dodaj domyślne szablony
            </button>
          )}
          <button
            onClick={() => setSelectedTemplate(null)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            Nowy szablon
          </button>
        </div>
      </div>

      {/* Seed status */}
      {seedStatus && (
        <div className="flex items-center gap-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl text-green-700 dark:text-green-400 text-sm flex-shrink-0">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          {seedStatus}
        </div>
      )}

      {/* Simulation notice */}
      <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3 flex items-start gap-3 flex-shrink-0">
        <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-amber-700 dark:text-amber-400">
          <strong>Tryb symulacji:</strong> Wysyłka emaili jest rejestrowana w konsoli serwera — wiadomości nie są faktycznie wysyłane. Integracja SMTP zostanie dodana w kolejnej wersji.
        </p>
      </div>

      {/* Master-detail layout */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left panel: template list */}
        <div className="w-80 flex-shrink-0 flex flex-col bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
          {/* Category tabs */}
          <div className="flex flex-wrap gap-1 p-3 border-b border-gray-100 dark:border-gray-700">
            {ALL_CATEGORIES.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setActiveCategory(value)}
                className={cn(
                  "px-2.5 py-1 text-xs font-medium rounded-lg transition-colors",
                  activeCategory === value
                    ? "bg-blue-600 text-white"
                    : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Template list */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center gap-2 py-12 text-gray-400">
                <Loader2 className="w-5 h-5 animate-spin" />
                <span className="text-sm">Ładowanie...</span>
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className="text-center py-12 text-gray-400">
                <Mail className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm">Brak szablonów</p>
                {activeCategory === "all" && (
                  <button
                    onClick={handleSeedTemplates}
                    className="mt-3 text-xs text-blue-500 hover:underline"
                  >
                    Dodaj domyślne →
                  </button>
                )}
              </div>
            ) : (
              <ul>
                {filteredTemplates.map((t) => (
                  <li
                    key={t.id}
                    onClick={() => setSelectedTemplate(t)}
                    className={cn(
                      "group px-4 py-3.5 cursor-pointer transition-colors border-b border-gray-50 dark:border-gray-700/50 last:border-b-0",
                      selectedTemplate && "id" in selectedTemplate && selectedTemplate.id === t.id
                        ? "bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-500"
                        : "hover:bg-gray-50 dark:hover:bg-gray-700/50"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          {t.is_default && <Star className="w-3 h-3 text-amber-400 flex-shrink-0" />}
                          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
                            {t.name}
                          </p>
                        </div>
                        <span
                          className={cn(
                            "inline-block mt-1 px-2 py-0.5 rounded-full text-xs font-medium",
                            CATEGORY_COLORS[t.category]
                          )}
                        >
                          {CATEGORY_LABELS[t.category]}
                        </span>
                        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1 truncate font-mono">
                          {t.subject}
                        </p>
                      </div>
                      {/* Quick actions */}
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => { e.stopPropagation(); setDeleteTarget(t); }}
                          className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                          title="Usuń"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* List footer */}
          <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/30">
            <p className="text-xs text-gray-400">
              {filteredTemplates.length} szablon{filteredTemplates.length !== 1 ? "ów" : ""}
              {activeCategory !== "all" && ` · ${CATEGORY_LABELS[activeCategory as EmailCategory]}`}
            </p>
          </div>
        </div>

        {/* Right panel: editor or empty state */}
        <div className="flex-1 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
          {selectedTemplate === undefined && (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 p-8">
              <Mail className="w-16 h-16 mb-4 opacity-20" />
              <p className="text-lg font-medium mb-2 text-gray-500 dark:text-gray-400">Wybierz szablon</p>
              <p className="text-sm text-center mb-6">
                Kliknij na szablon po lewej stronie, aby go edytować,<br />
                lub utwórz nowy.
              </p>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 rounded-xl hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Nowy szablon
              </button>
            </div>
          )}

          {(selectedTemplate === null || (selectedTemplate && "id" in selectedTemplate)) && (
            <TemplateEditor
              template={selectedTemplate as EmailTemplate | null}
              onSave={handleEditorSave}
              onCancel={handleEditorCancel}
            />
          )}
        </div>
      </div>

      {/* Delete confirm modal */}
      {deleteTarget && (
        <DeleteConfirmModal
          template={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          isDeleting={deleteMutation.isPending}
        />
      )}
    </div>
  );
}
