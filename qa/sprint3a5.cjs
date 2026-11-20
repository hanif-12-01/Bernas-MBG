// Browser acceptance. The Python runner provides isolated services and fixtures.
const assert = require("node:assert/strict");
const { readFile, writeFile } = require("node:fs/promises");
const path = require("node:path");
const { chromium, devices } = require(process.env.QA_PLAYWRIGHT_MODULE || "playwright");

const baseURL = process.env.QA_WEB_URL;
const evidence = process.env.QA_ARTIFACTS;
const fixtures = process.env.QA_FIXTURES;
const password = process.env.GIZIOPTIMA_DEMO_PASSWORD;
const stateFile = path.join(fixtures, "workflow.json");
const planName = "Rencana Impor QA";
const datasetName = "Dataset Impor QA";
const revisionNote = "Periksa komposisi rencana dan ajukan ulang.";
const qcNote = "Komponen diperiksa ulang oleh petugas QA.";
const correctedFood = "Sayur teramati oleh petugas QA";
const qcDecision = "Foto ulang untuk dokumentasi operasional.";
const api = "/api/v1";

function button(page, name) {
  return page.getByRole("button", { name, exact: typeof name === "string" });
}

async function request(client, method, route, { status = 200, csrf, ...options } = {}) {
  const response = await client.fetch(api + route, {
    method,
    ...(csrf ? { headers: { "X-CSRF-Token": csrf } } : {}),
    ...options,
  });
  const acceptable = [].concat(status);
  if (!acceptable.includes(response.status())) {
    throw new Error(`${method} ${route}: expected ${acceptable}, got ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  if (response.headers()["content-type"]?.includes("json")) return response.json();
  return response;
}

async function login(browser, username, phone = false) {
  const options = phone
    ? { ...devices["iPhone 13"], defaultBrowserType: undefined }
    : { viewport: { width: 1440, height: 1000 } };
  const context = await browser.newContext({ ...options, baseURL });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Nama Pengguna atau Email").fill(username);
  await page.getByLabel("Kata Sandi").fill(password);
  const [loginResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/auth/login")),
    button(page, "Masuk").click(),
  ]);
  assert.equal(loginResponse.status(), 200, `Login ${username}`);
  await page.waitForURL("**/dashboard");
  return { context, page, csrf: (await loginResponse.json()).csrf_token };
}

async function uiMutation(page, endpoint, action, expected = 200) {
  const [response] = await Promise.all([
    page.waitForResponse((r) => {
      const pathname = new URL(r.url()).pathname;
      return pathname.startsWith(api) && pathname.endsWith(endpoint) && r.request().method() !== "GET";
    }),
    action(),
  ]);
  assert.equal(response.status(), expected, `${endpoint}: ${(await response.text()).slice(0, 600)}`);
  return response.json();
}

async function saveScreenshot(page, filename) {
  await page.screenshot({ path: path.join(evidence, filename), animations: "disabled" });
}

async function setup(browser) {
  const anonymous = await browser.newContext({ baseURL });
  const entry = await anonymous.newPage();
  await entry.goto("/dashboard");
  await entry.waitForURL("**/login");
  await anonymous.close();

  const planner = await login(browser, "perencana_menu");
  await planner.page.goto("/settings");
  await planner.page.getByLabel("Nama Versi Dataset").fill(datasetName);
  await planner.page.getByLabel(/Tandai sebagai Data Simulasi/).check();
  for (const [selector, filename] of [
    ["#file-ing", "ingredients.csv"], ["#file-price", "prices.csv"],
    ["#file-stock", "stock.csv"], ["#file-rec", "recipes.csv"],
  ]) {
    await planner.page.locator(selector).setInputFiles(path.join(fixtures, filename));
  }
  const dataset = await uiMutation(
    planner.page, "/datasets/import", () => button(planner.page, /Validasi & Impor/).click(), 201,
  );
  await planner.page.getByRole("link", { name: /Gunakan Dataset Ini untuk Rencana Baru/i }).click();
  await planner.page.getByLabel("Nama rencana").fill(planName);
  const datasetSelector = planner.page.getByLabel("Dataset bahan, harga dan stok");
  assert.equal(await datasetSelector.inputValue(), dataset.dataset_version_id);
  for (const [label, value] of [
    ["Porsi per hari", "50"], ["Jumlah hari", "2"], ["Anggaran per porsi (Rp)", "12000"],
    ["Maksimum pengulangan keluarga resep", "2"],
  ]) {
    await planner.page.getByLabel(label, { exact: true }).fill(value);
  }
  const run = await uiMutation(planner.page, "/optimize", () => button(planner.page, /Simpan & Hitung Rencana/).click());
  assert.equal(run.dataset_version_id, dataset.dataset_version_id);
  assert.equal(run.validation_passed, true);
  assert.equal(run.solver_status, "OPTIMAL");
  await planner.page.getByText(/Tumis.*Import|Ayam.*Import|Nasi Import|Pisang Import/).first().waitFor();
  const submission = await uiMutation(planner.page, "/submit", () => button(planner.page, /Ajukan Peninjauan/).click());
  assert.equal(submission.status, "SUBMITTED");
  await planner.page.getByText(/telah diajukan ke Kepala Dapur/).waitFor();
  await planner.page.evaluate(() => window.scrollTo(0, 0));
  await saveScreenshot(planner.page, "desktop-rencana-impor.png");

  const manager = await login(browser, "kepala_dapur");
  await manager.page.getByText(/Ringkasan Kepala Dapur/).first().waitFor();
  await manager.page.getByRole("textbox").last().fill(revisionNote);
  const rejected = await uiMutation(manager.page, "/review", () => button(manager.page, "Minta Revisi").click());
  assert.equal(rejected.status, "REVISION_REQUIRED");
  await planner.page.goto(`/menu-planning?run=${run.run_id}`);
  await planner.page.getByText(revisionNote).waitFor();
  await planner.page.getByLabel("Catatan peninjauan").fill("Komposisi sudah ditinjau ulang.");
  const revised = await uiMutation(planner.page, "/submit", () => button(planner.page, "Ajukan Ulang").click());
  assert.equal(revised.version_number, 2);
  assert.equal(revised.status, "SUBMITTED");
  await manager.page.reload();
  const approved = await uiMutation(manager.page, "/review", () => button(manager.page, "Setujui Operasional").click());
  assert.equal(approved.status, "APPROVED");
  await saveScreenshot(manager.page, "desktop-kepala-dapur.png");

  const qc = await login(browser, "petugas_qc", true);
  await qc.page.goto("/kitchen-qc");
  const select = qc.page.getByLabel("Rencana Menu Acuan");
  await select.selectOption(approved.id);
  const inspection = await uiMutation(qc.page, "/qc/inspections", () => button(qc.page, /Mulai Pemeriksaan/).click(), 201);
  assert.equal(inspection.run_id, run.run_id);
  assert.equal(inspection.expected_menu.length, 4);
  const gallery = qc.page.locator("#qc-photo-file");
  await gallery.setInputFiles(path.join(fixtures, "upload-test.jpg"));
  const image = await uiMutation(qc.page, "/images", () => button(qc.page, /Unggah Foto/).click(), 201);
  await qc.page.getByText("Konfigurasi Vision AI diperlukan.", { exact: true }).waitFor();
  assert.equal(await button(qc.page, /Periksa dengan AI/).isEnabled(), false);
  await request(qc.context.request, "POST", `/qc/inspections/${inspection.id}/analyze`, { csrf: qc.csrf, status: 503 });
  assert.equal(await qc.page.locator("#qc-photo-camera").getAttribute("capture"), "environment");
  await qc.page.getByText("Konfigurasi Vision AI diperlukan.", { exact: true }).scrollIntoViewIfNeeded();
  await saveScreenshot(qc.page, "mobile-390-vision-konfigurasi.png");

  const foreign = await login(browser, "perencana_menu_b");
  const visibleDatasets = await request(foreign.context.request, "GET", "/datasets");
  assert.ok(visibleDatasets.every((row) => row.id !== dataset.dataset_version_id));
  await request(foreign.context.request, "GET", `/datasets/${dataset.dataset_version_id}`, { status: 404 });
  await request(foreign.context.request, "POST", "/scenarios", {
    csrf: foreign.csrf, status: [403, 404], data: { name: "Cross-kitchen", dataset_version_id: dataset.dataset_version_id },
  });
  await request(foreign.context.request, "GET", `/runs/${run.run_id}`, { status: 404 });
  const foreignQc = await login(browser, "petugas_qc_b");
  await request(foreignQc.context.request, "GET", image.image_url.replace(/^\/api\/v1/, ""), { status: 404 });

  await writeFile(stateFile, JSON.stringify({
    datasetId: dataset.dataset_version_id, runId: run.run_id, reviewId: approved.id,
    firstReviewId: rejected.id, inspectionId: inspection.id, imageUrl: image.image_url,
  }));
  console.log("PASS: browser CSV import, dataset-scoped MILP, plan submission/revision/reapproval, QC upload, unconfigured Vision and cross-kitchen authorization");
}

async function workflow(browser) {
  const state = JSON.parse(await readFile(stateFile, "utf-8"));
  const qc = await login(browser, "petugas_qc", true);
  await qc.page.goto(`/kitchen-qc?inspection=${state.inspectionId}`);
  await qc.page.route(
    (url) => url.pathname.endsWith("/analyze"),
    (route) => route.abort("internetdisconnected"),
    { times: 1 },
  );
  await button(qc.page, "Periksa dengan AI").click();
  await qc.page.getByText(/Tidak dapat terhubung ke server backend GiziOptima/).waitFor();
  const analysis = await uiMutation(qc.page, "/analyze", () => button(qc.page, "Coba Analisis Lagi").click());
  assert.equal(analysis.status, "AI_ANALYZED");
  assert.equal(analysis.ai_observations[0].is_live_ai, false);
  assert.equal(analysis.ai_observations[0].provider_mode, "test_deterministic");
  await qc.page.getByText(/Test Provider|Pengujian Deterministik|Non-Live/i).first().waitFor();
  const findings = qc.page.getByRole("heading", { name: /perbandingan|temuan.*visual/i }).first();
  if (await findings.count()) await findings.scrollIntoViewIfNeeded();
  await saveScreenshot(qc.page, "mobile-390-qc-perbandingan-uji.png");
  await qc.page.locator("#qc-food-vegetable").fill(correctedFood);
  await qc.page.getByLabel("Catatan Umum Pemeriksaan QC").fill(qcNote);
  const corrected = await uiMutation(qc.page, "/observations", () => button(qc.page, /Simpan Tinjauan Manusia/).click());
  assert.equal(corrected.status, "HUMAN_REVIEWED");
  assert.equal(corrected.human_reviews.at(-1).notes, qcNote);
  assert.equal(corrected.human_reviews.at(-1).corrected_components.find((item) => item.slot === "vegetable").observed_food_name, correctedFood);
  const submitted = await uiMutation(qc.page, "/submit", () => button(qc.page, /Kirim Pemeriksaan ke Kepala Dapur/).click());
  assert.equal(submitted.status, "SUBMITTED");
  const manager = await login(browser, "kepala_dapur");
  await manager.page.goto(`/kitchen-qc?inspection=${state.inspectionId}`);
  await manager.page.locator("#qc-manager-notes").fill(qcDecision);
  const decision = await uiMutation(manager.page, "/review", () => button(manager.page, /Foto Ulang/i).click());
  assert.equal(decision.status, "REVIEWED");
  assert.equal(decision.review_outcome, "RETAKE_REQUIRED");
  await qc.page.reload();
  await button(qc.page, "Siapkan Pemeriksaan Tindak Lanjut").click();
  const followup = await uiMutation(
    qc.page, "/qc/inspections", () => button(qc.page, "Mulai Pemeriksaan Tindak Lanjut").click(), 201,
  );
  assert.notEqual(followup.id, state.inspectionId);
  assert.equal(followup.run_id, state.runId);
  assert.equal(followup.day_index, decision.day_index);
  state.followupId = followup.id;
  state.managerStorage = await manager.context.storageState();
  await writeFile(stateFile, JSON.stringify(state));
  console.log("PASS: mobile QC connection failure and retry, explicit test-mode analysis, human review, submission, manager retake and linked follow-up");
}

async function persistence(browser) {
  const state = JSON.parse(await readFile(stateFile, "utf-8"));
  const restored = await browser.newContext({ baseURL, storageState: state.managerStorage });
  const current = await request(restored.request, "GET", "/auth/me");
  assert.equal(current.active_role, "KITCHEN_MANAGER");
  const inspection = await request(restored.request, "GET", `/qc/inspections/${state.inspectionId}`);
  assert.equal(inspection.review_outcome, "RETAKE_REQUIRED");
  assert.equal(inspection.manager_notes, qcDecision);
  assert.equal(inspection.human_reviews.at(-1).notes, qcNote);
  assert.equal(inspection.ai_observations[0].is_live_ai, false);
  const image = await request(restored.request, "GET", state.imageUrl.replace(/^\/api\/v1/, ""));
  assert.ok((await image.body()).length > 0);
  const approvedReview = await request(restored.request, "GET", `/menu-reviews/${state.reviewId}`);
  const previousReview = await request(restored.request, "GET", `/menu-reviews/${state.firstReviewId}`);
  assert.equal(approvedReview.status, "APPROVED");
  assert.equal(previousReview.reviewer_notes, revisionNote);
  const run = await request(restored.request, "GET", `/runs/${state.runId}`);
  assert.equal(run.dataset_version_id, state.datasetId);
  const audit = await request(restored.request, "GET", "/auth/audit-events");
  assert.ok(audit.some((entry) => entry.entity_id === state.inspectionId));
  assert.ok(audit.some((entry) => entry.entity_id === state.followupId && entry.metadata?.previous_inspection_id === state.inspectionId));
  console.log("PASS: persisted session, exact dataset selection, review revisions, private image, QC decision and audit after backend process restart");

  const widths = [320, 375, 390, 428, 768, 1024, 1440];
  const screenResults = [];
  for (const [role, routes] of [
    ["perencana_menu", ["/dashboard", "/menu-planning", "/simulator", "/inventory", "/shopping-list", "/settings"]],
    ["kepala_dapur", ["/dashboard", "/menu-planning", "/inventory", "/shopping-list", "/settings", `/kitchen-qc?inspection=${state.inspectionId}`]],
    ["petugas_qc", ["/dashboard", "/menu-planning", `/kitchen-qc?inspection=${state.inspectionId}`]],
  ]) {
    const { page, context } = await login(browser, role, true);
    for (const route of routes) {
      const failures = [];
      const recordError = (error) => failures.push(error.message);
      page.on("pageerror", recordError);
      await page.goto(route);
      await page.locator("main h1").first().waitFor();
      await page.waitForLoadState("networkidle");
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        const size = await page.evaluate(async () => {
          await document.fonts.ready;
          return { layout: window.innerWidth, scroll: document.documentElement.scrollWidth };
        });
        screenResults.push({ role, route: route.split("?")[0], width, ...size, errors: [...failures] });
        if (role === "petugas_qc" && route.startsWith("/kitchen-qc") && width === 320) {
          await saveScreenshot(page, "mobile-320-qc-riwayat.png");
        }
      }
      page.off("pageerror", recordError);
    }
    if (role === "petugas_qc") {
      await page.setViewportSize({ width: 390, height: 844 });
      await button(page, "Buka menu navigasi").click();
      const drawer = page.getByRole("dialog", { name: "Menu navigasi" });
      await drawer.waitFor();
      assert.equal(await drawer.getByRole("link", { name: "Bahan & Stok" }).count(), 0);
      await page.keyboard.press("Escape");
      await drawer.waitFor({ state: "hidden" });
    }
    await context.close();
  }
  await writeFile(path.join(evidence, "responsive-results.json"), JSON.stringify(screenResults, null, 2));
  const failures = screenResults.filter((result) => result.scroll > result.layout || result.errors.length || result.layout !== result.width);
  assert.deepEqual(failures, [], "Horizontal overflow or runtime errors");
  console.log(`PASS: ${screenResults.length} role/route/width checks with no horizontal page overflow or runtime errors`);
}

(async () => {
  const phase = { unconfigured: setup, workflow, persistence }[process.argv[2]];
  assert.ok(phase, "Choose unconfigured, workflow or persistence");
  const browser = await chromium.launch({ executablePath: process.env.QA_CHROMIUM_EXECUTABLE });
  try {
    console.log(`Chromium ${browser.version()} | ${process.argv[2]}`);
    await phase(browser);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
