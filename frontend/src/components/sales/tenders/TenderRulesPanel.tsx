"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useSaveTenderRules, useTenderRules, type TenderRulesView } from "@/lib/api/sales-tenders";
import { resolveViewState } from "@/lib/view-state";

import { SalesSelect } from "../SalesSelect";

const MAX_ITEMS = 80;
const MAX_CHARS = 60;

type ListKey = "phrases" | "reject_subject" | "reject_buyer";

const LISTS: { key: ListKey; label: string; hint: string }[] = [
  {
    key: "phrases",
    label: "Frazy, które wpuszczają ogłoszenie",
    hint: "Szukane w przedmiocie. Ogłoszenie wchodzi też zawsze z kodem CPV usług IT (72…, bez 721) albo dostarczania personelu (7961…, 7962…).",
  },
  {
    key: "reject_subject",
    label: "Odrzucam przedmiot",
    hint: "Słowo w przedmiocie odsiewa ogłoszenie, nawet gdy pasuje fraza.",
  },
  {
    key: "reject_buyer",
    label: "Odrzucam zamawiającego",
    hint: "Słowo w nazwie zamawiającego. Wielkość zamówienia oceni dopiero Grok Analityk (etap 2).",
  },
];

function toLines(values: string[]): string {
  return values.join("\n");
}

function fromLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}

function ReadOnlyRules({ rules }: { rules: TenderRulesView }) {
  return (
    <div className="space-y-3">
      {LISTS.map(({ key, label }) => (
        <div key={key}>
          <p className="text-sm font-medium text-foreground">{label}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {rules[key].map((item) => (
              <Badge key={item} variant="neutral">
                {item}
              </Badge>
            ))}
          </div>
        </div>
      ))}
      <p className="text-sm text-muted-foreground">
        {rules.only_services ? "Tylko usługi: dostawy i roboty budowlane odpadają." : "Także dostawy i roboty budowlane."}{" "}
        Opiekun nowych szans: {rules.owner_name ?? "bez opiekuna"}.
      </p>
    </div>
  );
}

/** Reguły bramki z instrukcji Kingi; zapis „Sprzedaż: edycja”, bez programisty. */
export function TenderRulesPanel() {
  const query = useTenderRules(true);
  const save = useSaveTenderRules();
  const { showError, showSuccess } = useToast();
  const [lists, setLists] = useState<Record<ListKey, string> | null>(null);
  const [onlyServices, setOnlyServices] = useState(true);
  const [owner, setOwner] = useState("");

  useEffect(() => {
    if (!query.data || lists !== null) return;
    setLists({
      phrases: toLines(query.data.phrases),
      reject_subject: toLines(query.data.reject_subject),
      reject_buyer: toLines(query.data.reject_buyer),
    });
    setOnlyServices(query.data.only_services);
    setOwner(query.data.owner_user_id ? String(query.data.owner_user_id) : "");
  }, [query.data, lists]);

  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data || lists === null) return <p className="py-6 text-sm text-muted-foreground">Wczytywanie reguł…</p>;
  if (!query.data.can_edit) return <ReadOnlyRules rules={query.data} />;

  const parsed = {
    phrases: fromLines(lists.phrases),
    reject_subject: fromLines(lists.reject_subject),
    reject_buyer: fromLines(lists.reject_buyer),
  };
  const problems = LISTS.flatMap(({ key, label }) => {
    const out: string[] = [];
    if (parsed[key].length > MAX_ITEMS) out.push(`${label}: najwyżej ${MAX_ITEMS} pozycji.`);
    const long = parsed[key].find((item) => item.length > MAX_CHARS);
    if (long) out.push(`${label}: „${long.slice(0, 20)}…” ma więcej niż ${MAX_CHARS} znaków.`);
    return out;
  });

  const onSave = () =>
    save.mutate(
      {
        ...parsed,
        only_services: onlyServices,
        owner_user_id: owner ? Number(owner) : null,
      },
      {
        onSuccess: (data) => {
          setLists({
            phrases: toLines(data.phrases),
            reject_subject: toLines(data.reject_subject),
            reject_buyer: toLines(data.reject_buyer),
          });
          showSuccess("Zapisano reguły. Następny bieg użyje nowych.");
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać reguł.")),
      },
    );

  return (
    <Card className="space-y-4 p-4">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Jedna pozycja w wierszu. Słowo łapie odmiany: „dostawa” znajdzie „dostawy” i „dostaw”, ale nie „dostawcę”.
        Skrót pisany wielkimi literami („IT”, „DORA”) pasuje tylko dosłownie.
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        {LISTS.map(({ key, label, hint }) => (
          <div key={key} className="space-y-1.5">
            <Label htmlFor={`tender-rules-${key}`}>{label}</Label>
            <Textarea
              id={`tender-rules-${key}`}
              rows={9}
              value={lists[key]}
              onChange={(event) => setLists({ ...lists, [key]: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">{hint}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-6">
        <div className="flex items-center gap-2">
          <Switch id="tender-rules-services" checked={onlyServices} onCheckedChange={setOnlyServices} />
          <Label htmlFor="tender-rules-services">Tylko usługi (dostawy i roboty budowlane odpadają)</Label>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tender-rules-owner">Opiekun nowych szans</Label>
          <SalesSelect
            id="tender-rules-owner"
            value={owner}
            onValueChange={setOwner}
            anyLabel="Bez opiekuna"
            options={query.data.owners.map((person) => ({ value: String(person.id), label: person.name }))}
            className="w-64"
          />
        </div>
        <Button onClick={onSave} disabled={save.isPending || problems.length > 0}>
          {save.isPending ? "Zapisuję…" : "Zapisz reguły"}
        </Button>
      </div>
      {problems.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-destructive">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}
