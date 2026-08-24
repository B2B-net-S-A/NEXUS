"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileSearch,
  Loader2,
  Trash2,
} from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  ClientOrderRead,
  ClientOrderUpdate,
  CreateDraftOrder,
} from "@/lib/api/dlPortal";
import { PROJECT_PARTS, isEzdrowieClient } from "@/lib/ezdrowie";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import { downloadOrderDocument, openOrderDocument } from "@/lib/order-documents";
import { extractionErrorMessage } from "@/lib/order-extraction";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

/** Serwerowy limit z `client_orders.py` (MAX_UPLOAD_BYTES). */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

interface EditOrderDialogProps {
  clientId: number;
  /**
   * `null` = kontraktor nie ma jeszcze żadnego zamówienia. Formularz otwiera
   * się wtedy pusty i zakłada szkic dopiero przy zapisie — anulowanie nie
   * zostawia w bazie wiersza „(bez numeru)", który potem dopominałby się
   * w pigułce „Draft".
   */
  order: ClientOrderRead | null;
  /** Zakłada zamówienie, gdy `order === null`. Zwraca id nowego wiersza. */
  onCreate?: CreateDraftOrder;
  /** Stawka kosztowa z powiązanego kontraktu (`ContractWithOrdersRead`). */
  rateCandidate: number | null;
  /** Serwer wylicza to per klient — patrz `can_manage_finance` w odpowiedzi. */
  canManageFinance: boolean;
  onClose: () => void;
  onSaved: () => void;
  /** Odświeża kartę po zmianie samego pliku, bez zamykania formularza. */
  onChanged?: () => void;
}

/**
 * „Uzupełnij zamówienie" — edycja draftu w jednym miejscu.
 *
 * Osobny dialog, a nie rozszerzenie edycji inline z `OrdersAndContractsTab`,
 * bo draft trafia do jednego z TRZECH slotów karty (aktualny / przyszły /
 * historia) w zależności od dat, a draft bez dat wpada do slotu aktualnego.
 * Ciągnięcie tych samych pól przez trzy różne wiersze to trzykrotna praca
 * i trzy okazje do rozjazdu; jeden dialog obsługuje każdy slot tak samo.
 *
 * Powłoka to `AppModal` (Radix), NIE wzorzec z `ExtendOrderDialog`, który
 * jest surowym `fixed inset-0` backdropem bez `role="dialog"`, focus-trapu
 * i obsługi Escape.
 */
export function EditOrderDialog({
  clientId,
  order,
  onCreate,
  rateCandidate,
  canManageFinance,
  onClose,
  onSaved,
  onChanged,
}: EditOrderDialogProps) {
  const { showToast } = useToast();
  const ezdrowie = isEzdrowieClient(clientId);

  const [title, setTitle] = useState(order?.title ?? "");
  const [description, setDescription] = useState(order?.description ?? "");
  const [startDate, setStartDate] = useState(order?.start_date ?? "");
  const [endDate, setEndDate] = useState(order?.end_date ?? "");
  const [rateCost, setRateCost] = useState(
    rateCandidate != null ? String(rateCandidate) : "",
  );
  const [rateRevenue, setRateRevenue] = useState(
    order?.rate_client != null ? String(order.rate_client) : "",
  );
  const [projectPart, setProjectPart] = useState(order?.project_part ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [busyFile, setBusyFile] = useState(false);
  const [hasExistingFile, setHasExistingFile] = useState(order?.has_file ?? false);

  // „Zczytaj dane z dokumentu" — ta sama funkcja co w przedłużeniu, ta sama
  // implementacja odczytu (`lib/order-extraction.ts`). W TYM widoku odczyt
  // NADPISUJE ręczne wpisy bez pytania — ticket żąda tego wprost, także dla
  // pól „Start"/„Koniec". Pytanie „Tak/Nie" jest zarezerwowane dla widoku
  // wielo-konsultantowego; ujednolicenie byłoby złamaniem jednego z ticketów.
  const [extracting, setExtracting] = useState(false);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  // Polityka klientowa (Bank Pocztowy) nie znalazła numeru w dokumencie —
  // komunikat „Sprawdź numer zamówienia" przy polu numeru, dopóki puste.
  const [titleCheck, setTitleCheck] = useState(false);
  // Oryginalna stawka za 1 MD z dokumentu (Bank Pocztowy) — pokazywana obok
  // pola stawki; samo pole niesie już wartość przeliczoną na zł/h (MD ÷ 8).
  const [rateMdOriginal, setRateMdOriginal] = useState<string | null>(null);

  async function handleExtract() {
    if (!file || extracting) return;
    setExtracting(true);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(clientId, file);
      if (data.title) setTitle(data.title);
      setTitleCheck(Boolean(data.title_needs_review));
      if (data.start_date) setStartDate(normalizeDateInput(data.start_date));
      if (data.end_date) setEndDate(normalizeDateInput(data.end_date));
      if (canManageFinance) {
        if (data.rate_client != null) setRateRevenue(String(data.rate_client));
        // Bank Pocztowy: pole stawki dostało wartość GODZINOWĄ; oryginał MD
        // pokazujemy obok, żeby obie wartości były widoczne przed zapisem.
        setRateMdOriginal(
          data.rate_client_md != null ? String(data.rate_client_md) : null,
        );
      }
      setCheckData(Boolean(data.uncertain));
      setCheckReasons(data.uncertain_reasons ?? []);
      showToast("Odczytano dane z dokumentu", "success");
    } catch (err: unknown) {
      showToast(
        extractionErrorMessage(err, "Nie udało się odczytać danych z dokumentu."),
        "error",
      );
    } finally {
      setExtracting(false);
    }
  }

  // Podgląd/pobranie/usunięcie dotyczą pliku, który JUŻ leży na zamówieniu —
  // w trybie tworzenia nie ma jeszcze czego wskazać.
  const docRef = order
    ? {
        order_id: order.id,
        client_id: order.client_id,
        filename: order.filename,
        content_type: order.content_type,
      }
    : null;

  function pickFile(picked: File | null) {
    // Dodanie pliku NIE zmienia żadnego pola — odczyt jest osobną, świadomą
    // akcją. Czyścimy tylko baner z poprzedniego odczytu. Walidację
    // rozszerzenia i rozmiaru robi `FileDropZone`, ta sama dla wyboru z okna
    // i dla przeciągnięcia.
    setFileError("");
    setFile(picked);
    setCheckData(false);
    setCheckReasons([]);
    setTitleCheck(false);
    setRateMdOriginal(null);
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const payload: ClientOrderUpdate = {
        title: title.trim(),
        description: description.trim() || null,
        start_date: startDate ? normalizeDateInput(startDate) : null,
        end_date: endDate ? normalizeDateInput(endDate) : null,
      };
      if (ezdrowie) payload.project_part = projectPart || null;
      // Kwoty POMIJAMY całkowicie, gdy rola ich nie prowadzi — wysłanie
      // zredagowanej (pustej) wartości nadpisałoby prawdziwą stawkę zerem.
      if (canManageFinance) {
        payload.rate_candidate = parseDecimalInput(rateCost);
        payload.rate_client = parseDecimalInput(rateRevenue);
      }
      if (order) {
        await dlPortalApi.updateOrder(clientId, order.id, payload);
        if (file) {
          await dlPortalApi.replaceOrderPo(clientId, order.id, file);
        }
        return;
      }
      if (!onCreate) {
        throw new Error(
          "Nie da się założyć zamówienia dla tego kontraktora z tego widoku.",
        );
      }
      // Tworzenie idzie JEDNYM żądaniem: `POST /orders` przyjmuje komplet pól
      // razem z plikiem. Rozbicie na create + upload zostawiałoby przy błędzie
      // drugiego kroku zamówienie bez PDF-a, o który formularz właśnie prosił.
      // Numer i część umowy jadą osobno, bo POST nazywa je inaczej niż PATCH.
      await onCreate(payload, {
        title: payload.title,
        projectPart: ezdrowie ? projectPart : undefined,
        file,
      });
    },
    onSuccess: () => {
      showToast("Zamówienie zaktualizowane", "success");
      // Bez tego ponowny wybór TEGO SAMEGO pliku nie odpali zdarzenia change.
      // Reset wybranego pliku po zapisie — `FileDropZone` sam czyści swój
      // input, gdy `file` wraca na `null`.
      setFile(null);
      onSaved();
    },
    onError: (err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      showToast(
        status === 415
          ? "Serwer przyjmuje tylko pliki PDF."
          : status === 413
            ? "Plik jest za duży (limit 25 MB)."
            : status === 403
              ? "Brak uprawnień do zapisu kwot na zamówieniach tego klienta."
              : err instanceof Error
                ? err.message
                : "Nie udało się zapisać zamówienia",
        "error",
      );
    },
  });

  async function withBusy(fn: () => Promise<void>, failMsg: string) {
    setBusyFile(true);
    try {
      await fn();
    } catch {
      showToast(failMsg, "error");
    } finally {
      setBusyFile(false);
    }
  }

  async function handleDeleteExistingFile() {
    if (!order) return;
    if (
      !window.confirm("Czy na pewno chcesz usunąć plik PDF zamówienia?")
    ) {
      return;
    }
    await withBusy(async () => {
      await dlPortalApi.deleteOrderPo(clientId, order.id);
      setHasExistingFile(false);
      setFile(null);
      setCheckData(false);
      setCheckReasons([]);
      setTitleCheck(false);
      setRateMdOriginal(null);
      onChanged?.();
      showToast("Plik PDF zamówienia usunięty", "success");
    }, "Nie udało się usunąć pliku PDF zamówienia.");
  }

  const canSubmit = title.trim().length > 0 && !mutation.isPending;

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Uzupełnij zamówienie"
      description="Dane zamówienia i PDF od klienta. Wgrany plik pojawi się także w Dokumentach kontraktu."
      size="lg"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Zapisz
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Baner NAD tytułem — tak samo jak w przedłużeniu; to pierwsze, co
            widać po odczycie, więc ostrzeżenie nie może być pod formularzem. */}
        {checkData && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900"
          >
            <AlertTriangle
              className="mt-0.5 h-4 w-4 shrink-0 text-orange-500"
              aria-hidden
            />
            <div>
              <p className="font-semibold">Sprawdź dane!</p>
              {checkReasons.length > 0 && (
                <ul className="mt-1 list-disc pl-4">
                  {checkReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        <label className="block">
          <span className="text-sm font-medium">Numer zamówienia</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
            placeholder="np. ZAM/2026/014"
          />
          {/* Po odczycie bez numeru (polityka klientowa, np. Bank Pocztowy)
              komunikat z ticketu wypiera generyczne „wymagany" — oba naraz
              mówiłyby to samo dwa razy. Znika po ręcznym wpisaniu numeru. */}
          {titleCheck && title.trim().length === 0 ? (
            <span className="text-xs text-destructive">
              Sprawdź numer zamówienia
            </span>
          ) : (
            title.trim().length === 0 && (
              <span className="text-xs text-destructive">
                Numer zamówienia jest wymagany.
              </span>
            )
          )}
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-sm font-medium">Data od</span>
            <input
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              onBlur={(e) => setStartDate(normalizeDateInput(e.target.value))}
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Data do</span>
            <input
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              onBlur={(e) => setEndDate(normalizeDateInput(e.target.value))}
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
            />
          </label>
        </div>

        {canManageFinance && (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-sm font-medium">Stawka kosztowa</span>
              <input
                value={rateCost}
                inputMode="decimal"
                onChange={(e) => setRateCost(sanitizeDecimalInput(e.target.value))}
                className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
                placeholder="np. 12000"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Stawka przychodowa</span>
              <input
                value={rateRevenue}
                inputMode="decimal"
                onChange={(e) => setRateRevenue(sanitizeDecimalInput(e.target.value))}
                className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
                placeholder="np. 18000"
              />
              {/* Bank Pocztowy: dokument podaje stawkę za 1 MD (8 h) — pole
                  wyżej ma już przeliczoną stawkę godzinową (edytowalną),
                  a oryginał z dokumentu zostaje widoczny obok. */}
              {rateMdOriginal !== null && (
                <span className="text-xs text-muted-foreground mt-0.5 block">
                  Z dokumentu: {rateMdOriginal} zł/MD → przeliczono na stawkę
                  godzinową (÷ 8, w górę do 2 miejsc)
                </span>
              )}
            </label>
          </div>
        )}

        {ezdrowie && (
          <label className="block">
            <span className="text-sm font-medium">Część umowy</span>
            <select
              value={projectPart}
              onChange={(e) => setProjectPart(e.target.value)}
              className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
            >
              <option value="">— uzupełnij —</option>
              {PROJECT_PARTS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block">
          <span className="text-sm font-medium">Opis</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-background"
          />
        </label>

        <div className="space-y-2">
          <span className="text-sm font-medium">PDF zamówienia</span>

          {hasExistingFile && docRef && (
            <div className="flex items-center gap-2 text-sm rounded-md border border-border bg-muted/40 px-3 py-2">
              <span className="truncate flex-1">{docRef.filename}</span>
              <button
                type="button"
                title="Otwórz"
                disabled={busyFile}
                onClick={() =>
                  withBusy(
                    () => openOrderDocument(docRef),
                    "Nie udało się otworzyć pliku.",
                  )
                }
                className="p-1 rounded hover:bg-muted text-muted-foreground disabled:opacity-50"
              >
                <ExternalLink className="w-4 h-4" />
              </button>
              <button
                type="button"
                title="Pobierz"
                disabled={busyFile}
                onClick={() =>
                  withBusy(
                    () => downloadOrderDocument(docRef),
                    "Nie udało się pobrać pliku.",
                  )
                }
                className="p-1 rounded hover:bg-muted text-muted-foreground disabled:opacity-50"
              >
                {busyFile ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
              </button>
              <button
                type="button"
                title="Usuń"
                aria-label="Usuń plik PDF zamówienia"
                disabled={busyFile}
                onClick={handleDeleteExistingFile}
                className="p-1 rounded hover:bg-destructive/10 text-destructive disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )}

          <FileDropZone
            inputId="order-po-input"
            file={file}
            onPick={pickFile}
            onError={setFileError}
            error={fileError || null}
            accept=".pdf"
            maxBytes={MAX_UPLOAD_BYTES}
            label="Zamień plik PDF"
            hint="PDF · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
          />
          <button
            type="button"
            onClick={handleExtract}
            disabled={!file || extracting}
            className="inline-flex items-center gap-1.5 rounded-md bg-orange-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <FileSearch className="w-4 h-4" aria-hidden />
            {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
          </button>
        </div>
      </div>
    </AppModal>
  );
}
