import { defineConfig, loadEnv } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { readFileSync } from "node:fs";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(
    mode,
    fileURLToPath(new URL(".", import.meta.url)),
    "VEXBOT_",
  );
  const backend = new URL(
    process.env.VEXBOT_BACKEND_URL ||
      environment.VEXBOT_BACKEND_URL ||
      "http://127.0.0.1:5800",
  );
  if (
    !["http:", "https:"].includes(backend.protocol) ||
    backend.username ||
    backend.password ||
    backend.pathname !== "/" ||
    backend.search ||
    backend.hash
  ) {
    throw new Error(
      "VEXBOT_BACKEND_URL must be an HTTP(S) origin without credentials or a path",
    );
  }
  const proxy = {
    "/api": {
      target: backend.origin,
      changeOrigin: true,
      proxyTimeout: 15000,
      timeout: 15000,
    },
  };
  return {
    server: { proxy },
    preview: { proxy },
    plugins: [
      tailwindcss(),
      {
        name: "include-source-licenses",
        generateBundle() {
          this.emitFile({
            type: "asset",
            fileName: "third-party/linux-do-cdk-LICENSE.txt",
            source: readFileSync(
              new URL(
                "./third-party/linux-do-cdk-LICENSE.txt",
                import.meta.url,
              ),
              "utf8",
            ),
          });
          this.emitFile({
            type: "asset",
            fileName: "LICENSE.txt",
            source: readFileSync(
              new URL("../LICENSE", import.meta.url),
              "utf8",
            ),
          });
        },
      },
    ],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
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
  };
});
