"use client";

// „Dodaj dodatek do rozliczenia” na karcie sprawy (potrzeba Finansów 13.11.2026):
// konsultant pisze, że dolicza do faktury premię za polecenie, weryfikację
// techniczną albo szkolenie. Z karty zapisujemy kto, za jaki okres i jaką kwotę;
// dodatek czeka na zatwierdzenie w Finanse → Rozliczenia.
import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAddCardSettlementExtra,
  useCardSettlementExtras,
  useExtraPeople,
  type BoExtraPerson,
} from "@/lib/api/back-office";

const MONTHS = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];

/** Bieżący miesiąc i dwa poprzednie (YYYY-MM), najnowszy pierwszy. */
export function extraMonths(today: string): string[] {
  const [y, m] = today.split("-").map(Number);
  return [0, 1, 2].map((i) => {
    const idx = y * 12 + (m - 1) - i;
    return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
  });
}

function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTHS[(m ?? 1) - 1]} ${y}`;
}

function pln(value: string): string {
  return `${Number(value).toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
}

export function CardSettlementExtras({ cardId, today, canAdd }: { cardId: number; today: string; canAdd: boolean }) {
  const query = useCardSettlementExtras(cardId, true);
  const add = useAddCardSettlementExtra(cardId);
  const { showToast } = useToast();
  const months = extraMonths(today);
  const [open, setOpen] = useState(false);
  const [person, setPerson] = useState<BoExtraPerson | null>(null);
  const [search, setSearch] = useState("");
  const people = useExtraPeople(open && !person && !query.data?.contract ? search : "");
  const [month, setMonth] = useState(months[0]);
  const [kind, setKind] = useState("tech_check");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");

  // 404 = moduł rozliczeń wyłączony: sekcji nie ma.
  const status = (query.error as { response?: { status?: number } } | null)?.response?.status;
  if (query.isError && status === 404) return null;
  if (query.isError) {
    return <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać dodatków do rozliczenia.")}</p>;
  }
  if (!query.isSuccess) return null;
  const data = query.data;
  const who = person ?? data.contract;
  const value = amount.trim().replace(/\s/g, "").replace(",", ".");
  const valid = who != null && value !== "" && Number(value) > 0 && (kind !== "other" || description.trim().length >= 3);

  const save = async () => {
    if (!who) return;
    try {
      await add.mutateAsync({
        contract_id: who.contract_id,
        month,
        kind,
        amount: value,
        description: description.trim() || null,
      });
      showToast("Dodatek zgłoszony do Finansów.", "success");
      setOpen(false);
      setAmount("");
      setDescription("");
      setPerson(null);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zgłosić dodatku."), "error");
    }
  };

  return (
    <section>
      <div className="flex items-center justify-between gap-2 pb-1.5">
        <h4 className="text-sm font-semibold">Dodatki do rozliczenia</h4>
        {canAdd && !open ? (
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            Dodaj dodatek do rozliczenia
          </Button>
        ) : null}
      </div>
      {data.items.length > 0 ? (
        <ul className="divide-y rounded-lg border text-sm">
          {data.items.map((item) => (
            <li key={item.id} className="px-3 py-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate">
                  {item.kind_label}
                  <span className="text-muted-foreground">
                    {" "}
                    · {[item.person !== data.contract?.person ? item.person : null, monthName(item.month)]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <span className="shrink-0 tabular-nums">{item.amount ? pln(item.amount) : null}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                {item.status_label}
                {item.status === "pending" ? " — czeka na Finanse" : ""}
                {item.decision_note ? ` · ${item.decision_note}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : !open ? (
        <p className="text-xs text-muted-foreground">
          Konsultant dolicza do faktury polecenie, weryfikację techniczną albo szkolenie? Zapisz to tutaj — trafi do Finansów.
        </p>
      ) : null}
      {open ? (
        <div className="mt-2 grid gap-2 rounded-lg border p-3 text-xs">
          <div className="grid gap-0.5">
            <span className="text-muted-foreground">Kto</span>
            {who ? (
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="min-w-0 truncate">
                  {who.person}
                  {who.client ? <span className="text-muted-foreground"> · {who.client}</span> : null}
                </span>
                {person ? (
                  <button type="button" className="text-xs text-primary hover:underline" onClick={() => setPerson(null)}>
                    Zmień
                  </button>
                ) : null}
              </div>
            ) : (
              <>
                <Input
                  aria-label="Szukaj osoby z kontraktem"
                  placeholder="Imię lub nazwisko"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8 text-sm"
                />
                {people.data?.length ? (
                  <ul className="max-h-40 divide-y overflow-y-auto rounded-md border">
                    {people.data.map((p) => (
                      <li key={p.contract_id}>
                        <button
                          type="button"
                          className="w-full px-2 py-1 text-left text-sm hover:bg-muted"
                          onClick={() => setPerson(p)}
                        >
                          {p.person}
                          {p.client ? <span className="text-muted-foreground"> · {p.client}</span> : null}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : search.trim().length >= 2 && people.isSuccess ? (
                  <p className="text-muted-foreground">Nikogo z kontraktem o tym nazwisku.</p>
                ) : null}
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="grid gap-0.5">
              <span className="text-muted-foreground">Za okres</span>
              <select
                aria-label="Okres dodatku"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10"
              >
                {months.map((m) => (
                  <option key={m} value={m}>
                    {monthName(m)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-0.5">
              <span className="text-muted-foreground">Rodzaj</span>
              <select
                aria-label="Rodzaj dodatku"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm pointer-coarse:h-10"
              >
                {data.kinds.map((k) => (
                  <option key={k.key} value={k.key}>
                    {k.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-0.5">
              <span className="text-muted-foreground">Kwota netto (zł)</span>
              <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-8 w-28 text-sm tabular-nums" />
            </label>
          </div>
          <label className="grid gap-0.5">
            <span className="text-muted-foreground">Opis {kind === "other" ? "" : "(opcjonalnie)"}</span>
            <Input value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} className="h-8 text-sm" />
          </label>
          <div className="flex gap-1.5">
            <Button size="sm" disabled={!valid || add.isPending} onClick={save}>
              Zgłoś do Finansów
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Anuluj
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
