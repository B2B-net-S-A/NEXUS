"use client";

import { useState, useMemo } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import {
  UserSquare2,
  Plus,
  Search,
  ChevronDown,
  ChevronUp,
  Building2,
  Mail,
  Phone,
  Star,
  X,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Contact {
  id: number;
  client_id: number;
  client_name?: string;
  name: string;
  email?: string;
  phone?: string;
  position?: string;
  department?: string;
  is_decision_maker: boolean;
  notes?: string;
  last_contacted_at?: string;
  created_at: string;
}

interface ClientOption {
  id: number;
  name: string;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div
      className={cn(
        "fixed bottom-6 right-6 z-50 flex items-center gap-3 px-5 py-3.5 rounded-xl shadow-xl text-white text-sm font-medium transition-all",
        type === "success" ? "bg-green-600" : "bg-red-600"
      )}
    >
      {message}
      <button onClick={onClose} className="ml-1 opacity-70 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ── Add Contact Modal ─────────────────────────────────────────────────────────

function AddContactModal({
  clients,
  onClose,
  onSuccess,
}: {
  clients: ClientOption[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    client_id: "",
    position: "",
    department: "",
    is_decision_maker: false,
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (field: string, value: string | boolean) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name || !form.client_id) {
      setError("Imię i firma są wymagane");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.post("/api/contacts", {
        ...form,
        client_id: Number(form.client_id),
        email: form.email || undefined,
        phone: form.phone || undefined,
        position: form.position || undefined,
        department: form.department || undefined,
        notes: form.notes || undefined,
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-card rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-bold text-foreground dark:text-foreground">Dodaj kontakt</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-4 py-2">{error}</div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                Imię i nazwisko <span className="text-destructive">*</span>
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="Jan Kowalski"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            <div className="col-span-2">
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
                Firma <span className="text-destructive">*</span>
              </label>
              <select
                value={form.client_id}
                onChange={(e) => set("client_id", e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card"
              >
                <option value="">— wybierz firmę —</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                placeholder="jan@firma.pl"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">Telefon</label>
              <input
                type="tel"
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                placeholder="+48 500 000 000"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">Stanowisko</label>
              <input
                type="text"
                value={form.position}
                onChange={(e) => set("position", e.target.value)}
                placeholder="HR Manager"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">Dział</label>
              <input
                type="text"
                value={form.department}
                onChange={(e) => set("department", e.target.value)}
                placeholder="HR / IT"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>

            <div className="col-span-2">
              <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">Notatki</label>
              <textarea
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
                rows={2}
                placeholder="Dodatkowe informacje..."
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring resize-none"
              />
            </div>

            <div className="col-span-2">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.is_decision_maker}
                  onChange={(e) => set("is_decision_maker", e.target.checked)}
                  className="w-4 h-4 rounded border-border text-primary focus-visible:ring-ring"
                />
                <span className="text-sm text-foreground">Decision Maker</span>
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground transition-colors"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-5 py-2 rounded-lg text-sm font-medium transition-all"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              Zapisz
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Row expand ────────────────────────────────────────────────────────────────

function ContactRow({
  contact,
  expanded,
  onToggle,
}: {
  contact: Contact;
  expanded: boolean;
  onToggle: () => void;
}) {
  const router = useRouter();

  return (
    <>
      <tr
        onClick={onToggle}
        className={cn(
          "cursor-pointer transition-colors",
          expanded ? "bg-primary/10" : "hover:bg-muted dark:bg-card"
        )}
      >
        <td className="px-4 py-3 text-sm font-medium text-foreground dark:text-foreground">
          <div className="flex items-center gap-2">
            {contact.is_decision_maker && (
              <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400 flex-shrink-0" />
            )}
            {contact.name}
          </div>
        </td>
        <td className="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground">
          <button
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/clients/${contact.client_id}`);
            }}
            className="flex items-center gap-1 hover:text-primary transition-colors"
          >
            <Building2 className="w-3.5 h-3.5 text-muted-foreground" />
            {contact.client_name || `Klient #${contact.client_id}`}
          </button>
        </td>
        <td className="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground">
          {contact.email ? (
            <a
              href={`mailto:${contact.email}`}
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 hover:text-primary transition-colors"
            >
              <Mail className="w-3.5 h-3.5 text-muted-foreground" />
              {contact.email}
            </a>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground">
          {contact.phone ? (
            <a
              href={`tel:${contact.phone}`}
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 hover:text-primary transition-colors"
            >
              <Phone className="w-3.5 h-3.5 text-muted-foreground" />
              {contact.phone}
            </a>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground">
          {contact.position || <span className="text-muted-foreground">—</span>}
        </td>
        <td className="px-4 py-3">
          {contact.is_decision_maker ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
              <Star className="w-3 h-3" />
              DM
            </span>
          ) : (
            <span className="text-muted-foreground text-xs">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-muted-foreground">
          {contact.last_contacted_at
            ? formatRelativeTime(contact.last_contacted_at)
            : <span className="text-muted-foreground">brak</span>}
        </td>
        <td className="px-4 py-3 text-muted-foreground">
          {expanded ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-primary/10 border-t border-primary/15">
          <td colSpan={8} className="px-6 py-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              {contact.department && (
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">Dział</p>
                  <p className="font-medium text-foreground">{contact.department}</p>
                </div>
              )}
              {contact.notes && (
                <div className="col-span-2">
                  <p className="text-xs text-muted-foreground mb-0.5">Notatki</p>
                  <p className="text-foreground">{contact.notes}</p>
                </div>
              )}
              <div className="flex items-end gap-2 md:col-start-4 justify-end">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    window.open(`/clients/${contact.client_id}`, "_blank");
                  }}
                  className="flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Przejdź do klienta
                </button>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ContactsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [groupByCompany, setGroupByCompany] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const { data: contacts = [], isLoading } = useQuery<Contact[]>({
    queryKey: ["contacts", search],
    queryFn: () =>
      api
        .get("/api/contacts", { params: search ? { search } : undefined })
        .then((r) => r.data),
  });

  const { data: clientsData } = useQuery({
    queryKey: ["clients-list"],
    queryFn: () => api.get("/api/clients", { params: { page_size: 200 } }).then((r) => r.data),
  });

  const clients: ClientOption[] = (clientsData?.items ?? []).map((c: any) => ({
    id: c.id,
    name: c.name,
  }));

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Group contacts by company if toggled
  const grouped = useMemo(() => {
    if (!groupByCompany) return null;
    const map = new Map<string, Contact[]>();
    for (const c of contacts) {
      const key = c.client_name ?? `Klient #${c.client_id}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(c);
    }
    return map;
  }, [contacts, groupByCompany]);

  const toggleRow = (id: number) =>
    setExpandedId((prev) => (prev === id ? null : id));

  const tableHead = (
    <thead>
      <tr className="border-b border-border dark:border-border bg-muted dark:bg-card text-left">
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Imię</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Firma</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Email</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Telefon</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Stanowisko</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">DM</th>
        <th className="px-4 py-3 text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide">Ostatni kontakt</th>
        <th className="px-4 py-3 w-8" />
      </tr>
    </thead>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground">Kontakty</h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground">{contacts.length} kontaktów</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 bg-primary hover:bg-primary/90 hover:scale-[1.02] active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Dodaj kontakt
        </button>
      </div>

      {/* Search & filters */}
      <div className="flex gap-3 items-center">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Szukaj po imieniu lub emailu..."
            className="w-full pl-9 pr-4 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground dark:text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={groupByCompany}
            onChange={(e) => setGroupByCompany(e.target.checked)}
            className="w-4 h-4 rounded border-border text-primary focus-visible:ring-ring"
          />
          Grupuj wg firmy
        </label>
      </div>

      {/* Table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden shadow-sm">
        {isLoading ? (
          <div className="p-12 flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-primary animate-spin" />
          </div>
        ) : contacts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 bg-muted rounded-full flex items-center justify-center mb-4">
              <UserSquare2 className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-muted-foreground dark:text-muted-foreground font-medium">Brak kontaktów</p>
            <p className="text-sm text-muted-foreground mt-1">
              {search ? "Brak wyników dla podanego wyszukiwania" : "Dodaj pierwszy kontakt aby zacząć"}
            </p>
          </div>
        ) : groupByCompany && grouped ? (
          // Grouped view
          Array.from(grouped.entries()).map(([companyName, companyContacts]) => (
            <div key={companyName} className="mb-0">
              <div className="flex items-center gap-2 px-4 py-2 bg-muted dark:bg-card border-b border-border dark:border-border">
                <Building2 className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm font-semibold text-foreground">{companyName}</span>
                <span className="text-xs text-muted-foreground ml-1">({companyContacts.length})</span>
              </div>
              <table className="w-full text-sm">
                {tableHead}
                <tbody className="divide-y divide-gray-100">
                  {companyContacts.map((contact) => (
                    <ContactRow
                      key={contact.id}
                      contact={contact}
                      expanded={expandedId === contact.id}
                      onToggle={() => toggleRow(contact.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ))
        ) : (
          // Flat view
          <table className="w-full text-sm">
            {tableHead}
            <tbody className="divide-y divide-gray-100">
              {contacts.map((contact) => (
                <ContactRow
                  key={contact.id}
                  contact={contact}
                  expanded={expandedId === contact.id}
                  onToggle={() => toggleRow(contact.id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <AddContactModal
          clients={clients}
          onClose={() => setShowModal(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["contacts"] });
            showToast("Kontakt dodany pomyślnie", "success");
          }}
        />
      )}

      {/* Toast */}
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}
    </div>
  );
}
