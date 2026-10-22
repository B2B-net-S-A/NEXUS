"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useApplyAutoAssignment,
  useCareAutoAssignment,
  useSaveOwnerPool,
  type CareAutoAssignment,
  type OwnerPoolPayload,
} from "@/lib/api/care";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { peopleText } from "./cadence-format";
import { orphansText } from "./team/team-format";

const LIST_LIMIT = 100;

interface Draft {
  managerId: number | null;
  excluded: number[];
  auto: boolean;
}

function draftOf(data: CareAutoAssignment): Draft {
  return {
    managerId: data.config.manager?.id ?? null,
    excluded: data.config.excluded_user_ids,
    // Niezapisana pula: proponujemy włączony automat, rusza po zapisie.
    auto: data.config.saved ? data.config.auto_new_contracts : true,
  };
}

function sameDraft(a: Draft, b: Draft): boolean {
  return (
    a.managerId === b.managerId &&
    a.auto === b.auto &&
    [...a.excluded].sort().join(",") === [...b.excluded].sort().join(",")
  );
}

function PoolEditor({
  data,
  saving,
  onSave,
  onDirtyChange,
}: {
  data: CareAutoAssignment;
  saving: boolean;
  onSave: (payload: OwnerPoolPayload) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const saved = draftOf(data);
  const [draft, setDraft] = useState<Draft>(saved);
  const dirty = !sameDraft(draft, saved) || !data.config.saved;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  const managers = data.config.manager && !data.manager_choices.some((m) => m.id === data.config.manager?.id)
    ? [{ id: data.config.manager.id, name: data.config.manager.name ?? `Konto ${data.config.manager.id}` }, ...data.manager_choices]
    : data.manager_choices;
  const toggleExcluded = (id: number) =>
    setDraft((current) => ({
      ...current,
      excluded: current.excluded.includes(id)
        ? current.excluded.filter((value) => value !== id)
        : [...current.excluded, id],
    }));
  const submit = () =>
    onSave({ manager_user_id: draft.managerId, excluded_user_ids: draft.excluded, auto_new_contracts: draft.auto });

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Opiekunami mogą być osoby podlegające pod</span>
        <Select
          value={draft.managerId ? String(draft.managerId) : ""}
          onValueChange={(value) => setDraft((current) => ({ ...current, managerId: Number(value) }))}
        >
          <SelectTrigger aria-label="Koordynator puli opiekunów" className="h-8 w-56">
            <SelectValue placeholder="Wybierz koordynatora…" />
          </SelectTrigger>
          <SelectContent>
            {managers.map((manager) => (
              <SelectItem key={manager.id} value={String(manager.id)}>
                {manager.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {data.config.manager_from_division ? (
          <span className="text-xs text-muted-foreground">(head back office — nikt nie wskazał innej osoby)</span>
        ) : null}
      </div>
      {data.pool.length ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm" aria-label="Pula opiekunów">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>Podopieczni teraz</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>Po przydziale</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Nie przypisuj</th>
              </tr>
            </thead>
            <tbody>
              {data.pool.map((member) => {
                const excluded = draft.excluded.includes(member.id);
                return (
                  <tr key={member.id} className={cn(CALM_ROW, excluded && "text-muted-foreground")}>
                    <td className="px-3 py-1.5 align-top">
                      <span className="font-medium">{member.name}</span>
                      {member.note ? (
                        <span className="block text-xs text-warning-muted-foreground">{member.note}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 text-right align-top tabular-nums">
                      {member.eligible ? member.consultants_now ?? 0 : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right align-top tabular-nums">
                      {member.eligible ? member.consultants_after ?? 0 : "—"}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <Checkbox
                        aria-label={`Nie przypisuj konsultantów: ${member.name}`}
                        checked={excluded}
                        onCheckedChange={() => toggleExcluded(member.id)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {draft.managerId
            ? "Pod tą osobą nikt nie pracuje w kartotece (Ludzie → Struktura)."
            : "Wskaż koordynatora — osoby z jego zespołu w kartotece będą opiekunami."}
        </p>
      )}
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={draft.auto}
          onCheckedChange={(value) => setDraft((current) => ({ ...current, auto: value === true }))}
        />
        Nowy kontrakt od razu dostaje opiekuna z puli według obłożenia
      </label>
      {dirty ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={saving} onClick={submit}>
            {saving ? "Zapisywanie…" : "Zapisz pulę"}
          </Button>
          {sameDraft(draft, saved) ? null : (
            <Button size="sm" variant="ghost" onClick={() => setDraft(saved)}>
              Cofnij zmiany
            </Button>
          )}
          <span className="text-xs text-muted-foreground">
            {data.config.saved
              ? "Podgląd przydziału przeliczy się po zapisie."
              : "Pula nie jest jeszcze zapisana — przydział i automat dla nowych kontraktów ruszą po zapisie."}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Zapis „Przypisz wg obłożenia” po potwierdzeniu — te same pary co w podglądzie. */
function useAutoApply(data: CareAutoAssignment) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const apply = useApplyAutoAssignment();
  const count = data.items.length;

  const submit = async () => {
    const ok = await askConfirm({
      title: `Przypisać opiekuna ${count === 1 ? "1 konsultantowi" : `${count} konsultantom`}?`,
      description:
        "Każdy dostanie osobę z puli z najmniejszą liczbą podopiecznych, tak jak w podglądzie. Zmiana zostaje na osi konsultanta.",
      confirmLabel: "Zapisz przydział",
    });
    if (!ok) return;
    apply.mutate(
      data.items.map((item) => ({ contract_id: item.contract_id, owner_user_id: item.owner.id })),
      {
        onSuccess: (result) =>
          showToast(
            result.skipped
              ? `Przypisano: ${peopleText(result.changed)}. Pominięto ${result.skipped} — mieli już opiekuna.`
              : `Przypisano: ${peopleText(result.changed)}`,
            "success",
          ),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać przydziału."), "error"),
      },
    );
  };
  return { submit, pending: apply.isPending, confirmDialog };
}

function PreviewTable({ data }: { data: CareAutoAssignment }) {
  const count = data.items.length;
  return (
    <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
      <table className="w-full text-sm" aria-label="Podgląd przydziału wg obłożenia">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
          </tr>
        </thead>
        <tbody>
          {data.items.slice(0, LIST_LIMIT).map((item) => (
            <tr key={item.contract_id} className={CALM_ROW}>
              <td className="px-3 py-1.5">{item.candidate_name ?? "Konsultant"}</td>
              <td className="px-3 py-1.5">{item.client_name}</td>
              <td className="px-3 py-1.5">{item.owner.name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {count > LIST_LIMIT ? (
        <p className="px-3 py-2 text-xs text-muted-foreground">
          i jeszcze {peopleText(count - LIST_LIMIT)} — zapis obejmie wszystkich z podglądu.
        </p>
      ) : null}
    </div>
  );
}

function AutoPreview({ data, stale }: { data: CareAutoAssignment; stale: boolean }) {
  const { submit, pending, confirmDialog } = useAutoApply(data);
  const [showList, setShowList] = useState(false);
  const count = data.items.length;

  return (
    <div className="space-y-2 border-t border-border pt-3">
      <p className="text-sm">
        <span className="font-medium">Bez opiekuna na kontrakcie: {data.counts.targets}.</span>{" "}
        <span className="text-muted-foreground">
          Automat daje każdego osobie z puli, która ma najmniej podopiecznych; przy remisie decyduje kolejność
          alfabetyczna. Osoby wykluczone i bez dostępu do Opieki pomija.
        </span>
      </p>
      {data.unassigned.length ? (
        <p className="text-sm text-warning-muted-foreground">
          Bez opiekuna zostanie {peopleText(data.unassigned.length)}: {data.unassigned[0].reason}.
        </p>
      ) : null}
      {count ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={pending || stale}
            title={stale ? "Najpierw zapisz pulę — podgląd liczy się z zapisanej" : undefined}
            onClick={() => void submit()}
          >
            {pending ? "Zapisywanie…" : `Przypisz wg obłożenia (${count})`}
          </Button>
          <Button size="sm" variant="ghost" aria-expanded={showList} onClick={() => setShowList((v) => !v)}>
            {showList ? "Ukryj podgląd" : "Pokaż podgląd"}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Nie ma kogo przypisać.</p>
      )}
      {showList && count ? <PreviewTable data={data} /> : null}
      {confirmDialog}
    </div>
  );
}

/**
 * „Opieka · Przydział” — pula opiekunów i „Przypisz wg obłożenia” (decyzja
 * Artura 18.10.2026). Pula = bezpośredni podwładni wskazanego przełożonego
 * w kartotece, minus osoby „nie przypisuj”. Widzi i zmienia head back office
 * albo administrator (``can_assign``).
 */
export function OwnerPoolPanel({
  withAutoPreview = true,
}: {
  /** Okno „Ustawienia przydziału” ma przydział na pasku ekranu, nie w oknie. */
  withAutoPreview?: boolean;
} = {}) {
  const { showToast } = useToast();
  const query = useCareAutoAssignment();
  // Zapis w rodzicu: edytor przemontowuje się po zapisie (``key``), a wtedy
  // callback z ``mutate`` w dziecku by przepadł.
  const save = useSaveOwnerPool();
  const [poolDirty, setPoolDirty] = useState(false);
  const onSave = (payload: OwnerPoolPayload) =>
    save.mutate(payload, {
      onSuccess: () => showToast("Pula opiekunów zapisana", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać puli opiekunów."), "error"),
    });
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const data = query.data;

  return (
    <section
      className="space-y-3 rounded-lg border border-border bg-card px-3 py-3"
      aria-label="Pula opiekunów"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold text-foreground">Pula opiekunów</h3>
        {data ? (
          <Badge variant="neutral" size="sm">
            przypisujemy do {peopleText(data.counts.eligible)}
          </Badge>
        ) : null}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie puli…</p>
      ) : state !== "ready" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={state === "error" ? "Nie udało się wczytać puli opiekunów." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : (
        <>
          <PoolEditor
            key={JSON.stringify(data.config)}
            data={data}
            saving={save.isPending}
            onSave={onSave}
            onDirtyChange={setPoolDirty}
          />
          {withAutoPreview ? <AutoPreview data={data} stale={poolDirty} /> : null}
        </>
      )}
    </section>
  );
}

/**
 * Pasek „bez opiekuna” w „Zespole opiekunów” (makieta P6): ilu konsultantów
 * nie ma opiekuna na kontrakcie, u których klientów i od kiedy, z „Podgląd”
 * i „Przypisz wg obłożenia (N)” — ten sam zapis co w puli. Gdy nie ma kogo
 * przypisać, pasek znika; awaria podglądu to komunikat, nie pustka.
 */
export function AutoAssignBar() {
  const query = useCareAutoAssignment();
  const data = query.data;
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się policzyć przydziału wg obłożenia."
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!data || !data.items.length) return null;
  return <AutoAssignBarBody data={data} />;
}

function AutoAssignBarBody({ data }: { data: CareAutoAssignment }) {
  const { submit, pending, confirmDialog } = useAutoApply(data);
  const [showList, setShowList] = useState(false);
  const count = data.items.length;
  return (
    <section
      aria-label="Konsultanci bez opiekuna"
      className="space-y-2 rounded-lg border border-warning/50 bg-warning/10 px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
        <p className="min-w-0 flex-1">
          <span className="font-semibold">{orphansText(data.items)}.</span>{" "}
          <span className="text-muted-foreground">
            Automat przypisze osobie z puli, która ma najmniej podopiecznych.
          </span>
          {data.unassigned.length ? (
            <span className="block text-xs text-warning-muted-foreground">
              Bez opiekuna zostanie {peopleText(data.unassigned.length)}: {data.unassigned[0].reason}.
            </span>
          ) : null}
        </p>
        <span className="flex shrink-0 items-center gap-1.5">
          <Button size="sm" variant="outline" aria-expanded={showList} onClick={() => setShowList((v) => !v)}>
            {showList ? "Ukryj podgląd" : "Podgląd"}
          </Button>
          <Button size="sm" disabled={pending} onClick={() => void submit()}>
            {pending ? "Zapisywanie…" : `Przypisz wg obłożenia (${count})`}
          </Button>
        </span>
      </div>
      {showList ? <PreviewTable data={data} /> : null}
      {confirmDialog}
    </section>
  );
}
