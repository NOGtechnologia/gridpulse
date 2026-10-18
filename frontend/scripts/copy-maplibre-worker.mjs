// MapLibre GL 6 loads its web worker as a separate ES module next to the bundle.
// Next.js does not emit that file, so it is served from /maplibre/ (see FlowsMap.tsx).
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("maplibre-gl/dist/maplibre-gl.css"));
const target = join(import.meta.dirname, "..", "public", "maplibre");
mkdirSync(target, { recursive: true });
copyFileSync(join(dist, "maplibre-gl-worker.mjs"), join(target, "maplibre-gl-worker.mjs"));
console.log("copied maplibre-gl-worker.mjs to public/maplibre/");
