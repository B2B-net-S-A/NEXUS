"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  BUILD_SHA,
  fetchDeployedSha,
  isBuildSha,
  isOtherBuild,
  reloadNow,
  reloadOnceForVersion,
} from "@/lib/app-version";
import { transfersInFlight } from "@/lib/transfers-in-flight";
import { useAuthStore } from "@/store/auth";

// Dawny adres `trackTransfer` — moduł żyje w `lib`, żeby `lib/*` nie importował komponentu.
export { trackTransfer } from "@/lib/transfers-in-flight";

/** Jak często karta pyta serwer o wersję. */
export const VERSION_CHECK_EVERY_MS = 60_000;
/** Ile spokoju (bez myszy, klawiatury, przewijania) wystarcza, żeby przeładować widoczną kartę. */
export const VERSION_IDLE_BEFORE_RELOAD_MS = 60_000;
/** Jak często stara karta sprawdza, czy to już bezpieczny moment. */
const SAFE_MOMENT_TICK_MS = 10_000;
/** Zmiana pola liczy się jako praca człowieka tylko tuż po jego geście. */
const GESTURE_WINDOW_MS = 2_000;

const GESTURES = ["pointerdown", "keydown", "touchstart", "paste", "drop"] as const;
const MOVEMENT = ["pointermove", "wheel", "scroll"] as const;
const EDITS = ["input", "change"] as const;

/** Otwarte okno modalne: Radix blokuje przewijanie strony, własne okna mają `aria-modal`. */
function modalOpen(): boolean {
  return (
    document.body.hasAttribute("data-scroll-locked") ||
    document.querySelector('[aria-modal="true"], [role="alertdialog"]') != null
  );
}

/**
 * Pilnuje, żeby otwarta karta nie została na starej wersji frontu
 * (`lib/app-version.ts`) — bez udziału człowieka.
 *
 * Nową wersję karta wczytuje sama w momencie, w którym nie ma czego stracić:
 * zaraz po otwarciu, przy przejściu na inną stronę, w tle, po powrocie do
 * karty i po minucie bez ruchu. Nie przeładowuje się tylko wtedy, gdy ktoś na
 * tej stronie coś wpisał albo zmienił, ma otwarte okno albo trwa zapis —
 * przeładowanie skasowałoby pracę. Wtedy czeka na przejście na inną stronę,
 * a mały komunikat mówi, że nic nie trzeba robić.
 */
export function AppVersionGuard() {
  const pathname = usePathname();
  // Tylko zalogowani: strony dla osób z zewnątrz (zgłoszenie z linku, podpis,
  // kariera) żyją w tej samej aplikacji, a komunikat o NEXUSIE nie jest dla nich.
  const loggedIn = useAuthStore((s) => s.user != null);
  const inert =
    !isBuildSha(BUILD_SHA) || !loggedIn || (pathname ?? "").startsWith("/preview");
  // Stara karta, której nie wolno teraz przeładować — do komunikatu.
  const [waitingFor, setWaitingFor] = useState<string | null>(null);
  // Przeładowanie dla tej wersji już było (albo nie da się go zlecić) — sama
  // się nie wczyta, komunikat musi poprosić o „Odśwież teraz”.
  const [manualOnly, setManualOnly] = useState(false);
  const [later, setLater] = useState<string | null>(null);

  const deployed = useRef<string | null>(null);
  // Wersja, dla której przeładowanie już było i nic nie dało (zostaje komunikat).
  const stuck = useRef<string | null>(null);
  // Od otwarcia strony / zmiany adresu: czy ktoś jej dotknął i czy coś zmienił.
  const touched = useRef(false);
  const edited = useRef(false);
  const lastGesture = useRef(0);
  const lastMovement = useRef(Date.now());
  const pendingWrites = useRef(0);
  const lastCheck = useRef(0);
  const lastPath = useRef(pathname);

  /** Przeładowanie, jeśli nic nie przepadnie; inaczej komunikat. */
  const settle = useCallback((moment: "fresh" | "navigated" | "quiet") => {
    const sha = deployed.current;
    if (!sha) return;
    const writing = pendingWrites.current > 0 || transfersInFlight() > 0;
    const busy = edited.current || modalOpen() || writing;
    const safe =
      moment === "navigated"
        ? !writing
        : moment === "fresh"
          ? !touched.current
          : !busy &&
            (document.hidden ||
              Date.now() - lastMovement.current >= VERSION_IDLE_BEFORE_RELOAD_MS);
    if (safe) {
      if (reloadOnceForVersion(sha)) return;
      stuck.current = sha;
    }
    // Aktywna osoba na czystej stronie: komunikat niepotrzebny, karta
    // przeładuje się przy pierwszej chwili spokoju.
    setManualOnly(stuck.current === sha);
    setWaitingFor(busy || stuck.current === sha ? sha : null);
  }, []);

  const check = useCallback(
    async (moment: "fresh" | "quiet") => {
      lastCheck.current = Date.now();
      const sha = await fetchDeployedSha();
      if (isOtherBuild(BUILD_SHA, sha)) deployed.current = sha;
      settle(moment);
    },
    [settle],
  );

  useEffect(() => {
    if (inert) return;
    const onGesture = () => {
      touched.current = true;
      lastGesture.current = Date.now();
      lastMovement.current = lastGesture.current;
    };
    const onMovement = () => {
      lastMovement.current = Date.now();
    };
    // Pola potrafią zmienić się same (dane doczytane z serwera) — pracą
    // człowieka jest zmiana tuż po kliknięciu albo naciśnięciu klawisza.
    const onEdit = () => {
      if (Date.now() - lastGesture.current <= GESTURE_WINDOW_MS) edited.current = true;
    };
    // Tekst wprowadzony bez klawiatury (dyktowanie, podpowiedź systemu):
    // `beforeinput` przychodzi tylko od człowieka, nigdy ze zmiany wartości w kodzie.
    const onTyped = () => {
      edited.current = true;
    };
    const onVisibility = () => {
      if (document.hidden) settle("quiet");
      else void check("quiet");
    };
    const options = { capture: true, passive: true };
    GESTURES.forEach((name) => window.addEventListener(name, onGesture, options));
    MOVEMENT.forEach((name) => window.addEventListener(name, onMovement, options));
    EDITS.forEach((name) => window.addEventListener(name, onEdit, options));
    window.addEventListener("beforeinput", onTyped, options);
    document.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(() => {
      if (Date.now() - lastCheck.current >= VERSION_CHECK_EVERY_MS) void check("quiet");
      else settle("quiet");
    }, SAFE_MOMENT_TICK_MS);
    void check("fresh");
    return () => {
      GESTURES.forEach((name) => window.removeEventListener(name, onGesture, options));
      MOVEMENT.forEach((name) => window.removeEventListener(name, onMovement, options));
      EDITS.forEach((name) => window.removeEventListener(name, onEdit, options));
      window.removeEventListener("beforeinput", onTyped, options);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(timer);
    };
  }, [inert, check, settle]);

  // Zapis w toku: przeładowanie przerwałoby żądanie (np. generowanie CV).
  useEffect(() => {
    if (inert) return;
    const isWrite = (config?: { method?: string }) =>
      (config?.method ?? "get").toLowerCase() !== "get";
    const done = (config?: { method?: string }) => {
      if (isWrite(config)) pendingWrites.current = Math.max(0, pendingWrites.current - 1);
    };
    const request = api.interceptors.request.use((config) => {
      if (isWrite(config)) pendingWrites.current += 1;
      return config;
    });
    const response = api.interceptors.response.use(
      (result) => {
        done(result.config);
        return result;
      },
      (error) => {
        done((error as { config?: { method?: string } } | null)?.config);
        return Promise.reject(error);
      },
    );
    return () => {
      api.interceptors.request.eject(request);
      api.interceptors.response.eject(response);
      pendingWrites.current = 0;
    };
  }, [inert]);

  // Zmiana strony: poprzednia i tak znika, więc to dobry moment na nową wersję.
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    if (inert) return;
    touched.current = false;
    edited.current = false;
    if (deployed.current) settle("navigated");
    else void check("fresh");
  }, [pathname, inert, check, settle]);

  if (inert || !waitingFor || later === waitingFor) return null;
  return (
    <div
      role="status"
      aria-label="Nowa wersja NEXUSA"
      className="fixed inset-x-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-[9998] mx-auto flex w-fit max-w-full flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border bg-card px-4 py-2.5 text-sm text-foreground shadow-lg"
    >
      <span className="min-w-0">
        {manualOnly
          ? "Wyszła nowa wersja NEXUSA, ale ta karta nie wczytała jej sama — kliknij „Odśwież teraz”."
          : "Wyszła nowa wersja NEXUSA. Wczyta się sama, gdy przejdziesz na inną stronę."}
      </span>
      <span className="flex items-center gap-2">
        <Button type="button" size="sm" onClick={reloadNow}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Odśwież teraz
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setLater(waitingFor)}>
          Ukryj
        </Button>
      </span>
    </div>
  );
}
