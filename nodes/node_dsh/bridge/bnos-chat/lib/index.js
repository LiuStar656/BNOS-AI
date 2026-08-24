/**
 * BNOS 桥接 — 宿主半边（Node ESM，跑在 dsh web 进程内）
 *
 * 职责：把浏览器端 BNOS 聊天视图的请求翻译成 BNOS 文件协议，
 * 读写 nodes/shared/ 下的 gui_input.json / gui_reply.json（与 PySide6
 * MessageManager 同协议，节点层零改动）。
 *
 * 路由：
 *   POST /bnos/api/send  {content, conversation_id, request_id} → 写 gui_input.json
 *   GET  /bnos/api/poll  轮询 gui_reply.json（mtime + md5 判新）→ 返回 reply
 *
 * shared 目录定位：优先环境变量 BNOS_SHARED_DIR；兜底从 cwd 向上找 nodes/shared。
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const inject = ["webServer"];

const ROUTE_PREFIX = "/bnos/api";

function resolveSharedDir() {
  // 环境变量优先且权威（web_server.py 注入）；目录不存在没关系，send 时 mkdir。
  const fromEnv = process.env.BNOS_SHARED_DIR;
  if (fromEnv) return fromEnv;
  let dir = process.cwd();
  for (let i = 0; i < 8; i++) {
    const cand = path.join(dir, "nodes", "shared");
    if (fs.existsSync(cand)) return cand;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.join(process.cwd(), "nodes", "shared");
}

const SHARED = resolveSharedDir();
const INPUT = path.join(SHARED, "gui_input.json");
const REPLY = path.join(SHARED, "gui_reply.json");

// 上次已消费的 reply 状态（mtime + hash），判新逻辑与 MessageManager 一致：
// 只有「mtime 更新且内容 hash 不同」才算新回复，避免重复消费同一份回执。
let lastReplyMtime = 0;
let lastReplyHash = "";

function initLastReply() {
  try {
    if (!fs.existsSync(REPLY)) return;
    const stat = fs.statSync(REPLY);
    const raw = fs.readFileSync(REPLY, "utf8");
    lastReplyMtime = stat.mtimeMs;
    lastReplyHash = crypto.createHash("md5").update(raw).digest("hex");
  } catch {
    /* 启动时读不到就保持初始值，首个新回复会正常触发 */
  }
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try {
        const text = Buffer.concat(chunks).toString("utf8").trim();
        resolve(text ? JSON.parse(text) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

/** 发送一条用户输入（协议与 MessageManager.send_text 完全同构）。 */
async function handleSend(req, res) {
  let body;
  try {
    body = await readBody(req);
  } catch {
    return sendJson(res, 400, { ok: false, error: "invalid json body" });
  }
  const content = String(body.content ?? "").trim();
  if (!content) return sendJson(res, 400, { ok: false, error: "empty content" });
  const data = {
    data_type: "text",
    content,
    source: "gui",
    identity_key: "gui:web",
    conversation_id: String(body.conversation_id || "default"),
    request_id: String(body.request_id || ""),
    timestamp: new Date().toISOString(),
  };
  if (Array.isArray(body.attachments) && body.attachments.length) {
    data.attachments = body.attachments;
  }
  try {
    fs.mkdirSync(SHARED, { recursive: true });
    // 原子写：tmp + rename，与 BNOS shared 协议一致，避免并发读撕裂
    fs.writeFileSync(INPUT + ".tmp", JSON.stringify(data, null, 2), "utf8");
    fs.renameSync(INPUT + ".tmp", INPUT);
    return sendJson(res, 200, { ok: true, request_id: data.request_id });
  } catch (err) {
    return sendJson(res, 500, { ok: false, error: String((err && err.message) || err) });
  }
}

/** 轮询 gui_reply.json，返回新回复（无新回复返回 reply: null）。 */
async function handlePoll(req, res) {
  try {
    if (!fs.existsSync(REPLY)) return sendJson(res, 200, { ok: true, reply: null });
    const stat = fs.statSync(REPLY);
    const raw = fs.readFileSync(REPLY, "utf8");
    const hash = crypto.createHash("md5").update(raw).digest("hex");
    const isNew = stat.mtimeMs > lastReplyMtime && hash !== lastReplyHash;
    if (!isNew) return sendJson(res, 200, { ok: true, reply: null });
    lastReplyMtime = stat.mtimeMs;
    lastReplyHash = hash;
    const reply = JSON.parse(raw);
    const content = String(reply.content || "");
    return sendJson(res, 200, {
      ok: true,
      reply: {
        content,
        request_id: String(reply.request_id || ""),
        pending: content.includes("<pending"),
      },
    });
  } catch (err) {
    return sendJson(res, 500, { ok: false, error: String((err && err.message) || err) });
  }
}

export const name = "@bnos/bridge";

export function apply(ctx, config) {
  try {
    initLastReply();

    const routes = {
      "/bnos/api/send": handleSend,
      "/bnos/api/poll": handlePoll,
    };

    const handler = (req, res) => {
      let pathname;
      try {
        pathname = new URL(req.url, "http://localhost").pathname;
      } catch {
        return sendJson(res, 400, { ok: false, error: "bad request" });
      }
      const fn = routes[pathname];
      if (!fn) {
        res.writeHead(404);
        return res.end();
      }
      fn(req, res).catch((err) => {
        try {
          sendJson(res, 500, { ok: false, error: String((err && err.message) || err) });
        } catch {
          /* 响应已发出，忽略 */
        }
      });
    };

    const dispose = ctx.webServer.register({
      kind: "prefix",
      path: ROUTE_PREFIX,
      handler,
    });
    return dispose;
  } catch (error) {
    console.warn("[bnos-bridge] webServer routes unavailable: " + (error?.message || error));
    return () => {};
  }
}
