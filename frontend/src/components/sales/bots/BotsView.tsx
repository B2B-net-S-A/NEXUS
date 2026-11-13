"use client";

import { Building2, Newspaper, Search, Users, Database } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import { useSalesBots, useSetBotPaused, type SalesBot, type SalesBotKey } from "@/lib/api/sales-bots";
import { resolveViewState } from "@/lib/view-state";

interface BotCopy {
  icon: typeof Search;
  job: string;
  writes: string[];
  when: string[];
  never: string;
}

/** Opis pracy botów: decyzje Artura z 13.11.2026 (`docs/claude/sprzedaz/cztery-boty-sprzedazy.md`). */
export const BOT_COPY: Record<SalesBotKey, BotCopy> = {
  leads: {
    icon: Search,
    job: "Szuka okazji: co dzieje się w obserwowanych firmach, przegrane do odświeżenia i nowe centra IT w Polsce.",
    writes: ["Lead w Leadach z linkiem do źródła"],
    when: ["poniedziałek 7:00: firmy z tagiem „sygnały”", "pierwszy poniedziałek miesiąca: Warto wrócić, Nowe centra IT"],
    never: "Nie pisze ani nie dzwoni do nikogo. Firma klienta NEXUSA idzie do Delivery Leada, nie do Leadów.",
  },
  research: {
    icon: Newspaper,
    job: "Przygotowuje do rozmowy: punkty o firmie, haczyk przed telefonem, punkty przed spotkaniem, punkty przy ofertach „Do decyzji” i odpowiedź na „Zapytaj bota”.",
    writes: ["Punkty na karcie firmy, szansy i spotkania", "Haczyk na karcie rozmowy w Dzwonieniu"],
    when: ["dzień roboczy 16:00: firmy z jutrzejszej kolejki i spotkań", "poniedziałek 7:30: szanse z krokiem i „Do decyzji”", "na żądanie: „Zapytaj bota”"],
    never: "Nie dostaje nazwisk, stawek ani treści rozmów, tylko nazwę i domenę firmy.",
  },
  company: {
    icon: Building2,
    job: "Uzupełnia kartę firmy: domena, strona, NIP, miasto, branża, wielkość, firma matka.",
    writes: ["Od razu w puste pola karty", "Pole wpisane ręcznie zostaje, wersja bota idzie do historii karty"],
    when: ["noc 1:00–6:00: karty z opiekunem albo szansą, najpierw bez domeny", "na przycisk „Uzupełnij dane” na karcie"],
    never: "Nie scala kart: domena albo NIP z innej karty to tylko wpis w historii.",
  },
  contacts: {
    icon: Users,
    job: "Prowadzi ludzi na karcie: decydenci ze źródeł publicznych, z linkiem i datą publikacji.",
    writes: ["Od razu na mapę konta, z e-mailem i telefonem tylko ze źródła"],
    when: ["poniedziałek 8:00: konta z mapą poniżej 3 osób", "na przycisk „Znajdź decydentów”"],
    never: "Nie zgaduje e-maili z wzorców, nie czyta LinkedIna, nigdzie się nie loguje.",
  },
  cognism: {
    icon: Database,
    job: "Dopasowuje decydentów z Cognism do mapy karty firmy.",
    writes: ["Od razu na mapę decydentów karty"],
    when: ["po eksporcie z panelu Cognism"],
    never: "Osobna rutyna z panelem Cognism; NEXUS nie loguje się do Cognism.",
  },
};

const ROUTINE: Record<SalesBot["webhook"], string> = {
  own: "własna rutyna",
  shared: "wspólna rutyna",
  none: "brak rutyny",
};

function stateOf(bot: SalesBot): { label: string; tone: "success" | "warning" | "neutral" | "danger" } {
  if (!bot.enabled) return { label: "Wyłączony", tone: "neutral" };
  if (bot.webhook === "none") return { label: "Bez rutyny", tone: "danger" };
  if (bot.paused) return { label: "Wstrzymany", tone: "warning" };
  return { label: "Działa", tone: "success" };
}

function formatAt(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function BotCard({ bot, canPause }: { bot: SalesBot; canPause: boolean }) {
  const copy = BOT_COPY[bot.key];
  const Icon = copy.icon;
  const state = stateOf(bot);
  const setPaused = useSetBotPaused();
  const { showError, showSuccess } = useToast();
  return (
    <Card className="flex flex-col gap-2.5 p-4" aria-label={bot.name}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Icon className="size-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-foreground">{bot.name}</h2>
            <p className="text-xs text-muted-foreground">Grok · {ROUTINE[bot.webhook]}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={state.tone} size="md">
            {state.label}
          </Badge>
          {canPause && (
            <Switch
              checked={bot.enabled && !bot.paused}
              disabled={!bot.enabled || setPaused.isPending}
              aria-label={bot.paused ? `Wznów: ${bot.name}` : `Wstrzymaj: ${bot.name}`}
              onCheckedChange={(checked) =>
                setPaused.mutate(
                  { bot: bot.key, paused: !checked },
                  {
                    onSuccess: () => showSuccess(checked ? `Wznowiono: ${bot.name}.` : `Wstrzymano: ${bot.name}.`),
                    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić stanu bota.")),
                  },
                )
              }
            />
          )}
        </div>
      </div>
      <p className="text-sm text-foreground">{copy.job}</p>
      <dl className="grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="font-medium text-foreground">Zapisuje od razu</dt>
          <dd>
            <ul className="list-disc pl-4 text-muted-foreground">
              {copy.writes.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="font-medium text-foreground">Kiedy</dt>
          <dd>
            <ul className="list-disc pl-4 text-muted-foreground">
              {copy.when.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Nigdy: </span>
        {copy.never}
      </p>
      <p className="mt-auto border-t border-border pt-2 text-xs text-muted-foreground">
        Ostatnie 7 dni: <span className="font-semibold tabular-nums text-foreground">{bot.runs_7d}</span> biegów,{" "}
        <span className="font-semibold tabular-nums text-foreground">{bot.received_7d}</span> z raportem
        {bot.failed_7d > 0 && (
          <>
            , <span className="font-semibold tabular-nums text-foreground">{bot.failed_7d}</span> bez raportu
          </>
        )}
        {bot.last_received_at && <> · ostatni raport {formatAt(bot.last_received_at)}</>}
      </p>
    </Card>
  );
}

/**
 * Sprzedaż → Leady → Boty (decyzja Artura z 13.11.2026): cztery boty i rutyna
 * Cognism, co robią, kiedy, czego nigdy nie robią i ile pracowały. Administrator
 * wstrzymuje i wznawia bota; główny włącznik zostaje we flagach środowiskowych.
 */
export function BotsView() {
  const query = useSalesBots();
  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) return <p className="py-6 text-sm text-muted-foreground">Wczytywanie botów…</p>;
  return (
    <div className="space-y-3">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Wynik bota zapisuje się od razu w karcie, bez „Przyjmij”. Każde pole i każdą osobę można poprawić jak zwykle;
        pola firmy poprawionego ręcznie bot już nie zmienia. Skąd przyszła wartość, widać w historii karty (Aktywności).
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        {query.data.items.map((bot) => (
          <BotCard key={bot.key} bot={bot} canPause={query.data.can_pause} />
        ))}
      </div>
    </div>
  );
}
