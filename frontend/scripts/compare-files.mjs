// Fails if the freshly generated API types differ from the committed ones.
import { readFileSync, rmSync } from "node:fs";

const [generated, committed] = process.argv.slice(2);
const norm = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const same = norm(generated) === norm(committed);
rmSync(generated);
if (!same) {
  console.error(`${committed} is outdated - run: pnpm generate:api`);
  process.exit(1);
}
console.log(`${committed} is up to date`);
