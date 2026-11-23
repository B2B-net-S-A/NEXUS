"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, Users } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  MASS_SEND_KEY,
  b2bMassSendApi,
  type MassSendBatch,
  type MassSendClientCount,
  type MassSendDryRun,
  type MassSendSettings,
} from "@/lib/api/b2bMassSend";

/** Ilu klientów pokazujemy z nazwy; reszta to „Pozostali klienci”. */
const TOP_CLIENTS = 6;

const SETTINGS_KEY = [...MASS_SEND_KEY, "settings"] as const;
const CURRENT_KEY = [...MASS_SEND_KEY, "current"] as const;

export function clientRows(
  clients: MassSendClientCount[],
): { name: string; ready: number; total: number }[] {
  const top = clients.slice(0, TOP_CLIENTS).map((c) => ({
    name: c.client_name,
    ready: c.ready,
    total: c.total,
  }));
  const rest = clients.slice(TOP_CLIENTS);
  if (rest.length === 0) return top;
  return [
    ...top,
    {
      name: "Pozostali klienci",
      ready: rest.reduce((sum, c) => sum + c.ready, 0),
      total: rest.reduce((sum, c) => sum + c.total, 0),
    },
  ];
}

function umow(n: number): string {
  if (n === 1) return "umowę";
  const tens = n % 100;
  const ones = n % 10;
  if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return "umowy";
  return "umów";
}

/**
 * „Nowa umowa dla aktywnych” w rejestrze Generatora (zakładka „Umowy”).
 * Dopóki nowy wzór nie jest podpięty, przycisk widzi tylko admin: podgląd
 * i próba bez wysyłki działają, wysyłka nie. Potem każdy, kto wysyła umowy
 * do podpisu.
 */
export function MassSendButton({ isAdmin }: { isAdmin: boolean }) {
  const [open, setOpen] = useState(false);
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: b2bMassSendApi.settings });
  const data = settings.data;
  if (!data) return null;
  if (!isAdmin && !(data.can_start && data.template_ready)) return null;
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Users className="h-4 w-4" aria-hidden /> Nowa umowa dla aktywnych
      </Button>
      {open ? (
        <MassSendDialog isAdmin={isAdmin} settings={data} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

export function MassSendDialog({
  isAdmin,
  settings,
  onClose,
}: {
  isAdmin: boolean;
  settings: MassSendSettings;
  onClose: () => void;
}) {
  const current = useQuery({
    queryKey: CURRENT_KEY,
    queryFn: b2bMassSendApi.current,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 30_000 : false,
  });
  const running = current.data?.status === "running" ? current.data : null;
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Nowa umowa dla aktywnych kontraktorów</DialogTitle>
          <DialogDescription>
            Każdy dostaje własny link do podpisu, ze swoimi danymi w umowie.
          </DialogDescription>
        </DialogHeader>
        {current.isPending ? (
          <DialogBody>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Sprawdzam, czy
              wysyłka już trwa…
            </p>
          </DialogBody>
        ) : current.isError ? (
          <DialogBody>
            <Alert
              variant="error"
              title="Nie udało się sprawdzić wysyłki"
              description={apiErrorMessage(current.error, "Spróbuj ponownie za chwilę.")}
            />
          </DialogBody>
        ) : running ? (
          <MassSendProgressView batch={running} settings={settings} onClose={onClose} />
        ) : (
          <MassSendForm isAdmin={isAdmin} settings={settings} onClose={onClose} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MassSendForm({
  isAdmin,
  settings,
  onClose,
}: {
  isAdmin: boolean;
  settings: MassSendSettings;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [skipEnding, setSkipEnding] = useState(true);
  const [signerId, setSignerId] = useState<number | null>(
    settings.company_signers[0]?.id ?? null,
  );
  const [days, setDays] = useState(settings.link_days.includes(14) ? 14 : settings.link_days[0]);
  const [dryRun, setDryRun] = useState<MassSendDryRun | null>(null);

  const preview = useQuery({
    queryKey: [...MASS_SEND_KEY, "preview", skipEnding],
    queryFn: () =>
      b2bMassSendApi.preview({ skip_ending: skipEnding, status: "needs_review", limit: 50 }),
  });
  const runDry = useMutation({
    mutationFn: () => b2bMassSendApi.dryRun(skipEnding),
    onSuccess: setDryRun,
  });
  const start = useMutation({
    mutationFn: () =>
      b2bMassSendApi.start({ skip_ending: skipEnding, company_signer_id: signerId ?? 0, days }),
    onSuccess: (batch) => {
      queryClient.setQueryData(CURRENT_KEY, batch);
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      toast.showSuccess("Wysyłka ruszyła. Pierwsza partia wyjdzie w ciągu 15 minut.");
    },
  });
  const mark = useMutation({
    mutationFn: (ready: boolean) => b2bMassSendApi.saveSettings(ready),
    onSuccess: (data) => queryClient.setQueryData(SETTINGS_KEY, data),
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się zapisać.")),
  });

  const onMark = async (ready: boolean) => {
    const ok = await askConfirm(
      ready
        ? {
            title: "Oznaczyć nowy wzór umowy jako podpięty?",
            description:
              "Od tej chwili wysyłka do kontraktorów jest odblokowana: każdy, kto wysyła umowy do podpisu, zobaczy ten przycisk, a paczka wyśle maile z linkiem. Oznacz dopiero, gdy nowy wzór jest w Generatorze.",
            confirmLabel: "Nowy wzór podpięty",
          }
        : {
            title: "Cofnąć oznaczenie nowego wzoru?",
            description:
              "Wysyłka do kontraktorów stanie od razu, także w trwającej paczce. Podgląd i próba zostają.",
            confirmLabel: "Cofnij oznaczenie",
            variant: "destructive",
          },
    );
    if (ok) mark.mutate(ready);
  };

  const summary = preview.data?.summary;
  const blockers: string[] = [];
  if (!settings.template_ready) blockers.push("nowy wzór nie jest podpięty");
  if (!settings.worker_enabled) blockers.push("wysyłka w tle jest wyłączona na serwerze");
  if (!settings.can_start) blockers.push("podpis w NEXUSIE nie jest włączony dla Twojego konta");
  if (!settings.mailbox_connected) blockers.push("Twoja skrzynka Microsoft 365 nie jest połączona");
  if (signerId === null) blockers.push("brak osoby podpisującej za B2Bnetwork");
  const ready = summary?.ready ?? 0;
  const canStart = blockers.length === 0 && ready > 0 && !start.isPending;

  return (
    <>
      <DialogBody className="space-y-4">
        {!settings.template_ready ? (
          <Alert
            variant="warning"
            title="Wysyłka zablokowana: nowy wzór umowy nie jest jeszcze podpięty"
            description="Podgląd i próba bez wysyłki działają. Do kontraktorów nic nie wyjdzie, dopóki admin nie oznaczy nowego wzoru jako podpiętego."
          />
        ) : null}
        {isAdmin ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm">
            <span className="text-muted-foreground">
              {settings.template_ready
                ? `Nowy wzór podpięty${settings.template_ready_by ? ` (${settings.template_ready_by})` : ""}.`
                : "Nowy wzór umowy: niepodpięty."}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={mark.isPending}
              onClick={() => void onMark(!settings.template_ready)}
            >
              {settings.template_ready ? "Cofnij oznaczenie" : "Oznacz nowy wzór jako podpięty"}
            </Button>
          </div>
        ) : null}

        <section className="space-y-1.5">
          <p className="text-sm font-medium text-foreground">1. Wzór</p>
          <p className="text-sm text-foreground">{settings.template_label}</p>
          <p className="text-xs text-muted-foreground">
            Dane każdej osoby z jej ostatniej podpisanej umowy w Generatorze albo z danych firmy
            potwierdzonych na „Dane firm z umów”. Czego brakuje, nie zgadujemy: osoba trafia do
            sprawdzenia.
          </p>
        </section>

        <section className="space-y-2">
          <p className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Users className="h-4 w-4 text-muted-foreground" aria-hidden /> 2. Kto dostanie
          </p>
          {preview.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Liczę aktywne kontrakty…
            </p>
          ) : preview.isError ? (
            <Alert
              variant="error"
              title="Nie udało się policzyć odbiorców"
              description={apiErrorMessage(preview.error, "Spróbuj ponownie za chwilę.")}
            />
          ) : preview.data.summary.total === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nie ma aktywnych kontraktów B2B, których umowę możesz wysłać do podpisu.
            </p>
          ) : (
            <>
              <div
                className="overflow-hidden rounded-lg border border-border text-sm"
                aria-label="Odbiorcy według klienta"
                role="table"
              >
                {clientRows(preview.data.summary.by_client).map((row) => (
                  <div
                    key={row.name}
                    role="row"
                    className="flex items-center justify-between border-t border-border px-3 py-1.5 first:border-t-0"
                  >
                    <span role="cell" className="text-foreground">
                      {row.name}
                    </span>
                    <span role="cell" className="tabular-nums text-muted-foreground">
                      {row.ready} z {row.total}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-sm text-foreground">
                Gotowe: <strong className="tabular-nums">{ready}</strong> · do sprawdzenia:{" "}
                <span className="tabular-nums">{preview.data.summary.needs_review}</span> ·
                pominięte: <span className="tabular-nums">{preview.data.summary.skipped}</span>
              </p>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={skipEnding}
                  onCheckedChange={(v) => {
                    setSkipEnding(v === true);
                    setDryRun(null);
                  }}
                />
                Pomiń osoby, którym umowa kończy się w ciągu 30 dni (
                {preview.data.summary.ending_soon})
              </label>
              {preview.data.no_email.length > 0 ? (
                <p className="text-xs text-muted-foreground">
                  Bez adresu e-mail, do uzupełnienia (nie dostaną linku):{" "}
                  {preview.data.no_email.map((p) => p.name).join(", ")}.
                </p>
              ) : null}
              {preview.data.rows.length > 0 ? (
                <details className="rounded-lg border border-border px-3 py-2 text-sm">
                  <summary className="cursor-pointer text-foreground">
                    Do sprawdzenia ({preview.data.summary.needs_review})
                  </summary>
                  <ul className="mt-2 space-y-1.5">
                    {preview.data.rows.map((row) => (
                      <li key={row.contract_id}>
                        <span className="font-medium text-foreground">{row.name}</span>
                        <span className="text-muted-foreground"> · {row.client_name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {[
                            row.missing.length ? `Brakuje: ${row.missing.join(", ")}.` : null,
                            ...row.issues,
                            row.missing.length || row.issues.length ? null : row.reason_label,
                          ]
                            .filter(Boolean)
                            .join(" ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {preview.data.rows_total > preview.data.rows.length ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Pokazano {preview.data.rows.length} z {preview.data.rows_total}.
                    </p>
                  ) : null}
                </details>
              ) : null}
            </>
          )}
        </section>

        <section className="space-y-2">
          <p className="text-sm font-medium text-foreground">3. Podpis</p>
          <p className="text-sm text-muted-foreground">
            Umowa: podpis kwalifikowany obu stron, bo przenosi autorskie prawa majątkowe.
            Przypomnienie dzień przed końcem terminu.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="mass-send-signer">Za B2Bnetwork</Label>
              <select
                id="mass-send-signer"
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                value={signerId ?? ""}
                onChange={(e) => setSignerId(Number(e.target.value) || null)}
              >
                {settings.company_signers.length === 0 ? (
                  <option value="">Brak osób w ustawieniach</option>
                ) : null}
                {settings.company_signers.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="mass-send-days">Termin na podpis</Label>
              <select
                id="mass-send-days"
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
              >
                {settings.link_days.map((d) => (
                  <option key={d} value={d}>
                    {d === 1 ? "1 dzień" : `${d} dni`}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Maile wychodzą z Twojej skrzynki partiami po {settings.chunk_size} co 15 minut.
          </p>
        </section>

        {dryRun ? (
          <Alert
            variant={dryRun.problems.length ? "warning" : "info"}
            title={`Próba: ${dryRun.would_send} ${umow(dryRun.would_send)} by poszło, ${dryRun.summary.needs_review} do sprawdzenia`}
            description={
              <div className="space-y-1">
                {dryRun.problems.slice(0, 10).map((row) => (
                  <p key={row.contract_id}>
                    {row.name}: {row.issues[row.issues.length - 1]}
                  </p>
                ))}
                {dryRun.block_reasons.map((reason) => (
                  <p key={reason}>{reason}</p>
                ))}
              </div>
            }
          />
        ) : null}
        {runDry.isError ? (
          <Alert
            variant="error"
            title="Próba się nie udała"
            description={apiErrorMessage(runDry.error, "Spróbuj ponownie.")}
          />
        ) : null}
        {start.isError ? (
          <Alert
            variant="error"
            title="Wysyłka nie ruszyła"
            description={apiErrorMessage(start.error, "Spróbuj ponownie.")}
          />
        ) : null}
        {blockers.length > 0 && settings.template_ready ? (
          <p className="text-xs text-muted-foreground">Wysyłka nieaktywna: {blockers.join(", ")}.</p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Anuluj
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={runDry.isPending || !preview.isSuccess}
          onClick={() => runDry.mutate()}
        >
          {runDry.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Próba bez wysyłki
        </Button>
        <Button type="button" variant="primary" disabled={!canStart} onClick={() => start.mutate()}>
          {start.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Send className="h-4 w-4" aria-hidden />
          )}
          Wyślij {ready} {umow(ready)}
        </Button>
      </DialogFooter>
      {confirmDialog}
    </>
  );
}

function MassSendProgressView({
  batch,
  settings,
  onClose,
}: {
  batch: MassSendBatch;
  settings: MassSendSettings;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const failed = useQuery({
    queryKey: [...MASS_SEND_KEY, "items", batch.id, "failed", batch.progress.failed],
    queryFn: () => b2bMassSendApi.items(batch.id, { status: "failed", limit: 20 }),
    enabled: batch.progress.failed > 0,
  });
  const cancel = useMutation({
    mutationFn: () => b2bMassSendApi.cancel(batch.id),
    onSuccess: (data) => {
      queryClient.setQueryData(CURRENT_KEY, data);
      toast.showSuccess("Wysyłka zatrzymana. Wysłane linki działają dalej.");
    },
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się zatrzymać.")),
  });
  const onCancel = async () => {
    const ok = await askConfirm({
      title: "Zatrzymać wysyłkę?",
      description:
        "Osoby, które jeszcze nie dostały linku, już go nie dostaną. Wysłane linki działają dalej i wycofasz je w rejestrze jak pojedynczą wysyłkę.",
      confirmLabel: "Zatrzymaj wysyłkę",
      variant: "destructive",
    });
    if (ok) cancel.mutate();
  };

  const p = batch.progress;
  const planned = batch.planned.ready ?? p.sent + p.pending + p.created + p.failed;
  const percent = planned > 0 ? Math.min(100, Math.round((p.sent / planned) * 100)) : 0;
  const tiles: [string, number][] = [
    ["Wysłane", p.sent],
    ["Podpisali", p.signed],
    ["Czeka na firmę", p.waiting_company],
    ["Problem", p.failed],
  ];
  return (
    <>
      <DialogBody className="space-y-3">
        {!batch.template_ready ? (
          <Alert
            variant="warning"
            title="Wysyłka wstrzymana"
            description="Oznaczenie nowego wzoru cofnięto, więc kolejne partie nie wychodzą."
          />
        ) : null}
        <Alert
          variant="info"
          title={`Wysłano ${p.sent} z ${planned}`}
          description={`Maile wychodzą partiami po ${settings.chunk_size} co 15 minut${batch.started_by ? ` ze skrzynki: ${batch.started_by.name}` : ""}. Reszta pójdzie sama.`}
        />
        <div
          className="h-2 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-label="Postęp wysyłki"
        >
          <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {tiles.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-border px-3 py-2">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="text-lg font-semibold tabular-nums text-foreground">{value}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Czeka na kontraktora: {p.waiting_contractor} · do sprawdzenia: {p.needs_review} ·
          pominięte: {p.skipped}
        </p>
        {p.failed > 0 ? (
          failed.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytuję problemy…
            </p>
          ) : failed.isError ? (
            <Alert
              variant="error"
              title="Nie udało się wczytać problemów"
              description={apiErrorMessage(failed.error, "Spróbuj ponownie za chwilę.")}
            />
          ) : (
            <ul className="space-y-1 text-sm">
              {failed.data.items.map((item) => (
                <li key={item.id}>
                  <span className="font-medium text-foreground">{item.name}</span>
                  <span className="block text-xs text-destructive">{item.error}</span>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          disabled={cancel.isPending}
          onClick={() => void onCancel()}
        >
          Zatrzymaj wysyłkę
        </Button>
        <Button type="button" variant="primary" onClick={onClose}>
          Zamknij
        </Button>
      </DialogFooter>
      {confirmDialog}
    </>
  );
}
