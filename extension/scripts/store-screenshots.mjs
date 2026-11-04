// Reproducible Chrome Web Store artwork from actual panel renderers.
// Usage: node extension/scripts/store-screenshots.mjs [output-directory]
// Requires the repository frontend's existing Playwright development dependency.
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, extname, resolve, sep } from "node:path";
import { createHash } from "node:crypto";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(process.argv[2] || resolve(root, "dist/webstore"));
const playwrightPath = process.env.PLAYWRIGHT_MODULE_PATH || resolve(root, "../frontend/node_modules/playwright/index.mjs");
const { chromium } = await import(playwrightPath);
const server = createServer(async (request, response) => {
  const path = resolve(root, `.${new URL(request.url, "http://localhost").pathname}`);
  if (!path.startsWith(root + sep)) { response.writeHead(403).end(); return; }
  try {
    const body = await readFile(path);
    const types = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css" };
    response.writeHead(200, { "Content-Type": types[extname(path)] || "application/octet-stream" }).end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
let browser;
try {
  await mkdir(output, { recursive: true });
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {}) });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, locale: "pl-PL", timezoneId: "Europe/Warsaw" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const files = [];
  for (const screen of ["person", "add", "message"]) {
    await page.goto(`http://127.0.0.1:${server.address().port}/test/store-preview.html?screen=${screen}`);
    await page.locator('html[data-ready="true"]').waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.getByRole("heading", { name: "Zofia Testowa", exact: true }).waitFor();
    const file = `nexus-linkedin-${screen}-1280x800.png`;
    const image = await page.screenshot({ path: resolve(output, file), type: "png", omitBackground: false });
    const width = image.readUInt32BE(16), height = image.readUInt32BE(20), colorType = image[25];
    if (width !== 1280 || height !== 800 || colorType !== 2) throw new Error(`Unexpected PNG format ${width}x${height} color type ${colorType}`);
    files.push({ file, width, height, sha256: createHash("sha256").update(image).digest("hex") });
  }
  if (errors.length) throw new Error(errors.join("\n"));
  await writeFile(resolve(output, "screenshots.json"), JSON.stringify({ type: "fictional-data-local-render", live_recruiter_verified: false, files }, null, 2) + "\n");
  console.log(JSON.stringify({ output, files }, null, 2));
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
