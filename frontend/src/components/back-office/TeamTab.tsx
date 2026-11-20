"use client";

import { useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoTeam,
  useReleaseOutsiders,
  useRemoveMember,
  useSaveMember,
  useSaveOutsideContacts,
  type BoMemberRole,
  type BoTeamSetup,
} from "@/lib/api/back-office";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { PortalFaqTab } from "./PortalFaqTab";
import { QualityTab } from "./QualityTab";
import { ReviewPanel } from "./ReviewPanel";
import { TalksTab } from "./TalksTab";

const SELECT = "h-8 rounded-md border border-border bg-card px-2 text-xs";

export type TeamSection = "team" | "outside" | "review" | "faq" | "talks" | "quality";
type Section = TeamSection;
const SECTIONS: { id: Section; label: string }[] = [
  { id: "team", label: "Skład i role" },
  { id: "outside", label: "Działy na zewnątrz" },
  { id: "review", label: "Przegląd przed startem" },
  { id: "faq", label: "FAQ portalu" },
  { id: "talks", label: "Rozmowy z portalu" },
  { id: "quality", label: "Jakość rozmów" },
];

function Roster({ data }: { data: BoTeamSetup }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const save = useSaveMember();
  const remove = useRemoveMember();
  const release = useReleaseOutsiders();
  const [adding, setAdding] = useState("");
  const memberIds = new Set(data.members.map((row) => row.user_id));
  const fail = (error: unknown, fallback: string) => showToast(apiErrorMessage(error, fallback), "error");
  const change = (userId: number, role: BoMemberRole, takesCalls: boolean) =>
    save.mutate({ user_id: userId, role, takes_calls: takesCalls }, { onError: (error) => fail(error, "Nie udało się zapisać składu.") });
  const outsiderCards = data.outsiders.reduce((sum, row) => sum + row.cards, 0);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-3">
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
          <h3 className="text-sm font-semibold">Zespół back office · {data.members.length} osób</h3>
          <div className="flex items-center gap-1.5">
            <select
              aria-label="Dodaj osobę do zespołu"
              className={SELECT}
              value={adding}
              onChange={(event) => setAdding(event.target.value)}
            >
              <option value="">dodaj osobę…</option>
              {data.candidates
                .filter((person) => !memberIds.has(person.id))
                .map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              disabled={!adding || save.isPending}
              onClick={() => {
                change(Number(adding), "member", true);
                setAdding("");
              }}
            >
              Dodaj do zespołu
            </Button>
          </div>
        </header>
        {data.from_permissions ? (
          <p className="border-b border-border bg-warning-muted/50 px-3 py-2 text-xs text-warning-muted-foreground">
            Skład nie jest jeszcze wpisany, więc do spraw wchodzi każdy z uprawnieniami Sprawy, Płace, Kontrakty albo Moduł
            Finanse — także Delivery Leadzi. Pierwsza dodana osoba zamyka tę furtkę.
          </p>
        ) : null}
        {data.members.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">Dodaj pierwszą osobę z back office&apos;u.</p>
        ) : (
          <table className="w-full text-sm" aria-label="Skład zespołu">
            <thead>
              <tr className={CALM_ROW}>
                {["Osoba", "Rola w zespole", "W toku", "Po terminie", "Rozmowy z portalu", ""].map((head) => (
                  <th key={head} className={cn(CALM_HEAD, "px-3 py-2 text-left")}>
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.members.map((row) => (
                <tr key={row.user_id} className={CALM_ROW}>
                  <td className="px-3 py-1.5 text-[13px] font-medium">{row.name}</td>
                  <td className="px-3 py-1.5">
                    <select
                      aria-label={`Rola: ${row.name}`}
                      className={SELECT}
                      value={row.role}
                      disabled={save.isPending}
                      onChange={(event) => change(row.user_id, event.target.value as BoMemberRole, row.takes_calls)}
                    >
                      {data.roles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">{row.in_progress || <span className={CALM_EMPTY}>0</span>}</td>
                  <td className={cn("px-3 py-1.5 tabular-nums", row.overdue > 0 && "text-destructive")}>
                    {row.overdue || <span className={CALM_EMPTY}>0</span>}
                  </td>
                  <td className="px-3 py-1.5">
                    <Switch
                      checked={row.takes_calls}
                      aria-label={`Przyjmuje rozmowy z portalu: ${row.name}`}
                      disabled={save.isPending}
                      onCheckedChange={(checked) => change(row.user_id, row.role, checked)}
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <Button
                      size="icon-sm"
                      variant="quiet"
                      aria-label={`Usuń z zespołu: ${row.name}`}
                      onClick={async () => {
                        const ok = await askConfirm({
                          title: `Usunąć ${row.name ?? "tę osobę"} z zespołu?`,
                          description: "Jej sprawy zostaną u niej; oddasz je do kolejki przyciskiem obok składu.",
                          confirmLabel: "Usuń",
                          cancelLabel: "Anuluj",
                        });
                        if (ok) remove.mutate(row.user_id, { onError: (error) => fail(error, "Nie udało się usunąć osoby.") });
                      }}
                    >
                      <Trash2 aria-hidden className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="px-3 py-2 text-[11.5px] text-muted-foreground">
          Jeden zespół, bez podziału na Opiekę, Finanse, Umowy i Zamówienia. Head of Back Office:{" "}
          {data.head?.name ?? "nie wskazany (kierownikiem kolejki jest admin)"}. Zastępca prowadzi kolejkę pod nieobecność
          Heada. Nikt nie ma przypisanych konsultantów.
        </p>
      </section>
      <aside className="space-y-3">
        {data.outsiders.length > 0 ? (
          <section className="rounded-xl border border-destructive/30 bg-destructive-muted/40 p-3">
            <h4 className="flex items-center gap-1.5 text-sm font-semibold text-destructive-muted-foreground">
              <AlertTriangle aria-hidden className="size-4" /> Sprawy u osób spoza zespołu
            </h4>
            <ul className="mt-2 space-y-1 text-[12.5px]">
              {data.outsiders.map((row) => (
                <li key={row.user_id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{row.name}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{row.cards} spraw</span>
                </li>
              ))}
            </ul>
            <Button
              size="sm"
              variant="outline"
              className="mt-2 h-7 text-xs"
              disabled={release.isPending}
              onClick={async () => {
                const ok = await askConfirm({
                  title: `Oddać ${outsiderCards} spraw do kolejki?`,
                  description: "Wrócą do „Nowe” bez osoby; każda dostanie wpis w historii.",
                  confirmLabel: "Oddaj do kolejki",
                  cancelLabel: "Anuluj",
                });
                if (!ok) return;
                release.mutate(undefined, {
                  onSuccess: (result) => showToast(`Wróciło do kolejki: ${result.released}`, "success"),
                  onError: (error) => fail(error, "Nie udało się oddać spraw."),
                });
              }}
            >
              Oddaj do kolejki ({outsiderCards})
            </Button>
          </section>
        ) : null}
        <section className="rounded-xl border border-border bg-card p-3 text-[12.5px] text-muted-foreground">
          <h4 className="mb-1 text-sm font-semibold text-foreground">Jak działa kolejka</h4>
          <p>
            Sprawę bierze pierwsza wolna osoba („Weź następną” daje najstarszą). Limit 5 w toku na osobę. Sprawa bez osoby po
            dniu roboczym trafia do „Do przydzielenia” u kierownika.
          </p>
        </section>
      </aside>
      {confirmDialog}
    </div>
  );
}

function OutsideContacts({ data }: { data: BoTeamSetup }) {
  const { showToast } = useToast();
  const save = useSaveOutsideContacts();
  return (
    <section className="max-w-[720px] overflow-hidden rounded-xl border border-border bg-card">
      <header className="border-b border-border px-3 py-2">
        <h3 className="text-sm font-semibold">Gdy back office nie da rady — do kogo</h3>
        <p className="text-xs text-muted-foreground">
          Osoba kontaktowa działu widzi, że sprawa na nią czeka; w karcie sprawy to przycisk „Na zewnątrz”.
        </p>
      </header>
      <table className="w-full text-sm" aria-label="Działy na zewnątrz">
        <tbody>
          {data.outside_contacts.map((row) => (
            <tr key={row.id} className={CALM_ROW}>
              <td className="w-[220px] px-3 py-1.5 text-[13px] font-medium">{row.label}</td>
              <td className="px-3 py-1.5">
                <select
                  aria-label={`Osoba kontaktowa: ${row.label}`}
                  className={cn(SELECT, "w-full")}
                  value={row.contact?.id ?? ""}
                  disabled={save.isPending}
                  onChange={(event) =>
                    save.mutate(
                      { [row.id]: event.target.value ? Number(event.target.value) : null },
                      { onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać działu."), "error") },
                    )
                  }
                >
                  <option value="">nie wskazano</option>
                  {data.candidates.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.name}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/**
 * Zespół (wariant A z 19.11.2026) i ustawienia modułu dla kierownika: skład
 * z rolami, działy na zewnątrz, przegląd przed startem, FAQ i rozmowy portalu,
 * jakość rozmów. Zastępuje „Zespół opiekunów”, „Zespoły”, „Jakość” i „Przegląd”.
 */
export function TeamTab({ initialSection = "team" }: { initialSection?: TeamSection }) {
  const query = useBoTeam();
  const [section, setSection] = useState<Section>(initialSection);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Zespół i ustawienia">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={section === item.id}
            onClick={() => setSection(item.id)}
            className={cn(
              "inline-flex h-7 items-center rounded-full border px-2.5 text-xs",
              section === item.id ? "border-primary bg-primary/10 font-medium text-primary" : "border-border bg-card text-muted-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
      {section === "team" || section === "outside" ? (
        query.isError ? (
          <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać zespołu.")}</p>
        ) : !query.data ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : section === "team" ? (
          <Roster data={query.data} />
        ) : (
          <OutsideContacts data={query.data} />
        )
      ) : null}
      {section === "review" ? <ReviewPanel /> : null}
      {section === "faq" ? <PortalFaqTab /> : null}
      {section === "talks" ? <TalksTab /> : null}
      {section === "quality" ? <QualityTab /> : null}
    </div>
  );
}
