import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/unit/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    env: { TZ: "UTC" },
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/lib/api/schema.ts",
        "src/app/**/layout.tsx",
        "src/app/**/page.tsx",
        "src/middleware.ts",
        "src/i18n/**",
      ],
      thresholds: { lines: 80, statements: 80, functions: 80, branches: 75 },
      reporter: ["text-summary", "text", "lcov"],
    },
  },
});
