"use client";

/**
 * „Do podpisu za B2Bnetwork” w rejestrze Generatora (makieta 6): umowy, które
 * kontraktor już podpisał, a czekają na tę osobę.
 *
 * K1 (22.11.2026): gdy serwer zwróci `company-remote/available`, reprezentant
 * zaznacza umowy i podpisuje je w NEXUSIE jednym zatwierdzeniem w aplikacji
 * dostawcy podpisu w chmurze; wraca z `?remote={session_id}` i panel pyta
 * o stan sesji. Pobierz i wgraj zostaje pod „Wolę pobrać plik…”. Bez dostawcy
 * panel wygląda jak dotąd.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  Download,
  FileSignature,
  Loader2,
  Smartphone,
} from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ESIGN_COMPANY_REMOTE_KEY,
  ESIGN_MINE_KEY,
  b2bEsignApi,
  signedPdfProblem,
  type CompanyRemoteSession,
  type EsignRequest,
} from "@/lib/api/b2bEsign";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { pluralPl } from "@/lib/plural-pl";
import {
  REMOTE_POLL_FAILED,
  RemotePollError,
  dropRemoteParam,
  leaveForProvider,
  useRemoteSigningPoll,
  type RemotePoll,
} from "@/lib/remote-signing";

import { SignedPdfField } from "./SignedPdfField";

/** Po podpisie za firmę odświeża te same listy, co wgranie pliku. */
function invalidateAfterCompanySign(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ESIGN_MINE_KEY });
  queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
  queryClient.invalidateQueries({ queryKey: ["kanban"] });
  queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
}

function useCompanyPdfDownload(request: EsignRequest) {
  const toast = useToast();
  return useMutation({
    mutationFn: () => b2bEsignApi.companyPdf(request.id),
    onSuccess: (res) =>
      downloadBlob(
        res.data,
        parseDispositionFilename(
          String(res.headers?.["content-disposition"] ?? ""),
          "Umowa B2B podpisana przez kontraktora.pdf",
        ),
      ),
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się pobrać pliku.")),
  });
}

function contractsLabel(count: number): string {
  return `${count} ${pluralPl(count, "umowa", "umowy", "umów")}`;
}

function appLabel(providerLabel: string | null): string {
  return providerLabel ? `w aplikacji ${providerLabel}` : "w aplikacji dostawcy podpisu";
}

function signedAt(value: string | null): string {
  return value
    ? new Date(value).toLocaleString("pl-PL", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Warsaw",
      })
    : "";
}

function SignRow({ request }: { request: EsignRequest }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const download = useCompanyPdfDownload(request);
  const sign = useMutation({
    mutationFn: (picked: File) => b2bEsignApi.companySign(request.id, picked),
    onSuccess: () => {
      toast.showSuccess("Umowa podpisana przez obie strony.");
      invalidateAfterCompanySign(queryClient);
    },
  });
  const problem = file ? signedPdfProblem(file) : null;
  return (
    <li className="space-y-3 border-t border-border p-4 first:border-t-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{request.contractor_name}</p>
          <p className="text-xs text-muted-foreground">
            Kontraktor podpisał podpisem kwalifikowanym
            {request.contractor_signed_at
              ? ` · ${new Date(request.contractor_signed_at).toLocaleString("pl-PL", {
                  timeZone: "Europe/Warsaw",
                })}`
              : ""}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => download.mutate()}
          disabled={download.isPending}
        >
          {download.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="h-4 w-4" aria-hidden />
          )}
          Pobierz do podpisu
        </Button>
      </div>
      <SignedPdfField
        id={`esign-company-${request.id}`}
        label="Plik z oboma podpisami"
        file={file}
        onFile={setFile}
        disabled={sign.isPending}
      />
      {sign.isError ? (
        <Alert
          variant="error"
          title="Podpis nie został przyjęty"
          description={apiErrorMessage(sign.error, "Spróbuj ponownie.")}
        />
      ) : null}
      <Button
        type="button"
        variant="primary"
        size="sm"
        disabled={!file || Boolean(problem) || sign.isPending}
        onClick={() => file && sign.mutate(file)}
      >
        {sign.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <FileSignature className="h-4 w-4" aria-hidden />
        )}
        Wgraj podpisaną za B2Bnetwork
      </Button>
    </li>
  );
}

function RemoteRow({
  request,
  waiting,
  checked,
  onChecked,
}: {
  request: EsignRequest;
  waiting: boolean;
  checked: boolean;
  onChecked: (value: boolean) => void;
}) {
  const download = useCompanyPdfDownload(request);
  const name = `${request.contract_number ?? `#${request.generated_contract_id}`} · ${request.contractor_name}`;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2.5 first:border-t-0">
      {waiting ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
      ) : (
        <Checkbox
          checked={checked}
          onCheckedChange={(value) => onChecked(value === true)}
          aria-label={`Zaznacz ${name}`}
        />
      )}
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{name}</p>
        <p className="text-xs text-muted-foreground">
          {request.client_name ? `${request.client_name} · ` : ""}
          <CheckCircle2 className="mb-0.5 inline h-3 w-3 text-success" aria-hidden /> kontraktor
          podpisał {signedAt(request.contractor_signed_at)}
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="ml-auto"
        aria-label={`Pobierz PDF: ${name}`}
        onClick={() => download.mutate()}
        disabled={download.isPending}
      >
        {download.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Download className="h-4 w-4" aria-hidden />
        )}
        Pobierz PDF
      </Button>
    </li>
  );
}

/** Lista z zaznaczaniem i „Podpisz zaznaczone w NEXUSIE (N)”. */
function RemoteSignList({
  requests,
  providerLabel,
  waiting,
}: {
  requests: EsignRequest[];
  providerLabel: string | null;
  waiting: boolean;
}) {
  // Pamiętamy odznaczone: umowa, która dojdzie do listy, jest od razu zaznaczona.
  const [unpicked, setUnpicked] = useState<ReadonlySet<number>>(new Set());
  const [ownTool, setOwnTool] = useState(false);
  const picked = requests.filter((r) => !unpicked.has(r.id)).map((r) => r.id);
  const start = useMutation({
    mutationFn: (ids: number[]) => b2bEsignApi.companyRemoteStart(ids),
    onSuccess: (started) => leaveForProvider(started.redirect_url),
  });
  // Po starcie przycisk zostaje zablokowany: strona przechodzi do dostawcy.
  const leaving = start.isPending || start.isSuccess;
  return (
    <section
      className="mb-4 overflow-hidden rounded-xl border border-primary/30 bg-card"
      aria-label="Umowy do podpisu za B2Bnetwork"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-primary/5 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">
            Do podpisu za B2Bnetwork ({requests.length})
          </h2>
          <p className="text-xs text-muted-foreground">
            {ownTool
              ? "Pobierz plik, podpisz go swoim podpisem kwalifikowanym (podpis dołoży się do podpisu kontraktora) i wgraj z powrotem."
              : `Kontraktorzy już podpisali. Zaznaczone podpiszesz jednym potwierdzeniem ${appLabel(providerLabel)}.`}
          </p>
        </div>
        {!ownTool && !waiting ? (
          <Button
            type="button"
            size="sm"
            disabled={picked.length === 0 || leaving}
            onClick={() => start.mutate(picked)}
          >
            {leaving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <FileSignature className="h-4 w-4" aria-hidden />
            )}
            Podpisz zaznaczone w NEXUSIE ({picked.length})
          </Button>
        ) : null}
      </div>
      {start.isError ? (
        <Alert
          variant="error"
          className="m-4"
          title="Nie udało się rozpocząć podpisu"
          description={apiErrorMessage(start.error, "Spróbuj ponownie za chwilę.")}
        />
      ) : null}
      <ul>
        {requests.map((request) =>
          ownTool ? (
            <SignRow key={request.id} request={request} />
          ) : (
            <RemoteRow
              key={request.id}
              request={request}
              waiting={waiting}
              checked={!unpicked.has(request.id)}
              onChecked={(value) =>
                setUnpicked((prev) => {
                  const next = new Set(prev);
                  if (value) next.delete(request.id);
                  else next.add(request.id);
                  return next;
                })
              }
            />
          ),
        )}
      </ul>
      {waiting ? null : (
        <div className="border-t border-dashed border-border px-4 py-2.5">
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setOwnTool((v) => !v)}
            aria-expanded={ownTool}
          >
            {ownTool
              ? "Wolę podpisać zaznaczone w NEXUSIE"
              : "Wolę pobrać plik, podpisać u siebie i wgrać"}
            <ChevronDown className={ownTool ? "h-3.5 w-3.5 rotate-180" : "h-3.5 w-3.5"} aria-hidden />
          </button>
        </div>
      )}
    </section>
  );
}

/** Stan sesji po powrocie od dostawcy: czekanie, wynik albo błąd. */
function RemoteSessionStatus({
  status,
  providerLabel,
  onRetry,
  onClose,
}: {
  status: RemotePoll<CompanyRemoteSession>;
  providerLabel: string | null;
  onRetry: () => void;
  onClose: () => void;
}) {
  if (status.phase === "polling") {
    const signing = status.result?.state === "signing";
    return (
      <section
        className="mb-4 flex flex-wrap items-center gap-4 rounded-xl border border-primary/30 bg-card px-4 py-4"
        aria-live="polite"
        aria-label="Podpis za B2Bnetwork u dostawcy"
      >
        <Smartphone className="h-6 w-6 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">
            {signing ? "Podpis zatwierdzony, kończymy" : `Zatwierdź podpis ${appLabel(providerLabel)}`}
          </p>
          <p className="text-xs text-muted-foreground">
            {status.result?.message ??
              (signing
                ? "NEXUS dołącza podpis do umów i sprawdza go na unijnej liście zaufanych."
                : "Po zatwierdzeniu lista sama się odświeży.")}
          </p>
        </div>
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
      </section>
    );
  }
  const close = (
    <Button type="button" variant="outline" size="sm" className="mt-2" onClick={onClose}>
      Zamknij
    </Button>
  );
  if (status.phase === "finished" && status.result.state === "done") {
    return (
      <Alert
        variant="success"
        className="mb-4"
        title={`Podpisane za B2Bnetwork: ${contractsLabel(status.result.done_request_ids.length)}`}
        description="Oba podpisy kwalifikowane sprawdzone. Kontraktorzy dostaną kopie mailem, a umowy przechodzą do potwierdzenia jak po „Oznacz jako podpisaną”."
      >
        {close}
      </Alert>
    );
  }
  if (status.phase === "finished") {
    const failed = status.result.state === "failed";
    return (
      <Alert
        variant={failed ? "error" : "warning"}
        className="mb-4"
        title={failed ? "Podpis za B2Bnetwork nie został złożony" : "Podpis za B2Bnetwork anulowany"}
        description={
          status.result.message ??
          (failed
            ? "Dostawca podpisu zgłosił błąd. Spróbuj ponownie albo pobierz plik i wgraj go podpisany."
            : "Prośba o podpis została anulowana w aplikacji albo wygasła.")
        }
      >
        {close}
      </Alert>
    );
  }
  return (
    <Alert
      variant={status.phase === "error" ? "error" : "warning"}
      className="mb-4"
      title={
        status.phase === "error"
          ? "Nie udało się sprawdzić stanu podpisu"
          : "Nie mamy jeszcze odpowiedzi od dostawcy podpisu"
      }
      description={
        status.phase === "error"
          ? status.message
          : "Minęły 3 minuty bez potwierdzenia. Jeśli podpis jest już zatwierdzony w aplikacji, sprawdź jeszcze raz za chwilę."
      }
    >
      <div className="mt-2 flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={onRetry}>
          Sprawdź jeszcze raz
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          Zamknij
        </Button>
      </div>
    </Alert>
  );
}

async function pollCompanySession(sessionId: string): Promise<CompanyRemoteSession> {
  try {
    return await b2bEsignApi.companyRemoteStatus(sessionId);
  } catch (error) {
    const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
    const clientError = typeof status === "number" && status >= 400 && status < 500;
    throw new RemotePollError(apiErrorMessage(error, REMOTE_POLL_FAILED), clientError);
  }
}

/** „Do podpisu za firmę” (makieta 6) — tylko gdy coś czeka na tę osobę. */
export function CompanySignaturesPanel() {
  const queryClient = useQueryClient();
  const remoteParam = useSearchParams()?.get("remote") ?? null;
  // Sesja zostaje w stanie po zdjęciu `?remote=` z adresu, żeby wynik nie znikł.
  const [sessionId, setSessionId] = useState<string | null>(remoteParam);
  useEffect(() => {
    if (remoteParam) setSessionId(remoteParam);
  }, [remoteParam]);
  const mine = useQuery({ queryKey: ESIGN_MINE_KEY, queryFn: b2bEsignApi.mine, staleTime: 30_000 });
  const hasWork = mine.isSuccess && mine.data.length > 0;
  const remote = useQuery({
    queryKey: ESIGN_COMPANY_REMOTE_KEY,
    queryFn: b2bEsignApi.companyRemoteAvailable,
    staleTime: 5 * 60_000,
    enabled: hasWork || Boolean(sessionId),
  });
  const providerLabel = remote.data?.provider_label ?? null;
  const { status, retry } = useRemoteSigningPoll(sessionId, pollCompanySession);
  const settled = Boolean(sessionId) && status.phase !== "polling";
  const doneNow = status.phase === "finished" && status.result.state === "done";
  useEffect(() => {
    if (!settled) return;
    dropRemoteParam();
    if (doneNow) invalidateAfterCompanySign(queryClient);
  }, [settled, doneNow, queryClient]);

  const sessionBand = sessionId ? (
    <RemoteSessionStatus
      status={status}
      providerLabel={providerLabel}
      onRetry={retry}
      onClose={() => setSessionId(null)}
    />
  ) : null;

  // Rejestr to miejsce pracy reprezentanta: awaria nie może wyglądać jak brak
  // umów (pas na pulpicie przy błędzie się chowa i odsyła tutaj).
  if (mine.isError) {
    return (
      <>
        {sessionBand}
        <Alert
          variant="error"
          className="mb-4"
          title={apiErrorMessage(
            mine.error,
            "Nie udało się wczytać umów do podpisu za B2Bnetwork.",
          )}
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => void mine.refetch()}
            disabled={mine.isFetching}
          >
            Ponów
          </Button>
        </Alert>
      </>
    );
  }
  if (!hasWork) return sessionBand;
  // Dostępność dostawcy jeszcze się wczytuje: bez mignięcia dzisiejszym panelem.
  // Awaria tego zapytania zostawia dzisiejszy panel, który działa bez dostawcy.
  if (remote.isPending) return sessionBand;
  if (remote.data?.available) {
    return (
      <>
        {sessionBand}
        <RemoteSignList
          requests={mine.data}
          providerLabel={providerLabel}
          waiting={Boolean(sessionId) && status.phase === "polling"}
        />
      </>
    );
  }
  return (
    <>
      {sessionBand}
      <section
        className="mb-4 overflow-hidden rounded-xl border border-primary/30 bg-card"
        aria-label="Umowy do podpisu za B2Bnetwork"
      >
        <div className="border-b border-border bg-primary/5 px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">
            Do podpisu za B2Bnetwork ({mine.data.length})
          </h2>
          <p className="text-xs text-muted-foreground">
            Pobierz plik, podpisz go swoim podpisem kwalifikowanym (podpis dołoży się do podpisu
            kontraktora) i wgraj z powrotem.
          </p>
        </div>
        <ul>
          {mine.data.map((request) => (
            <SignRow key={request.id} request={request} />
          ))}
        </ul>
      </section>
    </>
  );
}
