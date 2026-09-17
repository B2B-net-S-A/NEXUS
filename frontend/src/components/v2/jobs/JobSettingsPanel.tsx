"use client";

import { type ReactNode, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import api, { clientTeamApi, pipelineTemplatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { formatIsoDatePl } from "@/lib/date-pl";
import { JOB_PRIORITY_LABEL, JOB_PRIORITY_OPTIONS } from "@/lib/job-priority";
import {
  CompetenceCategoryPicker,
  type CompetenceCategory,
} from "@/components/jobs/CompetenceCategoryPicker";
import type { JobPriority } from "@/types/client-profile";

interface DirectoryUser {
  id: number;
  name?: string | null;
  email?: string | null;
}

export interface JobSettingsPanelProps {
  jobId: number;
  clientId: number | null;
  jobTitle: string;
  jobDescription?: string | null;
  jobRequirements?: string | null;
  tacId: number | null;
  deliveryLeadId: number | null;
  pipelineTemplateId: number | null;
  competenceCategoryId: number | null;
  trainName: string | null;
  priority: JobPriority | null;
  /** ISO `YYYY-MM-DD` (`Job.deadline`), jak zwraca `GET /api/jobs/{id}`. */
  deadline: string | null;
  /** `canWritePipeline && job.update` — lustro `HiringManagerPicker` w tym
   *  samym doku (`JobReadinessDock`, `PATCH /api/jobs/{id}` to `TacPlus`). */
  canEdit: boolean;
}

type FieldKey =
  | "tac_id"
  | "delivery_lead_id"
  | "pipeline_template_id"
  | "competence_category_id"
  | "train_name"
  | "priority"
  | "deadline";

const ROW_LABEL_CLASS =
  "w-[6.5rem] shrink-0 text-[11px] uppercase tracking-wider text-muted-foreground";
const NOTE_INDENT_CLASS = "pl-[7rem]";
const CONTROL_CLASS =
  "min-w-0 flex-1 rounded border border-border bg-card px-2 py-1 text-xs dark:bg-muted";

/**
 * „Ustawienia zlecenia" — zakładka „Zespół" doku gotowości (krok 02,
 * `variant="champion"`), między `JobOwnershipPanel` (właściciel/współpracownicy)
 * a `HiringManagerPicker` (osoba po stronie klienta).
 *
 * Siedem pól, które dotąd żyły WYŁĄCZNIE w pełnym oknie edycji rekrutacji
 * (`EditJobModal` / `JobFormFields` w `AppShell.tsx`, 22 pola na dwóch ekranach
 * scrolla): Owner requestu (TAC), Delivery Lead, Szablon procesu, Kategoria
 * kompetencji, Program / Train, Priorytet, Deadline. Rekruter/właściciel
 * ZOSTAJE w `JobOwnershipPanel` — to inna oś (kto prowadzi kandydatów),
 * nie „ustawienia" rekrutacji.
 *
 * Każdy wiersz to read-view + „Zmień" → kontrolka, która zapisuje NATYCHMIAST
 * po zmianie (wzorzec `HiringManagerPicker`) przez `PATCH /api/jobs/{id}`
 * z JEDNYM polem — `JobUpdate` w backendzie czyta `model_fields_set`, więc
 * wysłanie samego zmienionego klucza nie rusza reszty rekrutacji.
 */
export function JobSettingsPanel({
  jobId,
  clientId,
  jobTitle,
  jobDescription,
  jobRequirements,
  tacId,
  deliveryLeadId,
  pipelineTemplateId,
  competenceCategoryId,
  trainName,
  priority,
  deadline,
  canEdit,
}: JobSettingsPanelProps) {
  const queryClient = useQueryClient();
  const [editingField, setEditingField] = useState<FieldKey | null>(null);
  const [savingField, setSavingField] = useState<FieldKey | null>(null);
  const [errorByField, setErrorByField] = useState<Partial<Record<FieldKey, string>>>({});
  // Szkic pola tekstowego (Program / Train) — jedyne pole bez kontrolki typu
  // select/date, więc jedyne, które potrzebuje lokalnego stanu przed zapisem.
  const [trainDraft, setTrainDraft] = useState(trainName ?? "");

  const startEdit = (field: FieldKey) => {
    setErrorByField((prev) => ({ ...prev, [field]: undefined }));
    if (field === "train_name") setTrainDraft(trainName ?? "");
    setEditingField(field);
  };
  const cancelEdit = () => setEditingField(null);

  const commit = async (field: FieldKey, value: unknown) => {
    setSavingField(field);
    setErrorByField((prev) => ({ ...prev, [field]: undefined }));
    try {
      await api.patch(`/api/jobs/${jobId}`, { [field]: value ?? null });
      // Ten sam komplet unieważnień co zapis Profilu Championa (M04-B02):
      // `["job", "<id>"]` (dok i strona czytają zlecenie z tego klucza),
      // `["job-readiness", jobId]` (deadline/priorytet nie są blokerami
      // bramki, ale rozjazd staleTime dałby przez 30 s stare dane) oraz
      // widoki poza tą stroną, które listują rekrutacje po tych samych polach.
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

  // ── Zespół klienta (TAC-y + Delivery Leadzi przypisani do KLIENTA tej
  //    rekrutacji) — ten sam klucz co `JobFormFields` w AppShell.tsx, więc
  //    otwarcie doku po edycji w oknie (albo odwrotnie) czyta z jednego cache'u.
  const { data: clientTeam } = useQuery({
    queryKey: ["client-team", clientId],
    queryFn: () => clientTeamApi.get(clientId as number).then((r) => r.data),
    enabled: clientId != null,
    staleTime: 30_000,
  });
  const clientTacs = clientTeam?.tacs ?? [];
  const headDl = clientTeam?.delivery_leads.find((d) => d.is_head) ?? null;
  const tacName = tacId != null ? clientTacs.find((t) => t.user_id === tacId)?.name ?? null : null;

  // ── Katalog DL-i (dla dowolnego klienta — DL rekrutacji nie musi dziś być
  //    w zespole TEGO klienta) — ten sam klucz co nagłówek `page.tsx`.
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

  const { data: templates } = useQuery({
    queryKey: ["pipeline-templates-list"],
    queryFn: () => pipelineTemplatesApi.list(false).then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const templateName =
    pipelineTemplateId != null
      ? templates?.find((t) => t.id === pipelineTemplateId)?.name ?? null
      : null;

  // Ten sam klucz co `CompetenceCategoryPicker` (montowany niżej w trybie
  // edycji) — react-query dedupe'uje, więc otwarcie edycji nie robi drugiego
  // żądania o listę pięciu kategorii.
  const { data: categories } = useQuery({
    queryKey: ["competence-categories"],
    queryFn: () => api.get<CompetenceCategory[]>("/api/competence-categories").then((r) => r.data),
    staleTime: 60 * 60_000,
  });
  const ccName =
    competenceCategoryId != null
      ? categories?.find((c) => c.id === competenceCategoryId)?.name_pl ?? null
      : null;

  // Podpowiedzi Program / Train zawężone do klienta — dociągane dopiero, gdy
  // wiersz jest w edycji (jak kontakty klienta w `HiringManagerPicker`).
  const { data: trainNamesData } = useQuery({
    queryKey: ["jobs-train-names", clientId],
    queryFn: () =>
      api
        .get<{ items: string[] }>("/api/jobs/train-names", {
          params: clientId != null ? { client_id: clientId } : {},
        })
        .then((r) => r.data),
    enabled: editingField === "train_name",
    staleTime: 60_000,
  });
  const trainNameSuggestions = trainNamesData?.items ?? [];

  return (
    <div
      className="space-y-1 rounded-lg border border-border/70 bg-card px-2.5 py-2"
      data-testid="job-settings-panel"
    >
      <div className="text-xs font-semibold text-foreground">Ustawienia zlecenia</div>

      <SettingsRow
        label="Owner (TAC)"
        canEdit={canEdit}
        editing={editingField === "tac_id"}
        saving={savingField === "tac_id"}
        error={errorByField.tac_id}
        onEdit={() => startEdit("tac_id")}
        onCancel={cancelEdit}
        value={tacId != null ? tacName ?? `Użytkownik #${tacId}` : "nie przypisano"}
        hint={
          clientTacs.length > 1 ? (
            <span>Klient ma {clientTacs.length} równorzędnych TAC-ów.</span>
          ) : null
        }
        editor={
          <select
            autoFocus
            aria-label="Owner requestu (TAC)"
            disabled={savingField === "tac_id"}
            defaultValue={tacId ?? ""}
            onChange={(e) => commit("tac_id", e.target.value ? Number(e.target.value) : null)}
            className={CONTROL_CLASS}
          >
            <option value="">— brak ownera requestu —</option>
            {clientTacs.length > 0 && (
              <optgroup label="TAC-y przypisani do klienta">
                {clientTacs.map((t) => (
                  <option key={t.user_id} value={t.user_id}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        }
      />

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
        label="Szablon procesu"
        canEdit={canEdit}
        editing={editingField === "pipeline_template_id"}
        saving={savingField === "pipeline_template_id"}
        error={errorByField.pipeline_template_id}
        onEdit={() => startEdit("pipeline_template_id")}
        onCancel={cancelEdit}
        value={
          pipelineTemplateId != null ? templateName ?? `#${pipelineTemplateId}` : "nie ustawiono"
        }
        editor={
          <select
            autoFocus
            aria-label="Szablon procesu rekrutacyjnego"
            disabled={savingField === "pipeline_template_id"}
            defaultValue={pipelineTemplateId ?? ""}
            onChange={(e) =>
              commit("pipeline_template_id", e.target.value ? Number(e.target.value) : null)
            }
            className={CONTROL_CLASS}
          >
            <option value="">— domyślny szablon —</option>
            {(templates ?? [])
              .filter((t) => !t.archived)
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.is_default ? " (domyślny)" : ""}
                </option>
              ))}
          </select>
        }
      />

      <SettingsRow
        label="Kat. kompetencji"
        canEdit={canEdit}
        editing={editingField === "competence_category_id"}
        saving={savingField === "competence_category_id"}
        error={errorByField.competence_category_id}
        onEdit={() => startEdit("competence_category_id")}
        onCancel={cancelEdit}
        value={competenceCategoryId != null ? ccName ?? `#${competenceCategoryId}` : "nie ustawiono"}
        editor={
          <div className="min-w-0 flex-1">
            <CompetenceCategoryPicker
              value={competenceCategoryId}
              onChange={(v) => commit("competence_category_id", v)}
              jobTitle={jobTitle}
              description={jobDescription ?? undefined}
              requirements={jobRequirements ?? undefined}
            />
          </div>
        }
      />

      <SettingsRow
        label="Program / Train"
        canEdit={canEdit}
        editing={editingField === "train_name"}
        saving={savingField === "train_name"}
        error={errorByField.train_name}
        onEdit={() => startEdit("train_name")}
        onCancel={cancelEdit}
        value={trainName || "nie ustawiono"}
        editor={
          <>
            <input
              autoFocus
              aria-label="Program / Train"
              list="job-settings-train-names"
              disabled={savingField === "train_name"}
              value={trainDraft}
              onChange={(e) => setTrainDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit("train_name", trainDraft.trim() || null);
                }
              }}
              onBlur={() => {
                if (trainDraft.trim() !== (trainName ?? "")) {
                  commit("train_name", trainDraft.trim() || null);
                }
              }}
              className={CONTROL_CLASS}
              placeholder="np. ART Payments"
            />
            <datalist id="job-settings-train-names">
              {trainNameSuggestions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </>
        }
      />

      <SettingsRow
        label="Priorytet"
        canEdit={canEdit}
        editing={editingField === "priority"}
        saving={savingField === "priority"}
        error={errorByField.priority}
        onEdit={() => startEdit("priority")}
        onCancel={cancelEdit}
        value={priority != null ? JOB_PRIORITY_LABEL[priority] ?? priority : "nie ustawiono"}
        editor={
          <select
            autoFocus
            aria-label="Priorytet"
            disabled={savingField === "priority"}
            defaultValue={priority ?? ""}
            onChange={(e) => commit("priority", e.target.value || null)}
            className={CONTROL_CLASS}
          >
            {JOB_PRIORITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
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
