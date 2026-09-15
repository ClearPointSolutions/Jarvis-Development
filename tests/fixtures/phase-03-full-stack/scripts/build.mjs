import { cp, mkdir, readFile, rm } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist");
for (const file of ["index.html", "app.mjs", "validation.mjs"]) {
  await readFile(`frontend/${file}`, "utf8");
  await cp(`frontend/${file}`, `dist/${file}`);
}
console.log("build: 3 frontend assets emitted");
