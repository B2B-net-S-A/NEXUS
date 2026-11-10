"use client";

// Reguły klienta (roadmapa E1.2, E1.6): stały katalog, Finanse ustawiają poziom
// i parametry. Zapis obowiązuje od wybranego miesiąca, wcześniejsze miesiące
// liczą się po starych regułach.
import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useClientRules,
  useCopyClientRules,
  useSaveClientRules,
  type RuleLevel,
  type SettlementClient,
  type SettlementRule,
} from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";

import { monthLabel } from "./format";

const LEVELS: { value: RuleLevel; label: string }[] = [
  { value: "block", label: "Blokuje" },
  { value: "warn", label: "Ostrzega" },
  { value: "off", label: "Wyłączone" },
];

type Draft = Record<string, { level: RuleLevel; params: Record<string, string> }>;

interface ClientRulesEditorProps {
  clientId: number;
  clients: SettlementClient[];
  month: string;
  months: string[];
  canWrite: boolean;
}

export function ClientRulesEditor({ clientId, clients, month, months, canWrite }: ClientRulesEditorProps) {
  const query = useClientRules(clientId, month);
  const save = useSaveClientRules(clientId);
  const copy = useCopyClientRules(clientId);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const [draft, setDraft] = useState<Draft>({});
  const [from, setFrom] = useState(months.includes(month) ? month : months[0]);
  const [copySource, setCopySource] = useState("");

  useEffect(() => {
    if (!query.data) return;
    const next: Draft = {};
    query.data.sections.forEach((s) => s.rules.forEach((r) => (next[r.key] = { level: r.level, params: { ...r.params } })));
    setDraft(next);
  }, [query.data]);

  if (query.isError) {
    return <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać reguł klienta.")} onRetry={() => query.refetch()} />;
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;

  function setLevel(key: string, level: RuleLevel) {
    setDraft((d) => ({ ...d, [key]: { ...d[key], level } }));
  }
  function setParam(key: string, param: string, value: string) {
    setDraft((d) => ({ ...d, [key]: { ...d[key], params: { ...d[key].params, [param]: value } } }));
  }

  async function onSave() {
    try {
      await save.mutateAsync({
        effective_from: from,
        rules: Object.entries(draft).map(([key, v]) => ({ key, level: v.level, params: v.params })),
      });
      showSuccess(`Reguły zapisane, działają od: ${monthLabel(from)}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać reguł."));
    }
  }

  async function onCopy() {
    const source = clients.find((c) => String(c.client_id) === copySource);
    if (!source) return;
    const ok = await askConfirm({
      title: `Skopiować reguły od: ${source.name}?`,
      description: `Obecne ustawienia ${data.client_name} zastąpi kopia. Zapisz je potem z miesiącem, od którego mają działać.`,
      confirmLabel: "Skopiuj",
    });
    if (!ok) return;
    try {
      await copy.mutateAsync(source.client_id);
      showSuccess("Skopiowano. Sprawdź wartości i zapisz.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się skopiować reguł."));
    }
  }

  return (
    <div className="space-y-3">
      {confirmDialog}
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-xs text-muted-foreground">
          {data.effective_from
            ? `Obecne reguły działają od: ${monthLabel(data.effective_from)}.`
            : "Ten klient nie ma jeszcze reguł: NEXUS przyjmuje pliki bez kontroli."}
        </p>
        {canWrite ? (
          <>
            <select
              aria-label="Skopiuj reguły od klienta"
              value={copySource}
              onChange={(e) => setCopySource(e.target.value)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs pointer-coarse:h-10"
            >
              <option value="">Skopiuj od klienta…</option>
              {clients
                .filter((c) => c.client_id !== clientId && c.rules_set)
                .map((c) => (
                  <option key={c.client_id} value={c.client_id}>
                    {c.name}
                  </option>
                ))}
            </select>
            <Button size="sm" variant="outline" disabled={!copySource || copy.isPending} onClick={onCopy}>
              Skopiuj
            </Button>
            <select
              aria-label="Od którego miesiąca działają reguły"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs pointer-coarse:h-10"
            >
              {months.map((m) => (
                <option key={m} value={m}>
                  od: {monthLabel(m)}
                </option>
              ))}
            </select>
            <Button size="sm" disabled={save.isPending} onClick={onSave}>
              Zapisz
            </Button>
          </>
        ) : null}
      </div>
      <div className="grid min-w-0 grid-cols-1 items-start gap-3 xl:grid-cols-2">
        {data.sections.map((s) => (
          <section key={s.key} className="rounded-xl border bg-card px-3 py-2">
            <h3 className="text-sm font-semibold">{s.title}</h3>
            <div className="divide-y">
              {s.rules.map((r) => (
                <RuleRow
                  key={r.key}
                  rule={r}
                  level={draft[r.key]?.level ?? r.level}
                  params={draft[r.key]?.params ?? r.params}
                  disabled={!canWrite}
                  onLevel={(l) => setLevel(r.key, l)}
                  onParam={(p, v) => setParam(r.key, p, v)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

interface RuleRowProps {
  rule: SettlementRule;
  level: RuleLevel;
  params: Record<string, string>;
  disabled: boolean;
  onLevel: (level: RuleLevel) => void;
  onParam: (key: string, value: string) => void;
}

function RuleRow({ rule, level, params, disabled, onLevel, onParam }: RuleRowProps) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-1.5">
      <div className="min-w-0">
        <p className={cn("text-[13px] font-medium", level === "off" && "text-muted-foreground")}>{rule.name}</p>
        {rule.param_fields.length > 0 || rule.hint ? (
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            {rule.param_fields.map((f) => (
              <label key={f.key} className="inline-flex items-center gap-1">
                {f.label}
                <Input
                  value={params[f.key] ?? ""}
                  disabled={disabled}
                  onChange={(e) => onParam(f.key, e.target.value)}
                  size={Math.max(4, (params[f.key] ?? "").length + 1)}
                  className="h-6 w-auto px-1.5 text-xs"
                />
                {f.suffix ?? null}
              </label>
            ))}
            {rule.hint ? <span>{rule.hint}</span> : null}
          </div>
        ) : null}
      </div>
      <div role="radiogroup" aria-label={`Poziom: ${rule.name}`} className="inline-flex rounded-md bg-muted p-0.5 text-[11px] font-medium">
        {LEVELS.map((l) => (
          <button
            key={l.value}
            type="button"
            role="radio"
            aria-checked={level === l.value}
            disabled={disabled}
            onClick={() => onLevel(l.value)}
            className={cn(
              "rounded px-1.5 py-0.5 pointer-coarse:min-h-8",
              level === l.value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}
