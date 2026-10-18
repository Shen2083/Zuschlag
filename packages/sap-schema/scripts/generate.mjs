// Generates src/generated/*.ts from schemas/*.schema.json.
// `--check` fails if the committed output is stale (used by lint/CI).
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const schemaDir = path.join(root, "schemas");
const outDir = path.join(root, "src", "generated");
const check = process.argv.includes("--check");

const banner =
  "/* eslint-disable */\n// AUTO-GENERATED from schemas/ by scripts/generate.mjs — do not edit.";
let stale = false;

for (const file of (await readdir(schemaDir)).filter((f) => f.endsWith(".schema.json"))) {
  const schema = JSON.parse(await readFile(path.join(schemaDir, file), "utf8"));
  const ts = await compile(schema, schema.title, {
    bannerComment: banner,
    additionalProperties: false,
    style: { singleQuote: false, printWidth: 100 },
  });
  const base = file.replace(".schema.json", "");
  const schemaModule =
    `${banner}\n\n` +
    `export const schema = ${JSON.stringify(schema, null, 2)} as const;\n\n` +
    `export default schema;\n`;
  await emit(path.join(outDir, `${base}.ts`), ts);
  await emit(path.join(outDir, `${base}.schema.ts`), schemaModule);
}

async function emit(outFile, content) {
  const current = await readFile(outFile, "utf8").catch(() => "");
  if (current === content) return;
  if (check) {
    console.error(`stale generated file: ${path.relative(root, outFile)} (run pnpm generate)`);
    stale = true;
  } else {
    await writeFile(outFile, content);
    console.log(`wrote ${path.relative(root, outFile)}`);
  }
}
if (stale) process.exit(1);
