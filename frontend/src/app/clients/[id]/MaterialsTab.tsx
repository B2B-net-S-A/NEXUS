"use client";

import { useState, FormEvent, ChangeEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  FileType,
  Plus,
  Download,
  Upload,
  Save,
  X,
} from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { DeleteButton } from "@/components/ConfirmDialog";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OnePager {
  id: number;
  client_id: number;
  title: string;
  description: string | null;
  version: string | null;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  uploaded_by: number | null;
  uploaded_by_email: string | null;
  created_at: string;
}

interface ContractTerms {
  id?: number;
  client_id?: number;
  off_limits_months: number | null;
  off_limits_scope: string | null;
  off_limits_notes: string | null;
  internalization_fee_pct: string | null;
  internalization_min_months: number | null;
  internalization_notice_days: number | null;
  internalization_notes: string | null;
  payment_net_days: number | null;
  payment_currency: string | null;
  payment_invoice_cycle: string | null;
  payment_late_fees: string | null;
  payment_notes: string | null;
  notice_period_days: number | null;
  warranty_replacement_days: number | null;
  warranty_notes: string | null;
  other_clauses: string | null;
  updated_by_email?: string | null;
  updated_at?: string;
}

const EMPTY_TERMS: ContractTerms = {
  off_limits_months: null,
  off_limits_scope: null,
  off_limits_notes: null,
  internalization_fee_pct: null,
  internalization_min_months: null,
  internalization_notice_days: null,
  internalization_notes: null,
  payment_net_days: null,
  payment_currency: null,
  payment_invoice_cycle: null,
  payment_late_fees: null,
  payment_notes: null,
  notice_period_days: null,
  warranty_replacement_days: null,
  warranty_notes: null,
  other_clauses: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const MAX_UPLOAD_MB = 20;
const ALLOWED_EXT = /\.(pdf|docx|doc)$/i;

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function fileIcon(filename: string) {
  const ext = filename.toLowerCase();
  if (ext.endsWith(".pdf")) {
    return <FileType className="w-5 h-5 text-red-500" />;
  }
  return <FileText className="w-5 h-5 text-blue-500" />;
}

// ── Main component ───────────────────────────────────────────────────────────

export function MaterialsTab({ clientId }: { clientId: number }) {
  return (
    <div className="space-y-8">
      <OnePagersSection clientId={clientId} />
      <ContractTermsSection clientId={clientId} />
    </div>
  );
}

// ── Section A: One-pagers ────────────────────────────────────────────────────

function OnePagersSection({ clientId }: { clientId: number }) {
  const qc = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [showUpload, setShowUpload] = useState(false);

  const { data: pagers = [], isLoading } = useQuery<OnePager[]>({
    queryKey: ["client-one-pagers", clientId],
    queryFn: () =>
      api.get(`/api/clients/${clientId}/one-pagers`).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      api.delete(`/api/clients/${clientId}/one-pagers/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-one-pagers", clientId] });
      showSuccess("Usunięto one-pager");
    },
    onError: () => showError("Nie udało się usunąć"),
  });

  async function handleDownload(p: OnePager) {
    try {
      const res = await api.get(
        `/api/clients/${clientId}/one-pagers/${p.id}/download`,
        { responseType: "blob" }
      );
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = p.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      showError("Nie udało się pobrać pliku");
    }
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <FileText className="w-5 h-5 text-purple-600" />
            One-pagery
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Materiały sprzedażowe (PDF/DOCX) przypięte do tego klienta
          </p>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" /> Dodaj
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-400">Ładowanie…</p>
      ) : pagers.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          Brak one-pagerów. Dodaj pierwszy, aby zacząć.
        </div>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-gray-700">
          {pagers.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
            >
              {fileIcon(p.filename)}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-gray-900 dark:text-gray-100 truncate">
                    {p.title}
                  </span>
                  {p.version && (
                    <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-gray-100 dark:bg-gray-700 text-gray-600">
                      v{p.version}
                    </span>
                  )}
                </div>
                <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                  <span className="truncate">{p.filename}</span>
                  <span>·</span>
                  <span>{formatSize(p.size_bytes)}</span>
                  <span>·</span>
                  <span>{formatDate(p.created_at)}</span>
                  {p.uploaded_by_email && (
                    <>
                      <span>·</span>
                      <span className="truncate">{p.uploaded_by_email}</span>
                    </>
                  )}
                </div>
                {p.description && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                    {p.description}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => handleDownload(p)}
                  className="p-1.5 text-gray-400 hover:text-purple-600 transition-colors"
                  title="Pobierz"
                >
                  <Download className="w-4 h-4" />
                </button>
                <DeleteButton onConfirm={() => deleteMutation.mutate(p.id)} />
              </div>
            </li>
          ))}
        </ul>
      )}

      {showUpload && (
        <UploadSheet
          clientId={clientId}
          onClose={() => setShowUpload(false)}
          onSuccess={() => {
            qc.invalidateQueries({ queryKey: ["client-one-pagers", clientId] });
            setShowUpload(false);
            showSuccess("Dodano one-pager");
          }}
          onError={(msg: string) => showError(msg)}
        />
      )}
    </section>
  );
}

// ── Upload sheet ─────────────────────────────────────────────────────────────

interface UploadSheetProps {
  clientId: number;
  onClose: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}

function UploadSheet({
  clientId,
  onClose,
  onSuccess,
  onError,
}: UploadSheetProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pickFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    if (!f) return setFile(null);
    if (!ALLOWED_EXT.test(f.name)) {
      setError("Tylko pliki PDF/DOCX/DOC");
      return;
    }
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`Plik za duży (max ${MAX_UPLOAD_MB} MB)`);
      return;
    }
    setError(null);
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return setError("Wybierz plik");
    if (!title.trim()) return setError("Podaj tytuł");

    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title.trim());
      if (description.trim()) fd.append("description", description.trim());
      if (version.trim()) fd.append("version", version.trim());

      await api.post(`/api/clients/${clientId}/one-pagers`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      onSuccess();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? "Błąd uploadu";
      setError(msg);
      onError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">
            Dodaj one-pager
          </h3>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Plik (PDF/DOCX, max {MAX_UPLOAD_MB} MB) *
            </label>
            <label className="flex items-center justify-center gap-2 px-3 py-3 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg hover:border-purple-500 cursor-pointer transition-colors">
              <Upload className="w-4 h-4 text-gray-500" />
              <span className="text-sm text-gray-600 dark:text-gray-300 truncate">
                {file ? file.name : "Wybierz plik…"}
              </span>
              <input
                type="file"
                accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                className="hidden"
                onChange={pickFile}
              />
            </label>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Tytuł *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="Oferta B2B dla ACME"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Wersja
            </label>
            <input
              type="text"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="1.0"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Opis
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="Notatki dla zespołu…"
            />
          </div>

          {error && (
            <div className="text-xs text-red-600 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-sm text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={submitting || !file || !title.trim()}
              className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 disabled:bg-gray-300 text-white text-sm font-medium transition-colors"
            >
              {submitting ? "Wysyłam…" : "Wyślij"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Section B: Contract terms ────────────────────────────────────────────────

function ContractTermsSection({ clientId }: { clientId: number }) {
  const qc = useQueryClient();
  const { showSuccess, showError } = useToast();

  const { data: terms, isLoading } = useQuery<ContractTerms | null>({
    queryKey: ["client-contract-terms", clientId],
    queryFn: () =>
      api
        .get(`/api/clients/${clientId}/contract-terms`)
        .then((r) => r.data ?? null),
  });

  const mutation = useMutation({
    mutationFn: (payload: Partial<ContractTerms>) =>
      api
        .put(`/api/clients/${clientId}/contract-terms`, payload)
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-contract-terms", clientId] });
      showSuccess("Zapisano warunki umowy");
    },
    onError: () => showError("Nie udało się zapisać"),
  });

  if (isLoading) {
    return (
      <section className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
        <p className="text-sm text-gray-400">Ładowanie warunków umowy…</p>
      </section>
    );
  }

  return (
    <TermsEditor
      initial={terms ?? EMPTY_TERMS}
      onSave={(payload) => mutation.mutate(payload)}
      saving={mutation.isPending}
    />
  );
}

interface TermsEditorProps {
  initial: ContractTerms;
  onSave: (payload: Partial<ContractTerms>) => void;
  saving: boolean;
}

function TermsEditor({ initial, onSave, saving }: TermsEditorProps) {
  const [form, setForm] = useState<ContractTerms>(initial);

  function update<K extends keyof ContractTerms>(key: K, value: ContractTerms[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const payload: Partial<ContractTerms> = { ...form };
    delete payload.id;
    delete payload.client_id;
    delete payload.updated_by_email;
    delete payload.updated_at;
    onSave(payload);
  }

  return (
    <form
      onSubmit={submit}
      className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6 space-y-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
            Najważniejsze rzeczy w umowie
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Kluczowe klauzule z umowy ramowej — off-limits, internalizacja,
            płatności
          </p>
          {initial.updated_at && (
            <p className="text-xs text-gray-400 mt-1">
              Ostatnia zmiana {formatDate(initial.updated_at)}
              {initial.updated_by_email ? ` · ${initial.updated_by_email}` : ""}
            </p>
          )}
        </div>
      </div>

      {/* Off-limits */}
      <FieldGroup title="Off-limits (ochrona pracowników klienta)">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <NumberField
            label="Okres (miesiące)"
            value={form.off_limits_months}
            onChange={(v) => update("off_limits_months", v)}
            placeholder="12"
          />
          <TextField
            label="Zakres"
            value={form.off_limits_scope}
            onChange={(v) => update("off_limits_scope", v)}
            placeholder="cała grupa kapitałowa"
          />
        </div>
        <TextareaField
          label="Notatki"
          value={form.off_limits_notes}
          onChange={(v) => update("off_limits_notes", v)}
          rows={2}
        />
      </FieldGroup>

      {/* Internalization */}
      <FieldGroup title="Internalizacja (klient bierze kontraktora na etat)">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <TextField
            label="Opłata (% rocznej pensji)"
            value={form.internalization_fee_pct}
            onChange={(v) => update("internalization_fee_pct", v)}
            placeholder="20.00"
          />
          <NumberField
            label="Min. okres współpracy (mies.)"
            value={form.internalization_min_months}
            onChange={(v) => update("internalization_min_months", v)}
            placeholder="6"
          />
          <NumberField
            label="Wypowiedzenie (dni)"
            value={form.internalization_notice_days}
            onChange={(v) => update("internalization_notice_days", v)}
            placeholder="30"
          />
        </div>
        <TextareaField
          label="Notatki"
          value={form.internalization_notes}
          onChange={(v) => update("internalization_notes", v)}
          rows={2}
        />
      </FieldGroup>

      {/* Payments */}
      <FieldGroup title="Płatności">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <NumberField
            label="Termin płatności (dni, net)"
            value={form.payment_net_days}
            onChange={(v) => update("payment_net_days", v)}
            placeholder="30"
          />
          <SelectField
            label="Waluta"
            value={form.payment_currency}
            onChange={(v) => update("payment_currency", v)}
            options={[
              { value: "", label: "—" },
              { value: "PLN", label: "PLN" },
              { value: "EUR", label: "EUR" },
              { value: "USD", label: "USD" },
              { value: "GBP", label: "GBP" },
            ]}
          />
          <SelectField
            label="Cykl faktur"
            value={form.payment_invoice_cycle}
            onChange={(v) => update("payment_invoice_cycle", v)}
            options={[
              { value: "", label: "—" },
              { value: "monthly", label: "Miesięczny" },
              { value: "biweekly", label: "Co 2 tyg." },
              { value: "other", label: "Inny" },
            ]}
          />
        </div>
        <TextField
          label="Odsetki za zwłokę"
          value={form.payment_late_fees}
          onChange={(v) => update("payment_late_fees", v)}
          placeholder="ustawowe"
        />
        <TextareaField
          label="Notatki"
          value={form.payment_notes}
          onChange={(v) => update("payment_notes", v)}
          rows={2}
        />
      </FieldGroup>

      {/* Termination & warranty */}
      <FieldGroup title="Wypowiedzenie i gwarancje">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <NumberField
            label="Okres wypowiedzenia umowy ramowej (dni)"
            value={form.notice_period_days}
            onChange={(v) => update("notice_period_days", v)}
            placeholder="30"
          />
          <NumberField
            label="Gwarancja wymiany kandydata (dni)"
            value={form.warranty_replacement_days}
            onChange={(v) => update("warranty_replacement_days", v)}
            placeholder="90"
          />
        </div>
        <TextareaField
          label="Notatki"
          value={form.warranty_notes}
          onChange={(v) => update("warranty_notes", v)}
          rows={2}
        />
      </FieldGroup>

      {/* Other */}
      <FieldGroup title="Inne klauzule">
        <TextareaField
          label=""
          value={form.other_clauses}
          onChange={(v) => update("other_clauses", v)}
          rows={6}
          placeholder="NDA, klauzule sub-kontraktowe, specyficzne kary umowne…"
        />
      </FieldGroup>

      <div className="flex items-center justify-end gap-2 pt-4 border-t border-gray-100 dark:border-gray-700">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-700 disabled:bg-gray-300 text-white text-sm font-medium transition-colors"
        >
          <Save className="w-4 h-4" />
          {saving ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
    </form>
  );
}

// ── Tiny field helpers (pattern reused inline) ───────────────────────────────

function FieldGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

interface BaseFieldProps {
  label: string;
  placeholder?: string;
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: BaseFieldProps & {
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  return (
    <div>
      {label && (
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
          {label}
        </label>
      )}
      <input
        type="text"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  placeholder,
}: BaseFieldProps & {
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
        {label}
      </label>
      <input
        type="number"
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />
    </div>
  );
}

function TextareaField({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
}: BaseFieldProps & {
  value: string | null;
  onChange: (v: string | null) => void;
  rows?: number;
}) {
  return (
    <div>
      {label && (
        <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
          {label}
        </label>
      )}
      <textarea
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        rows={rows}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: BaseFieldProps & {
  value: string | null;
  onChange: (v: string | null) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
        {label}
      </label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-900 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
