import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const { createSubmissionKeeper, fingerprint, newIdempotencyKey } = await loadTs("lib/idempotency.ts");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("same payload reuses the key regardless of key order", () => {
  const keeper = createSubmissionKeeper();
  const a = keeper.keyFor({ category: "water", text: "Leak", upload_ids: ["u1"], meta: { a: 1, b: 2 } });
  const b = keeper.keyFor({ meta: { b: 2, a: 1 }, upload_ids: ["u1"], text: "Leak", category: "water" });
  assert.equal(a, b);
  assert.equal(fingerprint({ x: 1, y: [1, 2] }), fingerprint({ y: [1, 2], x: 1 }));
  assert.notEqual(fingerprint([1, 2]), fingerprint([2, 1]));
});

test("a changed payload gets a new key", () => {
  const keeper = createSubmissionKeeper();
  const a = keeper.keyFor({ text: "Leak" });
  const b = keeper.keyFor({ text: "Leak in kitchen" });
  assert.notEqual(a, b);
  assert.equal(keeper.keyFor({ text: "Leak in kitchen" }), b);
});

test("after succeeded() the same payload gets a new key", () => {
  const keeper = createSubmissionKeeper();
  const a = keeper.keyFor({ text: "Leak" });
  keeper.succeeded();
  assert.notEqual(keeper.keyFor({ text: "Leak" }), a);
});

test("newIdempotencyKey is a unique v4 UUID", () => {
  const keys = new Set(Array.from({ length: 1000 }, () => newIdempotencyKey()));
  assert.equal(keys.size, 1000);
  for (const k of [...keys].slice(0, 20)) assert.match(k, UUID);
});

test("newIdempotencyKey falls back without randomUUID", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const real = globalThis.crypto;
  try {
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: { getRandomValues: (b) => real.getRandomValues(b) } });
    assert.match(newIdempotencyKey(), UUID);
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: undefined });
    const k = newIdempotencyKey();
    assert.match(k, /^k-[0-9a-z]+-[0-9a-z]+$/);
    assert.notEqual(newIdempotencyKey(), k);
  } finally {
    Object.defineProperty(globalThis, "crypto", original);
  }
});
