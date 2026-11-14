// Recovery UI test runner: bundles every *.test.ts(x) in this directory with
// esbuild and runs the bundle in Node. Usage (from frontend/):
//   node src/components/recovery/__tests__/run.mjs
import { build } from "esbuild";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const testsDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(testsDir, "../../../..");
const outDir = join(frontendDir, "node_modules", ".cache", "recovery-tests");
const outfile = join(outDir, "bundle.mjs");

const testFiles = readdirSync(testsDir)
  .filter((f) => /\.test\.tsx?$/.test(f))
  .sort();

if (testFiles.length === 0) {
  console.error(`No *.test.ts / *.test.tsx files found in ${testsDir}`);
  process.exit(1);
}

const entry = [
  ...testFiles.map((f) => `import ${JSON.stringify("./" + f)};`),
  `import { runAll } from "./harness";`,
  `await runAll();`,
  "",
].join("\n");

// CSS is irrelevant to these tests. Stub every .css import as empty; warn (don't fail) when the file
// doesn't exist yet, so a component whose stylesheet is still being written can be tested.
const emptyCss = {
  name: "empty-css",
  setup(b) {
    b.onResolve({ filter: /\.css$/ }, (args) => {
      const path = resolve(args.resolveDir, args.path);
      if (!existsSync(path)) console.warn(`warning: ${args.path} imported by ${args.importer} does not exist (stubbed for tests)`);
      return { path, namespace: "empty-css" };
    });
    b.onLoad({ filter: /.*/, namespace: "empty-css" }, () => ({ contents: "", loader: "js" }));
  },
};

try {
  mkdirSync(outDir, { recursive: true });
  await build({
    stdin: { contents: entry, resolveDir: testsDir, sourcefile: "recovery-tests-entry.ts", loader: "ts" },
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node18",
    jsx: "automatic",
    loader: { ".css": "empty" },
    packages: "external",
    plugins: [emptyCss],
    outfile,
    sourcemap: "inline",
    logLevel: "warning",
  });
} catch (err) {
  console.error("Failed to build recovery tests.");
  if (err && !err.errors) console.error(err);
  process.exit(1);
}

process.setSourceMapsEnabled?.(true);
// Run in a US timezone so a date-only value parsed as UTC midnight would visibly shift a day.
process.env.TZ = process.env.RECOVERY_TEST_TZ || "America/Los_Angeles";
console.log(`Running ${testFiles.length} test file(s): ${testFiles.join(", ")}\n`);
try {
  await import(pathToFileURL(outfile).href);
} catch (err) {
  console.error(`\n${err && err.message ? err.message : err}`);
  process.exit(1);
}
