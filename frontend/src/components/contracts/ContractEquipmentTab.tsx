"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  contractEquipmentApi,
  type ContractEquipmentItem,
  type EquipmentItemType,
  type EquipmentOwner,
  type EquipmentReturnStatus,
} from "@/lib/api";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { apiErrorMessage } from "@/lib/api-error";
import { warsawToday } from "@/lib/warsaw-date";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { useHrConfig } from "@/lib/api/hr";
import {
  useContractEquipmentRegister,
  useHolderEquipment,
  type AssignmentRow,
  type HolderEquipment,
} from "@/lib/api/equipment";
import { CATEGORY_LABELS, itemIdentifier } from "@/components/equipment/equipment-format";
import { IssueWizard } from "@/components/equipment/IssueWizard";
import { ReturnWizard } from "@/components/equipment/ReturnWizard";
import { Laptop, Plus, Trash2, Check, AlertTriangle, X, PackagePlus, PackageMinus } from "lucide-react";

interface Props {
  contractId: number;
  readOnly?: boolean;
}

const ITEM_TYPE_LABELS: Record<EquipmentItemType, string> = {
  laptop: "Laptop",
  phone: "Telefon",
  monitor: "Monitor",
  headset: "Słuchawki",
  docking_station: "Docking station",
  security_token: "Token",
  keycard: "Karta dostępu",
  sim_card: "Karta SIM",
  other: "Inne",
};

const OWNER_LABELS: Record<EquipmentOwner, string> = {
  ours: "Nasze",
  client: "Klienta",
};

const STATUS_STYLES: Record<EquipmentReturnStatus, string> = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  returned: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  lost: "bg-destructive/15 text-red-800 dark:bg-red-900 dark:text-red-200",
  written_off:
    "bg-muted text-foreground dark:bg-muted dark:text-muted-foreground",
};

const STATUS_LABELS: Record<EquipmentReturnStatus, string> = {
  pending: "Oczekuje",
  returned: "Zwrócony",
  lost: "Zgubiony",
  written_off: "Spisany",
};

/** Pozycja wydana z magazynu (rejestr „Sprzęt”, 0464) — zwrot przyjmuje recepcja. */
type RegisterLinkedItem = ContractEquipmentItem & {
  item_id?: number | null;
  assignment_id?: number | null;
};

function fromRegister(item: ContractEquipmentItem): boolean {
  return (item as RegisterLinkedItem).item_id != null;
}

function issuedFromRegister(item: ContractEquipmentItem): boolean {
  return (item as RegisterLinkedItem).assignment_id != null && item.return_status === "pending";
}

function isOverdue(item: ContractEquipmentItem): boolean {
  if (item.return_status !== "pending" || !item.return_due_date) return false;
  // Porównujemy DNI KALENDARZOWE, nie chwile. `new Date("2026-08-20")`
  // ECMAScript parsuje jako północ UTC, czyli 02:00 w Warszawie, więc
  // zestawienie z `new Date()` malowało sprzęt z terminem DZIŚ jako spóźniony
  // przez 22 z 24 godzin doby — i rozjeżdżało się z backendem, który dla tej
  // samej pozycji wysyła powiadomienie „(0 dni)", a nie „po terminie".
  // Stringi "YYYY-MM-DD" porządkują się leksykograficznie, więc obchodzimy
  // parsowanie `Date` w całości.
  return item.return_due_date.slice(0, 10) < warsawToday();
}

/** Wiersz zakładki: wydanie z rejestru „Sprzęt” albo wpis ręczny `contract_equipment`. */
type TabRow =
  | { kind: "register"; assignment: AssignmentRow; entry: ContractEquipmentItem | null }
  | { kind: "manual"; entry: ContractEquipmentItem };

/**
 * Wiersze zakładki z dwóch źródeł (zgłoszenie 19.11.2026). Import plików
 * recepcji zakłada same wydania w rejestrze, bez wpisów zakładki: na kopii
 * produkcji z 19.11 wpisów było 0, a 27 obowiązujących kontraktów miało
 * niezwrócony sprzęt, który zakładka pokazywała jako „Brak pozycji”.
 *
 * Wpis założony przy wydaniu kreatorem (`assignment_id`) to ta sama rzecz co
 * wydanie — zostaje z niego termin zwrotu, bez drugiego wiersza. Wydanie
 * z anulowanego protokołu znika, tak jak znikał jego wpis zakładki. Najpierw
 * to, co jest jeszcze u konsultanta. Bez rejestru (`register` puste) — same
 * wpisy, jak przed modułem.
 */
function tabRows(
  register: HolderEquipment | undefined,
  entries: ContractEquipmentItem[],
): TabRow[] {
  if (!register) return entries.map((entry) => ({ kind: "manual", entry }));
  const assignmentOf = (entry: ContractEquipmentItem) =>
    (entry as RegisterLinkedItem).assignment_id ?? null;
  const linked = new Map<number, ContractEquipmentItem>();
  for (const entry of entries) {
    const id = assignmentOf(entry);
    if (id != null) linked.set(id, entry);
  }
  const inRegister = new Set(
    [...register.active, ...register.history].map((row) => row.assignment_id),
  );
  const cancelled = new Set(
    register.protocols.filter((p) => p.status === "anulowany").map((p) => p.id),
  );
  const registerRow = (assignment: AssignmentRow): TabRow => ({
    kind: "register",
    assignment,
    entry: linked.get(assignment.assignment_id) ?? null,
  });
  const manual = entries.filter((entry) => {
    const id = assignmentOf(entry);
    return id == null || !inRegister.has(id);
  });
  const returned = register.history.filter(
    (row) => row.issue_protocol_id == null || !cancelled.has(row.issue_protocol_id),
  );
  return [
    ...register.active.map(registerRow),
    ...manual
      .filter((entry) => entry.return_status === "pending")
      .map((entry): TabRow => ({ kind: "manual", entry })),
    ...returned.map(registerRow),
    ...manual
      .filter((entry) => entry.return_status !== "pending")
      .map((entry): TabRow => ({ kind: "manual", entry })),
  ];
}

function registerStatus(row: AssignmentRow): EquipmentReturnStatus {
  if (row.returned_at == null) return "pending";
  return row.return_condition === "zgubiony" ? "lost" : "returned";
}

/** Numer, po którym konsultant i recepcja poznają rzecz (S/N, IMEI, karta, numer ewidencyjny). */
function registerIdentifier(row: AssignmentRow): string {
  const number = row.inventory_number ? ` · nr ewid. ${row.inventory_number}` : "";
  return `${itemIdentifier(row)}${number} · z magazynu`;
}

export function ContractEquipmentTab({ contractId, readOnly = false }: Props) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  // Potwierdzenie w wierszu zamiast natywnego `confirm("Usunąć pozycję ? ")`
  // (audyt 24.09, N7 — literówka i zamrożona automatyzacja przeglądarki).
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const { showToast } = useToast();
  const onMutationError = (fallback: string) => (err: unknown) =>
    showToast(apiErrorMessage(err, fallback), "error");

  // Rejestr „Sprzęt” (moduł „Ludzi w NEXUSIE”): wydanie z magazynu z protokołem
  // i zwrot przez recepcję. Wydaje i przyjmuje zwrot tylko recepcja; listę
  // z rejestru widzi też podgląd Delivery. Bez modułu (404) albo bez dostępu
  // do rejestru (403) zakładka działa jak dotąd — wpisy ręczne.
  const hrConfig = useHrConfig();
  const canUseRegister = Boolean(
    hrConfig.data?.open_modules.equipment &&
      (hrConfig.data.me.equipment || hrConfig.data.me.is_admin),
  );
  const register = useHolderEquipment(
    canUseRegister ? "contract" : null,
    canUseRegister ? contractId : null,
  );
  const [wizard, setWizard] = useState<"issue" | "return" | null>(null);
  const registerList = useContractEquipmentRegister(contractId);
  const registerState = resolveViewState({
    isLoading: registerList.isLoading,
    error: registerList.error,
    isSuccess: registerList.isSuccess,
  });
  const registerFailed = registerState === "error";

  const equipmentQuery = useQuery({
    queryKey: ["contract-equipment", contractId],
    queryFn: async () => {
      const res = await contractEquipmentApi.list(contractId);
      return res.data as ContractEquipmentItem[];
    },
  });
  const rows = tabRows(
    registerState === "ready" ? registerList.data : undefined,
    equipmentQuery.data ?? [],
  );
  const manualState = resolveViewState({
    isLoading: equipmentQuery.isLoading,
    error: equipmentQuery.error,
    isSuccess: equipmentQuery.isSuccess,
  });
  const viewState = registerState === "loading" ? "loading" : manualState;
  const blocked = viewState === "loading" || isBlockingViewState(viewState);

  const createMut = useMutation({
    mutationFn: (payload: Partial<ContractEquipmentItem>) =>
      contractEquipmentApi.create(contractId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] });
      setAdding(false);
    },
    onError: onMutationError("Nie udało się dodać sprzętu."),
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Partial<ContractEquipmentItem>;
    }) => contractEquipmentApi.update(contractId, id, payload),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] }),
    onError: onMutationError("Nie udało się zapisać zmiany sprzętu."),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => contractEquipmentApi.delete(contractId, id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] }),
    onError: onMutationError("Nie udało się usunąć pozycji sprzętu."),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
          {/* Liczba tylko z pełnej odpowiedzi — przy ładowaniu i awarii byłaby zaniżona. */}
          Sprzęt kontraktora{blocked || registerFailed ? "" : ` (${rows.length})`}
        </h3>
        <div className="flex items-center gap-2">
          {canUseRegister && register.data ? (
            <>
              {register.data.active.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setWizard("return")}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border hover:bg-muted text-xs px-3 py-1.5"
                >
                  <PackageMinus className="w-3.5 h-3.5" aria-hidden />
                  Przyjmij zwrot
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => setWizard("issue")}
                className="inline-flex items-center gap-1.5 rounded-md border border-border hover:bg-muted text-xs px-3 py-1.5"
              >
                <PackagePlus className="w-3.5 h-3.5" aria-hidden />
                Wydaj z magazynu
              </button>
            </>
          ) : null}
          {!readOnly && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary hover:bg-primary/90 text-white text-xs px-3 py-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              Dodaj sprzęt
            </button>
          )}
        </div>
      </div>

      {!readOnly && adding && (
        <EquipmentForm
          onSubmit={(payload) => createMut.mutate(payload)}
          onCancel={() => setAdding(false)}
          submitting={createMut.isPending}
        />
      )}

      {!blocked && registerFailed ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać sprzętu wydanego z magazynu. Lista może być niepełna — spróbuj ponownie za chwilę."
          onRetry={() => void registerList.refetch()}
        />
      ) : null}

      {viewState === "loading" ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void equipmentQuery.refetch()}
        />
      ) : rows.length === 0 ? (
        registerFailed ? null : (
          <p className="text-sm text-muted-foreground italic">
            Brak pozycji. Dodaj laptop, telefon, token itp. aby śledzić zwrot.
          </p>
        )
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border dark:border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">Typ</th>
                <th className="text-left px-3 py-2">Model / serial</th>
                <th className="text-left px-3 py-2">Właściciel</th>
                <th className="text-left px-3 py-2">Termin zwrotu</th>
                <th className="text-left px-3 py-2">Status</th>
                {!readOnly && (
                  <th className="text-right px-3 py-2">Akcje</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {rows.map((row) => {
                if (row.kind === "register") {
                  return (
                    <RegisterRow
                      key={`r-${row.assignment.assignment_id}`}
                      assignment={row.assignment}
                      entry={row.entry}
                      readOnly={readOnly}
                      canUseRegister={canUseRegister}
                      onReturn={() => setWizard("return")}
                    />
                  );
                }
                const item = row.entry;
                return (
                <tr
                  key={`m-${item.id}`}
                  className={
                    isOverdue(item)
                      ? "bg-destructive/10 dark:bg-red-950/30"
                      : "bg-card dark:bg-card"
                  }
                >
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1.5">
                      <Laptop className="w-3.5 h-3.5 text-muted-foreground" />
                      {ITEM_TYPE_LABELS[item.item_type]}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-medium">{item.brand_model || "—"}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.serial_number || "—"}
                      {fromRegister(item) ? " · z magazynu" : ""}
                    </div>
                  </td>
                  <td className="px-3 py-2">{OWNER_LABELS[item.owner]}</td>
                  <td className="px-3 py-2">
                    {item.return_due_date ? (
                      <span className="flex items-center gap-1">
                        {isOverdue(item) && (
                          <AlertTriangle className="w-3.5 h-3.5 text-destructive" />
                        )}
                        {formatDate(item.return_due_date)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[item.return_status]}`}
                    >
                      {STATUS_LABELS[item.return_status]}
                    </span>
                  </td>
                  {!readOnly && (
                    <td className="px-3 py-2 text-right">
                      {issuedFromRegister(item) ? (
                        canUseRegister ? (
                          <button
                            type="button"
                            onClick={() => setWizard("return")}
                            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                          >
                            <PackageMinus className="w-3.5 h-3.5" aria-hidden />
                            Przyjmij zwrot
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            zwrot przyjmuje recepcja
                          </span>
                        )
                      ) : (
                      <div className="inline-flex gap-1">
                        {item.return_status === "pending" && (
                          <button
                            type="button"
                            onClick={() =>
                              updateMut.mutate({
                                id: item.id,
                                payload: {
                                  return_status: "returned",
                                  returned_date: warsawToday(),
                                },
                              })
                            }
                            className="inline-flex items-center gap-1 text-xs text-green-700 hover:underline"
                          >
                            <Check className="w-3.5 h-3.5" />
                            Zwrócono
                          </button>
                        )}
                        {confirmDeleteId === item.id ? (
                          <span className="inline-flex items-center gap-1 text-xs">
                            <span className="text-muted-foreground">Usunąć pozycję?</span>
                            <button
                              type="button"
                              onClick={() =>
                                deleteMut.mutate(item.id, {
                                  onSettled: () => setConfirmDeleteId(null),
                                })
                              }
                              disabled={deleteMut.isPending}
                              aria-label={`Potwierdź usunięcie: ${ITEM_TYPE_LABELS[item.item_type]}`}
                              className="rounded px-2 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:opacity-60"
                            >
                              Usuń
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              aria-label="Anuluj usuwanie"
                              className="rounded p-1 hover:bg-muted"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(item.id)}
                            aria-label={`Usuń pozycję: ${ITEM_TYPE_LABELS[item.item_type]}`}
                            className="inline-flex items-center text-xs text-destructive hover:underline"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                      )}
                    </td>
                  )}
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {wizard === "issue" && register.data ? (
        <IssueWizard presetHolder={register.data.holder} onClose={() => setWizard(null)} />
      ) : null}
      {wizard === "return" && register.data ? (
        <ReturnWizard presetHolder={register.data.holder} onClose={() => setWizard(null)} />
      ) : null}
    </div>
  );
}

interface RegisterRowProps {
  assignment: AssignmentRow;
  /** Wpis zakładki założony przy wydaniu kreatorem (termin zwrotu), jeśli jest. */
  entry: ContractEquipmentItem | null;
  readOnly: boolean;
  canUseRegister: boolean;
  onReturn: () => void;
}

/** Wydanie z rejestru: zwrot przyjmuje recepcja kreatorem (powstaje protokół zwrotu). */
function RegisterRow({
  assignment,
  entry,
  readOnly,
  canUseRegister,
  onReturn,
}: RegisterRowProps) {
  const status = registerStatus(assignment);
  const dueDate = entry?.return_due_date ?? null;
  const overdue = status === "pending" && entry != null && isOverdue(entry);
  return (
    <tr className={overdue ? "bg-destructive/10 dark:bg-red-950/30" : "bg-card dark:bg-card"}>
      <td className="px-3 py-2">
        <span className="inline-flex items-center gap-1.5">
          <Laptop className="w-3.5 h-3.5 text-muted-foreground" />
          {CATEGORY_LABELS[assignment.category]}
        </span>
      </td>
      <td className="px-3 py-2">
        <div className="font-medium">{assignment.model_name || "—"}</div>
        <div className="text-xs text-muted-foreground">{registerIdentifier(assignment)}</div>
      </td>
      <td className="px-3 py-2">
        {OWNER_LABELS[assignment.ownership === "klienta" ? "client" : "ours"]}
      </td>
      <td className="px-3 py-2">
        {dueDate ? (
          <span className="flex items-center gap-1">
            {overdue && <AlertTriangle className="w-3.5 h-3.5 text-destructive" />}
            {formatDate(dueDate)}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="px-3 py-2">
        <span
          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
        >
          {STATUS_LABELS[status]}
        </span>
      </td>
      {!readOnly && (
        <td className="px-3 py-2 text-right">
          {status !== "pending" ? null : canUseRegister ? (
            <button
              type="button"
              onClick={onReturn}
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <PackageMinus className="w-3.5 h-3.5" aria-hidden />
              Przyjmij zwrot
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">zwrot przyjmuje recepcja</span>
          )}
        </td>
      )}
    </tr>
  );
}

interface EquipmentFormProps {
  onSubmit: (payload: Partial<ContractEquipmentItem>) => void;
  onCancel: () => void;
  submitting: boolean;
}

function EquipmentForm({ onSubmit, onCancel, submitting }: EquipmentFormProps) {
  const [form, setForm] = useState({
    item_type: "laptop" as EquipmentItemType,
    owner: "ours" as EquipmentOwner,
    brand_model: "",
    serial_number: "",
    handed_over_date: warsawToday(),
    return_due_date: "",
    description: "",
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      item_type: form.item_type,
      owner: form.owner,
      brand_model: form.brand_model || null,
      serial_number: form.serial_number || null,
      handed_over_date: form.handed_over_date || null,
      return_due_date: form.return_due_date || null,
      description: form.description || null,
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border dark:border-border p-4 space-y-3 bg-muted dark:bg-muted"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-muted-foreground">Typ</span>
          <select
            value={form.item_type}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                item_type: e.target.value as EquipmentItemType,
              }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          >
            {Object.entries(ITEM_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Właściciel</span>
          <select
            value={form.owner}
            onChange={(e) =>
              setForm((f) => ({ ...f, owner: e.target.value as EquipmentOwner }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          >
            {Object.entries(OWNER_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Model</span>
          <input
            value={form.brand_model}
            onChange={(e) =>
              setForm((f) => ({ ...f, brand_model: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
            placeholder="ThinkPad X1 Carbon Gen 11"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Numer seryjny</span>
          <input
            value={form.serial_number}
            onChange={(e) =>
              setForm((f) => ({ ...f, serial_number: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Wydany</span>
          <input
            type="date"
            value={form.handed_over_date}
            onChange={(e) =>
              setForm((f) => ({ ...f, handed_over_date: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Termin zwrotu</span>
          <input
            type="date"
            value={form.return_due_date}
            onChange={(e) =>
              setForm((f) => ({ ...f, return_due_date: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs text-muted-foreground">Notatka</span>
        <textarea
          value={form.description}
          onChange={(e) =>
            setForm((f) => ({ ...f, description: e.target.value }))
          }
          className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          rows={2}
        />
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-muted-foreground hover:underline"
        >
          Anuluj
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-md px-3 py-1.5"
        >
          {submitting ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
    </form>
  );
}
