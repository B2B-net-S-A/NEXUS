"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Check, Search, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { useIssueToHolder } from "@/lib/api/academy-edition";
import {
  useEquipmentItems,
  type EquipmentCategory,
  type EquipmentHolder,
  type EquipmentItem,
  type EquipmentProtocol,
} from "@/lib/api/equipment";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  CATEGORY_PLURAL,
  ISSUE_KITS,
  formatPln,
  groupByModel,
  modelKey,
  isNoValueCategory,
  issueTotal,
  itemIdentifier,
  itemNumber,
  itemTitle,
  lineValue,
  pickKit,
  type IssueDraftLine,
  type IssueKitKey,
  type ModelGroup,
} from "./equipment-format";
import { CategoryIcon } from "./equipment-visuals";
import { HolderPicker } from "./HolderPicker";
import { ITEMS_PAGE } from "./ItemsTab";
import { ProtocolLinkBox } from "./ProtocolLinkBox";
import { ProtocolDownloads } from "./ProtocolDownloads";

interface IssueWizardProps {
  onClose: () => void;
  /** Posiadacz z góry (np. zakładka „Sprzęt” kontraktu) — krok 1 jest pominięty. */
  presetHolder?: EquipmentHolder | null;
  /** Sztuki z góry („Wydaj” przy pozycji albo modelu w „Ewidencji”). */
  presetItems?: EquipmentItem[];
  /** Zestaw podpowiadany przez zadanie „Przygotuj” (start kontraktu, wejście). */
  suggestedKit?: IssueKitKey | null;
}

type Step = 1 | 2 | 3;
const STEPS: { step: Step; label: string }[] = [
  { step: 1, label: "Osoba" },
  { step: 2, label: "Pozycje" },
  { step: 3, label: "Protokół i podpis" },
];

/** Wolny sprzęt kreatora — jedno zapytanie, filtr kategorii i szukanie na miejscu. */
export const FREE_ITEMS_FILTERS = { free: true, limit: ITEMS_PAGE } as const;

function matchesQuery(item: EquipmentItem, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    item.model.name,
    CATEGORY_LABELS[item.category],
    item.inventory_number,
    item.serial_number,
    item.imei,
    item.phone_number,
    item.access_card_number,
    item.location,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("pl");
  return haystack.includes(needle);
}

/**
 * „Wydaj sprzęt”: osoba → pozycje (gotowe zestawy, wolne po modelu, żywy
 * podgląd protokołu) → protokół i podpis (wzór recepcji, link albo papier).
 * Osobą bywa też uczestnik Akademii (przełącznik w kroku 1).
 */
export function IssueWizard({
  onClose,
  presetHolder = null,
  presetItems = [],
  suggestedKit = null,
}: IssueWizardProps) {
  const [step, setStep] = useState<Step>(presetHolder ? 2 : 1);
  const [holder, setHolder] = useState<EquipmentHolder | null>(presetHolder);
  const [lines, setLines] = useState<IssueDraftLine[]>(() =>
    presetItems.map((item) => ({ item, value: "", accessories: "" })),
  );
  const [date, setDate] = useState(() => warsawToday());
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<EquipmentCategory | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [kitNote, setKitNote] = useState<string | null>(null);
  const deferred = useDeferredValue(query.trim().toLocaleLowerCase("pl"));
  const free = useEquipmentItems(FREE_ITEMS_FILTERS, step === 2);
  const issue = useIssueToHolder();
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    protocol: EquipmentProtocol;
    linkUrl: string | null;
  } | null>(null);

  const chosen = useMemo(() => new Set(lines.map((line) => line.item.id)), [lines]);
  const available = useMemo(
    () => (free.data?.items ?? []).filter((item) => !chosen.has(item.id)),
    [free.data, chosen],
  );
  const freeCount = (key: EquipmentCategory) =>
    available.filter((item) => item.category === key).length;
  const categories = CATEGORY_ORDER.filter((key) => freeCount(key) > 0);
  const activeCategory = category ?? categories[0] ?? null;
  const groups = groupByModel(
    available.filter(
      (item) =>
        (deferred ? true : item.category === activeCategory) && matchesQuery(item, deferred),
    ),
  );
  const total = issueTotal(lines);
  const countLabel = countPl(lines.length, "pozycja", "pozycje", "pozycji");

  const add = (items: EquipmentItem[]) =>
    setLines((prev) => [
      ...prev,
      ...items
        .filter((item) => !prev.some((line) => line.item.id === item.id))
        .map((item) => ({ item, value: "", accessories: "" })),
    ]);
  const patch = (id: number, change: Partial<IssueDraftLine>) =>
    setLines((prev) => prev.map((line) => (line.item.id === id ? { ...line, ...change } : line)));
  const remove = (id: number) => setLines((prev) => prev.filter((line) => line.item.id !== id));

  const addKit = (key: IssueKitKey) => {
    const kit = ISSUE_KITS.find((entry) => entry.key === key);
    if (!kit) return;
    const picked = pickKit(
      kit,
      available,
      lines.map((line) => line.item),
    );
    add(picked.added);
    setKitNote(
      picked.missing.length
        ? `${kit.title}: brak wolnych — ${picked.missing.join(", ")}.`
        : picked.added.length
          ? `${kit.title}: dodano ${countPl(picked.added.length, "pozycję", "pozycje", "pozycji")}.`
          : `${kit.title}: wszystko już jest w protokole.`,
    );
  };

  const submit = (sendLink: boolean) => {
    if (!holder) return;
    setError(null);
    issue.mutate(
      {
        holder_kind: holder.kind,
        holder_id: holder.id,
        protocol_date: date || null,
        send_link: sendLink,
        lines: lines.map((line) => ({
          item_id: line.item.id,
          unit_value:
            line.value.trim() && !isNoValueCategory(line.item.category)
              ? line.value.trim().replace(",", ".")
              : null,
          accessories: line.accessories.trim() || null,
        })),
      },
      {
        onSuccess: (data) => setResult({ protocol: data.protocol, linkUrl: data.link_url }),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wydać sprzętu.")),
      },
    );
  };

  if (result) {
    return (
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title={`Wydano · protokół ${result.protocol.number}`}
        description={`${result.protocol.lines?.length ?? lines.length} pozycji u: ${result.protocol.holder.name}. Protokół czeka na podpis.`}
        footer={<Button onClick={onClose}>Gotowe</Button>}
      >
        <div className="space-y-4">
          <ProtocolDownloads protocol={result.protocol} />
          {result.linkUrl ? (
            <ProtocolLinkBox
              url={result.linkUrl}
              number={result.protocol.number}
              email={result.protocol.holder.email}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Wydrukuj protokół do podpisu. Podpisany skan wgrasz w zakładce „Protokoły”, a podpis
              potwierdzasz tam jednym kliknięciem.
            </p>
          )}
        </div>
      </AppModal>
    );
  }

  const canGoBack = step > 1 && !(presetHolder && step === 2);

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={holder ? `Wydaj sprzęt · ${holder.name}` : "Wydaj sprzęt"}
      size="xl"
      footer={
        <>
          {canGoBack ? (
            <Button variant="ghost" className="mr-auto" onClick={() => setStep((step - 1) as Step)}>
              ← Wstecz
            </Button>
          ) : null}
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          {step === 1 ? (
            <Button disabled={!holder} onClick={() => setStep(2)}>
              Dalej
            </Button>
          ) : step === 2 ? (
            <Button disabled={lines.length === 0} onClick={() => setStep(3)}>
              {lines.length ? `Dalej: protokół · ${countLabel}` : "Dalej: protokół"}
            </Button>
          ) : (
            <>
              <Button variant="outline" disabled={issue.isPending} onClick={() => submit(false)}>
                Wydaj, podpis na papierze
              </Button>
              <Button disabled={issue.isPending} onClick={() => submit(true)}>
                {issue.isPending ? "Zapisywanie…" : "Wydaj i utwórz link"}
              </Button>
            </>
          )}
        </>
      }
    >
      <ol
        className="mb-4 flex flex-wrap items-center gap-3 rounded-md bg-muted/50 px-3 py-2.5 text-xs"
        aria-label="Kroki"
      >
        {STEPS.map(({ step: number, label }, index) => {
          const done = number < step || (number === 1 && holder != null && step > 1);
          const current = step === number;
          return (
            <li key={number} className="flex items-center gap-3">
              {index > 0 ? (
                <span
                  aria-hidden
                  className={cn("h-0.5 w-8 rounded", done || current ? "bg-primary/40" : "bg-border")}
                />
              ) : null}
              <span
                aria-current={current ? "step" : undefined}
                className="flex items-center gap-2"
              >
                <span
                  aria-hidden
                  className={cn(
                    "inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold",
                    done
                      ? "bg-success text-success-foreground"
                      : current
                        ? "bg-primary text-primary-foreground"
                        : "bg-border text-muted-foreground",
                  )}
                >
                  {done ? <Check className="h-3 w-3" /> : number}
                </span>
                {number === 1 && holder && step > 1 ? (
                  <span className="min-w-0">
                    <span className="block font-semibold text-foreground">{holder.name}</span>
                    <span className="block text-muted-foreground">
                      {holder.detail ? holder.detail : "Osoba"}
                      {presetHolder ? null : (
                        <>
                          {" · "}
                          <button
                            type="button"
                            className="font-medium text-primary hover:underline"
                            onClick={() => setStep(1)}
                          >
                            Zmień
                          </button>
                        </>
                      )}
                    </span>
                  </span>
                ) : (
                  <span
                    className={cn(
                      current ? "font-semibold text-primary" : "text-muted-foreground",
                    )}
                  >
                    {number} · {label}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>

      {step === 1 ? (
        <div className="space-y-3">
          {lines.length ? (
            <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
              W protokole:{" "}
              {lines
                .map(
                  (line) =>
                    `${itemTitle(line.item)} (${itemNumber(line.item)})`,
                )
                .join(", ")}
              . Wybierz osobę, której wydajesz sprzęt.
            </p>
          ) : null}
          <HolderPicker academy value={holder} onChange={setHolder} />
        </div>
      ) : step === 2 ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
          <section aria-label="Wolne pozycje" className="min-w-0 space-y-3">
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Gotowe zestawy
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {ISSUE_KITS.map((kit) => {
                  const suggested = kit.key === suggestedKit;
                  return (
                    <div
                      key={kit.key}
                      className={cn(
                        "flex flex-col gap-1.5 rounded-lg border p-3",
                        suggested ? "border-primary/40 bg-primary/5" : "border-border",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold">{kit.title}</span>
                        <Button
                          size="sm"
                          variant={suggested ? "primary" : "outline"}
                          disabled={!free.isSuccess}
                          aria-label={`Dodaj zestaw: ${kit.title}`}
                          onClick={() => addKit(kit.key)}
                        >
                          Dodaj zestaw
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {kit.slots.map((slot) => slot.label).join(" · ")} — pierwsze wolne sztuki
                      </p>
                    </div>
                  );
                })}
              </div>
              {kitNote ? (
                <p role="status" className="mt-2 text-xs text-muted-foreground">
                  {kitNote}
                </p>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div role="tablist" aria-label="Kategorie wolnego sprzętu" className="flex flex-wrap gap-1">
                {categories.map((key) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={!deferred && key === activeCategory}
                    onClick={() => {
                      setCategory(key);
                      setQuery("");
                    }}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium",
                      !deferred && key === activeCategory
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {CATEGORY_PLURAL[key]}{" "}
                    <span className="tabular-nums opacity-70">{freeCount(key)}</span>
                  </button>
                ))}
              </div>
              <div className="relative w-full sm:w-56">
                <Search
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  aria-label="Szukaj wolnej pozycji"
                  placeholder="Numer, S/N, model…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="h-8 pl-8"
                />
              </div>
            </div>

            {free.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(free.error, "Nie udało się wczytać wolnego sprzętu.")}
              </p>
            ) : free.isLoading ? (
              <p className="text-sm text-muted-foreground">Wczytywanie…</p>
            ) : groups.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {deferred ? "Nic wolnego nie pasuje." : "Brak wolnego sprzętu na stanie."}
              </p>
            ) : (
              <ul className="max-h-[42dvh] divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {groups.map((group) => (
                  <ModelRow
                    key={group.key}
                    group={group}
                    inProtocol={lines.some((line) => modelKey(line.item) === group.key)}
                    onAdd={(item) => add([item])}
                  />
                ))}
              </ul>
            )}
          </section>

          <section
            aria-label="Pozycje do wydania"
            className="min-w-0 space-y-2 rounded-lg border border-border bg-muted/30 p-3"
          >
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Protokół wydania · szkic
              </span>
              <span className="text-xs text-muted-foreground">{countLabel}</span>
            </div>
            {lines.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                Dodaj zestaw albo pozycje z listy wolnego sprzętu.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {lines.map((line) => {
                  const noValue = isNoValueCategory(line.item.category);
                  const open = editing === line.item.id;
                  return (
                    <li key={line.item.id} className="space-y-1.5 py-2 text-sm">
                      <div className="flex items-center gap-2">
                        <CategoryIcon category={line.item.category} modelName={line.item.model.name} />
                        <div className="min-w-0 flex-1">
                          <span className="block truncate font-medium" title={itemTitle(line.item)}>
                            {itemTitle(line.item)}
                            {line.accessories.trim() ? ` ${line.accessories.trim()}` : ""}
                          </span>
                          <span className="block truncate font-mono text-xs text-muted-foreground">
                            {[itemNumber(line.item), itemIdentifier(line.item)]
                              .filter((part) => part && part !== "—")
                              .join(" · ")}
                          </span>
                        </div>
                        <span
                          className={cn(
                            "shrink-0 tabular-nums text-xs",
                            lineValue(line) == null && "text-muted-foreground",
                          )}
                        >
                          {formatPln(lineValue(line))}
                        </span>
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`Usuń z wydania: ${line.item.model.name}`}
                          onClick={() => remove(line.item.id)}
                        >
                          <X className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                      <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setEditing(open ? null : line.item.id)}
                        className="ml-10 text-xs font-medium text-primary hover:underline"
                      >
                        {open ? "Gotowe" : noValue ? "Dodatki" : "Dodatki i wartość"}
                      </button>
                      {open ? (
                        <div className="ml-10 flex gap-2">
                          <Input
                            aria-label={`Dodatki: ${line.item.model.name}`}
                            placeholder="Dodatki, np. zasilacz, mysz"
                            value={line.accessories}
                            onChange={(event) =>
                              patch(line.item.id, { accessories: event.target.value })
                            }
                            className="h-8 text-xs"
                          />
                          {noValue ? null : (
                            <Input
                              aria-label={`Wartość w protokole: ${line.item.model.name}`}
                              placeholder={line.item.model.price_pln ?? "Wartość"}
                              inputMode="decimal"
                              value={line.value}
                              onChange={(event) => patch(line.item.id, { value: event.target.value })}
                              className="h-8 w-28 text-xs"
                            />
                          )}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="flex items-baseline justify-between border-t border-border pt-2">
              <span className="font-semibold">Razem</span>
              <span className="text-lg font-semibold tabular-nums">{formatPln(total)}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Wartości z cennika modelu; zmiana tutaj dotyczy tylko tego protokołu. Karta SIM
              i karta dostępu są w protokole bez wartości.
            </p>
          </section>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <FormField label="Data protokołu" htmlFor="eq-issue-date">
            <Input
              id="eq-issue-date"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="w-44"
            />
          </FormField>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left">Lp.</th>
                  <th className="px-3 py-1.5 text-left">Nazwa sprzętu</th>
                  <th className="px-3 py-1.5 text-left">Nr seryjny</th>
                  <th className="px-3 py-1.5 text-right">Wartość</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {lines.map((line, index) => (
                  <tr key={line.item.id}>
                    <td className="px-3 py-1.5">{index + 1}</td>
                    <td className="px-3 py-1.5">
                      {itemTitle(line.item)}
                      {line.accessories.trim() ? ` ${line.accessories.trim()}` : ""}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs">{itemIdentifier(line.item)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {lineValue(line) == null ? "—" : formatPln(lineValue(line))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Razem <span className="font-semibold tabular-nums">{formatPln(total)}</span> — kwotę
            słownie i resztę treści wzoru recepcji uzupełnia protokół.
          </p>
          <p className="text-xs text-muted-foreground">
            Po wydaniu pozycje mają stan „Wydany”, a protokół „Czeka na podpis”. Link do
            potwierdzenia odbioru jest ważny 14 dni i działa jeden raz; podpis potwierdza recepcja.
          </p>
        </div>
      )}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** Wiersz modelu: liczba wolnych, miejsce, cena, wybór sztuki i „+ Dodaj”. */
function ModelRow({
  group,
  inProtocol,
  onAdd,
}: {
  group: ModelGroup;
  inProtocol: boolean;
  onAdd: (item: EquipmentItem) => void;
}) {
  const [pickedId, setPickedId] = useState<number | null>(null);
  const picked = group.items.find((item) => item.id === pickedId) ?? group.items[0];
  // Cena z modelu wybranej sztuki — grupa może łączyć modele różnie zapisane w imporcie.
  const price = picked.model.price_pln;
  const facts = [
    countPl(group.items.length, "wolna", "wolne", "wolnych"),
    group.locations[0],
    isNoValueCategory(group.category) ? "bez wartości" : price ? formatPln(price) : null,
  ].filter(Boolean);
  const label = (item: EquipmentItem) =>
    itemNumber(item) === "SIM" ? itemIdentifier(item) : itemNumber(item);
  return (
    <li
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_120px_auto]",
        inProtocol && "bg-primary/5",
      )}
    >
      <div className="min-w-0">
        <span className="block truncate text-sm font-medium">
          {itemTitle(group)}
          {inProtocol ? (
            <Badge size="sm" variant="success" className="ml-1.5 align-middle">
              w protokole
            </Badge>
          ) : null}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{facts.join(" · ")}</span>
      </div>
      <Select
        value={String(picked.id)}
        onValueChange={(value) => setPickedId(Number(value))}
      >
        <SelectTrigger
          aria-label={`Sztuka: ${group.model.name}`}
          className="hidden h-8 font-mono text-xs sm:flex"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {group.items.map((item) => (
            <SelectItem key={item.id} value={String(item.id)} className="font-mono text-xs">
              {label(item)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        variant="outline"
        aria-label={`Dodaj: ${group.model.name} ${label(picked)}`}
        onClick={() => {
          onAdd(picked);
          setPickedId(null);
        }}
      >
        + Dodaj
      </Button>
    </li>
  );
}
