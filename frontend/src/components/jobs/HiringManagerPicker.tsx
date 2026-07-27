"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2, UserPlus, X } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";

interface ClientContact {
  id: number;
  name: string;
  position?: string | null;
}

interface Props {
  jobId: number;
  clientId: number | null;
  value: number | null;
  valueName?: string | null;
  /** TacPlus on the backend — hide the control for everyone else. */
  canEdit: boolean;
  onSaved: () => void;
}

/**
 * Assign the client-side hiring manager to a job.
 *
 * The field existed on `jobs` long before anything read it, and the header only
 * rendered it once it was already set — so nobody ever learned it was there and
 * production has it filled on 0 of 4075 jobs. Traffit has no such field either,
 * so the import cannot backfill it: it has to be entered here.
 *
 * It is what the hiring-manager veto matches on, so every job filled in makes
 * that check able to fire.
 */
export function HiringManagerPicker({
  jobId,
  clientId,
  value,
  valueName,
  canEdit,
  onSaved,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ["client-contacts", clientId],
    queryFn: () =>
      api
        .get<ClientContact[]>(`/api/clients/${clientId}/contacts`)
        .then((r) => r.data),
    // Only fetch once the user actually opens the picker.
    enabled: editing && clientId != null,
    staleTime: 5 * 60 * 1000,
  });

  const save = async (contactId: number | null) => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/api/jobs/${jobId}`, {
        hiring_manager_contact_id: contactId,
      });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(extractErrorMsg(err));
    } finally {
      setSaving(false);
    }
  };

  // No client, no contacts to choose from.
  if (clientId == null) return null;

  if (!editing) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">
          Hiring manager (klient):
        </span>
        {value && valueName ? (
          <Link
            href={`/clients/${clientId}?tab=zespol`}
            className="font-medium text-violet-600 hover:underline"
          >
            {valueName}
          </Link>
        ) : (
          <span className="text-muted-foreground italic">nie przypisano</span>
        )}
        {canEdit && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            title="Kto po stronie klienta zamawia tę rekrutację"
          >
            <UserPlus className="w-3 h-3" />
            {value ? "Zmień" : "Przypisz"}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-xs uppercase tracking-wider text-muted-foreground">
        Hiring manager (klient):
      </span>
      {isLoading ? (
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      ) : (
        <select
          autoFocus
          disabled={saving}
          defaultValue={value ?? ""}
          onChange={(e) => save(e.target.value ? Number(e.target.value) : null)}
          className="rounded border border-border bg-card dark:bg-muted px-2 py-1 text-sm"
          aria-label="Wybierz hiring managera"
        >
          <option value="">— nie przypisano —</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.position ? ` — ${c.position}` : ""}
            </option>
          ))}
        </select>
      )}
      {saving ? (
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      ) : (
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setError(null);
          }}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Anuluj"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
      {contacts.length === 0 && !isLoading && (
        <span className="text-xs text-muted-foreground">
          Ten klient nie ma jeszcze kontaktów —{" "}
          <Link
            href={`/clients/${clientId}?tab=zespol`}
            className="text-primary hover:underline"
          >
            dodaj osobę
          </Link>
        </span>
      )}
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default HiringManagerPicker;
