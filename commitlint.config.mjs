// Conventional Commits (spec 11.5): feat(adapter): …, fix(api): …, test(domain): …
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "scope-enum": [
      1,
      "always",
      ["adapter", "domain", "validation", "storage", "api", "worker", "alerts", "web", "ci", "deploy", "docs", "deps", "repo"],
    ],
  },
};
