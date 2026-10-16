"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Plus, Search, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEquipmentItems,
  useIssueEquipment,
  type EquipmentHolder,
  type EquipmentItem,
  type EquipmentProtocol,
} from "@/lib/api/equipment";
import { warsawToday } from "@/lib/warsaw-date";

import {
  CATEGORY_LABELS,
  formatPln,
  isNoValueCategory,
  issueTotal,
  itemIdentifier,
  itemNumber,
  lineValue,
  type IssueDraftLine,
} from "./equipment-format";
import { HolderPicker } from "./HolderPicker";
import { ProtocolLinkBox } from "./ProtocolLinkBox";
import { ProtocolDownloads } from "./ProtocolDownloads";

interface IssueWizardProps {
  onClose: () => void;
  /** Posiadacz z góry (np. zakładka „Sprzęt” kontraktu) — krok 1 jest pominięty. */
  presetHolder?: EquipmentHolder | null;
}

type Step = 1 | 2 | 3;
const STEPS: { step: Step; label: string }[] = [
  { step: 1, label: "Osoba" },
  { step: 2, label: "Pozycje" },
  { step: 3, label: "Protokół" },
];

/** „Wydaj sprzęt”: osoba → pozycje → protokół (wzór recepcji, link albo papier). */
export function IssueWizard({ onClose, presetHolder = null }: IssueWizardProps) {
  const [step, setStep] = useState<Step>(presetHolder ? 2 : 1);
  const [holder, setHolder] = useState<EquipmentHolder | null>(presetHolder);
  const [lines, setLines] = useState<IssueDraftLine[]>([]);
  const [date, setDate] = useState(() => warsawToday());
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const free = useEquipmentItems({ q: deferred, free: true }, step === 2);
  const issue = useIssueEquipment();
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    protocol: EquipmentProtocol;
    linkUrl: string | null;
  } | null>(null);

  const chosen = useMemo(() => new Set(lines.map((line) => line.item.id)), [lines]);
  const candidates = (free.data?.items ?? []).filter((item) => !chosen.has(item.id));
  const total = issueTotal(lines);

  const add = (item: EquipmentItem) =>
    setLines((prev) => [...prev, { item, value: "", accessories: "" }]);
  const patch = (id: number, change: Partial<IssueDraftLine>) =>
    setLines((prev) => prev.map((line) => (line.item.id === id ? { ...line, ...change } : line)));
  const remove = (id: number) => setLines((prev) => prev.filter((line) => line.item.id !== id));

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
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          {step > 1 && !(presetHolder && step === 2) ? (
            <Button variant="outline" onClick={() => setStep((step - 1) as Step)}>
              Wstecz
            </Button>
          ) : null}
          {step === 1 ? (
            <Button disabled={!holder} onClick={() => setStep(2)}>
              Dalej
            </Button>
          ) : step === 2 ? (
            <Button disabled={lines.length === 0} onClick={() => setStep(3)}>
              Dalej: protokół
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
      <ol className="mb-4 flex gap-4 text-xs" aria-label="Kroki">
        {STEPS.map(({ step: number, label }) => (
          <li
            key={number}
            aria-current={step === number ? "step" : undefined}
            className={
              step === number ? "font-semibold text-foreground" : "text-muted-foreground"
            }
          >
            {number} · {label}
          </li>
        ))}
      </ol>

      {step === 1 ? (
        <HolderPicker value={holder} onChange={setHolder} />
      ) : step === 2 ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section aria-label="Wolne pozycje" className="space-y-2">
            <div className="relative">
              <Search
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                aria-label="Szukaj wolnej pozycji"
                placeholder="Numer, S/N, model…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-9 pl-8"
              />
            </div>
            {free.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(free.error, "Nie udało się wczytać wolnego sprzętu.")}
              </p>
            ) : free.isLoading ? (
              <p className="text-sm text-muted-foreground">Wczytywanie…</p>
            ) : candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {query.trim() ? "Nic wolnego nie pasuje." : "Brak wolnego sprzętu na stanie."}
              </p>
            ) : (
              <ul className="max-h-[50dvh] divide-y divide-border overflow-y-auto rounded-md border border-border">
                {candidates.slice(0, 60).map((item) => (
                  <li key={item.id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                    <span className="w-14 shrink-0 font-mono text-xs">{itemNumber(item)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">
                        {CATEGORY_LABELS[item.category]} {item.model.name}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {itemIdentifier(item)}
                        {item.location ? ` · ${item.location}` : ""}
                      </span>
                    </span>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Dodaj: ${item.model.name} ${itemNumber(item)}`}
                      onClick={() => add(item)}
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-label="Pozycje do wydania" className="space-y-2">
            {lines.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                Dodaj pozycje z listy wolnego sprzętu.
              </p>
            ) : (
              <ul className="divide-y divide-border rounded-md border border-border">
                {lines.map((line) => {
                  const noValue = isNoValueCategory(line.item.category);
                  return (
                    <li key={line.item.id} className="space-y-1.5 px-3 py-2 text-sm">
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-xs">{itemNumber(line.item)}</span>
                        <span className="min-w-0 flex-1 truncate font-medium">
                          {CATEGORY_LABELS[line.item.category]} {line.item.model.name}
                        </span>
                        <span className="tabular-nums text-xs text-muted-foreground">
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
                      <div className="flex gap-2">
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
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="flex justify-between text-sm">
              <span className="text-muted-foreground">Razem</span>
              <span className="font-semibold tabular-nums">{formatPln(total)}</span>
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
          <div className="rounded-md border border-border">
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
                      {CATEGORY_LABELS[line.item.category]} {line.item.model.name}
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
