/**
 * Minimal test harness for recovery UI tests. No dependencies beyond React.
 * Runs in Node via run.mjs (esbuild bundle) but deliberately imports no node:
 * modules so it typechecks under the browser-oriented project tsconfig.
 */
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

type TestFn = () => void | Promise<void>;

const registry: { name: string; fn: TestFn }[] = [];

export class AssertionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AssertionError";
  }
}

export function test(name: string, fn: TestFn): void {
  registry.push({ name, fn });
}

export function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new AssertionError(msg);
}

function show(value: unknown): string {
  if (typeof value === "string") return JSON.stringify(value);
  try {
    const json = JSON.stringify(value);
    return json === undefined ? String(value) : json;
  } catch {
    return String(value);
  }
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]));
}

/** Structural equality (Object.is for primitives, recursive for plain objects and arrays). */
export function assertEqual<T>(actual: T, expected: T, msg?: string): void {
  if (!deepEqual(actual, expected)) {
    throw new AssertionError(`${msg ? msg + ": " : ""}expected ${show(expected)}, got ${show(actual)}`);
  }
}

function excerpt(text: string): string {
  return text.length > 300 ? text.slice(0, 300) + `… (${text.length} chars)` : text;
}

export function assertIncludes(text: string, needle: string, msg?: string): void {
  if (!text.includes(needle)) {
    throw new AssertionError(`${msg ? msg + ": " : ""}expected text to include ${show(needle)} in ${show(excerpt(text))}`);
  }
}

export function assertNotIncludes(text: string, needle: string, msg?: string): void {
  if (text.includes(needle)) {
    const at = text.indexOf(needle);
    const around = text.slice(Math.max(0, at - 80), at + needle.length + 80);
    throw new AssertionError(`${msg ? msg + ": " : ""}expected text NOT to include ${show(needle)}, found near ${show(around)}`);
  }
}

/** Server-render an element to static HTML for string assertions. */
export function render(el: ReactElement): string {
  return renderToStaticMarkup(el);
}

/** Runs every registered test in order, prints results, and throws if any failed. */
export async function runAll(): Promise<void> {
  const tests = registry.splice(0, registry.length);
  if (tests.length === 0) throw new Error("No tests were registered.");
  const failures: string[] = [];
  for (const t of tests) {
    try {
      await t.fn();
      console.log(`  ok    ${t.name}`);
    } catch (err) {
      failures.push(t.name);
      const message = err instanceof Error ? (err instanceof AssertionError ? err.message : err.stack ?? err.message) : String(err);
      console.log(`  FAIL  ${t.name}\n        ${message.split("\n").join("\n        ")}`);
    }
  }
  const passed = tests.length - failures.length;
  console.log(`\n${passed} passed, ${failures.length} failed, ${tests.length} total`);
  if (failures.length > 0) {
    throw new Error(`${failures.length} test(s) failed: ${failures.join("; ")}`);
  }
}
