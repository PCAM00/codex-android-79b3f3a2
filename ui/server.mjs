// Codex UI: local web client for a Responses-API gateway. No external deps, Node >=18.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const PORT = Number(process.env.CODEX_UI_PORT || 8099);
const BASE = process.env.CODEX_UI_BASE || 'https://ps.air-outer.com/v1';
const MODEL = process.env.CODEX_UI_MODEL || 'gpt-6.1-sol';
const KEY_FILE = path.join(os.homedir(), '.codex-ui-key');
const UI = path.join(path.dirname(new URL(import.meta.url).pathname), 'index.html');

const readKey = () => {
  if (process.env.CODEX_UI_KEY) return process.env.CODEX_UI_KEY.trim();
  try { return fs.readFileSync(KEY_FILE, 'utf8').trim(); } catch { return ''; }
};
const saveKey = (key) => {
  fs.writeFileSync(KEY_FILE, key.trim() + '\n', { mode: 0o600 });
  fs.chmodSync(KEY_FILE, 0o600);
};

function send(res, code, type, body) {
  res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
  res.end(body);
}

async function chat(req, res) {
  const key = readKey();
  if (!key) return send(res, 401, 'application/json', JSON.stringify({ error: '尚未保存 API 令牌' }));
  let payload;
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return send(res, 400, 'application/json', JSON.stringify({ error: '请求体不是有效 JSON' }));
  }
  const turns = Array.isArray(payload.messages) ? payload.messages : [];
  if (!turns.length) return send(res, 400, 'application/json', JSON.stringify({ error: '没有消息' }));

  // Stateless replay: text only, no item ids — a multi-resource gateway rejects foreign ids.
  const input = turns
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && typeof m.text === 'string' && m.text.trim())
    .map((m) => ({ role: m.role, content: [{ type: m.role === 'user' ? 'input_text' : 'output_text', text: m.text }] }));

  const upstream = await fetch(`${BASE}/responses`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${key}`,
      'user-agent': 'codex-local-ui/1.0',
      originator: 'codex_cli_rs',
    },
    body: JSON.stringify({ model: payload.model || MODEL, input, stream: true, store: false }),
  });

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => '');
    return send(res, upstream.status || 502, 'application/json', JSON.stringify({ error: detail.slice(0, 400) || '上游返回失败' }));
  }

  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-store',
    connection: 'keep-alive',
  });
  const reader = upstream.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index).replace(/\r$/, '');
        buffer = buffer.slice(index + 1);
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (!raw || raw === '[DONE]') continue;
        let event;
        try { event = JSON.parse(raw); } catch { continue; }
        if (event.type === 'response.output_text.delta' && event.delta) {
          res.write(`data: ${JSON.stringify({ delta: event.delta })}\n\n`);
        } else if (event.type === 'response.completed') {
          res.write(`data: ${JSON.stringify({ done: true })}\n\n`);
        } else if (event.type === 'response.failed' || event.type === 'error') {
          res.write(`data: ${JSON.stringify({ error: JSON.stringify(event.error || event).slice(0, 300) })}\n\n`);
        }
      }
    }
  } catch (error) {
    res.write(`data: ${JSON.stringify({ error: String(error.message || error) })}\n\n`);
  }
  res.end();
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
    return send(res, 200, 'text/html; charset=utf-8', fs.readFileSync(UI));
  }
  if (req.method === 'GET' && url.pathname === '/api/state') {
    return send(res, 200, 'application/json', JSON.stringify({ hasKey: Boolean(readKey()), model: MODEL, base: BASE }));
  }
  if (req.method === 'POST' && url.pathname === '/api/key') {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    let body = {};
    try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { /* ignore */ }
    const key = String(body.key || '').trim();
    if (!/^sk-[A-Za-z0-9_-]{16,}$/.test(key)) return send(res, 400, 'application/json', JSON.stringify({ error: '令牌格式不像有效密钥' }));
    saveKey(key);
    return send(res, 200, 'application/json', JSON.stringify({ saved: true }));
  }
  if (req.method === 'POST' && url.pathname === '/api/chat') {
    try { return await chat(req, res); } catch (error) { return send(res, 500, 'application/json', JSON.stringify({ error: String(error.message || error) })); }
  }
  return send(res, 404, 'application/json', JSON.stringify({ error: 'not found' }));
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Codex UI ready: http://127.0.0.1:${PORT}/  (model ${MODEL})`);
  if (!readKey()) console.log('尚未保存 API 令牌：打开页面后填写。');
});
