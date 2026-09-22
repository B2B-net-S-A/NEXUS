"use client";

import { type ReactNode, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import api, { clientTeamApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { formatIsoDatePl } from "@/lib/date-pl";

interface DirectoryUser {
  id: number;
  name?: string | null;
  email?: string | null;
}

export interface JobSettingsPanelProps {
  jobId: number;
  clientId: number | null;
  deliveryLeadId: number | null;
  /** ISO `YYYY-MM-DD` (`Job.deadline`), jak zwraca `GET /api/jobs/{id}`. */
  deadline: string | null;
  /** `canWritePipeline && job.update` — lustro `HiringManagerPicker` w tym
   *  samym doku (`JobReadinessDock`, `PATCH /api/jobs/{id}` to `TacPlus`). */
  canEdit: boolean;
}

type FieldKey = "delivery_lead_id" | "deadline";

const ROW_LABEL_CLASS =
  "w-[6.5rem] shrink-0 text-[11px] uppercase tracking-wider text-muted-foreground";
const NOTE_INDENT_CLASS = "pl-[7rem]";
const CONTROL_CLASS =
  "min-w-0 flex-1 rounded border border-border bg-card px-2 py-1 text-xs dark:bg-muted";

/**
 * „Ustawienia zlecenia" — zakładka „Zespół" doku gotowości.
 *
 * Od 22.09.2026 (decyzja Artura przy stronie `/jobs/new`) DWA pola: Delivery
 * Lead i Deadline. Owner (TAC), Szablon procesu, Kategoria kompetencji,
 * Program / Train i Priorytet zniknęły z tworzenia I z ustawień — ustawia je
 * backend (szablon z klienta, kategoria z klasyfikatora, priorytet domyślny),
 * a dane w bazie zostają. Nie przywracaj ich tu bez decyzji właściciela.
 *
 * Każdy wiersz to read-view + „Zmień" → kontrolka, która zapisuje NATYCHMIAST
 * przez `PATCH /api/jobs/{id}` z JEDNYM polem (`JobUpdate` czyta
 * `model_fields_set`, więc reszta rekrutacji zostaje nietknięta).
 */
export function JobSettingsPanel({
  jobId,
  clientId,
  deliveryLeadId,
  deadline,
  canEdit,
}: JobSettingsPanelProps) {
  const queryClient = useQueryClient();
  const [editingField, setEditingField] = useState<FieldKey | null>(null);
  const [savingField, setSavingField] = useState<FieldKey | null>(null);
  const [errorByField, setErrorByField] = useState<Partial<Record<FieldKey, string>>>({});

  const startEdit = (field: FieldKey) => {
    setErrorByField((prev) => ({ ...prev, [field]: undefined }));
    setEditingField(field);
  };
  const cancelEdit = () => setEditingField(null);

  const commit = async (field: FieldKey, value: unknown) => {
    setSavingField(field);
    setErrorByField((prev) => ({ ...prev, [field]: undefined }));
    try {
      await api.patch(`/api/jobs/${jobId}`, { [field]: value ?? null });
      // Ten sam komplet unieważnień co zapis Profilu Championa (M04-B02).
      invalidateChampionDependents(queryClient, jobId);
      void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard", "my-jobs"] });
      setEditingField(null);
    } catch (err) {
      setErrorByField((prev) => ({
        ...prev,
        [field]: apiErrorMessage(err, "Nie udało się zapisać zmiany."),
      }));
    } finally {
      setSavingField(null);
    }
  };

  // Head DL klienta — do podpowiedzi „✓ Head DL klienta" / „Nadpisane".
  const { data: clientTeam } = useQuery({
    queryKey: ["client-team", clientId],
    queryFn: () => clientTeamApi.get(clientId as number).then((r) => r.data),
    enabled: clientId != null,
    staleTime: 30_000,
  });
  const headDl = clientTeam?.delivery_leads.find((d) => d.is_head) ?? null;

  // Katalog DL-i (dla dowolnego klienta) — ten sam klucz co nagłówek `page.tsx`.
  const { data: dlDirectory } = useQuery({
    queryKey: ["users-directory", "delivery-lead-roles"],
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["delivery_lead", "admin", "head_of_recruitment"] },
          // FastAPI wiąże powtórzone `roles=`; axios domyślnie wysyła
          // `roles[]=`, które backend ignoruje. Patrz `JobHandoffButton.tsx`.
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as DirectoryUser[]),
    staleTime: 5 * 60_000,
  });
  const deliveryLeadName =
    deliveryLeadId != null
      ? dlDirectory?.find((u) => u.id === deliveryLeadId)?.name ?? null
      : null;

  return (
    <div
      className="space-y-1 rounded-lg border border-border/70 bg-card px-2.5 py-2"
      data-testid="job-settings-panel"
    >
      <div className="text-xs font-semibold text-foreground">Ustawienia zlecenia</div>

      <SettingsRow
        label="Delivery Lead"
        canEdit={canEdit}
        editing={editingField === "delivery_lead_id"}
        saving={savingField === "delivery_lead_id"}
        error={errorByField.delivery_lead_id}
        onEdit={() => startEdit("delivery_lead_id")}
        onCancel={cancelEdit}
        value={
          deliveryLeadId != null
            ? deliveryLeadName ?? `Użytkownik #${deliveryLeadId}`
            : "nie przypisano"
        }
        hint={
          headDl && deliveryLeadId === headDl.user_id ? (
            <span className="text-success">✓ Head DL klienta</span>
          ) : headDl && deliveryLeadId != null ? (
            <span>Nadpisane (head DL klienta: {headDl.name})</span>
          ) : null
        }
        editor={
          <select
            autoFocus
            aria-label="Delivery Lead"
            disabled={savingField === "delivery_lead_id"}
            defaultValue={deliveryLeadId ?? ""}
            onChange={(e) =>
              commit("delivery_lead_id", e.target.value ? Number(e.target.value) : null)
            }
            className={CONTROL_CLASS}
          >
            <option value="">— brak DL —</option>
            {(dlDirectory ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.name || u.email}
              </option>
            ))}
          </select>
        }
      />

      <SettingsRow
        label="Deadline"
        canEdit={canEdit}
        editing={editingField === "deadline"}
        saving={savingField === "deadline"}
        error={errorByField.deadline}
        onEdit={() => startEdit("deadline")}
        onCancel={cancelEdit}
        value={deadline ? formatIsoDatePl(deadline) : "nie ustawiono"}
        editor={
          <input
            autoFocus
            type="date"
            aria-label="Deadline"
            disabled={savingField === "deadline"}
            defaultValue={deadline ?? ""}
            onChange={(e) => commit("deadline", e.target.value || null)}
            className={CONTROL_CLASS}
          />
        }
      />
    </div>
  );
}

interface SettingsRowProps {
  label: string;
  value: ReactNode;
  canEdit: boolean;
  editing: boolean;
  saving: boolean;
  error?: string;
  hint?: ReactNode;
  editor: ReactNode;
  onEdit: () => void;
  onCancel: () => void;
}

function SettingsRow({
  label,
  value,
  canEdit,
  editing,
  saving,
  error,
  hint,
  editor,
  onEdit,
  onCancel,
}: SettingsRowProps) {
  return (
    <div className="py-1">
      <div className="flex items-center gap-2">
        <span className={ROW_LABEL_CLASS}>{label}</span>
        {editing ? (
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {editor}
            {saving ? (
              <Loader2
                className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground"
                aria-hidden="true"
              />
            ) : (
              <button
                type="button"
                onClick={onCancel}
                aria-label="Anuluj"
                className="shrink-0 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="min-w-0 truncate text-xs font-medium text-foreground">{value}</span>
            {canEdit ? (
              <button
                type="button"
                onClick={onEdit}
                className="shrink-0 text-[11px] font-medium text-primary hover:underline"
              >
                Zmień
              </button>
            ) : null}
          </div>
        )}
      </div>
      {hint ? <div className={`${NOTE_INDENT_CLASS} text-[11px] text-muted-foreground`}>{hint}</div> : null}
      {error ? <div className={`${NOTE_INDENT_CLASS} text-[11px] text-destructive`}>{error}</div> : null}
    </div>
  );
}

export default JobSettingsPanel;
