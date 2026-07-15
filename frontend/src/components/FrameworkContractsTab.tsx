"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Download,
  FileText,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import type {
  FrameworkContractRead,
  FrameworkContractStatus,
  FrameworkContractSignedVia,
  AmendmentRead,
} from "@/lib/api/dlPortal";

interface FrameworkContractsTabProps {
  clientId: number;
}

const STATUS_LABELS: Record<FrameworkContractStatus, string> = {
  draft: "Szkic",
  pending_signature: "Czeka na podpis",
  active: "Aktywna",
  expired: "Wygasła",
  terminated: "Rozwiązana",
  superseded: "Zastąpiona",
};

const STATUS_COLORS: Record<FrameworkContractStatus, string> = {
  draft: "bg-muted text-muted-foreground",
  pending_signature: "bg-yellow-100 text-yellow-800",
  active: "bg-green-100 text-green-800",
  expired: "bg-red-100 text-red-700",
  terminated: "bg-orange-100 text-orange-800",
  superseded: "bg-zinc-200 text-zinc-700",
};

export function FrameworkContractsTab({ clientId }: FrameworkContractsTabProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [expandedFcId, setExpandedFcId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listFrameworkContracts(clientId);
      return res.data;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (fcId: number) => dlPortalApi.deleteFrameworkContract(clientId, fcId),
    onSuccess: () => {
      showToast("Umowa usunięta / oznaczona jako zastąpiona", "success");
      queryClient.invalidateQueries({ queryKey: ["framework-contracts", clientId] });
    },
    onError: () => showToast("Nie udało się usunąć", "error"),
  });

  if (isLoading) {
    return <div className="text-muted-foreground">Ładowanie umów ramowych...</div>;
  }

  const contracts = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Umowy ramowe (MSA)</h3>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <Plus className="w-4 h-4" />
          Nowa umowa
        </button>
      </div>

      {contracts.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-8 text-center text-muted-foreground">
          <FileText className="w-12 h-12 mx-auto mb-2 opacity-40" />
          Brak umów ramowych. Dodaj pierwszą MSA aby móc tworzyć zamówienia.
        </div>
      ) : (
        <ul className="space-y-2">
          {contracts.map((fc) => (
            <FrameworkContractRow
              key={fc.id}
              fc={fc}
              clientId={clientId}
              expanded={expandedFcId === fc.id}
              onToggle={() => setExpandedFcId(expandedFcId === fc.id ? null : fc.id)}
              onDelete={() => {
                if (confirm(`Usunąć "${fc.name}"?`)) deleteMutation.mutate(fc.id);
              }}
            />
          ))}
        </ul>
      )}

      {showCreate && (
        <CreateFrameworkContractDialog
          clientId={clientId}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            queryClient.invalidateQueries({ queryKey: ["framework-contracts", clientId] });
          }}
        />
      )}
    </div>
  );
}

interface FrameworkContractRowProps {
  fc: FrameworkContractRead;
  clientId: number;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

function FrameworkContractRow({
  fc,
  clientId,
  expanded,
  onToggle,
  onDelete,
}: FrameworkContractRowProps) {
  const { showToast } = useToast();
  const expiringWarn =
    fc.days_to_expiry !== null && fc.days_to_expiry >= 0 && fc.days_to_expiry <= 30;

  // The file endpoint is Bearer-guarded — a raw <a href> sends no Authorization
  // header (and the relative path would resolve to the frontend origin anyway).
  // Fetch the bytes with the token and download the resulting same-origin blob.
  const handleDownload = async () => {
    if (!fc.filename) return;
    try {
      await downloadAuthenticatedFile(
        `/api/clients/${clientId}/framework-contracts/${fc.id}/file`,
        fc.filename,
      );
    } catch {
      showToast("Nie udało się pobrać pliku umowy.", "error");
    }
  };

  return (
    <li className="border border-border rounded-lg overflow-hidden bg-card">
      <div className="p-4 hover:bg-accent/30 cursor-pointer" onClick={onToggle}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{fc.name}</span>
              <span
                className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[fc.status]}`}
              >
                {STATUS_LABELS[fc.status]}
              </span>
              {expiringWarn && (
                <span className="text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  wygasa za {fc.days_to_expiry} dni
                </span>
              )}
              {fc.amendments_count > 0 && (
                <span className="text-xs text-muted-foreground">
                  {fc.amendments_count} {fc.amendments_count === 1 ? "aneks" : "aneksy"}
                </span>
              )}
            </div>
            <div className="flex items-center gap-4 mt-1 text-xs text-muted-foreground">
              {fc.effective_date && (
                <span className="flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  od {fc.effective_date}
                </span>
              )}
              {fc.expiry_date && <span>do {fc.expiry_date}</span>}
              {fc.currency && <span>{fc.currency}</span>}
              {fc.has_file && fc.filename && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDownload();
                  }}
                  className="flex items-center gap-1 hover:text-violet-600"
                >
                  <Download className="w-3 h-3" />
                  {fc.filename}
                </button>
              )}
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="text-muted-foreground hover:text-destructive p-1"
            title="Usuń"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
      {expanded && <AmendmentsSection clientId={clientId} fcId={fc.id} />}
    </li>
  );
}

interface AmendmentsSectionProps {
  clientId: number;
  fcId: number;
}

function AmendmentsSection({ clientId, fcId }: AmendmentsSectionProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["amendments", clientId, fcId],
    queryFn: async () => {
      const res = await dlPortalApi.listAmendments(clientId, fcId);
      return res.data;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (amendmentId: number) =>
      dlPortalApi.deleteAmendment(clientId, fcId, amendmentId),
    onSuccess: () => {
      showToast("Aneks usunięty", "success");
      queryClient.invalidateQueries({ queryKey: ["amendments", clientId, fcId] });
      queryClient.invalidateQueries({ queryKey: ["framework-contracts", clientId] });
    },
  });

  if (isLoading) return <div className="px-6 pb-4 text-xs text-muted-foreground">Ładowanie aneksów…</div>;
  const amendments: AmendmentRead[] = data ?? [];

  return (
    <div className="bg-muted/30 px-6 py-4 border-t border-border">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-medium">Aneksy</h4>
        <button
          onClick={() => setShowCreate(true)}
          className="text-xs text-violet-600 hover:text-violet-700 flex items-center gap-1"
        >
          <Plus className="w-3 h-3" />
          Dodaj aneks
        </button>
      </div>
      {amendments.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">Brak aneksów.</p>
      ) : (
        <ul className="space-y-1.5">
          {amendments.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between text-sm bg-card border border-border rounded p-2"
            >
              <div>
                <span className="font-medium">{a.name}</span>
                <span className="text-xs text-muted-foreground ml-2">
                  obowiązuje od {a.effective_date}
                </span>
                {a.changes_summary && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {a.changes_summary}
                  </p>
                )}
              </div>
              <button
                onClick={() => {
                  if (confirm(`Usunąć aneks "${a.name}"?`)) deleteMutation.mutate(a.id);
                }}
                className="text-muted-foreground hover:text-destructive p-1"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {showCreate && (
        <CreateAmendmentDialog
          clientId={clientId}
          fcId={fcId}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            queryClient.invalidateQueries({ queryKey: ["amendments", clientId, fcId] });
            queryClient.invalidateQueries({ queryKey: ["framework-contracts", clientId] });
          }}
        />
      )}
    </div>
  );
}

interface CreateFrameworkContractDialogProps {
  clientId: number;
  onClose: () => void;
  onCreated: () => void;
}

function CreateFrameworkContractDialog({
  clientId,
  onClose,
  onCreated,
}: CreateFrameworkContractDialogProps) {
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [contractStatus, setContractStatus] = useState<FrameworkContractStatus>("draft");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [signedVia, setSignedVia] = useState<FrameworkContractSignedVia>("upload");
  const [currency, setCurrency] = useState("PLN");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("contract_status", contractStatus);
      if (effectiveDate) fd.append("effective_date", effectiveDate);
      if (expiryDate) fd.append("expiry_date", expiryDate);
      fd.append("signed_via", signedVia);
      if (currency) fd.append("currency", currency);
      if (notes) fd.append("notes", notes);
      if (file) fd.append("file", file);
      await dlPortalApi.createFrameworkContract(clientId, fd);
      showToast("Umowa ramowa dodana", "success");
      onCreated();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Błąd zapisu";
      showToast(msg, "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={handleSubmit}
        className="bg-card rounded-lg shadow-xl max-w-md w-full p-6 space-y-3"
      >
        <h3 className="text-lg font-semibold">Nowa umowa ramowa</h3>
        <label className="block">
          <span className="text-sm">Nazwa</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. MSA 2026"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Status</span>
            <select
              value={contractStatus}
              onChange={(e) =>
                setContractStatus(e.target.value as FrameworkContractStatus)
              }
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="draft">Szkic</option>
              <option value="active">Aktywna</option>
              <option value="pending_signature">Czeka na podpis</option>
            </select>
          </label>
          <label>
            <span className="text-sm">Sposób podpisu</span>
            <select
              value={signedVia}
              onChange={(e) => setSignedVia(e.target.value as FrameworkContractSignedVia)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="upload">Skan / PDF</option>
              <option value="autenti">Autenti</option>
            </select>
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Obowiązuje od</span>
            <input
              type="date"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Wygasa</span>
            <input
              type="date"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>
        <label>
          <span className="text-sm">Waluta</span>
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            maxLength={3}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="PLN"
          />
        </label>
        <label>
          <span className="text-sm">Plik PDF (opcjonalny)</span>
          <input
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 w-full text-sm"
          />
        </label>
        <label>
          <span className="text-sm">Notatki</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-3 py-2 text-sm border border-border rounded">
            Anuluj
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 flex items-center gap-1"
          >
            <Upload className="w-4 h-4" />
            {submitting ? "Zapisywanie…" : "Zapisz"}
          </button>
        </div>
      </form>
    </div>
  );
}

interface CreateAmendmentDialogProps {
  clientId: number;
  fcId: number;
  onClose: () => void;
  onCreated: () => void;
}

function CreateAmendmentDialog({
  clientId,
  fcId,
  onClose,
  onCreated,
}: CreateAmendmentDialogProps) {
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changesSummary, setChangesSummary] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !effectiveDate) return;
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("effective_date", effectiveDate);
      if (changesSummary) fd.append("changes_summary", changesSummary);
      if (file) fd.append("file", file);
      await dlPortalApi.createAmendment(clientId, fcId, fd);
      showToast("Aneks dodany", "success");
      onCreated();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Błąd zapisu", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={handleSubmit}
        className="bg-card rounded-lg shadow-xl max-w-md w-full p-6 space-y-3"
      >
        <h3 className="text-lg font-semibold">Nowy aneks</h3>
        <label className="block">
          <span className="text-sm">Nazwa</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. Aneks 1 — zmiana stawek"
          />
        </label>
        <label>
          <span className="text-sm">Obowiązuje od</span>
          <input
            type="date"
            value={effectiveDate}
            onChange={(e) => setEffectiveDate(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          />
        </label>
        <label>
          <span className="text-sm">Opis zmian</span>
          <textarea
            value={changesSummary}
            onChange={(e) => setChangesSummary(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
          />
        </label>
        <label>
          <span className="text-sm">Plik PDF (opcjonalny)</span>
          <input
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 w-full text-sm"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-3 py-2 text-sm border border-border rounded">
            Anuluj
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Zapisz"}
          </button>
        </div>
      </form>
    </div>
  );
}
