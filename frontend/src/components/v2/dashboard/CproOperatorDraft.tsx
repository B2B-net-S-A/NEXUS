"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { copyTextToClipboard } from "@/lib/clipboard";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import {
  CPRO_QUEUE_QUERY_KEY, closeAbsentCproOperatorDraft, confirmCproOperatorDraft, createCproOperatorDraft, cproAccountName,
  getCproOperatorRun, type CproOperatorDraft as Draft, type CproOperatorRun,
} from "@/lib/api/boardTasks";

/** Dane tylko z autoryzowanego snapshotu; żadnych tokenów ani lokalnego magazynu. */
export function CproOperatorDraft({ stageId, draft, onActiveChange }: {
  stageId: number;
  draft: Draft;
  onActiveChange: (active: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [runId, setRunId] = useState(draft.run_id);
  const [run, setRun] = useState<CproOperatorRun | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const activeCallback = useRef(onActiveChange);
  activeCallback.current = onActiveChange;
  const protectedRef = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [offerId, setOfferId] = useState("");
  const [confirmedDraft, setConfirmedDraft] = useState(false);
  const [confirmedPdf, setConfirmedPdf] = useState(false);
  const [pdfDownloaded, setPdfDownloaded] = useState(false);
  const [confirmedAbsent, setConfirmedAbsent] = useState(false);
  const account = cproAccountName(draft);
  const received = draft.state === "received" || run?.status === "received";
  const allowCreate = fresh && run?.allow_create === true && run.status === "started" && !received;
  const canConfirm = !!run && ["started", "expired", "failed"].includes(run.status) && !received;
  protectedRef.current = runId != null || uncertain || pending.current;
  const refreshQueue = () => { void queryClient.invalidateQueries({ queryKey: CPRO_QUEUE_QUERY_KEY }); };

  useEffect(() => () => activeCallback.current(protectedRef.current), []);

  useEffect(() => {
    if (draft.run_id != null) {
      setRunId(draft.run_id);
      setUncertain(false);
    }
  }, [draft.run_id]);

  // Every reopen/resume is GET-only. A failed GET never offers creation.
  useEffect(() => {
    if (!open || runId == null) return;
    if (!account) {
      setRun(null);
      setError("Nieznane konto Cpro — przerwij i odśwież kolejkę.");
      return;
    }
    let current = true;
    setBusy(true);
    setError("");
    setRun(null);
    getCproOperatorRun(runId).then((data) => {
      if (!current) return;
      if (data.run_id !== runId || data.stage_id !== stageId || data.delivery_lead_id !== draft.delivery_lead_id || cproAccountName(data) !== account || data.request_number !== draft.request_number || data.offer.cv_format !== "pdf" || !data.offer.cv_file_name.toLowerCase().endsWith(".pdf")) {
        setError("Zlecenie nie pasuje do tej karty, konta, requestu lub formatu PDF. Przerwij i odśwież kolejkę.");
        return;
      }
      setRun(data);
    }).catch((err) => { if (current) setError(apiErrorMessage(err, "Nie udało się otworzyć zapisanego zlecenia. Odśwież kolejkę; nie twórz kolejnego szkicu.")); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [open, runId, stageId, draft.delivery_lead_id, draft.request_number, account]);

  const toggle = () => {
    onActiveChange(!open || runId != null || uncertain);
    if (open) {
      setFresh(false);
      setOfferId("");
      setConfirmedDraft(false);
      setConfirmedPdf(false);
      setPdfDownloaded(false);
      setConfirmedAbsent(false);
    }
    setOpen(!open);
  };
  const create = async () => {
    if (pending.current || runId != null || draft.state !== "ready" || uncertain || !account) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setOfferId("");
    setConfirmedDraft(false);
    setConfirmedPdf(false);
    setPdfDownloaded(false);
    setConfirmedAbsent(false);
    try {
      const created = await createCproOperatorDraft(stageId, {
        delivery_lead_id: draft.delivery_lead_id, request_number: draft.request_number,
      });
      if (!Number.isInteger(created.run_id) || created.run_id <= 0) throw new Error("Invalid run");
      setFresh(created.created === true);
      setRunId(created.run_id);
    } catch (err) {
      setUncertain(true);
      setError(apiErrorMessage(err, "Nie udało się potwierdzić utworzenia zlecenia. Odśwież kolejkę i sprawdź zapisane zlecenie przed kolejną próbą."));
    } finally {
      setBusy(false);
      pending.current = false;
      refreshQueue();
    }
  };
  const download = async () => {
    if (!run || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const { blob, filename } = await fetchAuthenticatedDownload(`/api/board-tasks/cpro/operator/runs/${run.run_id}/cv`);
      if (blob.type.split(";")[0] !== "application/pdf" || (filename != null && !filename.toLowerCase().endsWith(".pdf"))) {
        throw new Error("Not PDF");
      }
      downloadBlob(blob, filename ?? run.offer.cv_file_name);
      setPdfDownloaded(true);
    } catch {
      setError("Nie udało się pobrać firmowego PDF. Nie zastępuj go plikiem DOCX ani innym CV; odśwież zlecenie.");
    } finally { pending.current = false; setBusy(false); }
  };
  const confirmSavedDraft = async () => {
    if (!run || !canConfirm || pending.current || !/^[0-9]{1,20}$/.test(offerId) || !/[1-9]/.test(offerId) || !confirmedDraft || !confirmedPdf || (allowCreate && !pdfDownloaded)) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await confirmCproOperatorDraft(run.run_id, offerId);
      setRun({ ...run, status: "received", offer_id: offerId });
      setNotice("Potwierdzono istniejący szkic DRAFT z PDF. Czeka na ocenę Sandry.");
    } catch (err) {
      setError(apiErrorMessage(err, "Brak potwierdzenia zapisu w NEXUSIE. Otwórz ponownie to samo zlecenie i sprawdź jego stan; nie twórz nowej oferty."));
    } finally { pending.current = false; setBusy(false); refreshQueue(); }
  };
  const copy = async (value: string) => {
    const ok = await copyTextToClipboard(value);
    setNotice(ok ? "Skopiowano widoczne dane." : "Przeglądarka nie pozwoliła skopiować — przepisz widoczne dane.");
  };
  const closeAbsent = async () => {
    if (!run || run.allow_close_absent !== true || received || !confirmedAbsent || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await closeAbsentCproOperatorDraft(run.run_id);
      setRun(null);
      setRunId(null);
      setFresh(false);
      setUncertain(false);
      setConfirmedAbsent(false);
      setOfferId("");
      setConfirmedDraft(false);
      setConfirmedPdf(false);
      setPdfDownloaded(false);
      setOpen(false);
      onActiveChange(false);
      setNotice("Zamknięto porzucone zlecenie po sprawdzeniu braku oferty. Niczego nie uruchomiono; kolejka jest odświeżana.");
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zamknąć rezerwacji. Otwórz ponownie zapisane zlecenie i sprawdź jego stan."));
    } finally { pending.current = false; setBusy(false); refreshQueue(); }
  };

  return (
    <div className="col-span-full space-y-2 border-t border-border pt-2" data-testid="cpro-operator-draft">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium">Pilot szkicu · konto Cpro: {account ?? "nieznane — przerwij"} · request {draft.request_number}</p>
        <Button size="sm" variant="outline" disabled={busy} onClick={toggle} aria-expanded={open}>
          {open ? "Zamknij panel szkicu" : received ? "Potwierdzony szkic" : runId != null ? "Wznów zapisane zlecenie" : "Przygotuj jeden szkic"}
        </Button>
      </div>
      {received ? <p className="text-xs text-info-muted-foreground">Szkic potwierdzony — czeka na ocenę Sandry. Nie twórz kolejnej oferty. Po osobnej ocenie i faktycznej publikacji domknij standardowy etap na Tablicy rekrutacji.</p> : null}
      {!open && notice ? <p role="status" className="text-xs">{notice}</p> : null}
      {open ? (
        <section aria-label="Pilot jednego szkicu Cpro" className="space-y-3 rounded-md border border-border bg-muted/30 p-3 text-sm">
          <p>Wyłącznie zapis szkicu DRAFT. Nie klikaj Submit ani Send i nie przesuwaj karty w NEXUSIE.</p>
          <p>Najpierw sprawdź konto {account ?? "—"} i request {draft.request_number}. W Cpro wyszukaj ofertę tej osoby w tym requeście.</p>
          {runId == null ? <p>Przed pierwszym zapisem sprawdź, czy oferta już istnieje. Jeśli istnieje lub wynik jest niejednoznaczny, przerwij — nie twórz duplikatu.</p> : allowCreate ? <p className="font-medium">To nowe zlecenie w tej sesji. Po sprawdzeniu braku istniejącej oferty możesz przygotować dokładnie jeden szkic z poniższych danych i firmowego PDF.</p> : <p className="font-medium">Wznawiasz zapisane zlecenie. Odszukaj już zapisany szkic i sprawdź go; nie twórz nowej oferty. Jeśli go nie ma lub wynik jest niejednoznaczny, przerwij i zgłoś do sprawdzenia.</p>}
          {busy ? <p role="status" className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" aria-hidden /> Wczytywanie…</p> : null}
          {error ? <p role="alert" className="text-destructive">{error}</p> : null}
          {notice ? <p role="status">{notice}</p> : null}
          {runId == null && draft.state === "ready" ? (
            <Button size="sm" disabled={busy || uncertain || !account} onClick={() => void create()}>Potwierdzam konto i request — otwórz zlecenie</Button>
          ) : null}
          {uncertain ? <p>Odśwież kolejkę i sprawdź zapisane zlecenie. Ten panel nie ponowi tworzenia po niejednoznacznym wyniku.</p> : null}
          {run ? <>
            <p className="text-xs text-muted-foreground">Zapisane zlecenie #{run.run_id} · {run.status === "received" ? "potwierdzone" : run.status === "started" ? "oczekuje na potwierdzenie szkicu" : canConfirm ? "przerwane — sprawdź istniejącą ofertę" : "nieaktywne — przerwij"}</p>
            <dl className="space-y-2">
              {([
                ["First name", run.candidate.first_name], ["Last name", run.candidate.last_name],
                ["Citizenship", run.candidate.citizenship], ["Title", run.candidate.profile_title],
                ["Profile description", run.candidate.profile_description],
                ["Offered rate", run.offer.rate], ["Currency", run.offer.currency],
                ["Available from", run.offer.available_from], ["Physical location", run.offer.physical_location],
                ["Former employee", run.offer.former_employee ? "Yes" : "No"],
                ["Former consultant", run.offer.former_consultant ? "Yes" : "No"],
                ["Motivation", run.offer.motivation],
              ] as [string, string][]).map(([label, value]) => (
                <div key={label} className="rounded border border-border bg-background p-2">
                  <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
                  <dd className="whitespace-pre-wrap break-words">{value}</dd>
                  <Button size="sm" variant="ghost" className="mt-1 h-6 px-2 text-xs" onClick={() => void copy(value)} aria-label={`Kopiuj ${label}`}>Kopiuj</Button>
                </div>
              ))}
            </dl>
            <p className="text-xs">Firmowy PDF: {run.offer.cv_file_name} · zatwierdzona wersja {run.offer.cv_version}. Otwórz plik i sprawdź układ oraz kompletność przed załączeniem.</p>
            <Button size="sm" variant="outline" disabled={busy || received || run.status !== "started"} onClick={() => void download()}>Pobierz firmowy PDF</Button>
            {received ? <p className="font-medium">Potwierdzony szkic DRAFT{run.offer_id ? ` · ID oferty ${run.offer_id}` : ""}. Czeka na ocenę Sandry.</p> : canConfirm ? (
              <div className="space-y-2 border-t border-border pt-3">
                <p>Po zapisaniu otwórz ponownie tę samą ofertę w Cpro. Sprawdź konto i request, widoczny status DRAFT, a następnie otwórz załącznik PDF z tej oferty. Dopiero wtedy potwierdź poniżej.</p>
                <label className="block">ID istniejącej oferty w Cpro
                  <input className="mt-1 block w-full rounded-md border border-input bg-background px-2 py-1.5" inputMode="numeric" value={offerId} onChange={(e) => setOfferId(e.target.value)} disabled={busy} />
                </label>
                <label className="flex items-start gap-2"><input type="checkbox" checked={confirmedDraft} onChange={(e) => setConfirmedDraft(e.target.checked)} disabled={busy} />Ponownie otworzyłem tę ofertę na właściwym koncie i requeście; widzę DRAFT.</label>
                <label className="flex items-start gap-2"><input type="checkbox" checked={confirmedPdf} onChange={(e) => setConfirmedPdf(e.target.checked)} disabled={busy || (allowCreate && !pdfDownloaded)} />Otworzyłem PDF z zapisanej oferty i sprawdziłem firmowy układ oraz kompletność.</label>
                <Button size="sm" disabled={busy || !/^[0-9]{1,20}$/.test(offerId) || !/[1-9]/.test(offerId) || !confirmedDraft || !confirmedPdf || (allowCreate && !pdfDownloaded)} onClick={() => void confirmSavedDraft()}>Potwierdź zapisany szkic DRAFT i PDF</Button>
              </div>
            ) : null}
            {run.allow_close_absent === true && !received ? <div className="space-y-2 border-t border-border pt-3">
              <p>Odzyskanie porzuconej karty jest możliwe wyłącznie po sprawdzeniu, że oferta nie powstała.</p>
              <label className="flex items-start gap-2"><input type="checkbox" checked={confirmedAbsent} disabled={busy} onChange={(e) => setConfirmedAbsent(e.target.checked)} />Osobiście sprawdziłem Our offers na koncie {account}, w oryginalnym requeście {draft.request_number}: oferta tej osoby nie istnieje.</label>
              <Button size="sm" variant="outline" disabled={busy || !confirmedAbsent} onClick={() => void closeAbsent()}>Zamknij porzucone zlecenie — brak oferty</Button>
            </div> : null}
          </> : null}
        </section>
      ) : null}
    </div>
  );
}
