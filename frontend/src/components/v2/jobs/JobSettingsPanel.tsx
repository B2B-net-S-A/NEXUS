"use client";

import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import api, { clientTeamApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { formatDeadlineTime, formatJobDeadline } from "@/lib/job-deadline";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import {
  PRIORITY_LEVEL_LABEL,
  PRIORITY_LEVEL_OPTIONS,
  rawPriorityForLevel,
  type PriorityLevel,
} from "@/lib/request-priority";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/Toast";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { JobCategoryRow } from "@/components/v2/jobs/JobCategoryRow";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";

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
  /** Godzina terminu `HH:MM[:SS]` (`Job.deadline_time`, 0406, czas Europe/Warsaw). */
  deadlineTime?: string | null;
  /** `canWritePipeline && job.update` — lustro `HiringManagerPicker` w tym
   *  samym doku (`JobReadinessDock`, `PATCH /api/jobs/{id}` to `TacPlus`). */
  canEdit: boolean;
  /**
   * Treść wiersza „Rekruter” — podaje ją dok (`JobOwnershipPanel`). Bez niej
   * wiersza nie ma.
   */
  recruiters?: ReactNode;
  /** Główna kategoria kompetencji rekrutacji (`competence_category_id`). */
  categoryId: number | null;
  /** Priorytet w trzech poziomach — `priorityLevelOf(job)`. */
  priorityLevel: PriorityLevel;
  /**
   * Czy bieżąca osoba ustawia priorytet: `can_set_priority` z serwera (admin,
   * Delivery Lead w swoim zakresie, TAC, Head of Recruitment) i zapis w sekcji.
   */
  canSetPriority: boolean;
}

type FieldKey = "delivery_lead_id" | "deadline";

const ROW_LABEL_CLASS =
  "text-[11px] uppercase tracking-wider text-muted-foreground";
const ROW_LABEL_COLUMN_CLASS = `w-[6.5rem] shrink-0 ${ROW_LABEL_CLASS}`;
const NOTE_INDENT_CLASS = "pl-[7rem]";
const CONTROL_CLASS =
  "w-0 min-w-0 flex-1 rounded border border-border bg-card px-2 py-1 text-xs dark:bg-muted";

/**
 * Karta zakładki „Zespół” doku gotowości: kto jest przy rekrutacji, do kiedy
 * i jak pilnie.
 *
 * Od 02.10.2026 (decyzja Artura, feedback Head of Recruitment) pięć wierszy
 * w stałej kolejności: Delivery Lead → Rekruter → Kategoria → Termin → Priorytet.
 * Trzy role zamiast „właściciela” i „współpracowników”: Delivery Lead otwiera
 * request, Rekruter nad nim pracuje, Kategoria tylko go widzi. Priorytet wrócił
 * w trzech poziomach (od 22.09 był niewidoczny). Kategorię potwierdza Delivery
 * Lead przy tworzeniu, a zmienia tutaj osoba z pełną edycją rekrutacji
 * (uczestnicy idą za kategorią). Owner (TAC), szablon procesu i Program / Train
 * nadal ustawia backend — nie przywracaj ich tu bez decyzji właściciela.
 *
 * Delivery Lead i Termin to read-view + „Zmień" → kontrolka, która zapisuje
 * NATYCHMIAST przez `PATCH /api/jobs/{id}` z JEDNYM polem (`JobUpdate` czyta
 * `model_fields_set`, więc reszta rekrutacji zostaje nietknięta). Priorytet
 * zapisuje się kliknięciem poziomu.
 */
export function JobSettingsPanel({
  jobId,
  clientId,
  deliveryLeadId,
  deadline,
  deadlineTime = null,
  canEdit,
  recruiters,
  categoryId,
  priorityLevel,
  canSetPriority,
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

  const commit = (field: FieldKey, value: unknown) =>
    save(field, { [field]: value ?? null });

  const save = async (field: FieldKey, body: Record<string, unknown>) => {
    setSavingField(field);
    setErrorByField((prev) => ({ ...prev, [field]: undefined }));
    try {
      await api.patch(`/api/jobs/${jobId}`, body);
      // Ten sam komplet unieważnień co zapis Profilu Championa (M04-B02)…
      invalidateChampionDependents(queryClient, jobId);
      // …oraz lista, jej liczniki i pulpit „Requesty i obłożenie”: Delivery
      // Lead i termin są tam kolumnami i filtrami.
      invalidateJobTeam(queryClient, jobId);
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
    <section
      aria-label="Zespół, termin i priorytet"
      className="divide-y divide-border/60 rounded-lg border border-border/70 bg-card px-2.5"
      data-testid="job-settings-panel"
    >
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

      {recruiters !== undefined ? (
        <StackedRow label="Rekruter">{recruiters}</StackedRow>
      ) : null}

      <StackedRow label="Kategoria">
        <JobCategoryRow categoryId={categoryId} jobId={jobId} canManage={canEdit} />
      </StackedRow>

      <SettingsRow
        label="Termin"
        canEdit={canEdit}
        editing={editingField === "deadline"}
        saving={savingField === "deadline"}
        error={errorByField.deadline}
        onEdit={() => startEdit("deadline")}
        onCancel={cancelEdit}
        value={formatJobDeadline(deadline, deadlineTime) ?? "nie ustawiono"}
        editor={
          <DeadlineEditor
            deadline={deadline}
            deadlineTime={deadlineTime}
            saving={savingField === "deadline"}
            onSave={(date, time) =>
              save("deadline", { deadline: date, deadline_time: date ? time : null })
            }
          />
        }
      />

      <PriorityRow jobId={jobId} level={priorityLevel} canSet={canSetPriority} />
    </section>
  );
}

/**
 * Priorytet w trzech poziomach. Kliknięcie zapisuje od razu, a przełącznik
 * pokazuje wybór natychmiast (wartość lokalna): strzałki klawiatury wybierają
 * od ręki, więc czekanie na serwer cofałoby zaznaczenie pod palcami.
 */
function PriorityRow({
  jobId,
  level,
  canSet,
}: {
  jobId: number;
  level: PriorityLevel;
  canSet: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const labelId = useId();
  const [value, setValue] = useState(level);
  // Ile zapisów jest w drodze.
  const [inFlight, setInFlight] = useState(0);
  // Wartość z serwera (odświeżona rekrutacja, zmiana innej osoby) wygrywa
  // z lokalną — ale dopiero gdy NAPRAWDĘ się zmieni, nie przy każdym renderze,
  // i nie w trakcie zapisów: odświeżenie po pierwszym zapisie serii cofałoby
  // na chwilę przełącznik do poziomu ze środka.
  const [seenLevel, setSeenLevel] = useState(level);
  if (level !== seenLevel) {
    setSeenLevel(level);
    if (inFlight === 0) setValue(level);
  }
  // Ostatni poziom potwierdzony przez serwer — do niego wracamy po odmowie.
  const confirmed = useRef(level);
  useEffect(() => {
    confirmed.current = level;
  }, [level]);
  // Ostatnio wybrany poziom: po odmowie cofamy tylko wtedy, gdy to on padł.
  const lastRequested = useRef<PriorityLevel | null>(null);
  // Zapisy idą po kolei: szybkie przejście strzałkami P1 → P2 → „Przyjmujemy”
  // nie może skończyć się na serwerze poziomem ze środka.
  const queue = useRef<Promise<void>>(Promise.resolve());

  const change = (next: PriorityLevel) => {
    setValue(next);
    lastRequested.current = next;
    setInFlight((count) => count + 1);
    queue.current = queue.current.then(async () => {
      try {
        await api.patch(`/api/jobs/${jobId}`, {
          priority: rawPriorityForLevel(next),
        });
        confirmed.current = next;
      } catch (err) {
        // Nowszy wybór czeka już w kolejce na swój zapis — jego nie cofamy.
        if (lastRequested.current === next) setValue(confirmed.current);
        toast.showError(apiErrorMessage(err, "Nie udało się zmienić priorytetu."));
      } finally {
        setInFlight((count) => count - 1);
        // Odpowiedź PATCH nie niesie obsady — odświeżamy, nie wkładamy do cache'u.
        invalidateJobTeam(queryClient, jobId);
      }
    });
  };

  if (!canSet) {
    return (
      <div className="flex items-center gap-2 py-2">
        <span className={ROW_LABEL_COLUMN_CLASS}>Priorytet</span>
        <div className="min-w-0 flex-1">
          {/* P2 to stan domyślny i nie ma plakietki — tu mówimy go słowem. */}
          {level === "p2" ? (
            <span className="text-xs font-medium text-foreground">
              {PRIORITY_LEVEL_LABEL.p2}
            </span>
          ) : (
            <RequestPriorityChip level={level} full size="md" />
          )}
        </div>
      </div>
    );
  }

  return (
    <StackedRow label="Priorytet" labelId={labelId}>
      <SegmentedRadio<PriorityLevel>
        size="sm"
        labelledBy={labelId}
        value={value}
        onChange={change}
        options={PRIORITY_LEVEL_OPTIONS}
      />
    </StackedRow>
  );
}

/**
 * Data i godzina terminu w jednym zapisie. Godzina jest opcjonalna (sam dzień
 * nadal działa), a bez daty jest zablokowana — backend i tak by ją wyczyścił.
 */
function DeadlineEditor({
  deadline,
  deadlineTime,
  saving,
  onSave,
}: {
  deadline: string | null;
  deadlineTime: string | null;
  saving: boolean;
  onSave: (date: string | null, time: string | null) => void;
}) {
  const [date, setDate] = useState(deadline ?? "");
  const [time, setTime] = useState(formatDeadlineTime(deadlineTime) ?? "");
  const submit = () => onSave(date || null, time || null);
  return (
    <form
      className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        autoFocus
        type="date"
        aria-label="Termin"
        disabled={saving}
        value={date}
        onChange={(e) => setDate(e.target.value)}
        className={`${CONTROL_CLASS} min-w-[8.5rem]`}
      />
      <input
        type="time"
        aria-label="Godzina terminu"
        disabled={saving || !date}
        value={time}
        onChange={(e) => setTime(e.target.value)}
        className="w-[5.5rem] shrink-0 rounded border border-border bg-card px-2 py-1 text-xs dark:bg-muted"
      />
      <button
        type="submit"
        disabled={saving}
        className="shrink-0 text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
      >
        Zapisz
      </button>
    </form>
  );
}

/**
 * Wiersz z etykietą NAD treścią. Dok ma 360 px: obok kolumny etykiet zostaje
 * ok. 190 px, a w tylu nie mieści się osoba z rolą („propozycja · rekruter”
 * ścinało się do jednej litery) ani trzy poziomy priorytetu.
 */
function StackedRow({
  label,
  labelId,
  children,
}: {
  label: string;
  /** `id` etykiety, gdy treść nazywa się nią (`aria-labelledby`). */
  labelId?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5 py-2">
      <span id={labelId} className={cn("block", ROW_LABEL_CLASS)}>
        {label}
      </span>
      <div className="min-w-0">{children}</div>
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
    <div className="py-2">
      <div className="flex items-center gap-2">
        <span className={ROW_LABEL_COLUMN_CLASS}>{label}</span>
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
                // Dwa wiersze mają „Zmień” — nazwa mówi, co się zmienia.
                aria-label={`Zmień: ${label}`}
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
