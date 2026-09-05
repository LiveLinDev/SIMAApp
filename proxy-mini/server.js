import http from "node:http";
import { request as httpRequest } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "..");

function loadDotenv(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }

  return fs
    .readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .reduce((env, rawLine) => {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) {
        return env;
      }

      const [key, ...valueParts] = line.split("=");
      env[key.trim()] = valueParts.join("=").trim().replace(/^['"]|['"]$/g, "");
      return env;
    }, {});
}

const env = { ...process.env, ...loadDotenv(path.join(ROOT_DIR, ".env")) };

function envText(name, fallback) {
  return String(env[name] ?? fallback).trim();
}

function envInt(name, fallback) {
  const value = Number.parseInt(envText(name, String(fallback)), 10);
  return Number.isFinite(value) ? value : fallback;
}

function envBool(name, fallback = false) {
  return ["1", "true", "yes", "on"].includes(envText(name, String(fallback)).toLowerCase());
}

// Destino del reenvio: por defecto el Django local. Para reenviar a otro host,
// cambia PROXY_TARGET_HOST / PROXY_TARGET_PORT en .env.
const PORT = envInt("PROXY_PORT", 25564);
const TARGET_HOST = envText("PROXY_TARGET_HOST", "127.0.0.1");
const TARGET_PORT = envInt("PROXY_TARGET_PORT", 8002);
const REWRITE_HOST = envBool("PROXY_REWRITE_HOST", false);

const server = http.createServer((req, res) => {
  if (req.url === "/_proxy/health") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(
      JSON.stringify({
        ok: true,
        proxy: `0.0.0.0:${PORT}`,
        target: `${TARGET_HOST}:${TARGET_PORT}`,
      })
    );
    return;
  }

  const headers = { ...req.headers };
  if (REWRITE_HOST) {
    headers.host = `${TARGET_HOST}:${TARGET_PORT}`;
  }

  const upstream = httpRequest(
    {
      host: TARGET_HOST,
      port: TARGET_PORT,
      method: req.method,
      path: req.url,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );

  upstream.on("error", (err) => {
    res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    res.end(
      JSON.stringify({
        error: `No se pudo conectar con el servidor en ${TARGET_HOST}:${TARGET_PORT}.`,
        detail: err.message,
        hint: "Ejecuta start-all.bat para cerrar puertos viejos y levantar Django antes del proxy.",
      })
    );
  });

  req.pipe(upstream);
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Proxy listo en http://127.0.0.1:${PORT} -> http://${TARGET_HOST}:${TARGET_PORT}`);
});
