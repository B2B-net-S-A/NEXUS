"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ownHiringApi,
  ownHiringKeys,
  type OwnHiringDetail,
  type OwnHiringStage,
} from "@/lib/api/ownHiring";
import { cn } from "@/lib/utils";

import { formatMonths, formatWhen } from "./format";
import { SlotPicker } from "./SlotPicker";

const AVAILABILITY = [
  ["now", "Od zaraz"],
  ["month", "Do 1 mies."],
  ["quarter", "1–3 mies."],
  ["later", "Ponad 3 mies."],
] as const;
const TECH = [
  ["good", "Ogarnia"],
  ["partial", "Częściowo"],
  ["poor", "Nie ogarnia"],
] as const;
const CONTRACTS = [
  ["b2b", "B2B"],
  ["employment", "Umowa o pracę"],
  ["mandate", "Zlecenie"],
] as const;
const MOVE_TARGETS: [OwnHiringStage, string][] = [
  ["new", "Nowi"],
  ["no_response", "Bez odpowiedzi"],
  ["assistant", "U asystentki"],
  ["teams", "Rozmowa Teams"],
  ["office", "Rozmowa w biurze"],
  ["contract", "Umowa wysłana"],
  ["signed", "Podpisani"],
];
const EVENT_LABELS: Record<string, string> = {
  invited: "Wysłano zaproszenie",
  replied_by_mail: "Odpisał(a) mailem",
  no_response: "Brak odpowiedzi w terminie",
  handed_off: "Przekazano asystentce",
  booked: "Wybrano termin Teams",
  no_show: "Nie dołączył(a) do Teams",
  teams_done: "Po rozmowie Teams",
  office_booked: "Termin w biurze",
  office_done: "Po rozmowie w biurze",
  contract_done: "Decyzja o umowie",
  rejected: "Odrzucono",
  moved: "Przeniesiono ręcznie",
  call_no_answer: "Nie odbiera",
  call_callback: "Oddzwonić",
  call_withdrawn: "Rezygnuje (telefon)",
  attempts_exhausted: "Wyczerpane próby telefonu",
  cancelled_by_candidate: "Kandydat odwołał termin",
  no_slot_fits: "Żaden termin nie pasuje",
  withdrawn_by_candidate: "Kandydat zrezygnował",
};

function Chips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly (readonly [T, string])[];
  value: T | null;
  onChange: (next: T) => void;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            aria-pressed={value === key}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs",
              value === key ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
            )}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

function Foot({ children }: { children: ReactNode }) {
  return <div className="flex gap-2 pt-1">{children}</div>;
}

function TeamsForm({ person, run, busy }: FormProps) {
  const [availability, setAvailability] = useState<string | null>(person.availability);
  const [money, setMoney] = useState(person.expected_money ?? "");
  const [tech, setTech] = useState<string | null>(person.tech_level);
  const [note, setNote] = useState(person.teams_note ?? "");
  const [office, setOffice] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const officeStart = custom ? new Date(custom).toISOString() : office;
  const payload = (decision: "office" | "reject") => ({
    availability,
    expected_money: money.trim() || null,
    tech_level: tech,
    note: note.trim() || null,
    decision,
    office_start: decision === "office" ? officeStart : null,
  });
  return (
    <div className="space-y-3">
      <Chips label="Dostępność" options={AVAILABILITY} value={availability} onChange={setAvailability} />
      <div>
        <label htmlFor="oh-money" className="text-xs font-medium text-muted-foreground">
          Oczekiwania finansowe
        </label>
        <Input id="oh-money" value={money} onChange={(e) => setMoney(e.target.value)} className="mt-1" maxLength={160} />
      </div>
      <Chips label="Czy ogarnia technologicznie" options={TECH} value={tech} onChange={setTech} />
      <div>
        <label htmlFor="oh-note" className="text-xs font-medium text-muted-foreground">
          Notatka (nieobowiązkowa)
        </label>
        <Textarea id="oh-note" value={note} onChange={(e) => setNote(e.target.value)} className="mt-1" rows={2} />
      </div>
      <div className="rounded-md bg-muted/50 p-3">
        <p className="mb-1.5 text-xs font-medium">Druga rozmowa w biurze</p>
        <SlotPicker kind="office" value={office} onChange={(slot) => { setOffice(slot); setCustom(""); }} />
        <label htmlFor="oh-office-custom" className="mt-2 block text-xs text-muted-foreground">
          Inny termin
        </label>
        <Input
          id="oh-office-custom"
          type="datetime-local"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          className="mt-1"
        />
      </div>
      <Foot>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => run(() => ownHiringApi.teamsOutcome(person.id, payload("reject")), "Zapisano odrzucenie")}
        >
          Odrzuć
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => run(() => ownHiringApi.noShow(person.id), "Wróciło do asystentki")}
        >
          Nie dołączył(a)
        </Button>
        <Button
          size="sm"
          className="flex-1"
          disabled={busy || !officeStart}
          onClick={() => run(() => ownHiringApi.teamsOutcome(person.id, payload("office")), "Termin w biurze zapisany")}
        >
          Zaproś do biura
        </Button>
      </Foot>
    </div>
  );
}

function OfficeForm({ person, run, busy }: FormProps) {
  const [note, setNote] = useState(person.office_note ?? "");
  const [kind, setKind] = useState<string | null>("b2b");
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor="oh-office-note" className="text-xs font-medium text-muted-foreground">
          Notatka po rozmowie
        </label>
        <Textarea id="oh-office-note" value={note} onChange={(e) => setNote(e.target.value)} className="mt-1" rows={2} />
      </div>
      <Chips label="Rodzaj umowy" options={CONTRACTS} value={kind} onChange={setKind} />
      <Foot>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() =>
            run(
              () => ownHiringApi.officeOutcome(person.id, { note: note.trim() || null, decision: "withdraw", contract_kind: null }),
              "Zapisano rezygnację",
            )
          }
        >
          Rezygnujemy
        </Button>
        <Button
          size="sm"
          className="flex-1"
          disabled={busy}
          onClick={() =>
            run(
              () => ownHiringApi.officeOutcome(person.id, { note: note.trim() || null, decision: "contract", contract_kind: kind }),
              "Oznaczono: umowa wysłana",
            )
          }
        >
          Umowa wysłana
        </Button>
      </Foot>
    </div>
  );
}

interface FormProps {
  person: OwnHiringDetail;
  run: (action: () => Promise<unknown>, success: string) => void;
  busy: boolean;
}

function StageActions({ person, run, busy, onInvite }: FormProps & { onInvite: (id: number) => void }) {
  switch (person.stage) {
    case "new":
      return (
        <Foot>
          <Button size="sm" disabled={busy || !person.has_email} onClick={() => onInvite(person.id)}>
            Zaproś na rozmowę
          </Button>
        </Foot>
      );
    case "no_response":
    case "invited":
      return (
        <Foot>
          <Button size="sm" disabled={busy} onClick={() => run(() => ownHiringApi.handOff([person.id]), "Przekazano asystentce")}>
            Przekaż asystentce
          </Button>
          {person.stage === "no_response" && (
            <Button size="sm" variant="outline" disabled={busy || !person.has_email} onClick={() => onInvite(person.id)}>
              Zaproś ponownie
            </Button>
          )}
        </Foot>
      );
    case "teams":
      return person.needs_decision ? (
        <TeamsForm person={person} run={run} busy={busy} />
      ) : (
        <Foot>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => ownHiringApi.noShow(person.id), "Wróciło do asystentki")}>
            Nie dołączył(a)
          </Button>
        </Foot>
      );
    case "office":
      return <OfficeForm person={person} run={run} busy={busy} />;
    case "contract":
      return (
        <Foot>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => ownHiringApi.contractOutcome(person.id, "withdrawn"), "Zapisano rezygnację")}>
            Rezygnacja
          </Button>
          <Button size="sm" className="flex-1" disabled={busy} onClick={() => run(() => ownHiringApi.contractOutcome(person.id, "signed"), "Umowa podpisana")}>
            Podpisana
          </Button>
        </Foot>
      );
    default:
      return null;
  }
}

interface PersonPanelProps {
  applicationId: number | null;
  onClose: () => void;
  onInvite: (id: number) => void;
}

export function PersonPanel({ applicationId, onClose, onInvite }: PersonPanelProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const detail = useQuery({
    queryKey: ["own-hiring", "detail", applicationId],
    queryFn: () => ownHiringApi.detail(applicationId as number),
    enabled: applicationId !== null,
  });
  const [target, setTarget] = useState<string>("");
  useEffect(() => setTarget(""), [applicationId]);
  const mutation = useMutation({
    mutationFn: ({ action }: { action: () => Promise<unknown>; success: string }) => action(),
    onSuccess: (_data, { success }) => {
      showSuccess(success);
      void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all });
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać. Spróbuj ponownie.")),
  });
  const run = (action: () => Promise<unknown>, success: string) => mutation.mutate({ action, success });
  const person = detail.data;
  return (
    <Sheet open={applicationId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col overflow-y-auto sm:max-w-[440px]">
        <SheetHeader>
          <SheetTitle>{person?.name ?? "Osoba"}</SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-3 px-6 pb-6">
        {detail.isPending && applicationId !== null && <p className="text-sm text-muted-foreground">Wczytuję…</p>}
        {detail.isError && <p className="text-sm text-destructive">Nie udało się wczytać tej osoby.</p>}
        {person && (
          <>
            <div className="space-y-1 text-sm">
              <p>
                {person.role ?? "Brak odczytanej roli"}
                {person.months !== null && <span className="text-muted-foreground"> · {formatMonths(person.months)}</span>}
                {person.is_it && <Badge variant="info" size="sm" className="ml-1.5">IT</Badge>}
              </p>
              <p className="text-xs text-muted-foreground">
                {[person.company, person.city, person.ad_title].filter(Boolean).join(" · ")}
              </p>
              <p className="text-xs tabular-nums">
                {[person.phone, person.email].filter(Boolean).join(" · ") || "Brak kontaktu"}
              </p>
              <Link href={`/candidates/${person.candidate_id}`} className="text-xs text-primary hover:underline">
                Profil i CV
              </Link>
            </div>
            {person.booking && (
              <p className="rounded-md bg-muted/50 px-3 py-2 text-xs">
                {person.booking.kind === "teams" ? "Rozmowa Teams" : "Rozmowa w biurze"}: {formatWhen(person.booking.start)}
                {person.booking.join_url && (
                  <a href={person.booking.join_url} target="_blank" rel="noreferrer" className="ml-2 text-primary hover:underline">
                    Dołącz
                  </a>
                )}
              </p>
            )}
            {(person.availability || person.expected_money || person.tech_level) && person.stage !== "teams" && (
              <p className="text-xs text-muted-foreground">
                Z Teams: {[AVAILABILITY.find(([k]) => k === person.availability)?.[1], person.expected_money, TECH.find(([k]) => k === person.tech_level)?.[1]].filter(Boolean).join(" · ")}
              </p>
            )}
            <StageActions person={person} run={run} busy={mutation.isPending} onInvite={onInvite} />
            <div className="flex items-center gap-2 border-t border-border pt-3">
              <Select value={target} onValueChange={setTarget}>
                <SelectTrigger className="h-8 flex-1 text-xs">
                  <SelectValue placeholder="Przenieś na etap…" />
                </SelectTrigger>
                <SelectContent>
                  {MOVE_TARGETS.filter(([stage]) => stage !== person.stage).map(([stage, label]) => (
                    <SelectItem key={stage} value={stage}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="outline"
                disabled={!target || mutation.isPending}
                onClick={() => run(() => ownHiringApi.move(person.id, target as OwnHiringStage), "Przeniesiono")}
              >
                Przenieś
              </Button>
              {person.stage !== "closed" && person.stage !== "signed" && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={mutation.isPending}
                  onClick={async () => {
                    const ok = await askConfirm({
                      title: "Odrzucić tę osobę?",
                      description: "Karta trafi do zamkniętych. Mail z odmową nie zostanie wysłany.",
                      confirmLabel: "Odrzuć",
                    });
                    if (ok) run(() => ownHiringApi.reject([person.id]), "Odrzucono");
                  }}
                >
                  Odrzuć
                </Button>
              )}
            </div>
            <div className="border-t border-border pt-3">
              <p className="text-xs font-medium text-muted-foreground">Historia</p>
              {person.events.length === 0 ? (
                <p className="mt-1 text-xs text-muted-foreground">Bez zdarzeń.</p>
              ) : (
                <ul className="mt-1 space-y-1 text-xs">
                  {person.events.map((event, index) => (
                    <li key={`${event.at}-${index}`} className="flex justify-between gap-3">
                      <span>{EVENT_LABELS[event.kind] ?? event.kind}</span>
                      <span className="shrink-0 text-muted-foreground">{formatWhen(event.at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
        </div>
        {confirmDialog}
      </SheetContent>
    </Sheet>
  );
}
