import { defineConfig } from "vitest/config";
import path from "node:path";

// Only pure logic (src/lib, src/api) is unit-tested here: those modules never import react-native, so they run in plain Node.
export default defineConfig({
  test: { include: ["src/**/*.test.ts"], environment: "node" },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
});
