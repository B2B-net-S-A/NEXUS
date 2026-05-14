// Renders the "Dodaj do NEXUS" modal inside a Shadow DOM so LinkedIn's CSS
// doesn't bleed in. All network calls go through the background SW via
// chrome.runtime.sendMessage — this module never touches fetch directly.

import { MSG } from "../shared/messages.js";
import { scrapeProfile, getProfileUrl } from "./linkedin-scraper.js";

const HOST_ID = "nexus-modal-host";
let activeHost = null;

async function send(payload) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(payload, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(resp || { ok: false, error: "no response" });
    });
  });
}

function closeModal() {
  if (activeHost) {
    activeHost.remove();
    activeHost = null;
  }
}

async function loadModalCss() {
  try {
    const url = chrome.runtime.getURL("src/content/modal.css");
    const resp = await fetch(url);
    return await resp.text();
  } catch (_err) {
    return "";
  }
}

export async function openModal() {
  closeModal();

  const host = document.createElement("div");
  host.id = HOST_ID;
  document.documentElement.appendChild(host);
  activeHost = host;
  const root = host.attachShadow({ mode: "closed" });

  const css = await loadModalCss();
  const style = document.createElement("style");
  style.textContent = css;
  root.appendChild(style);

  const overlay = document.createElement("div");
  overlay.className = "overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  root.appendChild(overlay);

  const dialog = document.createElement("div");
  dialog.className = "dialog";
  overlay.appendChild(dialog);

  // Header
  const header = document.createElement("div");
  header.className = "header";
  header.innerHTML = `
    <h2 class="title">
      <span class="title-badge">NEXUS</span>
      Dodaj z LinkedIn
    </h2>
    <button class="close" aria-label="Zamknij" title="Zamknij">×</button>
  `;
  header.querySelector(".close").addEventListener("click", closeModal);
  dialog.appendChild(header);

  const body = document.createElement("div");
  body.className = "body";
  dialog.appendChild(body);

  const footer = document.createElement("div");
  footer.className = "footer";
  dialog.appendChild(footer);

  // Auth gate
  const authState = await send({ type: MSG.GET_AUTH_STATE });
  if (!authState.authed) {
    renderNotAuthed(body, footer);
    return;
  }

  renderForm(body, footer);
}

function renderNotAuthed(body, footer) {
  body.innerHTML = `
    <div class="banner banner-info">
      Aby dodawać kandydatów, zaloguj się do NEXUS.
    </div>
    <p style="color: hsl(var(--muted-foreground)); font-size: 13px; margin: 0;">
      Otwórz ustawienia rozszerzenia i podaj swój email + hasło NEXUS.
      Po zalogowaniu wróć tutaj — rozszerzenie automatycznie wykryje sesję.
    </p>
  `;
  footer.innerHTML = `
    <button class="btn btn-secondary" id="nx-cancel">Anuluj</button>
    <button class="btn btn-primary" id="nx-open-options">Otwórz ustawienia</button>
  `;
  footer.querySelector("#nx-cancel").addEventListener("click", closeModal);
  footer.querySelector("#nx-open-options").addEventListener("click", () => {
    send({ type: MSG.OPEN_OPTIONS });
  });
}

function renderForm(body, footer) {
  const profile = scrapeProfile();
  const fallbackUrl = getProfileUrl();
  const displayName =
    [profile.name, profile.lastname].filter(Boolean).join(" ") ||
    "(nie udało się odczytać nazwiska)";

  body.innerHTML = `
    <div class="preview">
      <div class="preview-name" id="nx-preview-name">${escapeHtml(displayName)}</div>
      ${profile.headline ? `<div class="preview-line">${escapeHtml(profile.headline)}</div>` : ""}
      ${profile.location ? `<div class="preview-line">📍 ${escapeHtml(profile.location)}</div>` : ""}
      ${profile.current_company ? `<div class="preview-line">🏢 ${escapeHtml(profile.current_company)}</div>` : ""}
    </div>

    <div class="field job-dropdown">
      <label class="label" for="nx-job-search">Przypisz do rekrutacji (opcjonalnie)</label>
      <div id="nx-job-suggested" hidden style="margin-bottom: 6px;"></div>
      <input class="input" type="text" id="nx-job-search" placeholder="Szukaj po tytule…" autocomplete="off" />
      <ul class="job-list" id="nx-job-list" hidden></ul>
    </div>

    <div class="field">
      <label class="label" for="nx-stage">Etap startowy</label>
      <select class="select" id="nx-stage" disabled>
        <option value="new">Nowy / Analiza CV</option>
        <option value="prep_call">Preparation Call</option>
        <option value="screening">Screening</option>
        <option value="interview">Interview</option>
      </select>
    </div>

    <div class="field">
      <label class="label" for="nx-tags">Tagi (rozdziel przecinkiem)</label>
      <input class="input" type="text" id="nx-tags" placeholder="python, senior, warsaw" />
    </div>

    <div class="field">
      <label class="label" for="nx-notes">Notatka (opcjonalnie)</label>
      <textarea class="textarea" id="nx-notes" placeholder="Skąd? Pierwsze wrażenie? Konkretne stanowisko?"></textarea>
    </div>

    <div id="nx-status"></div>
  `;

  footer.innerHTML = `
    <button class="btn btn-secondary" id="nx-cancel">Anuluj</button>
    <button class="btn btn-primary" id="nx-submit">Dodaj do NEXUS</button>
  `;

  footer.querySelector("#nx-cancel").addEventListener("click", closeModal);
  const submitBtn = footer.querySelector("#nx-submit");

  // Job search with 300ms debounce
  const searchInput = body.querySelector("#nx-job-search");
  const list = body.querySelector("#nx-job-list");
  const stageSelect = body.querySelector("#nx-stage");
  const suggestedWrap = body.querySelector("#nx-job-suggested");
  let selectedJobId = null;
  let debounceTimer = null;

  function pickJob(jobId, title) {
    selectedJobId = jobId;
    searchInput.value = title;
    list.hidden = true;
    stageSelect.disabled = false;
  }

  // Pre-fill from open NEXUS tabs — non-blocking, fire-and-forget.
  (async () => {
    const resp = await send({ type: MSG.GET_OPEN_NEXUS_JOBS });
    if (!resp.ok || !resp.items || resp.items.length === 0) return;
    const chips = resp.items
      .slice(0, 5)
      .map(
        (j) =>
          `<button type="button" class="chip" data-job-id="${j.id}">${escapeHtml(j.title)}</button>`,
      )
      .join("");
    suggestedWrap.innerHTML = `<div class="preview-line" style="margin-bottom:6px;">Otwarte rekrutacje:</div>${chips}`;
    suggestedWrap.hidden = false;
    suggestedWrap.querySelectorAll("button.chip").forEach((btn) => {
      btn.style.cursor = "pointer";
      btn.style.border = "0";
      btn.addEventListener("click", () => {
        pickJob(Number(btn.dataset.jobId), btn.textContent);
      });
    });
  })();

  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = searchInput.value.trim();
    if (!q) {
      list.hidden = true;
      list.innerHTML = "";
      selectedJobId = null;
      stageSelect.disabled = true;
      return;
    }
    debounceTimer = setTimeout(async () => {
      const resp = await send({ type: MSG.SEARCH_JOBS, q });
      list.innerHTML = "";
      if (!resp.ok) {
        list.hidden = true;
        return;
      }
      const items = resp.items || [];
      if (items.length === 0) {
        const li = document.createElement("li");
        li.className = "job-item";
        li.style.color = "hsl(var(--muted-foreground))";
        li.style.cursor = "default";
        li.textContent = "Brak wyników";
        list.appendChild(li);
      } else {
        for (const item of items) {
          const li = document.createElement("li");
          li.className = "job-item";
          li.dataset.jobId = String(item.id);
          li.innerHTML = `${escapeHtml(item.title)}${item.client_name ? ` <span class="client">· ${escapeHtml(item.client_name)}</span>` : ""}`;
          li.addEventListener("click", () => {
            pickJob(item.id, item.title);
          });
          list.appendChild(li);
        }
      }
      list.hidden = false;
    }, 300);
  });
  searchInput.addEventListener("blur", () => {
    setTimeout(() => {
      list.hidden = true;
    }, 200);
  });
  searchInput.addEventListener("focus", () => {
    if (list.children.length > 0) list.hidden = false;
  });

  // Submit
  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Dodaję…';
    const statusEl = body.querySelector("#nx-status");
    statusEl.innerHTML = "";

    const tagsRaw = body.querySelector("#nx-tags").value.trim();
    const tags = tagsRaw
      ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean)
      : null;
    const notes = body.querySelector("#nx-notes").value.trim() || null;
    const payload = {
      linkedin_url: profile.linkedin_url || fallbackUrl,
      preview: {
        name: profile.name,
        lastname: profile.lastname,
        headline: profile.headline,
        location: profile.location,
        current_company: profile.current_company,
      },
      tags,
      notes,
      job_id: selectedJobId,
      stage: selectedJobId ? stageSelect.value : null,
    };

    const resp = await send({ type: MSG.ADD_CANDIDATE, payload });
    submitBtn.disabled = false;
    submitBtn.textContent = "Dodaj do NEXUS";

    if (!resp.ok) {
      if (resp.code === "unauthorized") {
        renderNotAuthed(body, footer);
        return;
      }
      statusEl.innerHTML = `<div class="banner banner-error">Błąd: ${escapeHtml(resp.error || "nieznany")}</div>`;
      return;
    }

    renderResult(body, footer, resp);
  });
}

function renderResult(body, footer, resp) {
  const c = resp.candidate || {};
  const isNew = c.action === "created";
  const bannerClass = isNew ? "banner-success" : "banner-info";
  const titleText = isNew
    ? `Dodano: ${escapeHtml(c.name || "kandydat")}`
    : `Już w bazie: ${escapeHtml(c.name || "kandydat")}`;
  const profileLink = resp.frontend_url
    ? `<a href="${escapeHtml(resp.frontend_url)}" target="_blank" rel="noopener">otwórz profil w NEXUS →</a>`
    : "";
  const resyncNote = c.resync_scheduled
    ? `<div class="preview-line" style="margin-top:6px;">Profil ostatnio synchronizowany dawno — zlecono odświeżenie z LinkedIn.</div>`
    : "";

  body.innerHTML = `
    <div class="banner ${bannerClass}">
      <div style="font-weight: 600;">${titleText}</div>
      <div style="margin-top: 4px;">${profileLink}</div>
      ${resyncNote}
    </div>
  `;

  footer.innerHTML = `
    <button class="btn btn-secondary" id="nx-close-result">Zamknij</button>
    ${!isNew ? `<button class="btn btn-primary" id="nx-resync">Odśwież z LinkedIn</button>` : ""}
  `;
  footer.querySelector("#nx-close-result").addEventListener("click", closeModal);
  const resyncBtn = footer.querySelector("#nx-resync");
  if (resyncBtn) {
    resyncBtn.addEventListener("click", async () => {
      resyncBtn.disabled = true;
      resyncBtn.innerHTML = '<span class="spinner"></span> Synchronizuję…';
      const r = await send({
        type: MSG.SYNC_LINKEDIN,
        candidate_id: c.candidate_id,
      });
      if (r.ok) {
        resyncBtn.textContent = "Zsynchronizowano ✓";
      } else {
        resyncBtn.disabled = false;
        resyncBtn.textContent = "Spróbuj ponownie";
        body.querySelector(".banner").insertAdjacentHTML(
          "afterend",
          `<div class="banner banner-error" style="margin-top:8px;">Błąd: ${escapeHtml(r.error || "nieznany")}</div>`,
        );
      }
    });
  }
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
