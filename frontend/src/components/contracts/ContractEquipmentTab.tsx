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
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { useHrConfig } from "@/lib/api/hr";
import {
  useClientProvider,
  useContractEquipmentRegister,
  useHolderEquipment,
  type AssignmentRow,
  type HolderEquipment,
} from "@/lib/api/equipment";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { CATEGORY_LABELS, CONDITION_LABELS, itemIdentifier } from "@/components/equipment/equipment-format";
import { categoryIcon } from "@/components/equipment/equipment-visuals";
import { IssueWizard } from "@/components/equipment/IssueWizard";
import { ReturnWizard } from "@/components/equipment/ReturnWizard";
import { cn } from "@/lib/utils";
import {
  Cable,
  Check,
  Cpu,
  FileText,
  Headphones,
  IdCard,
  KeyRound,
  Laptop,
  Monitor,
  Package,
  PackageMinus,
  PackagePlus,
  Plus,
  Smartphone,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";

interface Props {
  contractId: number;
  readOnly?: boolean;
  /** Klient kontraktu — „kto daje sprzęt” w pustym stanie (sprzęt klienta = nic tu nie dodajemy). */
  clientId?: number | null;
  /** Nazwy plików z dokumentów kontraktu — podpowiedź o protokole sprzętu poza rejestrem. */
  documentNames?: readonly string[];
}

const ITEM_TYPE_LABELS: Record<EquipmentItemType, string> = {
  laptop: "Laptop",
  phone: "Telefon",
  monitor: "Monitor",
  headset: "Słuchawki",
  docking_station: "Stacja dokująca",
  security_token: "Token",
  keycard: "Karta dostępu",
  sim_card: "Karta SIM",
  other: "Inne",
};

const ITEM_TYPE_ICONS: Record<EquipmentItemType, LucideIcon> = {
  laptop: Laptop,
  phone: Smartphone,
  monitor: Monitor,
  headset: Headphones,
  docking_station: Cable,
  security_token: KeyRound,
  keycard: IdCard,
  sim_card: Cpu,
  other: Package,
};

const OWNER_LABELS: Record<EquipmentOwner, string> = {
  ours: "Nasze",
  client: "Klienta",
};

const STATUS_LABELS: Record<EquipmentReturnStatus, string> = {
  pending: "u konsultanta",
  returned: "zwrócony",
  lost: "zgubiony",
  written_off: "spisany",
};

const STATUS_TONE: Record<EquipmentReturnStatus, StatusDotTone> = {
  pending: "info",
  returned: "success",
  lost: "danger",
  written_off: "neutral",
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

/** Rzecz jest jeszcze u konsultanta (do licznika w nagłówku sekcji). */
function stillOut(row: TabRow): boolean {
  return row.kind === "register"
    ? row.assignment.returned_at == null
    : row.entry.return_status === "pending";
}

/** Zwrot w jednej kropce: stan, a pod nim termin albo dzień i stan zwrotu. */
function returnView(
  status: EquipmentReturnStatus,
  due: string | null,
  overdue: boolean,
  returnedOn: string | null,
  condition: string | null,
): { tone: StatusDotTone; label: string; note: string } {
  if (status === "pending") {
    if (overdue && due) return { tone: "danger", label: "zwrot po terminie", note: `termin ${formatDate(due)}` };
    return { tone: "info", label: STATUS_LABELS.pending, note: due ? `zwrot do ${formatDate(due)}` : "bez terminu zwrotu" };
  }
  return {
    tone: STATUS_TONE[status],
    label: STATUS_LABELS[status],
    note: [returnedOn ? formatDate(returnedOn) : null, condition].filter(Boolean).join(" · "),
  };
}

function DeviceCell({ icon: Icon, title, sub }: { icon: LucideIcon; title: string; sub: string }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium text-foreground" title={title}>
          {title}
        </span>
        {sub ? <span className={CALM_SUBLINE}>{sub}</span> : null}
      </span>
    </span>
  );
}

/**
 * „Sprzęt u konsultanta” w zakładce „Start i sprzęt” (wariant A, 20.11.2026):
 * spokojna tabela urządzeń z rejestru „Sprzęt” i wpisów ręcznych — co, numer,
 * kiedy wydano (z protokołem) i stan zwrotu kropką. Wydanie z magazynu
 * i zwrot przez recepcję kreatorem, wpisy ręczne z „Zwrócono” i usunięciem
 * jak dotąd.
 */
export function ContractEquipmentTab({ contractId, readOnly = false, clientId = null, documentNames = [] }: Props) {
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
  // Kto daje sprzęt u klienta — tylko do zdania w pustym stanie.
  const provider = useClientProvider(clientId ?? 0, clientId != null && !blocked && rows.length === 0).data;
  const protocolDoc = documentNames.find((name) => /sprz[eę]t/i.test(name)) ?? null;

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

  const out = rows.filter(stillOut).length;
  const back = rows.length - out;

  const manualActions = (item: ContractEquipmentItem) =>
    issuedFromRegister(item) ? (
      canUseRegister ? (
        <button
          type="button"
          onClick={() => setWizard("return")}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          <PackageMinus className="h-3.5 w-3.5" aria-hidden />
          Przyjmij zwrot
        </button>
      ) : (
        <span className="text-xs text-muted-foreground">zwrot przyjmuje recepcja</span>
      )
    ) : (
      <div className="inline-flex items-center gap-1">
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
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-foreground hover:bg-muted"
          >
            <Check className="h-3.5 w-3.5" aria-hidden />
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
              className="hit-area rounded p-1 hover:bg-muted"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmDeleteId(item.id)}
            aria-label={`Usuń pozycję: ${ITEM_TYPE_LABELS[item.item_type]}`}
            className="hit-area inline-flex items-center rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    );

  return (
    <section aria-label="Sprzęt" className="space-y-2 px-4 py-3">
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-baseline gap-2 text-[13.5px] font-semibold text-foreground">
          Sprzęt u konsultanta
          {/* Liczba tylko z pełnej odpowiedzi — przy ładowaniu i awarii byłaby zaniżona. */}
          {blocked || registerFailed || rows.length === 0 ? null : (
            <>
              {" "}
              <span className="text-[12px] font-normal tabular-nums text-muted-foreground">
                {out} u konsultanta{back ? ` · ${back} zwrócone` : ""}
              </span>
            </>
          )}
        </h3>
        <div className="flex flex-wrap items-center gap-1.5">
          {canUseRegister && register.data ? (
            <>
              {register.data.active.length > 0 ? (
                <Button type="button" size="sm" variant="ghost" onClick={() => setWizard("return")}>
                  <PackageMinus className="h-3.5 w-3.5" aria-hidden />
                  Przyjmij zwrot
                </Button>
              ) : null}
              <Button type="button" size="sm" variant="outline" onClick={() => setWizard("issue")}>
                <PackagePlus className="h-3.5 w-3.5" aria-hidden />
                Wydaj z magazynu
              </Button>
            </>
          ) : null}
          {!readOnly && (
            <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden />
              Dodaj sprzęt
            </Button>
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
        <p className="text-[13px] text-muted-foreground">Wczytywanie sprzętu…</p>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void equipmentQuery.refetch()}
        />
      ) : rows.length === 0 ? (
        registerFailed ? null : (
          <div className="space-y-1.5 rounded-lg bg-muted/50 px-3 py-2.5 text-[13px] text-muted-foreground">
            <p>
              {provider === "klienta"
                ? "Nic nie wydano z magazynu — u tego klienta konsultanci pracują na sprzęcie klienta, więc to normalne."
                : "Nic nie wydano z magazynu. Jeśli konsultant pracuje na sprzęcie klienta, nic tu nie dodawaj."}
            </p>
            {protocolDoc ? (
              <p className="flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
                W dokumentach jest „{protocolDoc}” — sprawdź, czy ten sprzęt nie powinien być w rejestrze.
              </p>
            ) : null}
          </div>
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] table-fixed text-[13px]">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "pb-1.5 text-left")}>Urządzenie</th>
                <th className={cn(CALM_HEAD, "w-[24%] pb-1.5 text-left")}>Numer</th>
                <th className={cn(CALM_HEAD, "w-[20%] pb-1.5 text-left")}>Wydano</th>
                <th className={cn(CALM_HEAD, "w-[18%] pb-1.5 text-left")}>Zwrot</th>
                {!readOnly && (
                  <th className={cn(CALM_HEAD, "w-[17%] pb-1.5 text-right")}>Akcje</th>
                )}
              </tr>
            </thead>
            <tbody>
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
                const kind = ITEM_TYPE_LABELS[item.item_type];
                const title = item.brand_model || kind;
                const ret = returnView(item.return_status, item.return_due_date, isOverdue(item), item.returned_date, null);
                return (
                  <tr key={`m-${item.id}`} className={cn(CALM_ROW, "last:border-b-0")}>
                    <td className="py-2 pr-3">
                      <DeviceCell
                        icon={ITEM_TYPE_ICONS[item.item_type] ?? Package}
                        title={title}
                        sub={[title === kind ? null : kind, item.owner === "client" ? "sprzęt klienta" : "nasz", fromRegister(item) ? "z magazynu" : null]
                          .filter(Boolean)
                          .join(" · ")}
                      />
                    </td>
                    <td className="py-2 pr-3 tabular-nums">
                      {item.serial_number ? (
                        <span className="block truncate text-foreground" title={item.serial_number}>
                          S/N {item.serial_number}
                        </span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {item.handed_over_date ? (
                        <span className="block tabular-nums text-foreground">{formatDate(item.handed_over_date)}</span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                      <span className={CALM_SUBLINE}>wpis ręczny</span>
                    </td>
                    <td className="py-2 pr-3">
                      <StatusDot tone={ret.tone} note={ret.note || undefined}>
                        {ret.label}
                      </StatusDot>
                    </td>
                    {!readOnly && <td className="py-2 text-right">{manualActions(item)}</td>}
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
    </section>
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
  const kind = CATEGORY_LABELS[assignment.category];
  const title = assignment.model_name || kind;
  const number = itemIdentifier(assignment);
  const ret = returnView(
    status,
    dueDate,
    overdue,
    warsawDateOf(assignment.returned_at),
    assignment.return_condition ? CONDITION_LABELS[assignment.return_condition].toLowerCase() : null,
  );
  return (
    <tr className={cn(CALM_ROW, "last:border-b-0")}>
      <td className="py-2 pr-3">
        <DeviceCell
          icon={categoryIcon(assignment.category, assignment.model_name)}
          title={title}
          sub={[title === kind ? null : kind, assignment.ownership === "klienta" ? "sprzęt klienta" : "nasz"]
            .filter(Boolean)
            .join(" · ")}
        />
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {number !== "—" ? (
          <span className="block truncate text-foreground" title={number}>
            {number}
          </span>
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
        {assignment.inventory_number ? (
          <span className={CALM_SUBLINE}>nr ewid. {assignment.inventory_number}</span>
        ) : null}
      </td>
      <td className="py-2 pr-3">
        <span className="block tabular-nums text-foreground">{formatDate(warsawDateOf(assignment.issued_at))}</span>
        <span className={CALM_SUBLINE}>
          z magazynu · {assignment.issue_protocol ? `protokół ${assignment.issue_protocol}` : "bez protokołu"}
        </span>
      </td>
      <td className="py-2 pr-3">
        <StatusDot tone={ret.tone} note={ret.note || undefined}>
          {ret.label}
        </StatusDot>
      </td>
      {!readOnly && (
        <td className="py-2 text-right">
          {status !== "pending" ? null : canUseRegister ? (
            <button
              type="button"
              onClick={onReturn}
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <PackageMinus className="h-3.5 w-3.5" aria-hidden />
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

const FIELD = "mt-1 w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm";

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
      className="space-y-3 rounded-lg border border-border bg-muted/40 p-3"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="block">
          <span className="text-xs text-muted-foreground">Typ</span>
          <Select
            value={form.item_type}
            onValueChange={(value) => setForm((f) => ({ ...f, item_type: value as EquipmentItemType }))}
          >
            <SelectTrigger aria-label="Typ" className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(ITEM_TYPE_LABELS).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="block">
          <span className="text-xs text-muted-foreground">Właściciel</span>
          <Select
            value={form.owner}
            onValueChange={(value) => setForm((f) => ({ ...f, owner: value as EquipmentOwner }))}
          >
            <SelectTrigger aria-label="Właściciel" className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(OWNER_LABELS).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="block">
          <span className="text-xs text-muted-foreground">Model</span>
          <input
            value={form.brand_model}
            onChange={(e) =>
              setForm((f) => ({ ...f, brand_model: e.target.value }))
            }
            className={FIELD}
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
            className={FIELD}
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
            className={FIELD}
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
            className={FIELD}
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
          className={FIELD}
          rows={2}
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Anuluj
        </Button>
        <Button type="submit" size="sm" disabled={submitting}>
          {submitting ? "Zapisywanie…" : "Zapisz"}
        </Button>
      </div>
    </form>
  );
}
