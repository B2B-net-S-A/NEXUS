import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const OLD = "a".repeat(40);
const NEW = "b".repeat(40);

type Config = { method?: string };
const mocks = vi.hoisted(() => ({
  pathname: "/jobs",
  buildSha: "",
  user: { id: 1 } as { id: number } | null,
  fetchDeployedSha: vi.fn(async (): Promise<string | null> => null),
  reloadOnceForVersion: vi.fn((_sha: string): boolean => true),
  reload: vi.fn(),
  onRequest: null as null | ((config: Config) => Config),
  onResponse: null as null | ((response: { config: Config }) => unknown),
}));

vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } | null }) => unknown) =>
    selector({ user: mocks.user }),
}));
vi.mock("@/lib/api", () => {
  const api = {
    interceptors: {
      request: {
        use: (fn: (config: Config) => Config) => {
          mocks.onRequest = fn;
          return 1;
        },
        eject: () => {
          mocks.onRequest = null;
        },
      },
      response: {
        use: (fn: (response: { config: Config }) => unknown) => {
          mocks.onResponse = fn;
          return 1;
        },
        eject: () => {
          mocks.onResponse = null;
        },
      },
    },
  };
  return { api, default: api };
});
vi.mock("@/lib/app-version", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/app-version")>();
  return {
    ...actual,
    get BUILD_SHA() {
      return mocks.buildSha;
    },
    fetchDeployedSha: () => mocks.fetchDeployedSha(),
    reloadOnceForVersion: (sha: string) => mocks.reloadOnceForVersion(sha),
    reloadNow: () => mocks.reload(),
  };
});

import {
  AppVersionGuard,
  VERSION_CHECK_EVERY_MS,
  VERSION_IDLE_BEFORE_RELOAD_MS,
} from "@/components/AppVersionGuard";

const notice = () => screen.queryByRole("status", { name: "Nowa wersja NEXUSA" });
const flush = () => act(async () => void (await Promise.resolve()));
const pass = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
const setHidden = (hidden: boolean) =>
  act(async () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
  });

/** Karta otwarta na aktualnej wersji; potem na serwer wchodzi nowa. */
async function openThenDeploy() {
  const view = render(
    <>
      <AppVersionGuard />
      <textarea aria-label="Notatka" />
    </>,
  );
  await flush();
  mocks.fetchDeployedSha.mockResolvedValue(NEW);
  return view;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  document.body.removeAttribute("data-scroll-locked");
  mocks.pathname = "/jobs";
  mocks.buildSha = OLD;
  mocks.user = { id: 1 };
  mocks.fetchDeployedSha.mockResolvedValue(OLD);
  mocks.reloadOnceForVersion.mockReturnValue(true);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AppVersionGuard — nowa wersja wczytuje się sama", () => {
  it("ta sama wersja: nic nie pokazuje i niczego nie przeładowuje", async () => {
    render(<AppVersionGuard />);
    await flush();
    await pass(VERSION_CHECK_EVERY_MS * 3);
    expect(mocks.fetchDeployedSha.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(notice()).toBeNull();
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
  });

  it("stara wersja zaraz po otwarciu karty: odświeża się od razu", async () => {
    mocks.fetchDeployedSha.mockResolvedValue(NEW);
    render(<AppVersionGuard />);
    await flush();
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
    expect(notice()).toBeNull();
  });

  it("wdrożenie, gdy ktoś tylko ogląda stronę: po minucie bez ruchu karta odświeża się sama, bez komunikatu", async () => {
    await openThenDeploy();
    await pass(VERSION_CHECK_EVERY_MS - 5_000);
    fireEvent.pointerDown(window); // kliknięcie w kartę na Tablicy — nic do stracenia
    fireEvent.pointerMove(window);
    await pass(10_000);
    // Wersja wykryta, ale ktoś był aktywny przed chwilą — czekamy na spokój.
    expect(mocks.fetchDeployedSha.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    expect(notice()).toBeNull();
    await pass(VERSION_IDLE_BEFORE_RELOAD_MS);
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("karta w tle odświeża się sama", async () => {
    await openThenDeploy();
    fireEvent.pointerDown(window);
    await setHidden(true);
    await pass(VERSION_CHECK_EVERY_MS + 1_000);
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("powrót do karty po wdrożeniu: sprawdza wersję i odświeża od razu", async () => {
    await openThenDeploy();
    await setHidden(true);
    mocks.fetchDeployedSha.mockResolvedValue(OLD); // w tle jeszcze stara wersja serwera
    await pass(VERSION_CHECK_EVERY_MS * 2);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    // Przeglądarka uśpiła kartę w tle; wdrożenie przyszło, zanim ktoś do niej wrócił.
    mocks.fetchDeployedSha.mockResolvedValue(NEW);
    await setHidden(false);
    await flush();
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
    expect(notice()).toBeNull();
  });

  it("wpisany tekst blokuje przeładowanie — także w tle; komunikat mówi, co dalej", async () => {
    await openThenDeploy();
    const note = screen.getByLabelText("Notatka");
    fireEvent.keyDown(note, { key: "a" });
    fireEvent.input(note, { target: { value: "Rozmowa: stawka 150" } });
    await pass(VERSION_CHECK_EVERY_MS + VERSION_IDLE_BEFORE_RELOAD_MS * 3);
    await setHidden(true);
    await pass(VERSION_CHECK_EVERY_MS);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    expect(notice()).not.toBeNull();
    expect(notice()).toHaveTextContent("Wczyta się sama, gdy przejdziesz na inną stronę");
    fireEvent.click(screen.getByRole("button", { name: "Odśwież teraz" }));
    expect(mocks.reload).toHaveBeenCalledTimes(1);
  });

  it("tekst wprowadzony bez klawiatury (dyktowanie, podpowiedź systemu) też blokuje przeładowanie", async () => {
    await openThenDeploy();
    // `beforeinput` wysyła tylko człowiek — zmiana wartości z kodu go nie daje.
    fireEvent(screen.getByLabelText("Notatka"), new Event("beforeinput", { bubbles: true }));
    await pass(VERSION_CHECK_EVERY_MS + VERSION_IDLE_BEFORE_RELOAD_MS * 2);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    expect(notice()).not.toBeNull();
  });

  it("po wpisaniu tekstu przejście na inną stronę odświeża kartę", async () => {
    const view = await openThenDeploy();
    const note = screen.getByLabelText("Notatka");
    fireEvent.keyDown(note, { key: "a" });
    fireEvent.input(note, { target: { value: "x" } });
    await pass(VERSION_CHECK_EVERY_MS + 1_000);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    mocks.pathname = "/candidates";
    await act(async () => {
      view.rerender(
        <>
          <AppVersionGuard />
          <textarea aria-label="Notatka" />
        </>,
      );
      await Promise.resolve();
    });
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("zmiana pola bez udziału człowieka (dane doczytane z serwera) nie blokuje przeładowania", async () => {
    await openThenDeploy();
    fireEvent.change(screen.getByLabelText("Notatka"), { target: { value: "z serwera" } });
    await pass(VERSION_CHECK_EVERY_MS + VERSION_IDLE_BEFORE_RELOAD_MS + 1_000);
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("otwarte okno (formularz w dialogu) blokuje przeładowanie", async () => {
    await openThenDeploy();
    document.body.setAttribute("data-scroll-locked", "1");
    await pass(VERSION_CHECK_EVERY_MS + VERSION_IDLE_BEFORE_RELOAD_MS * 2);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    document.body.removeAttribute("data-scroll-locked");
    await pass(15_000);
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("trwający zapis (żądanie inne niż GET) blokuje przeładowanie do odpowiedzi serwera", async () => {
    await openThenDeploy();
    const config = { method: "post" };
    mocks.onRequest!(config);
    await pass(VERSION_CHECK_EVERY_MS + VERSION_IDLE_BEFORE_RELOAD_MS * 2);
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    mocks.onResponse!({ config });
    await pass(15_000);
    expect(mocks.reloadOnceForVersion).toHaveBeenCalledWith(NEW);
  });

  it("gdy przeładowanie dla tej wersji już było, zostaje komunikat — bez pętli", async () => {
    mocks.fetchDeployedSha.mockResolvedValue(NEW);
    mocks.reloadOnceForVersion.mockReturnValue(false);
    render(<AppVersionGuard />);
    await flush();
    await pass(15_000);
    expect(notice()).not.toBeNull();
  });

  it("osoba z zewnątrz (zgłoszenie z linku, podpis, strona kariery) nie dostaje komunikatu o NEXUSIE", async () => {
    mocks.user = null;
    mocks.pathname = "/apply/abc";
    mocks.fetchDeployedSha.mockResolvedValue(NEW);
    render(<AppVersionGuard />);
    await flush();
    await pass(VERSION_CHECK_EVERY_MS * 2);
    expect(mocks.fetchDeployedSha).not.toHaveBeenCalled();
    expect(mocks.reloadOnceForVersion).not.toHaveBeenCalled();
    expect(notice()).toBeNull();
  });

  it("paczka bez SHA (lokalnie) i podglądy `/preview/*` nie pytają serwera", async () => {
    mocks.buildSha = "";
    const local = render(<AppVersionGuard />);
    await flush();
    local.unmount();
    mocks.buildSha = OLD;
    mocks.pathname = "/preview/new-job";
    render(<AppVersionGuard />);
    await flush();
    await pass(VERSION_CHECK_EVERY_MS * 2);
    expect(mocks.fetchDeployedSha).not.toHaveBeenCalled();
  });
});
