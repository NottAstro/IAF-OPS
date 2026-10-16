// Wind sidecar (ARCHITECTURE §7.1): God's Eye View's wind server (vendor/, MIT) behind a tiny node:http wrapper.
// Same contract as God's Eye: GET /api/wind/manifest?model=gfs|ifs, /api/wind/grid/{id}.bin, /api/wind/status.
import http from "node:http";
import { windProxy } from "./vendor/server/providers/wind.js";

const PORT = Number(process.env.WIND_PORT || 8787);
let handler;
windProxy().configureServer({ middlewares: { use: (_prefix, h) => (handler = h) } });

http.createServer((req, res) => {
  if (!req.url.startsWith("/api/wind")) {
    res.writeHead(404, { "content-type": "application/json" });
    return res.end('{"error":"not_found"}');
  }
  req.url = req.url.slice("/api/wind".length) || "/";
  handler(req, res).catch((err) => {
    console.error("wind error", err);
    if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" });
    res.end('{"error":"wind_failed"}');
  });
}).listen(PORT, "127.0.0.1", () => console.log(`wind sidecar on http://127.0.0.1:${PORT}`));
