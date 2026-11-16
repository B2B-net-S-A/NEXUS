"use client";

import { ListPlus } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import { useOwnerCandidates } from "@/lib/api/sales";
import {
  ROLE_OPTIONS,
  SIZE_OPTIONS,
  SOURCE_OPTIONS,
  TRIGGER_OPTIONS,
  useBotList,
  useBuildList,
  useSaveBrief,
  type BotListBrief,
  type BotListRate,
  type BotListRole,
  type BotListSize,
  type BotListSource,
} from "@/lib/api/sales-bot-lists";
import type { CallCampaign } from "@/lib/api/sales-calling";
import { formatIsoDatePl } from "@/lib/date-pl";

const SKIPPED_LABELS: Record<string, string> = {
  already_in_campaign: "już w kampanii",
  other_caller: "dzwoni ktoś inny",
  client: "klient NEXUSA",
  do_not_contact: "sprzeciw",
  no_phone: "bez telefonu",
};

function words(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toggle<T>(list: T[], value: T, on: boolean): T[] {
  return on ? [...new Set([...list, value])] : list.filter((item) => item !== value);
}

function percent(rate: number): string {
  return `${(rate * 100).toFixed(1).replace(".", ",")}%`;
}

/** „Co działa”: rozmowy z wynikiem po roli albo po źródle listy. */
export function WorksTable({ title, rows }: { title: string; rows: BotListRate[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="min-w-0 space-y-1 overflow-x-auto">
      <h3 className="text-xs font-medium text-foreground">{title}</h3>
      <table className="w-full min-w-[22rem] text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-0.5 font-medium" />
            <th className="py-0.5 text-right font-medium">Rozmowy</th>
            <th className="py-0.5 text-right font-medium">Spotkania</th>
            <th className="py-0.5 text-right font-medium">Skuteczność</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="max-w-[18rem] truncate py-0.5 pr-2 text-foreground">{row.label}</td>
              <td className="py-1 text-right tabular-nums">{row.calls}</td>
              <td className="py-1 text-right tabular-nums">{row.meetings}</td>
              <td className="py-1 text-right font-semibold tabular-nums text-foreground">{percent(row.rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function BriefForm({ initial, onSave, saving }: { initial: BotListBrief; onSave: (brief: BotListBrief) => void; saving: boolean }) {
  const owners = useOwnerCandidates();
  const [brief, setBrief] = useState<BotListBrief>(initial);
  const [industries, setIndustries] = useState(initial.industries.join(", "));
  const [cities, setCities] = useState(initial.cities.join(", "));
  const [regions, setRegions] = useState(initial.regions.join(", "));
  const [pkd, setPkd] = useState(initial.pkd.join(", "));
  const external = brief.sources.some((source) => source !== "base");
  const set = (patch: Partial<BotListBrief>) => setBrief((current) => ({ ...current, ...patch }));

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({
          ...brief,
          industries: words(industries),
          cities: words(cities),
          regions: words(regions),
          pkd: words(pkd),
        });
      }}
    >
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-foreground">Do kogo dzwonimy</legend>
        <div className="flex flex-wrap gap-3">
          {ROLE_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm">
              <Checkbox
                checked={brief.roles.includes(option.value)}
                onCheckedChange={(on) => set({ roles: toggle<BotListRole>(brief.roles, option.value, on === true) })}
              />
              {option.label}
            </label>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">Kolejność ról bot ustala sam z „Co działa”.</p>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="bot-list-industries">Branża (słowa, po przecinku)</Label>
          <Input id="bot-list-industries" value={industries} placeholder="np. bank, finans, oprogramowanie" onChange={(e) => setIndustries(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="bot-list-cities">Miasto siedziby (po przecinku)</Label>
          <Input id="bot-list-cities" value={cities} placeholder="np. Warszawa, Kraków" onChange={(e) => setCities(e.target.value)} />
        </div>
      </div>
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-foreground">Skąd firmy</legend>
        <div className="flex flex-wrap gap-3">
          {SOURCE_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm">
              <Checkbox
                checked={brief.sources.includes(option.value)}
                onCheckedChange={(on) => set({ sources: toggle<BotListSource>(brief.sources, option.value, on === true) })}
              />
              {option.label}
            </label>
          ))}
        </div>
        {external && (
          <p className="text-[11px] text-muted-foreground">
            Firmy z rejestr.io i researchu szuka Bot Listy w Groku; dochodzą do kolejki po kilku minutach.
          </p>
        )}
      </fieldset>
      {external && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="bot-list-pkd">Kody PKD (po przecinku)</Label>
            <Input id="bot-list-pkd" value={pkd} placeholder="np. 64, 65, 62.01" onChange={(e) => setPkd(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bot-list-regions">Województwa (po przecinku)</Label>
            <Input id="bot-list-regions" value={regions} placeholder="np. mazowieckie, małopolskie" onChange={(e) => setRegions(e.target.value)} />
          </div>
          <fieldset className="space-y-1 sm:col-span-2">
            <legend className="text-xs font-medium text-foreground">Wyzwalacz (firma idzie wyżej)</legend>
            <div className="flex flex-wrap gap-3">
              {TRIGGER_OPTIONS.map((option) => (
                <label key={option.value} className="flex items-center gap-1.5 text-sm">
                  <Checkbox
                    checked={brief.triggers.includes(option.value)}
                    onCheckedChange={(on) => set({ triggers: toggle(brief.triggers, option.value, on === true) })}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <Switch checked={brief.lookalike} onCheckedChange={(on) => set({ lookalike: on })} />
            Szukaj firm podobnych do tych, z którymi umówiliśmy spotkanie
          </label>
        </div>
      )}
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-foreground">Wielkość firmy (osoby)</legend>
        <div className="flex flex-wrap gap-3">
          {SIZE_OPTIONS.map((size) => (
            <label key={size} className="flex items-center gap-1.5 text-sm tabular-nums">
              <Checkbox
                checked={brief.sizes.includes(size)}
                onCheckedChange={(on) => set({ sizes: toggle<BotListSize>(brief.sizes, size, on === true) })}
              />
              {size}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={brief.include_unknown} onCheckedChange={(on) => set({ include_unknown: on })} />
        Bierz też firmy bez branży, miasta i wielkości na karcie
      </label>
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-foreground">Osoby dzwoniące</legend>
        <div className="flex flex-wrap gap-3">
          {(owners.data ?? []).map((person) => (
            <label key={person.id} className="flex items-center gap-1.5 text-sm">
              <Checkbox
                checked={brief.caller_ids.includes(person.id)}
                onCheckedChange={(on) => set({ caller_ids: toggle(brief.caller_ids, person.id, on === true) })}
              />
              {person.name}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1">
          <Label htmlFor="bot-list-batch">Firm na osobę tygodniowo</Label>
          <Input
            id="bot-list-batch"
            type="number"
            min={1}
            max={200}
            className="w-24"
            value={brief.per_caller}
            onChange={(e) => set({ per_caller: Number(e.target.value) || 0 })}
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <Switch checked={brief.auto_refill} onCheckedChange={(on) => set({ auto_refill: on })} />
          Dosypuj w poniedziałek od 7:00
        </label>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Pomija zawsze: klientów NEXUSA, „Nie kontaktować”, firmy z otwartą szansą, dzwonione w ostatnich 6 miesiącach
        i „Nie zainteresowany — nigdy”.
      </p>
      <div className="flex justify-end">
        <Button type="submit" size="sm" variant="outline" loading={saving} disabled={brief.roles.length === 0 || brief.caller_ids.length === 0}>
          Zapisz brief
        </Button>
      </div>
    </form>
  );
}

const EMPTY: Omit<BotListBrief, "caller_ids"> = {
  roles: ["manager", "head"],
  industries: [],
  pkd: [],
  regions: [],
  cities: [],
  sizes: [],
  triggers: [],
  sources: ["base"],
  include_unknown: true,
  per_caller: 40,
  auto_refill: true,
  lookalike: false,
};

/**
 * Bot Listy dla kampanii (decyzje Artura 13.11.2026): brief, „Zbuduj listę” i „Co działa”.
 * Lista trafia do kolejki od razu, przez te same bramki co import pliku.
 */
export function BotListPanel({ campaign, onBack }: { campaign: CallCampaign; onBack: () => void }) {
  const state = useBotList(campaign.id);
  const save = useSaveBrief(campaign.id);
  const build = useBuildList(campaign.id);
  const { showError, showSuccess } = useToast();

  if (state.isError) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 text-sm text-destructive">
        <span>{apiErrorMessage(state.error, "Nie udało się wczytać Bota Listy.")}</span>
        <Button size="sm" variant="outline" onClick={() => void state.refetch()}>
          Spróbuj ponownie
        </Button>
      </div>
    );
  }
  if (!state.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
  const data = state.data;
  if (!data.enabled) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">Bot Listy jest wyłączony.</p>
        <Button size="sm" variant="outline" onClick={onBack}>
          Wróć do kampanii
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <BriefForm
        key={data.brief ? "saved" : "new"}
        initial={data.brief ?? { ...EMPTY, caller_ids: [] }}
        saving={save.isPending}
        onSave={(brief) =>
          save.mutate(brief, {
            onSuccess: () => showSuccess("Zapisano brief kampanii."),
            onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać briefu.")),
          })
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          {data.built_at ? `Ostatnia lista: ${formatIsoDatePl(data.built_at)}. ` : ""}
          Lista trafia do kolejki od razu, bez przeglądania.
        </p>
        <Button
          size="sm"
          loading={build.isPending}
          disabled={!data.brief}
          onClick={() =>
            build.mutate(undefined, {
              onSuccess: (result) => {
                const skipped = Object.entries(result.skipped)
                  .map(([fate, count]) => `${SKIPPED_LABELS[fate] ?? fate}: ${count}`)
                  .join(", ");
                showSuccess(
                  result.added > 0
                    ? `Dodano ${result.added} do kolejki${skipped ? ` (pominięte — ${skipped})` : ""}.`
                    : "Każda osoba ma już pełną paczkę nowych rekordów.",
                );
              },
              onError: (error) => showError(apiErrorMessage(error, "Nie udało się zbudować listy.")),
            })
          }
        >
          <ListPlus className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Zbuduj listę
        </Button>
      </div>
      <div className="space-y-3 border-t border-border pt-3">
        <WorksTable title="Co działa: rola" rows={data.by_role} />
        <WorksTable title="Co działa: źródło listy" rows={data.by_source} />
      </div>
      <div className="flex justify-start">
        <Button size="sm" variant="quiet" onClick={onBack}>
          Wróć do kampanii
        </Button>
      </div>
    </div>
  );
}
