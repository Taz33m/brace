import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL, fileURLToPath } from "node:url";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Run the actual screen handlers with explicit mount/cleanup, without adding a DOM dependency.
// SSR supplies real React refs; the proxy captures effect cleanup and rendered button handlers.
const require = createRequire(import.meta.url);
const dataUrl = code => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const hooksUrl = dataUrl(`import * as React from ${JSON.stringify(pathToFileURL(require.resolve("react")).href)};
export * from ${JSON.stringify(pathToFileURL(require.resolve("react")).href)};
export function useEffect(fn) { globalThis.__residentFlowEffects.push(fn); }
export const useLayoutEffect = useEffect;
export function useState(initial) { return React.useState(initial === 'form' ? 'review' : initial); }
`);
const jsxUrl = dataUrl(`import {jsx as make, jsxs as makes, Fragment} from ${JSON.stringify(pathToFileURL(require.resolve("react/jsx-runtime")).href)};
export {Fragment};
export function jsx(type, props, key) { if(type === 'button') globalThis.__residentFlowButtons.push(props); return make(type,props,key); }
export function jsxs(type, props, key) { if(type === 'button') globalThis.__residentFlowButtons.push(props); return makes(type,props,key); }
`);
const modules = new Map();
async function compile(source) {
  if (modules.has(source)) return modules.get(source);
  let { outputText } = ts.transpileModule(await readFile(source, "utf8"), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
  } });
  const rewrites = new Map();
  for (const [, spec] of outputText.matchAll(/from\s+"([^"]+)"/g)) {
    if (rewrites.has(spec)) continue;
    if (spec === "react") rewrites.set(spec, hooksUrl);
    else if (spec === "react/jsx-runtime") rewrites.set(spec, jsxUrl);
    else if (spec.startsWith(".")) {
      const base = new URL(spec, pathToFileURL(source));
      const target = [base.pathname, `${base.pathname}.ts`, `${base.pathname}.tsx`].find(existsSync);
      assert.ok(target, `Missing module ${spec}`);
      rewrites.set(spec, await compile(target));
    } else rewrites.set(spec, pathToFileURL(require.resolve(spec)).href);
  }
  outputText = outputText.replace(/from\s+"([^"]+)"/g, (_all, spec) => `from ${JSON.stringify(rewrites.get(spec))}`);
  const url = dataUrl(outputText);
  modules.set(source, url);
  return url;
}
const { ReportFlow } = await import(await compile(fileURLToPath(new URL("../screens/ReportFlow.tsx", import.meta.url))));
const { SupportFlow } = await import(await compile(fileURLToPath(new URL("../screens/SupportFlow.tsx", import.meta.url))));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const expired = { status: 401, code: "session_expired", message: "Expired", retryable: false };

function props(overrides = {}) {
  const calls = { patches: 0, completed: 0, expired: 0, succeeded: 0, keys: 0 };
  return {
    calls,
    api: {}, home: { unit_label: "A", selectable_locations: [] }, connection: "live",
    draft: { category: "water", selected_location_id: null, location_description: "Kitchen",
      text: "Leak near ceiling", observed_choice: "unknown", observed_local: "", photos: [1, 2].map(n => ({
        local_id: `photo-${n}`, file: new File(["photo"], `${n}.jpg`, { type: "image/jpeg" }),
        preview_url: null, state: "ready", idempotency_key: `upload-key-${n}`, upload_id: null, error: null,
      })) },
    set_draft: () => { calls.patches++; },
    keeper: { keyFor: () => { calls.keys++; return "submission-key"; }, succeeded: () => { calls.succeeded++; } },
    now_stamp: { current: null }, on_submitted: () => { calls.completed++; },
    on_expired: () => { calls.expired++; }, on_cancel() {}, ...overrides,
  };
}
function mount(Component, input, { replay = true } = {}) {
  globalThis.window = { scrollTo() {} };
  globalThis.__residentFlowEffects = [];
  globalThis.__residentFlowButtons = [];
  renderToStaticMarkup(React.createElement(Component, input));
  const buttons = globalThis.__residentFlowButtons;
  const cleanups = [];
  for (const setup of globalThis.__residentFlowEffects.splice(0)) {
    if (replay) { const cleanup = setup(); if (typeof cleanup === "function") cleanup(); }
    const cleanup = setup(); if (typeof cleanup === "function") cleanups.push(cleanup);
  }
  return {
    send() {
      const button = buttons.find(button => button.children === (Component === ReportFlow ? "Send report" : "Send request"));
      assert.ok(button, "Actual send button rendered");
      return button.onClick();
    },
    unmount() { cleanups.forEach(cleanup => cleanup()); },
  };
}

test("new invitation during first upload cannot send the second photo or old report", async () => {
  const first = deferred(), requests = [];
  let household = "old";
  const input = props({ api: {
    upload_image(file, key) { requests.push({ operation: "upload", household, file: file.name, key }); return first.promise; },
    submit_report() { requests.push({ operation: "report", household }); return Promise.resolve({}); },
  } });
  const old = mount(ReportFlow, input);
  old.send();
  assert.equal(requests.length, 1);
  const patchesBeforeUnmount = input.calls.patches;
  old.unmount();
  household = "new";
  const nextInput = props({ api: input.api });
  const next = mount(ReportFlow, nextInput);
  first.resolve({ upload_id: "old-upload" });
  await tick();
  assert.deepEqual(requests, [{ operation: "upload", household: "old", file: "1.jpg", key: "upload-key-1" }]);
  assert.equal(input.calls.patches, patchesBeforeUnmount, "No stale draft update");
  assert.equal(input.calls.completed + input.calls.expired + input.calls.succeeded + input.calls.keys, 0);
  assert.deepEqual(nextInput.calls, { patches: 0, completed: 0, expired: 0, succeeded: 0, keys: 0 });
  next.unmount();
});

test("expired pending upload cannot expire the replacement household", async () => {
  const first = deferred(); let uploads = 0, reports = 0;
  const input = props({ api: { upload_image() { uploads++; return first.promise; }, submit_report() { reports++; } } });
  const screen = mount(ReportFlow, input);
  screen.send(); screen.unmount(); first.reject(expired); await tick();
  assert.equal(uploads, 1); assert.equal(reports, 0); assert.equal(input.calls.expired, 0);
});

test("mounted report still uploads both photos with their keys then submits once", async () => {
  const requests = [];
  const input = props({ api: {
    async upload_image(file, key) { requests.push({ operation: "upload", key }); return { upload_id: file.name }; },
    async submit_report(report, key) { requests.push({ operation: "report", key, ids: report.upload_ids }); return {}; },
  } });
  const screen = mount(ReportFlow, input);
  screen.send(); await tick();
  assert.deepEqual(requests, [ { operation: "upload", key: "upload-key-1" }, { operation: "upload", key: "upload-key-2" },
    { operation: "report", key: "submission-key", ids: ["1.jpg", "2.jpg"] } ]);
  assert.equal(input.calls.completed, 1); assert.equal(input.calls.succeeded, 1);
  screen.unmount();
});

for (const failure of [false, true]) {
  test(`pending report ${failure ? "expiry" : "receipt"} after unmount cannot call shell or reset its key`, async () => {
    const pending = deferred();
    const input = props({ api: { async upload_image() { return { upload_id: "uploaded" }; }, submit_report() { return pending.promise; } } });
    const screen = mount(ReportFlow, input);
    screen.send(); await tick(); screen.unmount();
    failure ? pending.reject(expired) : pending.resolve({}); await tick();
    assert.equal(input.calls.keys, 1);
    assert.equal(input.calls.completed + input.calls.expired + input.calls.succeeded, 0);
  });
  test(`pending support ${failure ? "expiry" : "receipt"} after unmount cannot call shell or reset its key`, async () => {
    const pending = deferred(); let requests = 0;
    const input = props({ draft: { category: "housing", description: "Somewhere to stay" },
      api: { request_support() { requests++; return pending.promise; } } });
    const screen = mount(SupportFlow, input);
    const sending = screen.send(); screen.unmount();
    failure ? pending.reject(expired) : pending.resolve({}); await sending;
    assert.equal(requests, 1); assert.equal(input.calls.keys, 1);
    assert.equal(input.calls.completed + input.calls.expired + input.calls.succeeded, 0);
  });
}

test("mounted support still completes after StrictMode setup replay", async () => {
  const input = props({ draft: { category: "housing", description: "Somewhere to stay" }, api: { async request_support() { return {}; } } });
  const screen = mount(SupportFlow, input);
  await screen.send();
  assert.equal(input.calls.completed, 1); assert.equal(input.calls.succeeded, 1);
  screen.unmount();
});

for (const Component of [ReportFlow, SupportFlow]) {
  test(`${Component.name} retires a conflicted draft and ignores another click on the old send handler`, async () => {
    const conflict = { status: 409, code: "idempotency_conflict", message: "Earlier submission exists", retryable: false };
    let requests = 0;
    const input = props({
      api: {
        async upload_image(file) { return { upload_id: file.name }; },
        async submit_report() { requests++; throw conflict; },
        async request_support() { requests++; throw conflict; },
      },
      ...(Component === SupportFlow ? { draft: { category: "housing", description: "Temporary housing" } } : {}),
    });
    input.set_draft = update => { input.draft = update(input.draft); };
    const screen = mount(Component, input);
    screen.send(); await tick();
    assert.equal(requests, 1);
    assert.equal(input.calls.succeeded, 1);
    assert.equal(input.draft.category, null, "Going home and returning cannot reuse the settled draft");
    if (Component === ReportFlow) { assert.equal(input.draft.text, ""); assert.deepEqual(input.draft.photos, []); }
    else assert.equal(input.draft.description, "");
    screen.send(); await tick();
    assert.equal(requests, 1, "No second request before the terminal state has rendered");
    assert.equal(input.calls.keys, 1, "No new idempotency key for the old draft");
    assert.equal(input.calls.completed, 0, "A conflict is not a fabricated receipt");
    screen.unmount();
  });
}
