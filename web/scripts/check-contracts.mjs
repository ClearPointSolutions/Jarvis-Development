import { readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const schema = "../packages/contracts/generated/jarvis-contracts.schema.json";
const checkedIn = resolve(
  "../packages/contracts/generated/jarvis-contracts.ts",
);
const candidate = resolve(tmpdir(), `jarvis-contract-${process.pid}.ts`);
const compiler = resolve(
  "node_modules/json-schema-to-typescript/dist/src/cli.js",
);
const banner =
  "/* Generated from authoritative Pydantic contracts. Do not edit. */";

try {
  const result = spawnSync(
    process.execPath,
    [compiler, "-i", schema, "-o", candidate, "--bannerComment", banner],
    { encoding: "utf8", stdio: "pipe" },
  );
  if (result.status !== 0) {
    process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }

  const [expected, actual] = await Promise.all([
    readFile(candidate),
    readFile(checkedIn),
  ]);
  if (!expected.equals(actual)) {
    console.error(
      "generated TypeScript contract is stale; run npm run contracts:generate in web",
    );
    process.exitCode = 1;
  } else {
    console.log("generated TypeScript contract is current");
  }
} finally {
  await rm(candidate, { force: true });
}

const apiCandidate = resolve(tmpdir(), `jarvis-api-${process.pid}.ts`);
try {
  const result = spawnSync(
    process.execPath,
    [
      resolve("node_modules/openapi-typescript/bin/cli.js"),
      "../packages/contracts/generated/jarvis-api.openapi.json",
      "-o",
      apiCandidate,
    ],
    { encoding: "utf8", stdio: "pipe" },
  );
  if (result.status !== 0) throw new Error(result.stderr);
  const [expected, actual] = await Promise.all([
    readFile(apiCandidate),
    readFile("../packages/contracts/generated/jarvis-api.ts"),
  ]);
  if (!expected.equals(actual)) {
    console.error(
      "Generated API path types are stale; regenerate from integrated OpenAPI",
    );
    process.exitCode = 1;
  } else console.log("Generated API path types: current");
} finally {
  await rm(apiCandidate, { force: true });
}
