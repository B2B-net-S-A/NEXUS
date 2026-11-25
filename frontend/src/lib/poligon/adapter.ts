// Adapter axiosa w trybie poligonu: pyta `store.ts`, a tylko odczyty spoza
// rekrutacji ćwiczebnej puszcza do prawdziwego API. Zestaw danych (ok. 250 KB)
// ładuje się dopiero przy pierwszym żądaniu w trybie poligonu, więc zwykła
// praca go nie pobiera.

import {
  AxiosError,
  getAdapter,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";

import { canSetPreContractStop } from "@/lib/pre-contract-stop";

import { viewerFrom, withPracticeClient, type PoligonViewer } from "./amounts";
import { createPoligonStore, type PoligonAction, type PoligonDataset, type PoligonStore } from "./store";

let storePromise: Promise<PoligonStore> | null = null;
const pending = new Set<(action: PoligonAction) => void>();

export function poligonStore(): Promise<PoligonStore> {
  storePromise ??= import("./dataset.json").then((mod) => {
    const store = createPoligonStore(mod.default as unknown as PoligonDataset);
    // Brak odpowiedzi w zestawie = ekran zmienił się od nagrania. Ślad dla
    // nocnego Testera: przebuduj zestaw (`backend/scripts/build_poligon_dataset.py`).
    store.subscribe((action) => {
      if (action.type === "missing") console.warn("[poligon] brak odpowiedzi w zestawie:", action.key);
    });
    for (const fn of pending) store.subscribe(fn);
    pending.clear();
    return store;
  });
  return storePromise;
}

/** Ćwiczenia słuchają zdarzeń poligonu (ruch karty, notatka, odmowa zapisu). */
export function onPoligonAction(fn: (action: PoligonAction) => void): () => void {
  let unsubscribe: (() => void) | null = null;
  let cancelled = false;
  pending.add(fn);
  void poligonStore().then((store) => {
    pending.delete(fn);
    if (!cancelled) unsubscribe = store.subscribe(fn);
  });
  return () => {
    cancelled = true;
    pending.delete(fn);
    unsubscribe?.();
  };
}

function parseBody(data: unknown): unknown {
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}

/** Zalogowana osoba z `nexus_user` (`store/auth.ts`). */
function storedUser(): Record<string, unknown> | null {
  try {
    const raw = window.localStorage.getItem("nexus_user");
    const user = raw ? (JSON.parse(raw) as unknown) : null;
    return user && typeof user === "object" ? (user as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Jej są zapisane wyszukiwania i listy na poligonie. */
function viewerId(): number | null {
  const id = storedUser()?.id;
  return typeof id === "number" ? id : null;
}

/** Co osoba widzi z kwot klienta ćwiczebnego — z jej uprawnień (`amounts.ts`). */
function viewer(): PoligonViewer {
  return viewerFrom(storedUser());
}

/**
 * Podgląd „Nowego CV” na poligonie (lekcja „Nowe CV”, 23.11.2026). Poligon nie
 * renderuje plików, więc PDF nowego układu to statyczny render serwera
 * fikcyjnego CV z `cv-fiction.ts` (bez nazwiska w tytule — pasuje do każdej
 * osoby ćwiczebnej), z nagłówkami jak z trasy. Plik przegenerowuje
 * `backend/scripts/poligon_new_cv_pdf.py`. Pobranie (`intent=download`)
 * i podgląd klasycznego Worda zostają odmową (`null`).
 */
export const POLIGON_NEW_CV_PDF = "/poligon/nowe-cv.pdf";
const POLIGON_NEW_CV_HEADERS: Record<string, string> = {
  "Content-Disposition": "inline; filename=\"SZKIC_CV.pdf\"",
  "X-CV-Layout": "new",
  "X-CV-Page1-Fits": "1",
  "X-CV-Page1-Font": "11",
  "X-CV-Unmapped-Sections": "0",
};
const PREVIEW_PDF = /\/api\/candidates\/stages\/(\d+)\/cv\/branded\/preview-pdf(\?.*)?$/;

export async function poligonFile(
  path: string,
): Promise<{ blob: Blob; filename: string | null; headers: Headers } | null> {
  const match = path.match(PREVIEW_PDF);
  if (!match || new URLSearchParams(match[2] ?? "").get("intent") === "download") return null;
  const store = await poligonStore();
  if (store.cvLayoutOf(Number(match[1])) !== "new") return null;
  const res = await fetch(POLIGON_NEW_CV_PDF);
  if (!res.ok) return null;
  return { blob: await res.blob(), filename: "SZKIC_CV.pdf", headers: new Headers(POLIGON_NEW_CV_HEADERS) };
}

const AUTH_ME = /^(https?:\/\/[^/]+)?\/api\/auth\/me(\?|$)/;

export const poligonAdapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
  const store = await poligonStore();
  const result = store.handle({
    method: config.method ?? "get",
    url: config.url ?? "",
    params: config.params as Record<string, unknown> | undefined,
    body: parseBody(config.data),
    viewerId: viewerId(),
    viewer: viewer(),
    // Lustro `pre_contract_stop.can_set_stop`: „Wyjątek dla tej osoby” tylko DL, HoR i admin.
    canSetPreContractStop: canSetPreContractStop(storedUser() as Parameters<typeof canSetPreContractStop>[0]),
  });
  if (result === "network") {
    const response = await getAdapter(["xhr", "fetch"])(config);
    // Klient ćwiczebny w portfelu Delivery Leada, który ćwiczy (`withPracticeClient`).
    if (AUTH_ME.test(config.url ?? "") && response.status === 200) {
      const data = parseBody(response.data);
      const me = withPracticeClient(data, store.meta.client_id);
      if (me !== data) response.data = typeof response.data === "string" ? JSON.stringify(me) : me;
    }
    return response;
  }
  const response: AxiosResponse = {
    data: result.data,
    status: result.status,
    statusText: String(result.status),
    headers: {},
    config,
    request: { poligon: true },
  };
  if (result.status >= 400) {
    throw new AxiosError(
      `Request failed with status code ${result.status}`,
      result.status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
      config,
      response.request,
      response,
    );
  }
  return response;
};
