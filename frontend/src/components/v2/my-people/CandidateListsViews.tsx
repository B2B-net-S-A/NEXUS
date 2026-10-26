"use client";

/**
 * Zakładka „Listy” w panelu „Moi ludzie” (prośba Olafa, decyzja Artura
 * 25.10.2026): listy, do których dokłada się ludzi ręcznie, obok listy
 * wyliczanej z procesów. Nowa lista jest „Tylko ja”; właściciel przełącza
 * „Widzi zespół”. Cudze listy zespołu są do podglądu i dodania do rekrutacji.
 */

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Lock, Plus, Trash2, UserPlus, Users, X } from "lucide-react";

import {
  TALENT_POOLS_PREFIX,
  candidateListsApi,
  memberName,
  memberSkills,
  useCandidateLists,
  useListMembers,
  type ListMember,
  type TalentPoolOut,
} from "@/lib/api/candidateLists";
import { apiErrorMessage } from "@/lib/api-error";
import { plural } from "@/lib/my-people-summary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { ErrorView } from "./MyPeopleViews";

type AddFn = (row: { candidate_id: number; full_name: string }) => void;

export function addedLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0) return "dodany dziś";
  if (days === 1) return "dodany wczoraj";
  return `dodany ${days} dni temu`;
}

function VisibilityBadge({ list }: { list: TalentPoolOut }) {
  return list.team_visible ? (
    <Badge size="sm" variant="soft" className="gap-1">
      <Users className="h-3 w-3" aria-hidden />
      Widzi zespół
    </Badge>
  ) : (
    <Badge size="sm" variant="neutral" className="gap-1">
      <Lock className="h-3 w-3" aria-hidden />
      Tylko ja
    </Badge>
  );
}

function ListCard({
  list,
  onOpen,
  showOwner,
}: {
  list: TalentPoolOut;
  onOpen: () => void;
  showOwner?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-left hover:bg-muted/60"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{list.name}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>
              {list.candidate_count} {plural(list.candidate_count, "osoba", "osoby", "osób")}
            </span>
            {showOwner ? (
              <span>· {list.owner_name ?? "inna osoba"}</span>
            ) : (
              <VisibilityBadge list={list} />
            )}
          </p>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      </button>
    </li>
  );
}

function MemberRow({
  member,
  onAdd,
  onRemove,
  busy,
}: {
  member: ListMember;
  onAdd: AddFn;
  onRemove?: () => void;
  busy?: boolean;
}) {
  const name = memberName(member);
  return (
    <li className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-muted/60">
      <div className="min-w-0 flex-1">
        <Link
          href={`/candidates/${member.id}`}
          className="truncate text-sm font-medium text-foreground hover:underline"
        >
          {name}
        </Link>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[memberSkills(member).join(", ") || null, member.location, addedLabel(member.added_at)]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Dodaj do rekrutacji: ${name}`}
          title="Dodaj do rekrutacji"
          onClick={() => onAdd({ candidate_id: member.id, full_name: name })}
        >
          <UserPlus className="h-4 w-4" aria-hidden />
        </Button>
        {onRemove ? (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Usuń z listy: ${name}`}
            title="Usuń z listy"
            disabled={busy}
            onClick={onRemove}
          >
            <X className="h-4 w-4" aria-hidden />
          </Button>
        ) : null}
      </div>
    </li>
  );
}

function ListDetail({
  list,
  editable,
  onBack,
  onAdd,
}: {
  list: TalentPoolOut;
  editable: boolean;
  onBack: () => void;
  onAdd: AddFn;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const members = useListMembers(list.id);
  const refresh = () => queryClient.invalidateQueries({ queryKey: TALENT_POOLS_PREFIX });

  const remove = useMutation({
    mutationFn: (candidateId: number) => candidateListsApi.remove(list.id, candidateId),
    onSuccess: refresh,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się usunąć osoby z listy.")),
  });
  const share = useMutation({
    mutationFn: (teamVisible: boolean) =>
      candidateListsApi.update(list.id, { team_visible: teamVisible }),
    onSuccess: (updated) => {
      showSuccess(updated.team_visible ? "Zespół widzi tę listę." : "Listę widzisz tylko Ty.");
      void refresh();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się zmienić widoczności listy.")),
  });
  const drop = useMutation({
    mutationFn: () => candidateListsApi.remove_list(list.id),
    onSuccess: () => {
      showSuccess(`Usunięto listę „${list.name}”.`);
      onBack();
      void refresh();
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się usunąć listy.")),
  });

  const count = members.data?.total ?? list.candidate_count;
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        Wszystkie listy
      </button>
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-foreground">{list.name}</h3>
        <p className="text-xs text-muted-foreground">
          {count} {plural(count, "osoba", "osoby", "osób")}
          {editable ? "" : ` · lista: ${list.owner_name ?? "inna osoba"}, tylko podgląd`}
        </p>
      </div>
      {editable ? (
        <div className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
          <label htmlFor={`list-share-${list.id}`} className="min-w-0 flex-1 text-xs">
            <span className="block font-medium text-foreground">Widzi zespół</span>
            <span className="block text-muted-foreground">
              {list.team_visible
                ? "Każdy w zespole widzi tę listę i jej osoby. Zmieniasz ją tylko Ty."
                : "Teraz widzisz ją tylko Ty."}
            </span>
          </label>
          <Switch
            id={`list-share-${list.id}`}
            checked={list.team_visible}
            disabled={share.isPending}
            onCheckedChange={(next) => share.mutate(next)}
          />
        </div>
      ) : null}

      {members.isError ? (
        <ErrorView
          message={apiErrorMessage(members.error, "Nie udało się wczytać osób z listy.")}
          onRetry={() => void members.refetch()}
        />
      ) : !members.isSuccess ? (
        <p className="px-2 py-6 text-center text-sm text-muted-foreground">Wczytuję listę…</p>
      ) : members.data.candidates.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Lista jest pusta. Dodajesz z profilu kandydata („Na listę”) albo zaznaczając kilka osób na
          liście kandydatów.
        </p>
      ) : (
        <ul className="space-y-0.5">
          {members.data.candidates.map((m) => (
            <MemberRow
              key={m.id}
              member={m}
              onAdd={onAdd}
              busy={remove.isPending}
              onRemove={editable ? () => remove.mutate(m.id) : undefined}
            />
          ))}
        </ul>
      )}

      {editable ? (
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive"
          disabled={drop.isPending}
          onClick={async () => {
            const ok = await askConfirm({
              title: `Usunąć listę „${list.name}”?`,
              description: "Osoby zostają w bazie, znika tylko ta lista.",
              confirmLabel: "Usuń listę",
              variant: "destructive",
            });
            if (ok) drop.mutate();
          }}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
          Usuń listę
        </Button>
      ) : null}
      {confirmDialog}
    </div>
  );
}

export function ListsTab({ userId, onAdd }: { userId: number; onAdd: AddFn }) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const lists = useCandidateLists(userId);
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: (listName: string) => candidateListsApi.create(listName),
    onSuccess: (list) => {
      setName("");
      setCreating(false);
      void queryClient.invalidateQueries({ queryKey: TALENT_POOLS_PREFIX });
      setOpenId(list.id);
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się utworzyć listy.")),
  });

  if (lists.isError) {
    return (
      <ErrorView
        message={apiErrorMessage(lists.error, "Nie udało się wczytać list.")}
        onRetry={() => void lists.refetch()}
      />
    );
  }
  if (!lists.isSuccess) {
    return <p className="px-2 py-6 text-center text-sm text-muted-foreground">Wczytuję listy…</p>;
  }

  const { mine, shared } = lists.data;
  const open = [...mine, ...shared].find((l) => l.id === openId);
  if (open) {
    return (
      <ListDetail
        list={open}
        editable={open.owner_id === userId}
        onBack={() => setOpenId(null)}
        onAdd={onAdd}
      />
    );
  }

  return (
    <div className="space-y-4">
      <section aria-label="Moje listy" className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="flex-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Moje listy
          </h3>
          <Button variant="ghost" size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Nowa lista
          </Button>
        </div>
        {creating ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const trimmed = name.trim();
              if (trimmed) create.mutate(trimmed);
            }}
          >
            <Input
              autoFocus
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              placeholder="Np. „Java — wracają w styczniu”"
              aria-label="Nazwa nowej listy"
            />
            <Button type="submit" size="sm" loading={create.isPending} disabled={!name.trim()}>
              Utwórz
            </Button>
          </form>
        ) : null}
        {mine.length ? (
          <ul className="space-y-1.5">
            {mine.map((l) => (
              <ListCard key={l.id} list={l} onOpen={() => setOpenId(l.id)} />
            ))}
          </ul>
        ) : (
          <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            Nie masz jeszcze żadnej listy. Utwórz ją tutaj albo kliknij „Na listę” na profilu
            kandydata. Nowa lista jest widoczna tylko dla Ciebie.
          </p>
        )}
      </section>
      {shared.length ? (
        <section aria-label="Udostępnione zespołowi" className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Udostępnione zespołowi
          </h3>
          <ul className="space-y-1.5">
            {shared.map((l) => (
              <ListCard key={l.id} list={l} onOpen={() => setOpenId(l.id)} showOwner />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
