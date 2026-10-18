import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { readFileSync } from "node:fs";

export default defineConfig({
  plugins: [
    tailwindcss(),
    {
      name: "include-source-licenses",
      generateBundle() {
        this.emitFile({
          type: "asset",
          fileName: "third-party/linux-do-cdk-LICENSE.txt",
          source: readFileSync(
            new URL("./third-party/linux-do-cdk-LICENSE.txt", import.meta.url),
            "utf8",
          ),
        });
        this.emitFile({
          type: "asset",
          fileName: "LICENSE.txt",
          source: readFileSync(new URL("../LICENSE", import.meta.url), "utf8"),
        });
      },
    },
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    license: true,
    rolldownOptions: {
      onwarn(warning, defaultHandler) {
        // This preview is entirely client-side; Next.js client directives have no effect.
        if (
          warning.code === "MODULE_LEVEL_DIRECTIVE" &&
          warning.message.includes("use client")
        )
          return;
        defaultHandler(warning);
      },
    },
  },
});
