// Injected on every linkedin.com/in/* page. Drops a floating "+ NEXUS"
// button next to the profile top card and re-injects on SPA navigation.
// All UI (modal) lives in modal-host.js inside a closed Shadow DOM.

const FAB_ID = "nexus-fab-root";
let observer = null;
let lastUrl = location.href;

function buildFab() {
  if (document.getElementById(FAB_ID)) return;
  const btn = document.createElement("button");
  btn.id = FAB_ID;
  btn.type = "button";
  btn.title = "Dodaj kandydata do NEXUS";
  btn.textContent = "+ NEXUS";
  Object.assign(btn.style, {
    position: "fixed",
    right: "24px",
    bottom: "24px",
    zIndex: "2147483646",
    background: "hsl(263 70% 50%)",
    color: "white",
    border: "0",
    borderRadius: "999px",
    padding: "12px 20px",
    fontFamily:
      'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
    fontSize: "14px",
    fontWeight: "600",
    boxShadow: "0 6px 18px rgba(108, 47, 217, 0.35)",
    cursor: "pointer",
    transition: "transform 0.12s, box-shadow 0.12s",
  });
  btn.addEventListener("mouseenter", () => {
    btn.style.transform = "translateY(-1px)";
    btn.style.boxShadow = "0 8px 22px rgba(108, 47, 217, 0.45)";
  });
  btn.addEventListener("mouseleave", () => {
    btn.style.transform = "";
    btn.style.boxShadow = "0 6px 18px rgba(108, 47, 217, 0.35)";
  });
  btn.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    try {
      const mod = await import(
        chrome.runtime.getURL("src/content/modal-host.js")
      );
      await mod.openModal();
    } catch (err) {
      console.error("[NEXUS] Failed to open modal", err);
    }
  });
  document.documentElement.appendChild(btn);
}

function removeFab() {
  document.getElementById(FAB_ID)?.remove();
}

function isProfilePage() {
  return /\/in\/[^\/?#]+/.test(location.pathname);
}

function refresh() {
  if (isProfilePage()) {
    buildFab();
  } else {
    removeFab();
  }
}

function startObserver() {
  if (observer) return;
  observer = new MutationObserver(() => {
    // LinkedIn SPA: URL changes without a full reload — detect via comparison.
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      refresh();
    } else if (isProfilePage() && !document.getElementById(FAB_ID)) {
      // LinkedIn sometimes rewrites the body and our button gets nuked
      buildFab();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

// Initial render + observer
refresh();
startObserver();

// React to "logged in elsewhere" auth changes — refresh button state.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "AUTH_CHANGED") {
    // Currently the FAB always shows; the modal handles auth gating itself.
    // Future: badge the button if not authed.
  }
});
