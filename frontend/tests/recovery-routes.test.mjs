import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/recovery/routes.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
});
const routes = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const { parseAppRoute, prepareHash, recoveryHash, residentHash, consumeResidentInvitation } = routes;

test("preparation and headset routes preserve existing links", () => {
  assert.deepEqual(parseAppRoute("#/beryl-2024/adv33/b/1190364"), {
    kind: "prepare", scenario: "beryl-2024", step: "adv33", building: 1190364, vr: false,
  });
  assert.deepEqual(parseAppRoute("#/vr/beryl-2024/-/b/1190364"), {
    kind: "prepare", scenario: "beryl-2024", step: null, building: 1190364, vr: true,
  });
  assert.deepEqual(parseAppRoute("#/beryl-2024/b/1190364"), {
    kind: "prepare", scenario: "beryl-2024", step: null, building: 1190364, vr: false,
  });
  assert.equal(parseAppRoute("#/la-red-flag-jan-2025/20250105T2240Z").step, "20250105T2240Z");
  for (const hash of ["", "#", "#/"]) assert.deepEqual(parseAppRoute(hash), {
    kind: "prepare", scenario: null, step: null, building: null, vr: false,
  });
});

test("resident routes cannot fall through to preparation", () => {
  assert.deepEqual(parseAppRoute("#/resident"), { kind: "resident", invitation_token: null });
  assert.deepEqual(parseAppRoute("#/resident?invite=opaque_token"), { kind: "resident", invitation_token: "opaque_token" });
  assert.deepEqual(parseAppRoute("#/recovery"), { kind: "recovery", case_id: null });
  assert.deepEqual(parseAppRoute("#/recovery/case_123"), { kind: "recovery", case_id: "case_123" });
  assert.equal(parseAppRoute("#/resident/beryl-2024").kind, "invalid");
  assert.equal(parseAppRoute("#/vr/resident/-/b/1").kind, "invalid");
});

test("malformed encodings, injected paths, and invalid building IDs return controlled errors", () => {
  for (const hash of [
    "#/resident?invite=%ZZ", "#/resident?invite=%ED%A0%80", "#/recovery/%E0%A4%A",
    "#/recovery/a%2Fb", "#/recovery/%2e%2e", "#/recovery/a%5Cb", "#/recovery/a%3Fb", "#/recovery/a%23b",
    "#/beryl-2024/adv33/b/NaN", "#/beryl-2024/adv33/b/-1", "#/beryl-2024/adv33/b/0",
    "#/beryl-2024/adv33/b/1.5", "#/beryl-2024/adv33/b/Infinity", "#/beryl-2024/adv33/b/9007199254740992",
    "#/beryl-2024/adv33/b/1/extra", "#/beryl-2024//b/1", "#/vr", "#/resident?invite=x#other",
  ]) {
    assert.doesNotThrow(() => parseAppRoute(hash));
    assert.equal(parseAppRoute(hash).kind, "invalid", hash);
  }
});

test("invitations reject duplicates, emptiness, excess length and whitespace", () => {
  for (const query of ["invite=", "invite", "invite=a&invite=b", "invite=a&%69nvite=b", `invite=${"a".repeat(513)}`, "invite=a%20b"]) {
    const result = parseAppRoute(`#/resident?${query}`);
    assert.equal(result.kind, "invalid");
    assert.ok(!result.message.includes(query));
  }
  assert.equal(parseAppRoute(`#/resident?invite=${"a".repeat(512)}`).kind, "resident");
});

test("route builders round trip and reject invalid identifiers", () => {
  assert.equal(prepareHash(null), "#/");
  assert.equal(prepareHash("beryl-2024", "adv33", 7), "#/beryl-2024/adv33/b/7");
  assert.equal(prepareHash("beryl-2024", null, 7, true), "#/vr/beryl-2024/-/b/7");
  assert.equal(recoveryHash(), "#/recovery");
  assert.deepEqual(parseAppRoute(recoveryHash("case:1")), { kind: "recovery", case_id: "case:1" });
  assert.deepEqual(parseAppRoute(residentHash("token+=/opaque")), { kind: "resident", invitation_token: "token+=/opaque" });
  assert.throws(() => recoveryHash("../private"));
  assert.throws(() => prepareHash("resident"));
  assert.throws(() => prepareHash("beryl-2024", "b"));
  assert.throws(() => prepareHash("beryl-2024", null, NaN));
  assert.throws(() => residentHash(""));
});

test("consume scrubs secret before returning, preserving URL outside hash and history state", () => {
  const calls = [];
  const location = { pathname: "/brace/index.html", search: "?keep=a%20b&invite=outside", hash: "#/resident?invite=secret%2Btoken&view=compact" };
  const history = { state: { keep: true }, replaceState(...args) { calls.push(args); } };
  const token = consumeResidentInvitation(location, history);
  assert.equal(token, "secret+token");
  assert.deepEqual(calls, [[{ keep: true }, "", "/brace/index.html?keep=a%20b&invite=outside#/resident?view=compact"]]);
});

test("consume scrubs malformed/duplicate/empty/oversized tokens before throwing", () => {
  for (const query of ["invite=TOP_SECRET&invite=second", "invite=", `invite=${"x".repeat(513)}`, "invite=SECRET%ZZ"]) {
    const calls = [];
    const location = { pathname: "/app", search: "?outside=unchanged", hash: `#/resident?${query}` };
    const history = { replaceState(...args) { calls.push(args); } };
    assert.throws(() => consumeResidentInvitation(location, history), (error) => {
      assert.equal(calls.length, 1, "scrubbing precedes the error");
      assert.equal(calls[0][2], "/app?outside=unchanged#/resident");
      assert.ok(!error.message.includes("TOP_SECRET") && !error.message.includes("SECRET"));
      return true;
    });
  }
});

test("no-invitation consumption is side-effect free and preparation remains separate", () => {
  const history = { replaceState() { assert.fail("no navigation expected"); } };
  assert.equal(consumeResidentInvitation({ pathname: "/", search: "", hash: "#/resident" }, history), null);
  assert.equal(consumeResidentInvitation({ pathname: "/", search: "", hash: "#/beryl-2024/adv33" }, history), null);
});
