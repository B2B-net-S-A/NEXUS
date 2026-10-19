"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CalendarCheck } from "lucide-react";

import { ConversationDialog } from "@/components/care/ConversationDialog";
import { EmptyState } from "@/components/ds/EmptyState";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Progress } from "@/components/ui/progress";
import { useCareWeek, type CareWeek, type WeekContact } from "@/lib/api/care";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { ConsultantPanel } from "./ConsultantPanel";
import { FeedbackRequestsSection } from "./FeedbackRequestsSection";
import { WeekBoard } from "./WeekBoard";
import { shiftIso, weekProgress, weekRangeLabel } from "./week-format";

/** `?contract=` — panel osi otwarty z linku (powiadomienie „Konsultant dla front office”). */
export function contractParam(value: string | null | undefined): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

interface TalkTarget {
  contractId: number;
  clientId: number;
  planItem: { id: number; label: string } | null;
}

/** Pasek tygodnia: ile zaplanowanych rozmów już zapisanych, zaległe, opinie. */
function WeekSummary({ data }: { data: CareWeek }) {
  const progress = weekProgress(data.counts);
  const parts = [
    `${data.counts.overdue} zaległe`,
    data.feedback_visible ? `${data.counts.feedback} opinie` : null,
    `${data.counts.front_office} do przekazania do front office`,
  ].filter(Boolean);
  return (
    <div className="flex min-w-60 flex-1 items-center gap-2.5" id="care-week-stats">
      <Progress
        value={progress.percent}
        aria-label={`Zapisane rozmowy: ${progress.done} z ${progress.total}`}
        className="h-2 max-w-56 flex-[0_1_14rem] bg-border [&>div]:bg-success"
      />
      <span className="text-sm text-muted-foreground">
        <span className="font-semibold text-foreground">
          {progress.done} z {progress.total}
        </span>{" "}
        zrobione · {parts.join(" · ")}
      </span>
    </div>
  );
}

/**
 * „Opieka · Ten tydzień” (D15, plan dni 19.10.2026): rozmowy z konsultantami
 * rozłożone na „Zaległe · pn … pt” z powodem, sygnałami i ostatnią oceną,
 * pod nimi pas próśb o opinię od menedżerów. Kliknięcie konsultanta otwiera
 * oś z „Przekaż do front office”. Awaria zapytania ≠ pusta kolejka.
 */
export function WeekPanel() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [from, setFrom] = useState<string | null>(null);
  const [talk, setTalk] = useState<TalkTarget | null>(null);
  const query = useCareWeek(scope, from);
  const data = query.data;
  // Panel z adresu (link z powiadomienia) i z kliknięcia; adres pisze
  // `useUrlWriter` (natywna historia), więc stan trzymamy też lokalnie.
  const urlContract = contractParam(searchParams?.get("contract"));
  const [selected, setSelected] = useState<number | null>(urlContract);
  useEffect(() => setSelected(urlContract), [urlContract]);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (data?.contacts.length ?? 0) + (data?.feedback.length ?? 0) === 0,
  });

  const setContract = (id: number | null) => {
    setSelected(id);
    const params = new URLSearchParams(window.location.search);
    if (id == null) params.delete("contract");
    else params.set("contract", String(id));
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  const talkTo = (row: WeekContact) => {
    const plan = row.reasons.find((reason) => reason.plan_item_id != null);
    setTalk({
      contractId: row.contract_id,
      clientId: row.client_id,
      planItem: plan?.plan_item_id ? { id: plan.plan_item_id, label: plan.label } : null,
    });
  };
  const selectedRow = data?.contacts.find((row) => row.contract_id === selected) ?? null;

  const list = (
    <div className="space-y-3.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Tydzień">
          <Button
            size="sm"
            variant="ghost"
            aria-label="Poprzedni tydzień"
            disabled={!data}
            onClick={() => data && setFrom(shiftIso(data.week.from, -7))}
          >
            ‹
          </Button>
          <span className="min-w-36 text-center text-sm font-semibold tabular-nums">
            {data
              ? `${data.week.is_current ? "Ten tydzień" : "Tydzień"} · ${weekRangeLabel(data.week.from, data.week.to)}`
              : "Ten tydzień"}
          </span>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Następny tydzień"
            disabled={!data}
            onClick={() => data && setFrom(shiftIso(data.week.from, 7))}
          >
            ›
          </Button>
          {data && !data.week.is_current ? (
            <Button size="sm" variant="ghost" onClick={() => setFrom(null)}>
              Wróć do tego tygodnia
            </Button>
          ) : null}
        </div>
        {state !== "loading" && data ? <WeekSummary data={data} /> : <div className="flex-1" />}
        <SegmentedRadio
          label="Zakres listy"
          size="sm"
          value={scope}
          onChange={setScope}
          options={[
            { value: "mine", label: "Moi" },
            { value: "all", label: "Wszyscy w moim zakresie" },
          ]}
        />
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie tygodnia…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "error" ? "Nie udało się wczytać kolejki na ten tydzień." : undefined
          }
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={CalendarCheck}
          title="W tym tygodniu nie ma zaplanowanych kontaktów"
          description={
            scope === "mine"
              ? "Kontakty z planu opieki i umówione rozmowy Twoich konsultantów pojawią się tutaj."
              : undefined
          }
          action={
            // Admin i osoby bez podopiecznych widziały tu pustkę, a w
            // „Wszyscy” czekało kilkaset kontaktów (testy produkcji 19.10).
            scope === "mine" ? (
              <Button size="sm" variant="outline" onClick={() => setScope("all")}>
                Pokaż wszystkich w moim zakresie
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {data.contacts.length ? (
            <WeekBoard
              data={data}
              showOwner={scope === "all"}
              selectedId={selected}
              onOpen={(row) => setContract(row.contract_id)}
              onTalk={talkTo}
            />
          ) : (
            <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
              Rozmów z konsultantami w tym tygodniu nie ma — zostały opinie od menedżerów.
            </p>
          )}
          <FeedbackRequestsSection
            items={data.feedback}
            canWrite={data.can_write_feedback}
            today={data.week.today}
          />
        </>
      )}
    </div>
  );

  return (
    <>
      <ListDetailLayout
        list={list}
        panel={
          selected != null ? (
            <ConsultantPanel
              key={selected}
              contractId={selected}
              onClose={() => setContract(null)}
              onTalk={(clientId) =>
                selectedRow
                  ? talkTo(selectedRow)
                  : setTalk({ contractId: selected, clientId, planItem: null })
              }
            />
          ) : null
        }
        onClose={() => setContract(null)}
        panelLabel="Oś konsultanta"
      />
      {talk ? (
        <ConversationDialog
          contractId={talk.contractId}
          clientId={talk.clientId}
          planItem={talk.planItem}
          open
          onOpenChange={(open) => {
            if (!open) setTalk(null);
          }}
        />
      ) : null}
    </>
  );
}
