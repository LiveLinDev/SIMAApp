import http from "node:http";
import { request as httpRequest } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, ".");

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

const PORT = envInt("PROXY_IA_PORT", 8003);
const TARGET_HOST = envText("PROXY_IA_TARGET_HOST", "127.0.0.1");
const TARGET_PORT = envInt("PROXY_IA_TARGET_PORT", 8001);
const TIMEOUT_MS = envInt("PROXY_IA_TIMEOUT_MS", 7_200_000);
const TARGET_URL = "http://" + TARGET_HOST + ":" + TARGET_PORT;

function log(msg) {
  const stamp = new Date().toISOString();
  console.log("[" + stamp + "] " + msg);
}

const server = http.createServer((req, res) => {
  const start = Date.now();
  log(req.method + " " + req.url);

  if (req.url === "/_proxy/health") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(
      JSON.stringify({
        ok: true,
        proxy: "0.0.0.0:" + PORT,
        target: TARGET_HOST + ":" + TARGET_PORT,
        timeout_ms: TIMEOUT_MS,
      })
    );
    return;
  }

  const headers = { ...req.headers };
  headers.host = TARGET_HOST + ":" + TARGET_PORT;

  const upstream = httpRequest(
    {
      host: TARGET_HOST,
      port: TARGET_PORT,
      method: req.method,
      path: req.url,
      headers,
      timeout: TIMEOUT_MS,
    },
    (upstreamRes) => {
      const elapsed = Date.now() - start;
      log("respuesta " + (upstreamRes.statusCode || 0) + " en " + elapsed + "ms");
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );

  upstream.on("timeout", () => {
    const elapsed = Date.now() - start;
    log("timeout upstream despues de " + elapsed + "ms");
    upstream.destroy();
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
      res.end(
        JSON.stringify({
          error: "Timeout llamando al modelo local",
          detail: "El modelo en " + TARGET_URL + " no respondio en " + TIMEOUT_MS + "ms.",
          hint: "Revisa que el servidor local (llama-server, LM Studio, etc.) este corriendo en el puerto correcto.",
        })
      );
    }
  });

  upstream.on("error", (err) => {
    const elapsed = Date.now() - start;
    log("error upstream despues de " + elapsed + "ms: " + err.message);
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
      res.end(
        JSON.stringify({
          error: "No se pudo conectar con " + TARGET_HOST + ":" + TARGET_PORT,
          detail: err.message,
          hint: "Verifica que el servidor de IA local este corriendo y que PROXY_IA_TARGET_HOST/PORT apunten al endpoint correcto.",
        })
      );
    }
  });

  req.pipe(upstream);
});

server.listen(PORT, "0.0.0.0", () => {
  log("Proxy IA listo en http://127.0.0.1:" + PORT + " -> " + TARGET_URL);
  log("Timeout configurado: " + TIMEOUT_MS + "ms");
});
