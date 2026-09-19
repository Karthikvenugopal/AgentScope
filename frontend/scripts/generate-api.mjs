import { execFileSync } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";
import { format } from "prettier";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python = process.env.PYTHON ?? `${root}.venv/bin/python`;
const schema = JSON.parse(
    execFileSync(python, [`${root}scripts/export_openapi.py`], {
        cwd: root,
        env: { ...process.env, PYTHONPATH: `${root}backend` },
        encoding: "utf8",
    }),
);
const output = new URL("../src/api/generated/schema.ts", import.meta.url);
const content = await format(
    "// Generated from FastAPI OpenAPI. Run npm run generate-api; do not edit.\n" +
        astToString(await openapiTS(schema, { defaultNonNullable: false })),
    { parser: "typescript" },
);
if (process.argv.includes("--check")) {
    if ((await readFile(output, "utf8")) !== content)
        throw new Error("API types are stale. Run npm run generate-api.");
} else {
    await mkdir(new URL("../src/api/generated/", import.meta.url), {
        recursive: true,
    });
    await writeFile(output, content);
}
