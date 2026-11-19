"use client";
// B · Wejście — w wąskiej kolumnie dwie karty jedna pod drugą: „Lista
// startowa” (postęp, pola wyboru, „Dodaj pozycję”, szablon, gdy pusta)
// i zwarty „Panel konsultanta” (stan, adres do logowania, tryb firmy, mail).
// Z kontraktu znikają przełącznik trybu panelu (ustawienie firmy — zmienia
// administrator w Ustawieniach) i edytor maila powitalnego na wierzchu
// (treść widać w „Podglądzie maila”). Zapis nic nie robi (makieta).
import { useState } from "react";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { mailBlocker } from "@/components/hr/onboarding/ConsultantPanelCard";
import type { PanelProposal } from "@/lib/api/consultant-panel";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkContract } from "../shared/data";
import { daysUntil, fmtDate, relDays } from "../shared/format";
import { onboardingCounts, panelModeLabel, useMkOnboarding, useMkPanel, type MkOnboardingItem } from "./StartA";
import type { TabProps } from "./types";

const MODE_EFFECT: Record<PanelProposal["portal_state"], string> = {
  off: "panel nie działa dla nikogo",
  internal: "konsultanci jeszcze nie wchodzą do panelu",
  pilot: "wchodzą tylko osoby z ręczną aktywacją",
  all: "wchodzą wszystkie osoby z aktywacją",
};

function Card({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-2 flex min-h-7 items-center justify-between gap-3">
        <h3 className="text-[13.5px] font-semibold text-foreground">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ItemRow({
  item,
  done,
  onToggle,
}: {
  item: MkOnboardingItem;
  done: boolean;
  onToggle: (id: number, value: boolean) => void;
}) {
  const na = item.status === "na";
  const late = !done && !na && item.due_date != null && (daysUntil(item.due_date) ?? 0) < 0;
  return (
    <li className="flex min-h-9 items-center gap-3 py-1">
      <Checkbox
        checked={done}
        disabled={na}
        onCheckedChange={(v) => onToggle(item.id, v === true)}
        aria-label={`${item.label} — ${done ? "zrobione" : "do zrobienia"}`}
      />
      <span className={cn("min-w-0 flex-1 text-[13px] text-foreground", (done || na) && "text-muted-foreground line-through")}>
        {item.label}
        {item.notes ? <span className="block text-[11.5px] text-muted-foreground no-underline">{item.notes}</span> : null}
      </span>
      {na ? (
        <span className="text-[12px] text-muted-foreground">nie dotyczy</span>
      ) : item.due_date ? (
        <span className={cn("text-[12px] tabular-nums", late ? "font-medium text-destructive" : "text-muted-foreground")}>
          {late ? `po terminie · ${fmtDate(item.due_date)}` : `do ${fmtDate(item.due_date)}`}
        </span>
      ) : null}
    </li>
  );
}

function StartListCard({ contractId }: { contractId: number }) {
  const c = useMkContract(contractId).data;
  const query = useMkOnboarding(contractId);
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const items = [...(query.data ?? [])].sort((a, b) => a.order - b.order);
  const { done, total } = onboardingCounts(items, checked);
  const pct = total ? Math.round((done / total) * 100) : 0;
  const started = (daysUntil(c?.start_date) ?? 0) <= 0;

  return (
    <Card
      title="Lista startowa"
      aside={
        items.length ? (
          <span className="text-[12.5px] tabular-nums text-muted-foreground">
            <span className="font-semibold text-foreground">{done}</span> / {total}
          </span>
        ) : null
      }
    >
      {query.isLoading ? (
        <p className="text-[13px] text-muted-foreground">Wczytywanie listy…</p>
      ) : query.isError ? (
        <p className="text-[13px] text-destructive">Nie udało się pobrać listy startowej.</p>
      ) : items.length === 0 ? (
        <div className="space-y-2">
          <p className="text-[13px] text-muted-foreground">
            {started
              ? `Listy startowej nie ma — przy współpracy od ${fmtDate(c?.start_date)} to normalne.`
              : `Listy startowej jeszcze nie ma — wygeneruj ją przed startem ${fmtDate(c?.start_date)} (${relDays(c?.start_date)}).`}
          </p>
          <Button type="button" variant="outline" size="sm">
            Wygeneruj z szablonu (BHP, sprzęt, dostępy, VPN…)
          </Button>
        </div>
      ) : (
        <>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Postęp listy startowej"
          >
            <div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1.5 text-[12px] text-muted-foreground">
            Założona {fmtDate(warsawDateOf(items.map((i) => i.created_at).sort()[0]))}
            {done === 0 ? " · nic jeszcze nie odhaczono" : ""}
          </p>
          <ul className="mt-1.5 divide-y divide-border/60">
            {items.map((item) => (
              <ItemRow
                key={item.id}
                item={item}
                done={checked[item.id] ?? item.status === "done"}
                onToggle={(id, v) => setChecked((s) => ({ ...s, [id]: v }))}
              />
            ))}
          </ul>
          <div className="mt-2 flex items-center gap-2">
            <label htmlFor="mk-start-add" className="sr-only">
              Nowa pozycja listy startowej
            </label>
            <Input id="mk-start-add" placeholder="Dodaj pozycję, np. karta dostępu do biura" className="h-9 text-[13px]" />
            <Button type="button" variant="ghost" size="sm">
              Dodaj
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[132px_minmax(0,1fr)] gap-3 py-1 text-[13px] leading-5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function PanelCard({ contractId }: { contractId: number }) {
  const panel = useMkPanel(contractId);
  const p = panel.data;
  const active = Boolean(p?.activation.active && !p.activation.address_changed);
  return (
    <Card
      title="Panel konsultanta"
      aside={
        p ? (
          <StatusDot tone={active ? "success" : p.activation.address_changed ? "warning" : "neutral"}>
            {active ? "aktywny" : p.activation.address_changed ? "zamknięty — zmiana adresu" : "nieaktywny"}
          </StatusDot>
        ) : null
      }
    >
      {panel.isLoading ? (
        <p className="text-[13px] text-muted-foreground">Wczytywanie panelu…</p>
      ) : panel.isError || !p ? (
        <p className="text-[13px] text-muted-foreground">Panelu konsultanta nie da się tu pokazać (brak dostępu albo błąd).</p>
      ) : (
        <>
          <dl className="divide-y divide-border/60">
            <Fact label="Adres do logowania">
              {active ? (
                p.activation.email
              ) : p.suggested_email ? (
                <>
                  {p.suggested_email} <span className="text-muted-foreground">· z kartoteki, sprawdź przed aktywacją</span>
                </>
              ) : (
                <span className="text-muted-foreground">brak adresu w kartotece</span>
              )}
            </Fact>
            {active ? (
              <Fact label="Aktywny">
                od {fmtDate(warsawDateOf(p.activation.activated_at))}
                {p.activation.activated_by ? `, ${p.activation.activated_by}` : ""}
                <span className="text-muted-foreground">
                  {p.activation.last_login_at
                    ? ` · ostatnie logowanie ${fmtDate(warsawDateOf(p.activation.last_login_at))}`
                    : " · jeszcze bez logowania"}
                </span>
              </Fact>
            ) : null}
            <Fact label="Tryb firmy">
              {panelModeLabel(p.portal_state)}
              <span className="text-muted-foreground">
                {" "}
                — {MODE_EFFECT[p.portal_state]} (zmienia administrator w Ustawieniach)
              </span>
            </Fact>
            <Fact label="Mail powitalny">
              {p.mail.sent_at ? (
                `wysłany ${fmtDate(warsawDateOf(p.mail.sent_at))}`
              ) : (
                <span className="text-muted-foreground">
                  {mailBlocker(p, { addressTyped: false }) ?? "wyjdzie przy aktywacji — treść w podglądzie"}
                </span>
              )}
            </Fact>
            <Fact label="Materiały">
              {p.materials.length ? (
                `${p.materials.filter((m) => m.selected).length} z ${p.materials.length} wybrane`
              ) : (
                <span className="text-muted-foreground">brak materiałów wspólnych i dla tego klienta</span>
              )}
            </Fact>
          </dl>
          <div className="mt-3 flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" size="sm">
              Podgląd maila
            </Button>
            {active ? (
              <Button type="button" variant="quiet" size="sm">
                Wyłącz panel…
              </Button>
            ) : p.can_activate ? (
              <Button type="button" variant="outline" size="sm">
                Aktywuj panel
              </Button>
            ) : (
              <span className="text-[12px] text-muted-foreground">aktywacja przy działającym kontrakcie</span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

export function WejscieB({ contractId }: TabProps) {
  return (
    <div className="space-y-3">
      <StartListCard contractId={contractId} />
      <PanelCard contractId={contractId} />
    </div>
  );
}
