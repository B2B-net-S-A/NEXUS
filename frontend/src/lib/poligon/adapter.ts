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

export const poligonAdapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
  const store = await poligonStore();
  const result = store.handle({
    method: config.method ?? "get",
    url: config.url ?? "",
    params: config.params as Record<string, unknown> | undefined,
    body: parseBody(config.data),
  });
  if (result === "network") {
    return getAdapter(["xhr", "fetch"])(config);
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
