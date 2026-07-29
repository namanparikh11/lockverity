// ESLint v10 flat config for the Lockverity frontend.
//
// This file replaces the legacy `.eslintrc.cjs`.
//
// v0.4.0-public-closure-cycle-7: migration from ESLint 8 / .eslintrc
// to ESLint 10 / eslint.config.js.
//
// The previous `.eslintrc.cjs` extended `plugin:react/recommended`
// from `eslint-plugin-react@7.37.5`. That release pulls in
// `minimatch@^3.1.2` as a direct dependency, which in turn pulls in
// `brace-expansion@1.1.16`. The npm advisory database flags the
// `brace-expansion <=5.0.7` family as vulnerable to
// GHSA-mh99-v99m-4gvg / CVE-2026-14257. Pinning to
// `eslint-plugin-react@7.22.0` removes the `minimatch` dep but the
// plugin still uses the pre-ESLint 8 rule-context API
// (`context.getSourceCode()`) and is therefore not runtime-compatible
// with ESLint 9 or 10. The `eslint-plugin-react` maintainers have not
// published an 8.x or 10.x-compatible release, and no replacement
// plugin in the same rule namespace supports ESLint 10 without
// pulling in the same vulnerable chain.
//
// v0.4.0-public-closure-cycle-7-final: the four material
// preventive React lint rules from `plugin:react/recommended`
// are restored via `@eslint-react/eslint-plugin@5.18.0` (a
// modern ESLint-10-compatible plugin with no vulnerable
// transitive `minimatch` or `brace-expansion` deps). The
// remaining 15 rules are documented in
// ``UNCOVERED_LEGACY_REACT_RULES`` and are explicitly
// out-of-scope for this release (per the operator
// instruction "do not restore all 19 rules merely for
// historical parity"). The exact mapping for the four
// restored rules is recorded in
// ``RESTORED_REACT_RULE_MAPPING`` below.

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import reactRefreshPlugin from "eslint-plugin-react-refresh";
import eslintReactPlugin from "@eslint-react/eslint-plugin";

// `plugin:react/recommended` rules from eslint-plugin-react that
// are still intentionally uncovered after the cycle-7 final
// closure. The four rules restored via
// `@eslint-react/eslint-plugin` are listed in
// ``RESTORED_REACT_RULE_MAPPING`` below; the rest are
// documented here for traceability. None of these
// uncovered rules is in the four-rule material set
// (jsx keys, unsafe target=_blank, danger-with-children,
// unknown DOM/JSX properties).
export const UNCOVERED_LEGACY_REACT_RULES = {
  "react/display-name": 2,
  "react/jsx-no-comment-textnodes": 2,
  "react/jsx-no-duplicate-props": 2,
  "react/jsx-no-undef": 2,
  "react/jsx-uses-react": 2,
  "react/jsx-uses-vars": 2,
  "react/no-children-prop": 2,
  "react/no-deprecated": 2,
  "react/no-direct-mutation-state": 2,
  "react/no-find-dom-node": 2,
  "react/no-is-mounted": 2,
  "react/no-render-return-value": 2,
  "react/no-string-refs": 2,
  "react/no-unescaped-entities": 2,
  "react/no-unsafe": 0,
  "react/prop-types": 2,
  "react/react-in-jsx-scope": 2,
  "react/require-render-return": 2,
};

// Exact mapping of the four material ``plugin:react/recommended``
// rules restored by the cycle-7-final closure. Each entry
// records the legacy rule name, the new rule name in the
// installed plugin (``@eslint-react/eslint-plugin@5.18.0``),
// and the severity. Every name was confirmed against the
// installed plugin's ``rules`` object (see the cycle-7
// release audit).
export const RESTORED_REACT_RULE_MAPPING = {
  "react/jsx-key": {
    legacy_severity: 2,
    new_rule: "@eslint-react/no-missing-key",
    new_severity: "error",
    notes:
      "Closest semantic match. ``react/jsx-key`` fires on every "
      + "implicit-key iterable; ``@eslint-react/no-missing-key`` "
      + "fires on the same patterns (plus adjacent array-index-key "
      + "warnings via ``@eslint-react/no-array-index-key``). The "
      + "duplicated-key sub-pattern is covered separately by "
      + "``@eslint-react/no-duplicate-key`` below.",
  },
  "react/jsx-no-target-blank": {
    legacy_severity: 2,
    new_rule: "@eslint-react/dom-no-unsafe-target-blank",
    new_severity: "error",
    notes:
      "Exact semantic match. Catches ``<a target=\"_blank\">`` "
      + "without a ``rel=\"noopener noreferrer\"`` and warns when "
      + "``target=\"_blank\"`` is used with a string variable "
      + "(reverse-tabnabbing protection).",
  },
  "react/no-danger-with-children": {
    legacy_severity: 2,
    new_rule: "@eslint-react/dom-no-dangerously-set-innerhtml-with-children",
    new_severity: "error",
    notes:
      "Closest semantic match. ``react/no-danger-with-children`` "
      + "fires on ``<Component dangerouslySetInnerHTML={...}>"
      + "{children}</Component>``. The @eslint-react rule "
      + "covers the same pattern on the DOM ``dangerously"
      + "SetInnerHTML`` attribute, which is the practical "
      + "manifestation in cycle 1-7 source code.",
  },
  "react/no-unknown-property": {
    legacy_severity: 2,
    new_rule: "@eslint-react/dom-no-unknown-property",
    new_severity: "error",
    notes:
      "Exact semantic match. Catches unknown DOM/JSX "
      + "properties on built-in elements and on the registered "
      + "custom elements.",
  },
  // ``react/jsx-key`` is complemented by ``@eslint-react/no-duplicate-key``
  // which catches the duplicate-key half of the same protection.
  "react/jsx-key (duplicate half)": {
    legacy_severity: 2,
    new_rule: "@eslint-react/no-duplicate-key",
    new_severity: "error",
    notes: "Catches duplicate ``key`` props across sibling iterables.",
  },
};

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      ".eslintcache",
      "*.config.js",
      "*.config.cjs",
      "*.config.mjs",
      "eslint.config.js",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        // Browser globals (jsdom-style subset)
        window: "readonly",
        document: "readonly",
        navigator: "readonly",
        console: "readonly",
        fetch: "readonly",
        Response: "readonly",
        Request: "readonly",
        Headers: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        FormData: "readonly",
        Blob: "readonly",
        File: "readonly",
        FileReader: "readonly",
        AbortController: "readonly",
        AbortSignal: "readonly",
        crypto: "readonly",
        localStorage: "readonly",
        sessionStorage: "readonly",
        HTMLElement: "readonly",
        HTMLInputElement: "readonly",
        HTMLFormElement: "readonly",
        HTMLButtonElement: "readonly",
        HTMLAnchorElement: "readonly",
        Element: "readonly",
        Event: "readonly",
        MouseEvent: "readonly",
        KeyboardEvent: "readonly",
        CustomEvent: "readonly",
        Promise: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        queueMicrotask: "readonly",
        structuredClone: "readonly",
        // Node globals (subset used by Vitest config / scripts)
        process: "readonly",
        global: "readonly",
        Buffer: "readonly",
      },
    },
    plugins: {
      "@eslint-react": eslintReactPlugin,
      "react-hooks": reactHooksPlugin,
      "react-refresh": reactRefreshPlugin,
    },
    rules: {
      // The cycle 1-6 `.eslintrc.cjs` did not enable
      // `no-useless-assignment` (introduced in
      // @typescript-eslint v7 as a stable rule and folded into
      // the cycle-7 v8 `recommended` preset). Disabling it here
      // preserves the cycle 1-6 source code, which uses the
      // common `let x = sentinel; x = computed;` pattern in
      // async-test scaffolds.
      "no-useless-assignment": "off",
      // TypeScript-ESLint `no-unused-vars` override from the
      // legacy config (preserves the cycle-1-3 `_` ignore
      // pattern).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // `plugin:react-hooks/recommended` parity with the
      // cycle 1-6 `4.6.2` setup. The 7.1.1 release adds
      // several new rules (`set-state-in-effect`, `purity`,
      // `set-state-in-render`, `error-boundaries`,
      // `void-use-memo`, `gating`, `config`,
      // `unsupported-syntax`, `incompatible-library`,
      // `immutability`, `refs`, `globals`,
      // `preserve-manual-memoization`, `use-memo`,
      // `static-components`) that the cycle 1-6 source code
      // does not yet comply with. We preserve the legacy
      // two-rule coverage here; a follow-up audit pass can
      // decide which new rules to opt in to.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // `react-refresh/only-export-components` from the
      // legacy config (was
      // `plugin:react-refresh/recommended` equivalent).
      // The ``allowConstantExport`` option is preserved.
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      // v0.4.0 cycle-7 final: the four material
      // ``plugin:react/recommended`` rules. See
      // ``RESTORED_REACT_RULE_MAPPING`` above for the exact
      // mapping rationale. Each is set to ``error`` to
      // match the original ``plugin:react/recommended``
      // severity of 2.
      "@eslint-react/no-missing-key": "error",
      "@eslint-react/no-duplicate-key": "error",
      "@eslint-react/dom-no-unsafe-target-blank": "error",
      "@eslint-react/dom-no-dangerously-set-innerhtml-with-children": "error",
      "@eslint-react/dom-no-unknown-property": "error",
    },
  },
  {
    // Type-aware rules disabled for config / test fixture
    // files (matches the cycle 1-6 ``.eslintrc.cjs``
    // behaviour).
    files: [
      "**/*.test.{ts,tsx}",
      "**/__tests__/**",
      "**/test/**",
      "vitest.config.ts",
      "vite.config.ts",
    ],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-empty-object-type": "off",
    },
  },
];
