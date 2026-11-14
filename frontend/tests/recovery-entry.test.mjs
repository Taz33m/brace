import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const dataModule = (code) => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const reactUrl = pathToFileURL(require.resolve("react")).href;
// Queue effects during SSR, then explicitly run setup/cleanup/setup to exercise
// root bootstrap boundaries and StrictMode replays without adding a DOM library.
const hooksUrl = dataModule(`export * from ${JSON.stringify(reactUrl)};
export function useEffect(callback) { globalThis.__braceEntryEffects.push(callback); }`);
let counter = 0;

async function compile(relative, imports = {}) {
  const source = await readFile(new URL(relative, import.meta.url), "utf8");
  let { outputText } = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
  } });
  outputText = outputText.replace(/import\s+"[^\"]+\.css";?/g, "")
    .replace(/import\.meta\.glob\([^)]*\)/g, "({})")
    .replace(/from\s+"([^"]+)"/g, (_all, name) => {
      const replacement = imports[name] ?? (name === "react" ? hooksUrl : pathToFileURL(require.resolve(name)).href);
      return `from ${JSON.stringify(replacement)}`;
    });
  return dataModule(`${outputText}\n// test module ${counter++}`);
}

globalThis.__braceEntryEffects = [];
globalThis.__braceEntryFetch = async () => { throw new Error("Unexpected fetch"); };
globalThis.fetch = (...args) => globalThis.__braceEntryFetch(...args);
const clientUrl = await compile("../src/recovery/client.ts");
const controllerUrl = await compile("../src/recovery/owner-controller.ts");
const routesUrl = await compile("../src/recovery/routes.ts");
const spatialUrl = await compile("../src/recovery/spatial.ts");
const noticeClientUrl = await compile("../src/recovery/notice-client.ts", { "./client": clientUrl });
const draftNoticesUrl = await compile("../src/recovery/DraftNotices.tsx", { "./client": clientUrl, "./notice-client": noticeClientUrl });
const entryUrl = await compile("../src/recovery/RecoveryEntry.tsx", {
  "./client": clientUrl, "./owner-controller": controllerUrl, "./routes": routesUrl, "./spatial": spatialUrl,
  "./DraftNotices": draftNoticesUrl,
});
const { ResidentBootstrap, EvidenceSlot, commandForCurrentCase } = await import(entryUrl);

function browser(hash) {
  let location = new URL(`http://localhost:5174/${hash}`);
  const replaced = [];
  globalThis.window = {
    get location() { return location; },
    history: { state: null, replaceState(_state, _unused, next) { replaced.push(next); location = new URL(next, location); } },
    addEventListener() {}, removeEventListener() {},
  };
  return replaced;
}

async function appModule(legacyCalls = [], importOverrides = {}) {
  globalThis.__braceEntryLegacy = legacyCalls;
  const apiUrl = dataModule(`export const api = {
    config() { globalThis.__braceEntryLegacy.push('/api/config'); return Promise.resolve({sdk_key:'',agent_ready:false}); },
    scenarios() { globalThis.__braceEntryLegacy.push('/api/scenarios'); return Promise.resolve([]); }
  };`);
  const component = (name) => dataModule(`export function ${name}() { return null; }`);
  const url = await compile("../src/App.tsx", {
    "./api": apiUrl, "./components/BuildingPage": component("BuildingPage"),
    "./components/MapPage": component("MapPage"), "./components/VrPage": component("VrPage"),
    "./recovery/RecoveryEntry": entryUrl, "./recovery/routes": routesUrl,
    ...importOverrides,
  });
  return import(url);
}

function replayEffects() {
  const cleanups = [];
  for (const effect of globalThis.__braceEntryEffects.splice(0)) {
    const first = effect();
    if (typeof first === "function") first();
    const second = effect();
    if (typeof second === "function") cleanups.push(second);
  }
  return () => cleanups.forEach(cleanup => cleanup());
}

test("resident initial route captures invitation once and scrubs before bootstrap", async () => {
  const replaced = browser("#/resident?invite=private-token");
  const { captureInitialRoute } = await appModule();
  assert.deepEqual(captureInitialRoute(), { kind: "resident", invitation_token: "private-token" });
  assert.equal(window.location.hash, "#/resident");
  assert.equal(captureInitialRoute().invitation_token, "private-token", "StrictMode second initializer retains captured token");
  assert.equal(replaced.length, 1);
});

test("resident StrictMode bootstrap exchanges once and never calls owner or legacy APIs", async () => {
  browser("#/resident?invite=private-token");
  const calls = [], legacy = [];
  globalThis.__braceEntryEffects = [];
  globalThis.__braceEntryFetch = async (url, init) => {
    assert.equal(window.location.hash, "#/resident", "Invitation removed before network use");
    calls.push({ url, init });
    return new Response('{"ok":true}', { headers: { "Content-Type": "application/json" } });
  };
  const { App } = await appModule(legacy);
  renderToStaticMarkup(React.createElement(App));
  const cleanup = replayEffects();
  await new Promise(resolve => setImmediate(resolve));
  cleanup();
  assert.deepEqual(calls.map(call => call.url), ["/api/resident/session"]);
  assert.deepEqual(JSON.parse(calls[0].init.body), { invitation_token: "private-token" });
  assert.deepEqual(legacy, []);
});

test("recovery route calls only recovery APIs while preparation retains its bootstrap", async () => {
  for (const [hash, expectedLegacy] of [["#/recovery/case-1", []], ["#/beryl-2024/adv33/b/4303509", ["/api/config", "/api/scenarios", "/api/config", "/api/scenarios"]]]) {
    browser(hash);
    const calls = [], legacy = [];
    globalThis.__braceEntryEffects = [];
    globalThis.__braceEntryFetch = async (url) => {
      calls.push(url);
      return new Response(JSON.stringify({ error: { code: "unavailable", message: "Recovery is unavailable", retryable: true } }),
        { status: 503, headers: { "Content-Type": "application/json" } });
    };
    const { App } = await appModule(legacy);
    renderToStaticMarkup(React.createElement(App));
    const cleanup = replayEffects();
    await new Promise(resolve => setImmediate(resolve));
    cleanup();
    assert.deepEqual(legacy, expectedLegacy);
    if (hash.includes("recovery")) assert.ok(calls.length > 0 && calls.every(path => path.startsWith("/api/recovery/")));
    else assert.deepEqual(calls, []);
  }
});

test("resident bootstrap reuses in-flight and completed promises and accepts a new invitation", async () => {
  let sessions = 0, homes = 0;
  const transport = { resident_session: async () => { sessions++; return { ok: true }; },
    resident_api: { get_home: async () => { homes++; return {}; } } };
  const bootstrap = new ResidentBootstrap();
  const first = bootstrap.start("first", transport);
  assert.equal(bootstrap.start("first", transport), first);
  await first;
  bootstrap.forget_token();
  assert.equal(bootstrap.start(null, transport), first);
  assert.equal(sessions, 1);
  await bootstrap.start("second", transport);
  assert.equal(sessions, 2);
  assert.equal(homes, 0);
  bootstrap.reset();
  const home = bootstrap.start(null, transport);
  assert.equal(bootstrap.start(null, transport), home);
  await home;
  assert.equal(homes, 1);
});

test("evidence slots accept only pinned authorized same-origin images", () => {
  browser("#/recovery/case-1");
  const evidence = { evidence_id: "e1", source_label: "Captured source", captured_at: null,
    summary: "An evidence image", limitations: [], location: null, media: null };
  for (const image_url of ["https://remote.example/image.jpg", "/api/buildings/1/aerial.jpg", "https://user:pass@localhost:5174/api/recovery/media/m1"]) {
    const html = renderToStaticMarkup(React.createElement(EvidenceSlot, { title: "Aerial evidence", evidence, image_url }));
    assert.ok(!html.includes("<img"));
    assert.ok(html.includes("Capture date unknown"));
  }
  const html = renderToStaticMarkup(React.createElement(EvidenceSlot, { title: "Aerial evidence", evidence,
    image_url: "/api/recovery/cases/case-1/evidence/e1/image" }));
  assert.ok(html.includes('src="/api/recovery/cases/case-1/evidence/e1/image"'));
  const suppressed = renderToStaticMarkup(React.createElement(EvidenceSlot, { title: "Aerial evidence", evidence: {
    ...evidence, media: { media_id: "m1", url: "/api/recovery/media/m1", alt: "Image", mime_type: "image/jpeg" },
  }, image_url: null }));
  assert.ok(!suppressed.includes("<img"), "An explicit missing pinned image cannot fall back to another media URL");
});

test("new resident invitations receive distinct component identities before effects run", async () => {
  const runtime = pathToFileURL(require.resolve("react/jsx-runtime")).href;
  globalThis.__braceResidentKeys = [];
  const jsxProxy = dataModule(`import {jsx as make, jsxs as makes, Fragment} from ${JSON.stringify(runtime)};
    export {Fragment};
    export function jsx(type, props, key) { if(type.name === 'ResidentEntry') globalThis.__braceResidentKeys.push(key); return make(type,props,key); }
    export function jsxs(type, props, key) { if(type.name === 'ResidentEntry') globalThis.__braceResidentKeys.push(key); return makes(type,props,key); }`);
  for (const hash of ["#/resident?invite=first-household", "#/resident?invite=second-household", "#/resident"]) {
    browser(hash); globalThis.__braceEntryEffects = [];
    const { App } = await appModule([], { "react/jsx-runtime": jsxProxy });
    renderToStaticMarkup(React.createElement(App));
  }
  assert.equal(new Set(globalThis.__braceResidentKeys).size, 3, "React remounts the resident root immediately when invitation identity changes");
});

test("old owner controller cannot mutate a newly selected case before cleanup", async () => {
  const calls = [];
  const controller = { state: { case_id: "old-case" }, command: async value => { calls.push(value); return { run_id: "run" }; } };
  const command = { type: "start_assessment", expected_revision: 2 };
  await assert.rejects(commandForCurrentCase(controller, "new-case", command), /selected case changed/);
  await assert.rejects(commandForCurrentCase(null, "new-case", command), /selected case changed/);
  assert.deepEqual(calls, []);
  await commandForCurrentCase(controller, "old-case", command);
  assert.deepEqual(calls, [command]);
});
