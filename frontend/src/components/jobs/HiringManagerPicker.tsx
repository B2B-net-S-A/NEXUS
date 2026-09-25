"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus, X } from "lucide-react";

import { extractErrorMsg } from "@/lib/api";
import {
  hiringManagerOptionsKey,
  saveHiringManager,
  type HiringManagerChoice,
} from "@/lib/hiring-manager";
import { HiringManagerCombobox } from "@/components/jobs/HiringManagerCombobox";

interface Props {
  jobId: number;
  clientId: number | null;
  value: number | null;
  valueName?: string | null;
  /** Ta sama bramka co edycja rekrutacji — reszta widzi tylko nazwisko. */
  canEdit: boolean;
  onSaved: () => void;
}

/**
 * Assign the client-side hiring manager to a job.
 *
 * The field existed on `jobs` long before anything read it, and the header only
 * rendered it once it was already set — so nobody ever learned it was there and
 * production has it filled on 0 of 4349 jobs. Traffit has no such field either,
 * so the import cannot backfill it: it has to be entered here.
 *
 * It is what the hiring-manager veto matches on, so every job filled in makes
 * that check able to fire. Od 25.09.2026 osobę spoza kontaktów klienta da się
 * wpisać — serwer zakłada ją jako kontakt klienta (`PUT …/hiring-manager`).
 */
export function HiringManagerPicker({
  jobId,
  clientId,
  value,
  valueName,
  canEdit,
  onSaved,
}: Props) {
  const queryClient = useQueryClient();
  const labelId = useId();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (choice: HiringManagerChoice | null) => {
    setSaving(true);
    setError(null);
    try {
      await saveHiringManager(jobId, choice);
      setEditing(false);
      if (choice?.kind === "new") {
        void queryClient.invalidateQueries({ queryKey: hiringManagerOptionsKey(clientId) });
        void queryClient.invalidateQueries({ queryKey: ["client-contacts", clientId] });
      }
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

  const current: HiringManagerChoice | null =
    value && valueName ? { kind: "contact", id: value, name: valueName } : null;

  return (
    <div className="flex flex-col gap-1 text-sm">
      <span id={labelId} className="text-xs uppercase tracking-wider text-muted-foreground">
        Hiring manager (klient):
      </span>
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <HiringManagerCombobox
            clientId={clientId}
            value={current}
            onChange={(choice) => void save(choice)}
            labelledBy={labelId}
            disabled={saving}
          />
        </div>
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
      </div>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export default HiringManagerPicker;
