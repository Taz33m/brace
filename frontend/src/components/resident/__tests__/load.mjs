// Test helper: transpile a resident .ts module (and its relative runtime imports) into a temp dir
// and import it. Type-only imports are erased by TypeScript; bare specifiers ("react") are resolved
// from the frontend's node_modules so they work from the temp dir.
import { existsSync, rmSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const RESIDENT_DIR = fileURLToPath(new URL("..", import.meta.url));
const SPECIFIER = /(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(["'])([^"']+)\2/g;

let outDir = null;
const emitted = new Map(); // absolute source path -> absolute output path

async function root() {
  if (!outDir) {
    outDir = await mkdtemp(path.join(os.tmpdir(), "resident-tests-"));
    process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));
  }
  return outDir;
}

function resolveRelative(fromFile, spec) {
  const base = path.resolve(path.dirname(fromFile), spec);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts")]) {
    if (/\.tsx?$/.test(candidate) && existsSync(candidate)) return candidate;
  }
  throw new Error(`load.mjs: cannot resolve ${spec} from ${fromFile}`);
}

async function emit(source) {
  if (emitted.has(source)) return emitted.get(source);
  const rel = path.relative(RESIDENT_DIR, source).split(path.sep).map((s) => (s === ".." ? "__up" : s)).join("/");
  const out = path.join(await root(), rel.replace(/\.tsx?$/, ".mjs"));
  emitted.set(source, out);

  const { outputText } = ts.transpileModule(await readFile(source, "utf8"), {
    fileName: source,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
  });

  const rewrites = new Map();
  for (const [, , , spec] of outputText.matchAll(SPECIFIER)) {
    if (rewrites.has(spec)) continue;
    if (spec.startsWith(".")) {
      const child = await emit(resolveRelative(source, spec));
      let link = path.relative(path.dirname(out), child).split(path.sep).join("/");
      if (!link.startsWith(".")) link = `./${link}`;
      rewrites.set(spec, link);
    } else if (!spec.startsWith("node:")) {
      rewrites.set(spec, import.meta.resolve(spec));
    }
  }
  const code = outputText.replace(SPECIFIER, (all, lead, q, spec) => (rewrites.has(spec) ? `${lead}${q}${rewrites.get(spec)}${q}` : all));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code);
  return out;
}

/** Import a module by its path relative to src/components/resident, e.g. "lib/status.ts". */
export async function loadTs(relativePath) {
  const out = await emit(path.resolve(RESIDENT_DIR, relativePath));
  return import(pathToFileURL(out).href);
}
