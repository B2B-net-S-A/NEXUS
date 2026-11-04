// Pamięć wyboru „Pracuję nad”: kontekst z adresu i zapis w `chrome.storage.local`.
import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";

import { workContext } from "../src/readers/kinds.js";
import { getActiveJob, setActiveJob } from "../src/storage.js";

let store;

beforeEach(() => {
  store = {};
  globalThis.chrome = {
    storage: {
      local: {
        get: async (key) => (key in store ? { [key]: store[key] } : {}),
        set: async (items) => Object.assign(store, items),
      },
    },
  };
});

test("workContext: projekt Recruitera z adresu, reszta wspólna", () => {
  assert.equal(workContext("https://www.linkedin.com/talent/hire/555/manage/all"), "hire/555");
  assert.equal(workContext("https://www.linkedin.com/talent/hire/555/manage/all/profile/AEM1?x=1"), "hire/555");
  assert.equal(workContext("https://www.linkedin.com/talent/hire/777/discover/recruiterSearch"), "hire/777");
  assert.equal(workContext("https://www.linkedin.com/talent/search"), "global");
  assert.equal(workContext("https://www.linkedin.com/talent/profile/AEM1"), "global");
  assert.equal(workContext("https://www.linkedin.com/in/zofia-testowa"), "global");
  assert.equal(workContext(undefined), "global");
  assert.equal(workContext("nie adres"), "global");
});

test("wybór osobno dla projektu, poza projektem wspólny, null czyści", async () => {
  assert.equal(await getActiveJob("production", "hire/555"), null);
  await setActiveJob("production", "hire/555", { id: 1, title: "A" });
  await setActiveJob("production", "hire/777", { id: 2, title: "B" });
  await setActiveJob("production", "global", { id: 3, title: "C" });
  assert.equal((await getActiveJob("production", "hire/555")).id, 1);
  assert.equal((await getActiveJob("production", "hire/777")).id, 2);
  assert.equal((await getActiveJob("production", "global")).id, 3);
  await setActiveJob("production", "hire/555", null);
  assert.equal(await getActiveJob("production", "hire/555"), null);
  assert.equal((await getActiveJob("production", "hire/777")).id, 2);
});

test("id rekrutacji ze stagingu nie przechodzi na produkcję", async () => {
  await setActiveJob("staging", "global", { id: 9, title: "Staging" });
  assert.equal(await getActiveJob("production", "global"), null);
  assert.equal((await getActiveJob("staging", "global")).id, 9);
});

test("pamięć nie rośnie bez końca: odpadają najdawniej wybrane projekty", async () => {
  for (let i = 0; i < 60; i += 1) await setActiveJob("production", `hire/${i}`, { id: i, title: "x" });
  await setActiveJob("production", "hire/10", { id: 1000, title: "wybrana ponownie" });
  assert.equal(Object.keys(store.activeJobs.production).length, 50);
  assert.equal(await getActiveJob("production", "hire/0"), null);
  assert.equal((await getActiveJob("production", "hire/59")).id, 59);
  assert.equal((await getActiveJob("production", "hire/10")).id, 1000);
});
