"use client";
// A · Start i sprzęt — łączy dzisiejsze „Wejście” i „Sprzęt” w jedną checklistę:
// nagłówek postępu, potem „Formalności”, „Lista startowa”, „Sprzęt u
// konsultanta” i „Panel konsultanta” jednym wierszem. Przełącznik trybu panelu
// to ustawienie firmy (Ustawienia), więc tu widać tylko jego stan; mail
// powitalny pokazuje dopiero okno aktywacji.
//
// Sprzęt czytamy z rejestru „Sprzęt” (`/api/equipment/contracts/{id}`) i ze
// starej tabeli kontraktu (`/api/contracts/{id}/equipment`) — na stagingu cały
// sprzęt jest w rejestrze, stara tabela jest pusta. Hooki i model urządzenia
// są eksportowane, bo korzystają z nich też `WejscieB` i `SprzetB`.
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Cable,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Cpu,
  FileText,
  Headphones,
  IdCard,
  KeyRound,
  Laptop,
  Monitor,
  Package,
  Plus,
  Smartphone,
  type LucideIcon,
} from "lucide-react";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { CATEGORY_LABELS, CONDITION_LABELS, phoneDisplay } from "@/components/equipment/equipment-format";
import { categoryIcon } from "@/components/equipment/equipment-visuals";
import api, { type ContractEquipmentItem, type EquipmentItemType } from "@/lib/api";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { PANEL_STATE_OPTIONS, type PanelProposal } from "@/lib/api/consultant-panel";
import type { AssignmentRow, EquipmentProvider, HolderEquipment } from "@/lib/api/equipment";
import type { ClientStartDoc } from "@/lib/api/start-documents";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkContract, useMkDocuments, useMkEquipment, type MkContract, type MkDocument } from "../shared/data";
import { daysUntil, fmtDate, plural, relDays } from "../shared/format";
import type { TabProps } from "./types";

// ── Dane (tylko GET) ──────────────────────────────────────────────────────────

const get = <T,>(url: string) => api.get<T>(url).then((r) => r.data);

/** Pozycja starej listy onboardingu (`/api/contracts/{id}/onboarding`). */
export interface MkOnboardingItem {
  id: number;
  label: string;
  status: "pending" | "done" | "na";
  assigned_to: number | null;
  due_date: string | null;
  notes: string | null;
  order: number;
  created_at: string;
}

export function useMkOnboarding(id: number) {
  return useQuery<MkOnboardingItem[]>({
    queryKey: ["mk-onboarding", id],
    queryFn: () => get<MkOnboardingItem[]>(`/api/contracts/${id}/onboarding`),
    enabled: Number.isFinite(id),
  });
}

/** Panel konsultanta: stan aktywacji, adres z kartoteki i tryb firmy. */
export function useMkPanel(id: number) {
  return useQuery<PanelProposal>({
    queryKey: ["mk-panel", id],
    queryFn: () => get<PanelProposal>(`/api/consultant-panel/contracts/${id}`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

/** Kto daje sprzęt u klienta (`nasz` / `klienta` / `nieznany`). */
export function useMkProvider(clientId: number | undefined) {
  return useQuery<{ equipment_provider: EquipmentProvider }>({
    queryKey: ["mk-equipment-provider", clientId],
    queryFn: () => get<{ equipment_provider: EquipmentProvider }>(`/api/equipment/clients/${clientId}/provider`),
    enabled: clientId != null,
    retry: false,
  });
}

function useMkRegister(id: number) {
  return useQuery<HolderEquipment>({
    queryKey: ["mk-register", id],
    queryFn: () => get<HolderEquipment>(`/api/equipment/contracts/${id}`),
    enabled: Number.isFinite(id),
    retry: false,
  });
}

/** Paczki importu rejestru — wydanie z importu ma `issued_at` = chwila zatwierdzenia paczki. */
function useMkImports() {
  return useQuery<{ items: { applied_at: string | null }[] }>({
    queryKey: ["mk-equipment-imports"],
    queryFn: () => get<{ items: { applied_at: string | null }[] }>(`/api/equipment/imports`),
    retry: false,
    staleTime: 10 * 60_000,
  });
}

function useMkClientStartDocs(clientId: number | undefined) {
  return useQuery<ClientStartDoc[]>({
    queryKey: ["mk-start-docs-client", clientId],
    queryFn: () => get<{ items: ClientStartDoc[] }>(`/api/start-documents/clients/${clientId}`).then((d) => d.items),
    enabled: clientId != null,
    retry: false,
  });
}

// ── Model urządzenia (rejestr + stara tabela) ─────────────────────────────────

export interface MkDevice {
  key: string;
  icon: LucideIcon;
  /** „Laptop”, „Karta dostępu”. */
  kind: string;
  /** Model, a gdy model to nazwa rodzaju — sam rodzaj. */
  title: string;
  ours: boolean | null;
  /** „S/N GCW98F2”, „IMEI …”, „+48 577 317 001”, „nr 1506”. */
  number: string | null;
  numberNote: string | null;
  issuedOn: string | null;
  /** Wpis z importu arkusza: data wydania nieznana, wiadomo tylko „przed”. */
  fromImport: boolean;
  protocol: string | null;
  returnDue: string | null;
  returnedOn: string | null;
  returnNote: string | null;
  lost: boolean;
}

const LEGACY_KIND: Record<EquipmentItemType, { label: string; icon: LucideIcon }> = {
  laptop: { label: "Laptop", icon: Laptop },
  phone: { label: "Telefon", icon: Smartphone },
  monitor: { label: "Monitor", icon: Monitor },
  headset: { label: "Słuchawki", icon: Headphones },
  docking_station: { label: "Stacja dokująca", icon: Cable },
  security_token: { label: "Token", icon: KeyRound },
  keycard: { label: "Karta dostępu", icon: IdCard },
  sim_card: { label: "Karta SIM", icon: Cpu },
  other: { label: "Inne", icon: Package },
};

function titleOf(model: string | null, kind: string): string {
  const m = (model ?? "").trim();
  return m || kind;
}

function registerNumber(row: AssignmentRow): string | null {
  if (row.category === "karta_sim") return phoneDisplay(row.phone_number);
  if (row.category === "karta_dostepu") return row.access_card_number ? `nr ${row.access_card_number}` : null;
  if (row.category === "telefon" && row.imei) return `IMEI ${row.imei}`;
  if (row.serial_number) return `S/N ${row.serial_number}`;
  return row.imei ? `IMEI ${row.imei}` : null;
}

function fromRegister(row: AssignmentRow, imported: Set<number>): MkDevice {
  const kind = CATEGORY_LABELS[row.category];
  return {
    key: `r-${row.assignment_id}`,
    icon: categoryIcon(row.category, row.model_name),
    kind,
    title: titleOf(row.model_name, kind),
    ours: row.ownership === "nasz",
    number: registerNumber(row),
    numberNote: row.inventory_number ? `nr ewid. ${row.inventory_number}` : null,
    issuedOn: warsawDateOf(row.issued_at),
    fromImport: imported.has(Date.parse(row.issued_at)),
    protocol: row.issue_protocol,
    returnDue: null,
    returnedOn: warsawDateOf(row.returned_at),
    returnNote: row.return_condition ? CONDITION_LABELS[row.return_condition] : null,
    lost: row.return_condition === "zgubiony",
  };
}

function fromLegacy(item: ContractEquipmentItem): MkDevice {
  const kind = LEGACY_KIND[item.item_type] ?? LEGACY_KIND.other;
  return {
    key: `l-${item.id}`,
    icon: kind.icon,
    kind: kind.label,
    title: titleOf(item.brand_model, kind.label),
    ours: item.owner === "ours",
    number: item.serial_number ? `S/N ${item.serial_number}` : null,
    numberNote: null,
    issuedOn: item.handed_over_date,
    fromImport: false,
    protocol: null,
    returnDue: item.return_due_date,
    returnedOn: item.return_status === "returned" ? item.returned_date : null,
    returnNote: item.return_status === "written_off" ? "Spisany" : null,
    lost: item.return_status === "lost",
  };
}

/** Sprzęt kontraktu z obu źródeł; najpierw to, co jest u konsultanta. */
export function useMkDevices(id: number) {
  const register = useMkRegister(id);
  const legacy = useMkEquipment(id);
  const imports = useMkImports();
  const imported = new Set(
    (imports.data?.items ?? []).map((b) => (b.applied_at ? Date.parse(b.applied_at) : Number.NaN)),
  );
  const fromReg = register.data ? [...register.data.active, ...register.data.history].map((r) => fromRegister(r, imported)) : [];
  const fromOld = ((legacy.data ?? []) as unknown as ContractEquipmentItem[]).map(fromLegacy);
  const devices = [...fromReg, ...fromOld].sort((a, b) => Number(Boolean(a.returnedOn)) - Number(Boolean(b.returnedOn)));
  return {
    devices,
    isLoading: register.isLoading || legacy.isLoading,
    // Awaria obu źródeł to błąd, nie „brak sprzętu”.
    isError: register.isError && legacy.isError,
    isSuccess: register.isSuccess || legacy.isSuccess,
  };
}

export function deviceIssued(d: MkDevice): { main: string; note: string } {
  const protocol = d.protocol ? `protokół ${d.protocol}` : "bez protokołu";
  if (d.fromImport && d.issuedOn) return { main: `przed ${fmtDate(d.issuedOn)}`, note: `z importu arkusza · ${protocol}` };
  return { main: fmtDate(d.issuedOn), note: protocol };
}

export function deviceReturn(d: MkDevice): { tone: StatusDotTone; label: string; note: string } {
  if (d.lost) return { tone: "danger", label: "zgubiony", note: d.returnedOn ? `zgłoszono ${fmtDate(d.returnedOn)}` : "bez zwrotu" };
  if (d.returnedOn) {
    return { tone: "success", label: "zwrócony", note: [fmtDate(d.returnedOn), d.returnNote?.toLowerCase()].filter(Boolean).join(" · ") };
  }
  if (d.returnDue) {
    const days = daysUntil(d.returnDue) ?? 0;
    return days < 0
      ? { tone: "danger", label: "zwrot po terminie", note: `${fmtDate(d.returnDue)} · ${relDays(d.returnDue)}` }
      : { tone: "info", label: "u konsultanta", note: `zwrot do ${fmtDate(d.returnDue)}` };
  }
  return { tone: "info", label: "u konsultanta", note: "bez terminu zwrotu" };
}

/** Plik w dokumentach, który wygląda na protokół sprzętu („Protokół sprzętu.pdf”). */
export function equipmentDocument(docs: MkDocument[] | undefined): MkDocument | null {
  return docs?.find((d) => /sprz[eę]t/i.test(d.filename)) ?? null;
}

export function panelModeLabel(state: PanelProposal["portal_state"]): string {
  return PANEL_STATE_OPTIONS.find((o) => o.value === state)?.label ?? state;
}

/** „0 z 8 kroków” — dopełniacz po „z”. */
export function ofSteps(done: number, total: number): string {
  return `${done} z ${total} ${total === 1 ? "kroku" : "kroków"}`;
}

export function onboardingCounts(items: MkOnboardingItem[], checked: Record<number, boolean>) {
  const counted = items.filter((i) => i.status !== "na");
  const done = counted.filter((i) => checked[i.id] ?? i.status === "done").length;
  return { done, total: counted.length };
}

// ── Widok ─────────────────────────────────────────────────────────────────────

function Section({
  title,
  meta,
  action,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="px-4 py-3">
      <div className="mb-1.5 flex min-h-8 items-center justify-between gap-3">
        <h3 className="flex items-baseline gap-2 text-[13.5px] font-semibold text-foreground">
          {title}
          {meta ? <span className="text-[12px] font-normal tabular-nums text-muted-foreground">{meta}</span> : null}
        </h3>
        {action ? <div className="flex shrink-0 items-center gap-1.5">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

type CheckState = "ok" | "check" | "missing";
const CHECK_ICON: Record<CheckState, { icon: LucideIcon; tone: string; label: string }> = {
  ok: { icon: CircleCheck, tone: "text-success", label: "jest" },
  check: { icon: CircleHelp, tone: "text-warning", label: "do sprawdzenia" },
  missing: { icon: CircleAlert, tone: "text-destructive", label: "brak" },
};

function CheckRow({
  state,
  title,
  detail,
  action,
}: {
  state: CheckState;
  title: string;
  detail: React.ReactNode;
  action?: React.ReactNode;
}) {
  const { icon: Icon, tone, label } = CHECK_ICON[state];
  return (
    <li className="flex items-start gap-3 py-1">
      <Icon aria-label={label} className={cn("mt-0.5 size-[18px] shrink-0", tone)} />
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline justify-between gap-3 text-[13px] font-medium leading-5 text-foreground">
          {title}
          {action ? <span className="shrink-0 font-normal">{action}</span> : null}
        </p>
        <p className="line-clamp-2 text-[12px] leading-4 text-muted-foreground">{detail}</p>
      </div>
    </li>
  );
}

function Formalities({ c, docs }: { c: MkContract; docs: MkDocument[] | undefined }) {
  const startDocs = useMkClientStartDocs(c.client_id);
  const agreement = docs?.find((d) => d.doc_type === "contract") ?? null;
  const required = startDocs.data ?? [];
  return (
    <ul className="grid grid-cols-2 gap-x-8">
      {docs == null ? (
        <CheckRow state="check" title="Umowa w dokumentach" detail="Wczytywanie dokumentów…" />
      ) : agreement ? (
        <CheckRow
          state="ok"
          title="Umowa w dokumentach"
          detail={
            <>
              <span title={agreement.filename}>„{agreement.filename}”</span> · dodano {fmtDate(agreement.created_at)}
            </>
          }
          action={
            <Link
              href={`/contracts/${c.id}/makieta?w=a&tab=dokumenty`}
              className="text-[12.5px] font-medium text-primary hover:underline"
            >
              Dokumenty
            </Link>
          }
        />
      ) : (
        <CheckRow
          state="missing"
          title="Brak umowy w dokumentach"
          detail="Bez podpisanej umowy w dokumentach nie wiadomo, co obowiązuje."
          action={
            <button type="button" className="text-[12.5px] font-medium text-primary hover:underline">
              Dodaj umowę
            </button>
          }
        />
      )}
      <CheckRow
        state="check"
        title="Dokumenty do startu"
        detail={
          startDocs.isLoading
            ? "Wczytywanie listy klienta…"
            : startDocs.isError
              ? "Nie udało się pobrać listy dokumentów klienta."
              : required.length === 0
                ? "Klient nie ma w NEXUSIE listy dokumentów do startu, więc nie wiadomo, czego wymaga."
                : `Klient wymaga: ${required.map((d) => d.name).join(", ")}. Kontrakt bez rekrutacji — stanu nie da się odczytać.`
        }
        action={
          <Link
            href={`/clients/${c.client_id}?tab=wejscie`}
            className="text-[12.5px] font-medium text-primary hover:underline"
          >
            Wejście u klienta
          </Link>
        }
      />
    </ul>
  );
}

/** Pozycje mają osobę, termin albo notatkę — wtedy tabela, inaczej zwarta checklista. */
export function onboardingDetailed(items: MkOnboardingItem[]): boolean {
  return items.some((i) => i.assigned_to != null || i.due_date != null || Boolean(i.notes));
}

function CheckItem({
  item,
  done,
  onToggle,
}: {
  item: MkOnboardingItem;
  done: boolean;
  onToggle: (id: number, value: boolean) => void;
}) {
  const na = item.status === "na";
  return (
    <li className="flex min-h-10 items-center gap-3 py-1.5">
      <Checkbox
        checked={done}
        disabled={na}
        onCheckedChange={(v) => onToggle(item.id, v === true)}
        aria-label={`${item.label} — ${done ? "zrobione" : "do zrobienia"}`}
      />
      <span className={cn("min-w-0 flex-1 text-[13px] text-foreground", (done || na) && "text-muted-foreground line-through")}>
        {item.label}
      </span>
      {na ? <span className="text-[12px] text-muted-foreground">nie dotyczy</span> : null}
    </li>
  );
}

function StartList({
  c,
  items,
  checked,
  onToggle,
}: {
  c: MkContract;
  items: MkOnboardingItem[];
  checked: Record<number, boolean>;
  onToggle: (id: number, value: boolean) => void;
}) {
  if (items.length === 0) {
    const started = (daysUntil(c.start_date) ?? 0) <= 0;
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2.5">
        <p className="text-[13px] text-muted-foreground">
          {started
            ? `Listy startowej nie ma — przy współpracy od ${fmtDate(c.start_date)} to normalne.`
            : `Listy startowej jeszcze nie ma — wygeneruj ją przed startem ${fmtDate(c.start_date)}.`}
        </p>
        <Button type="button" variant="outline" size="sm">
          Wygeneruj z szablonu (BHP, sprzęt, dostępy, VPN…)
        </Button>
      </div>
    );
  }
  if (!onboardingDetailed(items)) {
    // Bez osób i terminów kolumny „Kto” i „Termin” byłyby samymi kreskami —
    // dwie kolumny listy (1–4 po lewej, 5–8 po prawej) mieszczą się w oknie.
    const half = Math.ceil(items.length / 2);
    return (
      <div className="grid grid-cols-2 gap-x-8">
        {[items.slice(0, half), items.slice(half)].map((col, i) => (
          <ul key={i} className="divide-y divide-border/60 border-y border-border/60">
            {col.map((item) => (
              <CheckItem key={item.id} item={item} done={checked[item.id] ?? item.status === "done"} onToggle={onToggle} />
            ))}
          </ul>
        ))}
      </div>
    );
  }
  return (
    <table className="w-full table-fixed text-[13px]">
      <thead>
        <tr className={CALM_ROW}>
          <th className="w-8 pb-1.5" aria-label="Zrobione" />
          <th className={cn(CALM_HEAD, "pb-1.5 text-left")}>Co</th>
          <th className={cn(CALM_HEAD, "w-[180px] pb-1.5 text-left")}>Kto</th>
          <th className={cn(CALM_HEAD, "w-[120px] pb-1.5 text-left")}>Termin</th>
          <th className={cn(CALM_HEAD, "w-[130px] pb-1.5 text-left")}>Stan</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => {
          const done = checked[item.id] ?? item.status === "done";
          const na = item.status === "na";
          const late = !done && !na && item.due_date != null && (daysUntil(item.due_date) ?? 0) < 0;
          return (
            <tr key={item.id} className={cn(CALM_ROW, "last:border-b-0")}>
              <td className="py-2 align-middle">
                <Checkbox
                  checked={done}
                  disabled={na}
                  onCheckedChange={(v) => onToggle(item.id, v === true)}
                  aria-label={`${item.label} — ${done ? "zrobione" : "do zrobienia"}`}
                />
              </td>
              <td className="py-2 pr-3">
                <span className={cn("text-foreground", (done || na) && "text-muted-foreground line-through")}>{item.label}</span>
                {item.notes ? <span className={CALM_SUBLINE}>{item.notes}</span> : null}
              </td>
              <td className="py-2 pr-3">
                {item.assigned_to ? <span className="text-foreground">przypisano</span> : <span className={CALM_EMPTY}>—</span>}
              </td>
              <td className="py-2 pr-3 tabular-nums">
                {item.due_date ? (
                  <span className={cn(late ? "font-medium text-destructive" : "text-foreground")}>
                    {fmtDate(item.due_date)}
                    {late ? <span className={CALM_SUBLINE}>{relDays(item.due_date)}</span> : null}
                  </span>
                ) : (
                  <span className={CALM_EMPTY}>—</span>
                )}
              </td>
              <td className="py-2">
                <StatusDot tone={done ? "success" : late ? "danger" : "neutral"}>
                  {na ? "nie dotyczy" : done ? "zrobione" : late ? "po terminie" : "do zrobienia"}
                </StatusDot>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function DeviceTable({ devices }: { devices: MkDevice[] }) {
  return (
    <table className="w-full table-fixed text-[13px]">
      <thead>
        <tr className={CALM_ROW}>
          <th className={cn(CALM_HEAD, "pb-1.5 text-left")}>Urządzenie</th>
          <th className={cn(CALM_HEAD, "w-[230px] pb-1.5 text-left")}>Numer</th>
          <th className={cn(CALM_HEAD, "w-[210px] pb-1.5 text-left")}>Wydano</th>
          <th className={cn(CALM_HEAD, "w-[170px] pb-1.5 text-left")}>Zwrot</th>
        </tr>
      </thead>
      <tbody>
        {devices.map((d) => {
          const Icon = d.icon;
          const issued = deviceIssued(d);
          const ret = deviceReturn(d);
          return (
            <tr key={d.key} className={cn(CALM_ROW, "last:border-b-0")}>
              <td className="py-2 pr-3">
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-foreground" title={d.title}>
                      {d.title}
                    </span>
                    <span className={CALM_SUBLINE}>
                      {[d.title === d.kind ? null : d.kind, d.ours === false ? "sprzęt klienta" : d.ours ? "nasz" : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                </span>
              </td>
              <td className="py-2 pr-3 tabular-nums">
                {d.number ? (
                  <span className="block truncate text-foreground" title={d.number}>
                    {d.number}
                  </span>
                ) : (
                  <span className={CALM_EMPTY}>—</span>
                )}
                {d.numberNote ? <span className={CALM_SUBLINE}>{d.numberNote}</span> : null}
              </td>
              <td className="py-2 pr-3">
                <span className="block tabular-nums text-foreground">{issued.main}</span>
                <span className={CALM_SUBLINE}>{issued.note}</span>
              </td>
              <td className="py-2">
                <StatusDot tone={ret.tone} note={ret.note}>
                  {ret.label}
                </StatusDot>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function EquipmentPart({ c, docs }: { c: MkContract; docs: MkDocument[] | undefined }) {
  const { devices, isLoading, isError } = useMkDevices(c.id);
  const provider = useMkProvider(c.client_id).data?.equipment_provider;
  const doc = equipmentDocument(docs);
  const active = devices.filter((d) => !d.returnedOn && !d.lost).length;

  return (
    <Section
      title="Sprzęt u konsultanta"
      meta={devices.length ? `${plural(active, ["urządzenie", "urządzenia", "urządzeń"])} u konsultanta` : null}
      action={
        <>
          {active > 0 ? (
            <Button type="button" variant="ghost" size="sm">
              Przyjmij zwrot
            </Button>
          ) : null}
          <Button type="button" variant="outline" size="sm">
            Wydaj z magazynu
          </Button>
        </>
      }
    >
      {isLoading ? (
        <p className="text-[13px] text-muted-foreground">Wczytywanie sprzętu…</p>
      ) : isError ? (
        <p className="text-[13px] text-destructive">Nie udało się pobrać sprzętu.</p>
      ) : devices.length === 0 ? (
        <div className="space-y-1.5 rounded-lg bg-muted/50 px-3 py-2.5 text-[13px]">
          <p className="text-muted-foreground">
            {provider === "klienta"
              ? "Nic nie wydano z magazynu — u tego klienta konsultanci pracują na sprzęcie klienta, więc to normalne."
              : "Nic nie wydano z magazynu. Jeśli konsultant pracuje na sprzęcie klienta, nic tu nie dodawaj."}
          </p>
          {doc ? (
            <p className="flex items-center gap-1.5 text-muted-foreground">
              <FileText className="size-3.5 shrink-0" aria-hidden />
              W dokumentach jest „{doc.filename}” — sprawdź, czy ten sprzęt nie powinien być w rejestrze.
            </p>
          ) : null}
        </div>
      ) : (
        <DeviceTable devices={devices} />
      )}
    </Section>
  );
}

function PanelRow({ contractId }: { contractId: number }) {
  const panel = useMkPanel(contractId);
  if (panel.isLoading) return <p className="text-[13px] text-muted-foreground">Wczytywanie panelu…</p>;
  if (panel.isError || !panel.data) {
    return <p className="text-[13px] text-muted-foreground">Panelu konsultanta nie da się tu pokazać (brak dostępu albo błąd).</p>;
  }
  const p = panel.data;
  const mode = panelModeLabel(p.portal_state);
  if (p.activation.active) {
    return (
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3 text-[13px]">
          <StatusDot tone="success">aktywny</StatusDot>
          <span className="truncate text-muted-foreground">
            od {fmtDate(warsawDateOf(p.activation.activated_at))}
            {p.activation.last_login_at ? ` · ostatnie logowanie ${fmtDate(warsawDateOf(p.activation.last_login_at))}` : " · jeszcze bez logowania"}
            {` · tryb firmy: ${mode}`}
          </span>
        </div>
        <Button type="button" variant="quiet" size="sm">
          Wyłącz panel…
        </Button>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3 text-[13px]">
        <StatusDot tone="neutral">nieaktywny</StatusDot>
        <span className="truncate text-muted-foreground">
          tryb firmy: <span className="text-foreground">{mode}</span> (zmienia administrator w Ustawieniach)
        </span>
      </div>
      {p.can_activate ? (
        <Button type="button" variant="outline" size="sm">
          Aktywuj panel…
        </Button>
      ) : (
        <span className="text-[12px] text-muted-foreground">aktywacja przy działającym kontrakcie</span>
      )}
    </div>
  );
}

export function StartA({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const docs = useMkDocuments(contractId).data;
  const onboarding = useMkOnboarding(contractId);
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  if (!c) return null;

  const items = [...(onboarding.data ?? [])].sort((a, b) => a.order - b.order);
  const { done, total } = onboardingCounts(items, checked);
  const pct = total ? Math.round((done / total) * 100) : 0;
  const started = (daysUntil(c.start_date) ?? 0) <= 0;
  const createdOn = items.length ? items.map((i) => i.created_at).sort()[0] : null;

  const subtitle = !onboarding.isSuccess
    ? null
    : items.length
      ? [
          started ? `Współpraca od ${fmtDate(c.start_date)}` : `Start ${fmtDate(c.start_date)} (${relDays(c.start_date)})`,
          `lista założona ${fmtDate(warsawDateOf(createdOn))}`,
          done === 0 ? "nic jeszcze nie odhaczono" : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : started
        ? `Współpraca od ${fmtDate(c.start_date)} · listy startowej nie założono`
        : `Start ${fmtDate(c.start_date)} (${relDays(c.start_date)}) · listy startowej jeszcze nie ma`;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-3.5">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-foreground">
            Start u klienta
            {items.length ? <span className="font-normal text-muted-foreground"> · {ofSteps(done, total)}</span> : null}
          </h2>
          {subtitle ? <p className="text-[12.5px] text-muted-foreground">{subtitle}</p> : null}
        </div>
        {items.length ? (
          <div className="flex w-[300px] items-center gap-3">
            <div
              className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Postęp listy startowej"
            >
              <div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-10 text-right text-[12.5px] font-medium tabular-nums text-foreground">{pct} %</span>
          </div>
        ) : null}
      </header>

      <div className="divide-y divide-border/70">
        <Section title="Formalności">
          <Formalities c={c} docs={docs} />
        </Section>

        <Section
          title="Lista startowa"
          meta={items.length && !onboardingDetailed(items) ? "bez przypisanych osób i terminów" : null}
          action={
            items.length ? (
              <Button type="button" variant="ghost" size="sm">
                <Plus className="size-3.5" aria-hidden />
                Dodaj pozycję
              </Button>
            ) : null
          }
        >
          {onboarding.isLoading ? (
            <p className="text-[13px] text-muted-foreground">Wczytywanie listy…</p>
          ) : onboarding.isError ? (
            <p className="text-[13px] text-destructive">Nie udało się pobrać listy startowej.</p>
          ) : (
            <StartList c={c} items={items} checked={checked} onToggle={(id, v) => setChecked((s) => ({ ...s, [id]: v }))} />
          )}
        </Section>

        <EquipmentPart c={c} docs={docs} />

        <Section title="Panel konsultanta">
          <PanelRow contractId={c.id} />
        </Section>
      </div>
    </div>
  );
}
