import assert from "node:assert/strict";
import test, { mock } from "node:test";
import { loadTs } from "./load.mjs";

const d = await loadTs("lib/useDictation.ts");

class FakeRecognition {
  static instances = [];
  constructor() {
    this.lang = ""; this.continuous = true; this.interimResults = true; this.maxAlternatives = 5;
    this.onresult = null; this.onerror = null; this.onend = null;
    this.started = 0; this.stopped = 0; this.aborted = 0;
    FakeRecognition.instances.push(this);
  }
  start() { this.started++; }
  stop() { this.stopped++; }
  abort() { this.aborted++; }
  // test drivers
  say(text, isFinal = true) {
    const result = Object.assign([{ transcript: text }], { isFinal });
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
  fail(error) { this.onerror?.({ error }); }
  end() { this.onend?.(); }
}

function setup() {
  FakeRecognition.instances = [];
  const texts = [];
  const states = [];
  const c = d.createDictationController(FakeRecognition, { lang: "en-GB", onText: (t) => texts.push(t), onChange: (s) => states.push(s) });
  const last = () => states.at(-1) ?? { listening: false, error: null };
  const rec = () => FakeRecognition.instances.at(-1);
  return { c, texts, states, last, rec };
}

test("unsupported outside a browser", () => {
  assert.equal(d.getSpeechRecognition(), null);
});

test("start configures and starts synchronously; final text is passed on", () => {
  const { c, texts, last, rec } = setup();
  c.start();
  assert.equal(rec().started, 1, "recognition starts inside the tap");
  assert.equal(rec().lang, "en-GB");
  assert.equal(rec().continuous, false);
  assert.equal(last().listening, true);
  rec().say("water on the ", false);
  rec().say("  water on the ceiling  ");
  assert.deepEqual(texts, ["water on the ceiling"]);
  rec().end();
  assert.equal(last().listening, false);
});

test("start while listening is a no-op", () => {
  const { c } = setup();
  c.start();
  c.start();
  assert.equal(FakeRecognition.instances.length, 1);
  assert.equal(FakeRecognition.instances[0].started, 1);
});

test("errors map to resident wording and clear on next start", () => {
  const { c, last, rec } = setup();
  const cases = {
    "not-allowed": "Microphone access is off. You can type instead.",
    "service-not-allowed": "Microphone access is off. You can type instead.",
    "no-speech": "Didn't catch that. Try again or type.",
    network: "Voice typing needs a connection. You can type instead.",
  };
  for (const [code, message] of Object.entries(cases)) {
    c.start();
    rec().fail(code);
    rec().end();
    assert.deepEqual(last(), { listening: false, error: message }, code);
  }
  c.start();
  assert.equal(last().error, null, "next start clears the error");
  rec().fail("bad-grammar");
  assert.ok(last().error, "unknown codes get a generic message");
  rec().end();
  c.start();
  rec().fail("aborted");
  assert.equal(last().error, null, "aborted is not shown");
});

test("stop() stops; a stuck recognizer is aborted after the grace period", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { c, last, rec } = setup();
    c.start();
    c.stop();
    assert.equal(rec().stopped, 1);
    assert.equal(last().listening, true, "waits for end so final words still arrive");
    mock.timers.tick(d.STOP_GRACE_MS);
    assert.equal(rec().aborted, 1);
    assert.equal(last().listening, false);
    c.start();
    assert.equal(FakeRecognition.instances.length, 2, "can listen again");
  } finally {
    mock.timers.reset();
  }
});

test("dispose aborts and silences callbacks", () => {
  const { c, texts, states, rec } = setup();
  c.start();
  const r = rec();
  const n = states.length;
  c.dispose();
  assert.equal(r.aborted, 1);
  assert.equal(r.onresult, null);
  c.start();
  assert.equal(FakeRecognition.instances.length, 1, "no restart after dispose");
  assert.equal(states.length, n);
  assert.deepEqual(texts, []);
});

test("a throwing start() reports a generic error and is not stuck listening", () => {
  class Throwing extends FakeRecognition { start() { throw new DOMException("already started", "InvalidStateError"); } }
  const states = [];
  const c = d.createDictationController(Throwing, { lang: "en-US", onText: () => {}, onChange: (s) => states.push(s) });
  c.start();
  assert.equal(states.at(-1).listening, false);
  assert.ok(states.at(-1).error);
});
