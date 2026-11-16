/// <reference types="node" />
// Golden protocol fixtures shared with Python (core/tests/test_protocol_fixtures.py): every file in
// contract-tests/fixtures/protocol/valid must validate against schemas/<name>.schema.json, every file in invalid/ must not.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const schemasDir = join(root, "schemas");
const fixturesDir = join(root, "contract-tests", "fixtures", "protocol");

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validators = new Map<string, ReturnType<typeof ajv.compile>>();
for (const file of readdirSync(schemasDir).filter((f) => f.endsWith(".schema.json"))) {
  const schema = JSON.parse(readFileSync(join(schemasDir, file), "utf8"));
  validators.set(file.replace(".schema.json", ""), ajv.compile(schema));
}

function load(kind: "valid" | "invalid"): [string, { schema: string; payload: unknown }][] {
  const dir = join(fixturesDir, kind);
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => [f, JSON.parse(readFileSync(join(dir, f), "utf8"))]);
}

describe("golden protocol fixtures", () => {
  const valid = load("valid");
  const invalid = load("invalid");

  it("has fixtures for both directions", () => {
    expect(valid.length).toBeGreaterThanOrEqual(15);
    expect(invalid.length).toBeGreaterThanOrEqual(15);
  });

  it.each(valid)("valid/%s validates", (_file, fx) => {
    const validate = validators.get(fx.schema);
    expect(validate, `schema ${fx.schema}`).toBeDefined();
    expect(validate!(fx.payload), JSON.stringify(validate!.errors)).toBe(true);
  });

  it.each(invalid)("invalid/%s is rejected", (_file, fx) => {
    const validate = validators.get(fx.schema);
    expect(validate, `schema ${fx.schema}`).toBeDefined();
    expect(validate!(fx.payload)).toBe(false);
  });
});
