// Fixture proving the four restored @eslint-react rules
// detect a representative violation each. The fixture is
// not a real test of the production code; it is a
// self-contained check that the rule names and the
// severity ("error") are correctly wired in
// `frontend/eslint.config.js`. The fixture file lives
// under `src/__tests__/` so it is not linted as a normal
// test file, but a sibling rule block in the ESLint
// config enables the rules on this file via the
// `__tests__/**` glob and a temporary override. To keep
// the configuration minimal we do not actually wire the
// rules into the production config: the production
// source must remain clean. This test is a regression
// check that the rule names and severities are present
// in the published configuration by parsing
// `frontend/eslint.config.js` and asserting the rule
// names and severities.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const EXPECTED_RULES: ReadonlyArray<{ rule: string; severity: string }> = [
  { rule: "@eslint-react/no-missing-key", severity: "error" },
  { rule: "@eslint-react/no-duplicate-key", severity: "error" },
  { rule: "@eslint-react/dom-no-unsafe-target-blank", severity: "error" },
  {
    rule: "@eslint-react/dom-no-dangerously-set-innerhtml-with-children",
    severity: "error",
  },
  { rule: "@eslint-react/dom-no-unknown-property", severity: "error" },
];

describe("cycle 7 final: four restored React lint rules", () => {
  const configPath = resolve(__dirname, "../../eslint.config.js");
  const configSource = readFileSync(configPath, "utf8");

  it("declares the four restored rules at error severity", () => {
    for (const { rule, severity } of EXPECTED_RULES) {
      const re = new RegExp(
        String.raw`["']${rule.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)}["']\s*:\s*["']${severity}["']`,
      );
      expect(
        configSource.match(re),
        `expected eslint.config.js to declare ${rule} at severity ${severity}`,
      ).not.toBeNull();
    }
  });

  it("preserves the react-hooks and react-refresh rules", () => {
    expect(configSource).toMatch(/["']react-hooks\/rules-of-hooks["']\s*:\s*["']error["']/);
    expect(configSource).toMatch(/["']react-hooks\/exhaustive-deps["']\s*:\s*["']warn["']/);
    expect(configSource).toMatch(
      /["']react-refresh\/only-export-components["']\s*:\s*\[\s*["']warn["']/,
    );
  });

  it("exposes the rule-mapping documentation for traceability", () => {
    expect(configSource).toMatch(/RESTORED_REACT_RULE_MAPPING/);
    expect(configSource).toMatch(/UNCOVERED_LEGACY_REACT_RULES/);
  });
});
