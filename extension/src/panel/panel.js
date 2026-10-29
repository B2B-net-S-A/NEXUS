// Panel boczny: stan, wybór ekranu i reakcja na zmianę karty.
// Strona LinkedIna jest czytana tylko przy otwarciu panelu, po zmianie adresu
// aktywnej karty (jedna strona naraz) albo po kliknięciu „Sprawdź tę stronę”.

import { createApi, ERROR_KINDS } from "../api.js";
import { connectUrl, SERVERS } from "../config.js";
import { readTab } from "../page.js";
import { detectPage, PAGE_KINDS } from "../readers/index.js";
import { clearConnection, getConnection, getServerId, onConnectionChanged, setServerId } from "../storage.js";
import { chooseScreen, firstName, initialsOf, SCREENS, screenForError, updateNotice, usageLabel, withLocalContact } from "../view/logic.js";
import { apiErrorText } from "./errors.js";
import { initialAddState, renderAdd } from "./screen-add.js";
import { applyBatch, initialListState, renderList } from "./screen-list.js";
import {
  renderAmbiguous,
  renderConnect,
  renderError,
  renderLimit,
  renderLoading,
  renderNotRead,
  renderSettings,
  renderUnsupported,
} from "./screen-misc.js";
import { initialPersonState, renderPerson } from "./screen-person.js";
import { externalLink, h, linkButton } from "./ui.js";

const CACHE_TTL_MS = 10 * 60 * 1000;
const READ_ATTEMPTS = 3;
const READ_RETRY_MS = 1200;
const NAVIGATION_SETTLE_MS = 700;

const state = {
  windowId: null,
  serverId: "production",
  connection: null,
  me: null,
  screen: SCREENS.LOADING,
  error: null,
  showSettings: false,
  menuOpen: false,
  connectMessage: null,
  connectPending: false,
  tab: null,
  page: null,
  read: null,
  lookup: null,
  add: null,
  person: null,
  list: null,
};

// Wynik lookup per strona — powrót na tę samą kartę nie zużywa odczytu.
const cache = new Map();
let generation = 0;
let navTimer = null;

const api = createApi({
  getConnection,
  onKeyInvalid: () => {
    state.connectMessage = "Połączenie z NEXUSEM wygasło albo zostało odłączone. Połącz wtyczkę ponownie.";
    clearConnection();
  },
});

const view = document.getElementById("view");
const userBox = document.getElementById("user");
const menu = document.getElementById("menu");
const updateBox = document.getElementById("update");

const ctx = {
  state,
  api,
  render,
  onWrite: () => cache.delete(state.page?.key),
  addLocalContact: (channel, note) => {
    state.lookup = withLocalContact(state.lookup, { channel, note, userName: state.me?.user?.name });
    render();
  },
  refreshLookup: () => {
    cache.delete(state.page?.key);
    handleActiveTab({ force: true });
  },
  retry: () => (state.connection && !state.me ? init() : handleActiveTab({ force: true })),
  forceAdd: () => {
    state.screen = SCREENS.ADD;
    render();
  },
  checkList,
  startConnect,
  openSettings: () => {
    state.showSettings = true;
    state.menuOpen = false;
    render();
  },
  closeSettings: () => {
    state.showSettings = false;
    render();
  },
  saveServer,
};

// ── Rysowanie ───────────────────────────────────────────────────────────────

const SCREEN_RENDERERS = {
  [SCREENS.CONNECT]: renderConnect,
  [SCREENS.LOADING]: renderLoading,
  [SCREENS.ERROR]: renderError,
  [SCREENS.LIMIT]: renderLimit,
  [SCREENS.UNSUPPORTED]: renderUnsupported,
  [SCREENS.NOT_READ]: renderNotRead,
  [SCREENS.ADD]: renderAdd,
  [SCREENS.PERSON]: renderPerson,
  [SCREENS.AMBIGUOUS]: renderAmbiguous,
  [SCREENS.LIST]: renderList,
};

function renderUpdate() {
  const manifest = chrome.runtime.getManifest();
  const notice = state.me ? updateNotice(state.me, manifest.version, state.connection, manifest.update_url) : null;
  updateBox.hidden = !notice;
  updateBox.replaceChildren();
  if (notice) updateBox.append(`Jest nowa wersja wtyczki (${notice.version}). `, externalLink("Pobierz z NEXUSA ↗", notice.url));
}

function renderHeader() {
  renderUpdate();
  userBox.replaceChildren();
  if (state.me?.user) {
    userBox.append(
      h(
        "button",
        {
          type: "button",
          class: "user",
          "aria-haspopup": "menu",
          "aria-expanded": String(state.menuOpen),
          onClick: (e) => {
            // Przerysowanie usuwa ten przycisk z DOM — bez tego klik „poza menu” zamknąłby je od razu.
            e.stopPropagation();
            state.menuOpen = !state.menuOpen;
            renderHeader();
          },
        },
        h("span", { class: "avatar", "aria-hidden": "true" }, initialsOf(state.me.user)),
        h("span", { class: "user__name" }, firstName(state.me.user.name)),
        h("span", { class: "user__chevron", "aria-hidden": "true" }, "▾"),
      ),
    );
  }
  menu.hidden = !state.menuOpen;
  menu.replaceChildren();
  if (state.menuOpen) {
    const usage = usageLabel(state.me?.usage);
    menu.append(
      state.me?.user?.name ? h("p", { class: "menu__who" }, state.me.user.name) : null,
      usage ? h("p", { class: "menu__usage" }, usage) : null,
      h("div", { class: "menu__row" }, h("span", { class: "muted" }, "Serwer:"), linkButton(SERVERS[state.serverId].label, ctx.openSettings)),
      h("div", { class: "menu__row" }, linkButton("Odłącz", disconnect, "link--danger")),
    );
  }
}

function render() {
  renderHeader();
  const scroll = view.scrollTop;
  const renderer = state.showSettings ? renderSettings : SCREEN_RENDERERS[state.screen] || renderLoading;
  try {
    view.replaceChildren(renderer(ctx));
  } catch (err) {
    console.error("NEXUS: błąd rysowania ekranu", state.screen, err);
    state.error = { message: "Panel nie potrafił pokazać tej osoby. Spróbuj ponownie." };
    view.replaceChildren(renderError(ctx));
  }
  view.scrollTop = scroll;
}

function show(screen) {
  state.screen = screen;
  render();
}

function showError(err) {
  const s = screenForError(err);
  if (s.screen === SCREENS.CONNECT) {
    state.me = null;
    show(SCREENS.CONNECT);
    return;
  }
  if (s.screen === SCREENS.ERROR) state.error = s;
  show(s.screen);
}

function updateUsage(usage) {
  if (usage && state.me) state.me = { ...state.me, usage: { ...state.me.usage, ...usage } };
}

// ── Połączenie ──────────────────────────────────────────────────────────────

async function init() {
  generation += 1;
  state.serverId = await getServerId();
  state.connection = await getConnection();
  if (!state.connection) {
    state.me = null;
    show(SCREENS.CONNECT);
    return;
  }
  show(SCREENS.LOADING);
  try {
    state.me = await api.me();
  } catch (err) {
    showError(err);
    return;
  }
  await handleActiveTab({ force: true });
}

function startConnect() {
  const front = SERVERS[state.serverId].frontUrl;
  chrome.tabs.create({ url: connectUrl(front, chrome.runtime.id, chrome.runtime.getManifest().version) });
  state.connectPending = true;
  state.connectMessage = null;
  render();
}

async function disconnect() {
  state.menuOpen = false;
  state.connectMessage = "Wtyczka odłączona. Klucz usunięty z tej przeglądarki.";
  await clearConnection();
}

async function saveServer(id) {
  state.showSettings = false;
  if (id !== state.serverId) {
    await setServerId(id);
    state.serverId = id;
    if (state.connection) {
      state.connectMessage = `Serwer zmieniony na: ${SERVERS[id].label}. Połącz wtyczkę ponownie.`;
      await clearConnection(); // reszta w onConnectionChanged
      return;
    }
  }
  render();
}

// ── Karta i odczyt ──────────────────────────────────────────────────────────

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ? { id: tab.id, url: tab.url } : null;
}

function applyLookup(read, lookup) {
  state.read = read;
  state.lookup = lookup;
  state.add = initialAddState(read);
  state.person = initialPersonState();
  show(chooseScreen(lookup).screen);
}

async function handleActiveTab({ force = false } = {}) {
  const gen = ++generation;
  const tab = await activeTab();
  if (gen !== generation) return;
  const page = detectPage(tab?.url);
  const samePage = state.page?.key && page.key === state.page.key && state.tab?.id === tab?.id;
  if (!force && samePage && ![SCREENS.ERROR, SCREENS.NOT_READ].includes(state.screen)) return;
  state.tab = tab;
  state.page = page;
  state.menuOpen = false;
  if (!state.connection) return show(SCREENS.CONNECT);

  if (page.kind === PAGE_KINDS.UNSUPPORTED) return show(SCREENS.UNSUPPORTED);
  if (page.kind === PAGE_KINDS.SEARCH_RESULTS) {
    if (!samePage || !state.list) state.list = initialListState();
    return show(SCREENS.LIST);
  }

  const cached = cache.get(page.key);
  if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return applyLookup(cached.read, cached.lookup);

  show(SCREENS.LOADING);
  let read = null;
  for (let attempt = 1; attempt <= READ_ATTEMPTS; attempt += 1) {
    try {
      read = await readTab(tab.id, tab.url);
    } catch (err) {
      console.warn("NEXUS: odczyt karty nie powiódł się", err);
      read = null;
    }
    if (gen !== generation) return;
    if (read?.profile?.full_name) break;
    if (attempt < READ_ATTEMPTS) await sleep(READ_RETRY_MS);
    if (gen !== generation) return;
  }
  if (!read) {
    state.error = { message: "Nie udało się odczytać strony LinkedIna. Odśwież kartę i spróbuj ponownie.", retryable: true };
    return show(SCREENS.ERROR);
  }
  if (!read.profile || (!read.profile.full_name && !read.profile.public_url)) return show(SCREENS.NOT_READ);

  try {
    const lookup = await api.lookup(read.profile);
    if (gen !== generation) return;
    updateUsage(lookup.usage);
    cache.set(page.key, { read, lookup, at: Date.now() });
    applyLookup(read, lookup);
  } catch (err) {
    if (gen !== generation) return;
    showError(err);
  }
}

async function checkList() {
  const ls = state.list;
  ls.busy = true;
  ls.error = null;
  render();
  try {
    const read = await readTab(state.tab.id, state.tab.url);
    if (read.kind !== PAGE_KINDS.SEARCH_RESULTS) {
      ls.error = "Ta karta nie pokazuje już listy osób.";
      return;
    }
    if (!read.people.length) {
      ls.error = "Nie widzę osób na tej stronie. Przewiń listę, żeby się wczytała, i spróbuj ponownie.";
      return;
    }
    const people = read.people.map((p) => ({ full_name: p.full_name, public_url: p.public_url, headline: p.headline, current_company: p.current_company }));
    const batch = await api.lookupBatch(people);
    updateUsage(batch.usage);
    applyBatch(ls, read, batch);
  } catch (err) {
    if (err?.kind === ERROR_KINDS.DAILY_LIMIT) {
      showError(err);
      return;
    }
    if (err?.kind === ERROR_KINDS.KEY_INVALID) return;
    ls.error = err?.name === "ApiError" ? apiErrorText(err) : "Nie udało się odczytać strony LinkedIna. Odśwież kartę i spróbuj ponownie.";
  } finally {
    ls.busy = false;
    if (state.screen === SCREENS.LIST) render();
  }
}

function scheduleTabCheck(delay) {
  clearTimeout(navTimer);
  navTimer = setTimeout(() => handleActiveTab(), delay);
}

// ── Start ───────────────────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(({ windowId }) => {
  if (windowId === state.windowId) scheduleTabCheck(0);
});
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (tabId === state.tab?.id && (info.url || info.status === "complete")) scheduleTabCheck(NAVIGATION_SETTLE_MS);
});
onConnectionChanged((connection) => {
  state.connection = connection;
  state.connectPending = false;
  cache.clear();
  if (connection) state.connectMessage = null;
  init();
});
document.addEventListener("click", (e) => {
  if (state.menuOpen && !menu.contains(e.target) && !userBox.contains(e.target)) {
    state.menuOpen = false;
    renderHeader();
  }
});

chrome.windows.getCurrent().then((w) => {
  state.windowId = w.id;
  init();
});
