"use client";

/**
 * Panel klienta od strony Delivery Leada (`?win=client-panel`): włącznik, link,
 * ważność, co widzi klient, słabe dowody, sprawy „Od klienta” i aktywność.
 * Panel jest domyślnie wyłączony. Awaria odczytu to komunikat z „Ponów”, nie
 * pusta lista: pustka czytałaby się jak „klient nic nie napisał”.
 */

import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Link2Off } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  clientPanelActivityKey,
  clientPanelAdminKey,
  clientPanelRequestsKey,
  httpClientPanelAdminTransport,
  type ClientPanelAdminTransport,
  type ClientPanelPerson,
  type ClientPanelRequestItem,
  type ClientPanelRequestKind,
  type ClientPanelSettings,
  type ClientPanelSettingsPatch,
} from "@/lib/api/clientPanelAdmin";
import { formatDateTimePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

import { formatPanelDate, warsawLocalToIso } from "./panel-logic";
import { PANEL_CARD, PanelRetry, PanelTabs, Pill } from "./parts";

export type ManageTab = "setup" | "inbox" | "activity";

const KIND_LABELS: Record<ClientPanelRequestKind, string> = {
  question: "Pytanie o kandydata",
  interview: "Prośba o rozmowę",
  not_fit: "Nie pasuje",
  requirements_change: "Zmiana wymagań",
};

const ACTIVITY_LABELS: Record<string, string> = {
  open: "otworzył panel",
  candidate: "otworzył kandydata",
  requirement: "sprawdził wymaganie",
  tab: "otworzył zakładkę",
  file: "otworzył plik",
};

function useManageErrorToast() {
  const { showError } = useToast();
  return (error: unknown, fallback: string) => showError(apiErrorMessage(error, fallback));
}

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2.5 border-b border-border py-2 last:border-b-0">
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} aria-label={label} className="mt-0.5" />
      <span className="min-w-0 text-sm">
        <span className="font-medium">{label}</span>
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
    </label>
  );
}

function SetupTab({
  jobId,
  settings,
  transport,
}: {
  jobId: number;
  settings: ClientPanelSettings;
  transport: ClientPanelAdminTransport;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const toastError = useManageErrorToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  // Data w polu czeka na „Zapisz datę”: wpisywanie roku cyframi daje po drodze
  // poprawne, ale bezsensowne daty, których serwer by odmówił.
  const [expiryDraft, setExpiryDraft] = useState<string | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: clientPanelAdminKey(jobId) });

  const update = useMutation({
    mutationFn: (patch: ClientPanelSettingsPatch) => transport.updateSettings(jobId, patch),
    onSuccess: refresh,
    onError: (error) => toastError(error, "Nie udało się zapisać ustawień panelu."),
  });
  const rotate = useMutation({
    mutationFn: () => transport.rotateLink(jobId),
    onSuccess: () => {
      showSuccess("Stary link przestał działać. Nowy jest poniżej.");
      void refresh();
    },
    onError: (error) => toastError(error, "Nie udało się odwołać linku."),
  });
  const person = useMutation({
    mutationFn: (args: {
      candidateId: number;
      patch: { hidden?: boolean; rejected_evidence?: string[]; shared_document_ids?: number[] };
    }) => transport.updatePerson(jobId, args.candidateId, args.patch),
    onSuccess: refresh,
    onError: (error) => toastError(error, "Nie udało się zapisać zmiany dla tej osoby."),
  });

  const setEnabled = async (enabled: boolean) => {
    if (!enabled) {
      const yes = await askConfirm({
        title: "Wyłączyć panel klienta?",
        description:
          "Link przestanie działać, także w CV, które klient już ma. Po ponownym włączeniu ten sam link zadziała znowu.",
        confirmLabel: "Wyłącz panel",
        variant: "destructive",
      });
      if (!yes) return;
    }
    update.mutate({ enabled });
  };

  const revokeLink = async () => {
    const yes = await askConfirm({
      title: "Odwołać link?",
      description:
        "Obecny link przestanie działać, także w CV, które klient już ma. Klient dostanie nowy dopiero z kolejnym CV albo od Ciebie.",
      confirmLabel: "Odwołaj link",
      variant: "destructive",
    });
    if (yes) rotate.mutate();
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      showSuccess("Link skopiowany");
    } catch {
      showError("Nie udało się skopiować linku. Zaznacz go i skopiuj ręcznie.");
    }
  };

  const expiresDay = warsawDateOf(settings.expires_at) ?? "";
  const saveExpiry = (day: string | null) => {
    if (!day) return;
    update.mutate(
      { expires_at: warsawLocalToIso(`${day}T23:59`) },
      { onSuccess: () => setExpiryDraft(null) },
    );
  };
  const rejectEvidence = async (entry: ClientPanelPerson, key: string, label: string) => {
    const yes = await askConfirm({
      title: `Usunąć dowód: ${label}?`,
      description: "Klient zobaczy to wymaganie jako „nie ma w CV” u tej osoby.",
      confirmLabel: "Usuń dowód",
    });
    if (!yes) return;
    person.mutate({
      candidateId: entry.candidate_id,
      patch: { rejected_evidence: [...(entry.rejected_evidence ?? []), key] },
    });
  };

  return (
    <div className="grid items-start gap-3 @3xl:grid-cols-2">
      {confirmDialog}
      <section className={cn(PANEL_CARD, "px-3.5 py-3")}>
        <h3 className="mb-1 font-display text-sm font-semibold">Panel tej rekrutacji</h3>
        <Toggle
          label="Panel włączony"
          hint="Link i kod QR w każdym CV tej rekrutacji"
          checked={settings.enabled}
          disabled={update.isPending || (settings.job_closed && !settings.enabled)}
          onChange={(value) => void setEnabled(value)}
        />
        {settings.job_closed && settings.enabled ? (
          <p className="mt-2 rounded-md bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground">
            Ta rekrutacja jest zamknięta, więc link z CV teraz nie działa. Klient widzi informację
            o zakończeniu rekrutacji.
          </p>
        ) : null}
        <Toggle
          label="Stawka do klienta"
          hint="Pokazuje stawkę do klienta. Oczekiwania kandydata nigdy nie wychodzą poza NEXUS."
          checked={settings.show_rate}
          disabled={update.isPending}
          onChange={(show_rate) => update.mutate({ show_rate })}
        />
        <Toggle
          label="Inni kandydaci w panelu"
          hint="Po wyłączeniu manager widzi tylko CV, z którego przyszedł"
          checked={settings.show_other_candidates}
          disabled={update.isPending}
          onChange={(show_other_candidates) => update.mutate({ show_other_candidates })}
        />
        <Toggle
          label="Pytania i prośby o rozmowę"
          hint="Wyłącz, gdy u klienta wszystko idzie przez procurement"
          checked={settings.allow_actions}
          disabled={update.isPending}
          onChange={(allow_actions) => update.mutate({ allow_actions })}
        />

        {settings.enabled && settings.url ? (
          <div className="mt-2.5 grid gap-2">
            <label className="grid gap-1 text-xs text-muted-foreground">
              Link do panelu
              <span className="flex gap-1.5">
                <Input readOnly value={settings.url} className="min-w-0 flex-1" data-testid="client-panel-url" />
                <Button variant="outline" onClick={() => void copy(settings.url as string)}>
                  <Copy className="h-3.5 w-3.5" />
                  Kopiuj
                </Button>
              </span>
            </label>
            {settings.short_url ? (
              <p className="text-xs text-muted-foreground">Krótki adres: {settings.short_url}</p>
            ) : null}
            <label className="grid gap-1 text-xs text-muted-foreground">
              Ważny do
              <span className="flex gap-1.5">
                <Input
                  type="date"
                  className="min-w-0 flex-1"
                  value={expiryDraft ?? expiresDay}
                  min={warsawToday()}
                  onChange={(event) => setExpiryDraft(event.target.value)}
                />
                <Button
                  variant="outline"
                  disabled={!expiryDraft || expiryDraft === expiresDay || update.isPending}
                  onClick={() => saveExpiry(expiryDraft)}
                >
                  Zapisz datę
                </Button>
              </span>
            </label>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline">
                <a href={settings.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" />
                  Zobacz jako klient
                </a>
              </Button>
              <Button variant="quiet" disabled={rotate.isPending} onClick={() => void revokeLink()}>
                <Link2Off className="h-3.5 w-3.5" />
                Odwołaj link
              </Button>
            </div>
          </div>
        ) : (
          <p className="mt-2.5 text-xs text-muted-foreground">
            {settings.job_closed
              ? "Ta rekrutacja jest zamknięta. Link by nie działał, więc panelu nie da się włączyć."
              : "Link powstanie po włączeniu panelu i będzie ważny 60 dni. Do tego czasu klient niczego nie widzi."}
          </p>
        )}
      </section>

      <section className={cn(PANEL_CARD, "px-3.5 py-3")}>
        <h3 className="mb-1 font-display text-sm font-semibold">Przed wysyłką: sprawdź dowody</h3>
        <p className="mb-2 text-xs text-muted-foreground">
          Klient zobaczy dokładnie to. „Nieprawda” usuwa dowód z panelu.
        </p>
        {settings.candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Na liście są osoby, których CV poszło do klienta. Takich osób jeszcze nie ma.
          </p>
        ) : (
          <div className="grid gap-2">
            {settings.candidates.map((entry) => (
              <div
                key={entry.candidate_id}
                className={cn("rounded-lg bg-muted px-2.5 py-2", entry.hidden && "opacity-70")}
                data-testid={`client-panel-person-${entry.candidate_id}`}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                  <span className="font-medium">{entry.name}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    w projektach {entry.in_projects} · na liście {entry.on_list} · brak{" "}
                    {entry.missing}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    disabled={person.isPending}
                    aria-pressed={entry.hidden}
                    onClick={() =>
                      person.mutate({
                        candidateId: entry.candidate_id,
                        patch: { hidden: !entry.hidden },
                      })
                    }
                  >
                    {entry.hidden ? "Pokaż w panelu" : "Ukryj w panelu"}
                  </Button>
                </div>
                {entry.documents?.length ? (
                  <fieldset className="mt-1.5">
                    <legend className="text-xs text-muted-foreground">Pliki dla klienta</legend>
                    {entry.documents.map((document) => {
                      const shared = entry.shared_document_ids ?? [];
                      return (
                        <label key={document.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={shared.includes(document.id)}
                            disabled={person.isPending}
                            onChange={(event) =>
                              person.mutate({
                                candidateId: entry.candidate_id,
                                patch: {
                                  shared_document_ids: event.target.checked
                                    ? [...shared, document.id]
                                    : shared.filter((id) => id !== document.id),
                                },
                              })
                            }
                          />
                          <span className="min-w-0 break-words">{document.name}</span>
                        </label>
                      );
                    })}
                  </fieldset>
                ) : null}
                {entry.weak.map((weak) => (
                  <div
                    key={weak.key}
                    className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border pt-1 text-xs"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{weak.label}</span>
                      {weak.quote ? `: ${weak.quote}` : ""}
                      {weak.where ? (
                        <span className="text-muted-foreground"> ({weak.where})</span>
                      ) : null}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={person.isPending}
                      onClick={() => void rejectEvidence(entry, weak.key, weak.label)}
                    >
                      Nieprawda
                    </Button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function RequestDetail({
  jobId,
  item,
  transport,
}: {
  jobId: number;
  item: ClientPanelRequestItem;
  transport: ClientPanelAdminTransport;
}) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const toastError = useManageErrorToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [answer, setAnswer] = useState("");
  const [sendEmail, setSendEmail] = useState(false);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: clientPanelRequestsKey(jobId) });
    void queryClient.invalidateQueries({ queryKey: clientPanelAdminKey(jobId) });
  };

  const answerMutation = useMutation({
    mutationFn: () =>
      transport.answerRequest(item.id, { answer: answer.trim(), send_email: sendEmail }),
    onSuccess: () => {
      showSuccess(sendEmail ? "Odpowiedź w panelu i w mailu" : "Odpowiedź widoczna w panelu klienta");
      refresh();
    },
    onError: (error) => toastError(error, "Nie udało się wysłać odpowiedzi."),
  });
  const closeMutation = useMutation({
    mutationFn: () => transport.closeRequest(item.id),
    onSuccess: () => {
      showSuccess("Sprawa zamknięta");
      refresh();
    },
    onError: (error) => toastError(error, "Nie udało się zamknąć sprawy."),
  });

  const sendAnswer = async () => {
    if (sendEmail && !item.email_domain_known) {
      const yes = await askConfirm({
        title: "Wysłać mail na adres spoza domen klienta?",
        description: `Adres ${item.author_email ?? ""} wpisała osoba z linku i nie zgadza się z kontaktami klienta. Jeśli to nie ta osoba, treść trafi do kogoś obcego.`,
        confirmLabel: "Wyślij mimo to",
        variant: "destructive",
      });
      if (!yes) return;
    }
    answerMutation.mutate();
  };

  return (
    <div className="px-3.5 py-3" data-testid="client-panel-request">
      {confirmDialog}
      <h3 className="font-display text-sm font-semibold">
        {item.candidate_name ? `${item.candidate_name}: ` : ""}
        {KIND_LABELS[item.kind]}
      </h3>
      <p className="mb-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
        {[item.author_name, item.author_email, formatDateTimePl(item.created_at)]
          .filter(Boolean)
          .join(" · ")}
        {!item.email_domain_known ? (
          <Pill tone="warning">Adres spoza domen kontaktów klienta</Pill>
        ) : null}
      </p>
      {item.reasons?.length ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {item.reasons.map((reason) => (
            <Pill key={reason}>{reason}</Pill>
          ))}
        </div>
      ) : null}
      {item.body ? (
        <p className="mb-2 whitespace-pre-wrap break-words rounded-lg border border-border px-3 py-2 text-sm">
          {item.body}
        </p>
      ) : null}

      {item.kind === "interview" ? (
        <p className="mb-2 text-xs text-muted-foreground">
          To ten sam wniosek co po wklejeniu maila od klienta: rekruter dostaje go w „Rozmowach”, a
          karta sama przechodzi na „Rozmowę u klienta”.
        </p>
      ) : null}
      {item.kind === "not_fit" ? (
        <p className="mb-2 text-xs text-muted-foreground">
          Ruch karty robisz Ty, klient nie przesuwa nic na Tablicy.
        </p>
      ) : null}

      {item.kind === "question" || item.kind === "requirements_change" ? (
        <div className="mb-2 grid gap-1.5">
          <label className="grid gap-1 text-xs text-muted-foreground">
            Odpowiedź dla klienta
            <Textarea
              value={answer}
              rows={4}
              maxLength={2000}
              placeholder={
                item.kind === "question"
                  ? "Klient zobaczy ją w panelu."
                  : "Odpowiedź o wymaganiach nie pojawia się w panelu, klient dostanie ją tylko mailem."
              }
              onChange={(event) => setAnswer(event.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={sendEmail}
              onChange={(event) => setSendEmail(event.target.checked)}
            />
            Wyślij też mailem{item.author_email ? ` na ${item.author_email}` : ""}
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {item.kind === "question" || item.kind === "requirements_change" ? (
          <Button
            disabled={!answer.trim() || answerMutation.isPending}
            onClick={() => void sendAnswer()}
          >
            Wyślij odpowiedź
          </Button>
        ) : null}
        {item.candidate_id ? (
          <Button asChild variant="outline">
            <Link href={`/jobs/${jobId}?candidate=${item.candidate_id}`}>Otwórz osobę na Tablicy</Link>
          </Button>
        ) : null}
        <Button
          variant="outline"
          disabled={closeMutation.isPending}
          onClick={() => closeMutation.mutate()}
        >
          Zamknij sprawę
        </Button>
      </div>
    </div>
  );
}

function InboxTab({
  jobId,
  transport,
}: {
  jobId: number;
  transport: ClientPanelAdminTransport;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const query = useQuery({
    queryKey: clientPanelRequestsKey(jobId),
    queryFn: () => transport.fetchRequests(jobId),
    staleTime: 30_000,
    retry: false,
  });
  if (query.isPending) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Wczytuję sprawy od klienta…
      </p>
    );
  }
  if (query.isError) {
    return (
      <PanelRetry
        text={apiErrorMessage(query.error, "Nie udało się wczytać spraw od klienta.")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  const items = query.data;
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Klient nie czeka teraz na nic.</p>;
  }
  const selected = items.find((item) => item.id === selectedId) ?? items[0];

  return (
    <div className="grid items-start gap-3 @3xl:grid-cols-[320px_minmax(0,1fr)]">
      <div className={PANEL_CARD}>
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={item.id === selected.id}
            onClick={() => setSelectedId(item.id)}
            className={cn(
              "block w-full border-b border-border px-3 py-2 text-left last:border-b-0",
              item.id === selected.id ? "bg-primary/10" : "hover:bg-muted",
            )}
          >
            <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
              {item.candidate_name ?? "Cała rekrutacja"}
              <Pill tone={item.kind === "interview" ? "success" : item.kind === "question" ? "warning" : "neutral"}>
                {KIND_LABELS[item.kind]}
              </Pill>
            </span>
            <span className="block text-xs text-muted-foreground">
              {[item.author_email, formatDateTimePl(item.created_at)].filter(Boolean).join(" · ")}
            </span>
          </button>
        ))}
      </div>
      <div className={PANEL_CARD}>
        <RequestDetail key={selected.id} jobId={jobId} item={selected} transport={transport} />
      </div>
    </div>
  );
}

function ActivityTab({
  jobId,
  settings,
  transport,
}: {
  jobId: number;
  settings: ClientPanelSettings;
  transport: ClientPanelAdminTransport;
}) {
  const query = useQuery({
    queryKey: clientPanelActivityKey(jobId),
    queryFn: () => transport.fetchActivity(jobId),
    staleTime: 30_000,
    retry: false,
  });
  const { views } = settings;
  let list: ReactNode;
  if (query.isPending) {
    list = (
      <p className="p-3 text-sm text-muted-foreground" role="status">
        Wczytuję aktywność…
      </p>
    );
  } else if (query.isError) {
    list = (
      <div className="p-3">
        <PanelRetry
          text={apiErrorMessage(query.error, "Nie udało się wczytać aktywności.")}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  } else if (query.data.length === 0) {
    list = <p className="p-3 text-sm text-muted-foreground">Nikt jeszcze nie otworzył panelu.</p>;
  } else {
    list = query.data.map((item, index) => (
      <div
        key={`${item.at}-${index}`}
        className="flex flex-wrap gap-x-2 border-b border-border px-3 py-1.5 text-sm last:border-b-0"
      >
        <span className="tabular-nums text-muted-foreground">{formatDateTimePl(item.at)}</span>
        <span>
          {ACTIVITY_LABELS[item.action] ?? item.action}
          {item.candidate_name ? `: ${item.candidate_name}` : ""}
          {item.detail ? ` (${item.detail})` : ""}
        </span>
      </div>
    ));
  }
  return (
    <div className="grid gap-2">
      <p className="text-sm tabular-nums text-muted-foreground">
        Wejścia: {views.total} · osoby: {views.people}
        {views.last_at ? ` · ostatnio ${formatPanelDate(views.last_at)}` : ""}
      </p>
      <div className={PANEL_CARD}>{list}</div>
    </div>
  );
}

export function ClientPanelManage({
  jobId,
  transport = httpClientPanelAdminTransport,
  initialTab,
}: {
  jobId: number;
  transport?: ClientPanelAdminTransport;
  initialTab?: ManageTab;
}) {
  const [chosenTab, setChosenTab] = useState<ManageTab | null>(initialTab ?? null);
  const query = useQuery({
    queryKey: clientPanelAdminKey(jobId),
    queryFn: () => transport.fetchSettings(jobId),
    staleTime: 30_000,
    retry: false,
  });
  const open = query.data?.requests_open ?? 0;
  const tabs = useMemo(
    () =>
      [
        { id: "setup", label: "Co widzi klient" },
        { id: "inbox", label: open > 0 ? `Od klienta (${open})` : "Od klienta" },
        { id: "activity", label: "Aktywność" },
      ] as const,
    [open],
  );
  if (query.isPending) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Wczytuję panel klienta…
      </p>
    );
  }
  if (query.isError || !query.data) {
    return (
      <PanelRetry
        text={apiErrorMessage(query.error, "Nie udało się wczytać panelu klienta.")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  // Bez wyboru otwiera się to, co czeka na odpowiedź: powiadomienie o pytaniu
  // prowadzi tutaj, więc pytanie ma być od razu na wierzchu.
  const tab = chosenTab ?? (open > 0 ? "inbox" : "setup");

  return (
    <div className="@container">
      <PanelTabs tabs={tabs} active={tab} onChange={setChosenTab} label="Panel klienta" />
      {tab === "setup" ? (
        <SetupTab jobId={jobId} settings={query.data} transport={transport} />
      ) : tab === "inbox" ? (
        <InboxTab jobId={jobId} transport={transport} />
      ) : (
        <ActivityTab jobId={jobId} settings={query.data} transport={transport} />
      )}
    </div>
  );
}
