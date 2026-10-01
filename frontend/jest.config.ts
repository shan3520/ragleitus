import fs from "node:fs";
import path from "node:path";

import type { Config } from "jest";
import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  // jsdom plus the fetch/stream globals Node provides (Response, ReadableStream, TextEncoder...).
  testEnvironment: "jest-fixed-jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
  testPathIgnorePatterns: ["<rootDir>/.next/", "<rootDir>/node_modules/", "<rootDir>/e2e/"],
};

/** Installed packages (including nested copies) that ship only ES modules: react-markdown and its unified/remark tree. */
function esmOnlyPackages(dir = path.join(process.cwd(), "node_modules"), found = new Set<string>()): Set<string> {
  if (!fs.existsSync(dir)) return found;
  const names = fs.readdirSync(dir).flatMap((name) =>
    name.startsWith("@") ? fs.readdirSync(path.join(dir, name)).map((sub) => `${name}/${sub}`) : [name],
  );
  for (const name of names) {
    const pkgDir = path.join(dir, name);
    try {
      if (JSON.parse(fs.readFileSync(path.join(pkgDir, "package.json"), "utf8")).type === "module") found.add(name);
    } catch {
      continue;
    }
    esmOnlyPackages(path.join(pkgDir, "node_modules"), found);
  }
  return found;
}

// next/jest leaves all of node_modules untransformed, which Jest (under Node 22)
// cannot load when a package is ESM-only. Transform exactly those packages.
export default async function jestConfig(): Promise<Config> {
  const resolved = await createJestConfig(config)();
  const escaped = [...esmOnlyPackages()].map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return {
    ...resolved,
    transformIgnorePatterns: [
      `/node_modules/(?!(${escaped.join("|")})/)`,
      ...(resolved.transformIgnorePatterns ?? []).filter((p) => !p.includes("node_modules")),
    ],
  };
}
