import { createHash } from 'node:crypto';
import { loadEnvFile } from 'node:process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';
import { Spectrum, attachment, poll } from 'spectrum-ts';
import { imessage } from 'spectrum-ts/providers/imessage';

const MAX_TEXT = 16_000;
const ref = (id) => createHash('sha256').update(String(id)).digest('hex').slice(0, 12);
const log = (event, id) => console.log(JSON.stringify({ event, ...(id ? { ref: ref(id) } : {}) }));
const validId = (id) => typeof id === 'string' && id.length > 0 && id.length <= 2048 && !/[\u0000-\u001f\u007f]/u.test(id);
const validText = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= MAX_TEXT;
// SDK canonical chat GUIDs, never an arbitrary phone passed into space.create().
export const isDirectSpaceId = (id) => validId(id) && /^[^;\s]+;-;[^;\s]+$/u.test(id);

export function inboundPayload(space, message) {
  if (message?.platform !== 'imessage' || message.direction !== 'inbound'
      || message.sender?.kind === 'agent' || space?.type !== 'dm'
      || !isDirectSpaceId(space.id) || !validId(message.id) || !validId(message.sender?.id)) return null;
  const base = { message_id: message.id, sender_id: message.sender.id, space_id: space.id };
  const content = message.content;
  if (content?.type === 'text' && validText(content.text)) return { ...base, text: content.text };
  if (content?.type === 'poll_option' && content.selected === true) {
    const pollId = content.pollMessageGuid ?? content.poll?.pollMessageGuid;
    const option = content.option;
    if (validId(pollId) && validId(option?.optionIdentifier) && validText(option.title)) {
      return { ...base, text: option.title, poll_id: pollId, option_id: option.optionIdentifier };
    }
  }
  return null;
}

export async function processInbound(space, message, bridge, emit = log) {
  const payload = inboundPayload(space, message);
  if (!payload) return;
  const result = await bridge('/api/recovery/photon/inbound', { method: 'POST', body: payload });
  if (result?.duplicate === true) {
    emit('inbound_duplicate', message.id);
    return;
  }
  if (!validText(result?.reply)) {
    emit('inbound_processed_no_reply', message.id);
    return;
  }
  // Never retry a provider send: a transport error can follow a successful send.
  await space.send(result.reply);
  emit('inbound_replied', message.id);
}

export function createBridge(baseUrl, secret, shutdownSignal, fetcher = fetch) {
  const base = new URL(baseUrl);
  if (base.username || base.password || base.search || base.hash
      || !['http:', 'https:'].includes(base.protocol)
      || (base.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(base.hostname))) {
    throw new Error('invalid_bridge_url');
  }
  return async (path, { method = 'GET', body } = {}) => {
    const response = await fetcher(new URL(path, base), {
      method,
      redirect: 'error',
      headers: { Authorization: `Bearer ${secret}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal: AbortSignal.any([shutdownSignal, AbortSignal.timeout(15_000)]),
    });
    if (!response.ok) throw new Error(`bridge_http_${response.status}`);
    if (response.status === 204) return null;
    return response.json();
  };
}

export function createOutboxHandler({ bridge, getSpace, emit = log }) {
  // If the send succeeds but ACK fails, only the ACK is retried. The backend
  // also claims rows atomically; it must not blindly recycle uncertain sends.
  const pendingAcks = new Map();
  const acknowledged = new Map();
  async function ack(id, result) {
    pendingAcks.set(id, result);
    await bridge(`/api/recovery/photon/outbox/${encodeURIComponent(id)}/ack`, { method: 'POST', body: result });
    pendingAcks.delete(id);
    acknowledged.set(id, true);
    if (acknowledged.size > 10_000) acknowledged.delete(acknowledged.keys().next().value);
    emit(result.status === 'sent' ? 'outbox_sent' : 'outbox_failed', id);
  }
  return {
    async flushAcks() {
      for (const [id, result] of pendingAcks) {
        try { await ack(id, result); } catch { emit('outbox_ack_pending', id); }
      }
    },
    async deliver(item) {
      if (!validId(item?.id)) return;
      if (acknowledged.has(item.id)) return;
      if (pendingAcks.has(item.id)) {
        await ack(item.id, pendingAcks.get(item.id));
        return;
      }
      let result;
      if (!isDirectSpaceId(item.space_id) || !validText(item.text)) {
        result = { status: 'failed', error: 'invalid_outbox_item' };
      } else {
        let space;
        try { space = await getSpace(item.space_id); }
        catch { result = { status: 'failed', error: 'conversation_unavailable' }; }
        if (!result && (space?.type !== 'dm' || space.id !== item.space_id)) {
          result = { status: 'failed', error: 'direct_conversation_required' };
        }
        if (!result) {
          try {
            let sent;
            if (Array.isArray(item.choices)) {
              sent = await space.send(poll(item.text, ...item.choices));
            } else if (typeof item.card_png === 'string' && item.card_png.length < 1_000_000) {
              const card = attachment(Buffer.from(item.card_png, 'base64'), {
                name: 'Brace Weather Advisory.png', mimeType: 'image/png',
              });
              [, sent] = await space.send(card, item.text);
            } else {
              sent = await space.send(item.text);
            }
            result = { status: 'sent', ...(validId(sent?.id) ? { provider_message_id: sent.id } : {}) };
          } catch {
            result = { status: 'failed', error: 'provider_send_failed_delivery_uncertain' };
          }
        }
      }
      await ack(item.id, result);
    },
  };
}

export async function runWorker(env = process.env) {
  for (const name of ['PHOTON_PROJECT_ID', 'PHOTON_PROJECT_SECRET', 'BRACE_PHOTON_BRIDGE_SECRET']) {
    if (typeof env[name] !== 'string' || !env[name].trim()) throw new Error(`missing_${name}`);
  }
  const stop = new AbortController();
  const bridge = createBridge(env.BRACE_PHOTON_BRIDGE_URL || 'http://127.0.0.1:8011', env.BRACE_PHOTON_BRIDGE_SECRET, stop.signal);
  let app;
  let stopping;
  const shutdown = () => {
    if (stopping) return stopping;
    stop.abort();
    log('worker_stopping');
    stopping = Promise.resolve(app?.stop()).catch(() => log('sdk_stop_failed'));
    return stopping;
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
  try {
    app = await Spectrum({
      projectId: env.PHOTON_PROJECT_ID,
      projectSecret: env.PHOTON_PROJECT_SECRET,
      providers: [imessage.config()],
      telemetry: false,
      options: { logLevel: 'silent' },
      signal: stop.signal,
    });
    if (stop.signal.aborted) { await app.stop(); return; }
    const im = imessage(app);
    const outbox = createOutboxHandler({ bridge, getSpace: (id) => im.space.get(id) });
    log('worker_ready');
    const inbound = async () => {
      for await (const [space, message] of app.messages) {
        if (stop.signal.aborted) break;
        try { await processInbound(space, message, bridge); }
        catch { if (!stop.signal.aborted) log('inbound_failed', message?.id); }
      }
      if (!stop.signal.aborted) throw new Error('incoming_stream_closed');
    };
    const outbound = async () => {
      while (!stop.signal.aborted) {
        try {
          await outbox.flushAcks();
          const result = await bridge('/api/recovery/photon/outbox');
          if (!Array.isArray(result?.items)) throw new Error('invalid_outbox_response');
          for (const item of result.items) {
            if (stop.signal.aborted) break;
            try { await outbox.deliver(item); }
            catch { log('outbox_ack_pending', item?.id); }
          }
        } catch { if (!stop.signal.aborted) log('outbox_poll_failed'); }
        try { await sleep(1500, undefined, { signal: stop.signal }); } catch { break; }
      }
    };
    await Promise.all([inbound(), outbound()]);
  } finally {
    await shutdown();
    process.removeListener('SIGINT', shutdown);
    process.removeListener('SIGTERM', shutdown);
  }
}

async function selftest() {
  const assert = (await import('node:assert/strict')).default;
  const requests = [];
  const sends = [];
  const space = { id: 'any;-;+15550000000', type: 'dm', send: async (text) => { sends.push(text); return { id: 'provider-receipt' }; } };
  const message = { id: 'incoming-1', platform: 'imessage', direction: 'inbound', sender: { id: '+15550000000' }, content: { type: 'text', text: 'status' } };
  assert.equal(inboundPayload({ ...space, type: 'group' }, message), null);
  assert.equal(inboundPayload(space, { ...message, direction: 'outbound' }), null);
  assert.equal(inboundPayload({ ...space, id: '+15550000000' }, message), null);
  await processInbound(space, message, async (path, request) => { requests.push({ path, ...request }); return { reply: 'Private status', kind: 'status', duplicate: false }; }, () => {});
  assert.equal(sends.length, 1);
  assert.deepEqual(requests[0].body, { message_id: message.id, sender_id: message.sender.id, space_id: space.id, text: 'status' });
  await processInbound(space, message, async () => ({ reply: 'Private status', duplicate: true }), () => {});
  assert.equal(sends.length, 1);
  let ackFails = true;
  const acks = [];
  const outbox = createOutboxHandler({ getSpace: async () => space, emit: () => {}, bridge: async (_path, request) => { acks.push(request.body); if (ackFails) throw new Error('backend unavailable'); } });
  const item = { id: 'notice-1', space_id: space.id, text: 'Owner-approved update' };
  await assert.rejects(outbox.deliver(item));
  assert.equal(sends.length, 2);
  ackFails = false;
  await outbox.deliver(item);
  await outbox.deliver(item);
  assert.equal(sends.length, 2);
  assert.deepEqual(acks[1], { status: 'sent', provider_message_id: 'provider-receipt' });
  await outbox.deliver({ ...item, id: 'notice-group', space_id: 'any;+;group' });
  assert.equal(acks.at(-1).status, 'failed');
  assert.equal(sends.length, 2);
  const failureAcks = [];
  const uncertain = createOutboxHandler({ emit: () => {}, getSpace: async () => ({ ...space, send: async () => { throw new Error('uncertain'); } }), bridge: async (_path, request) => { failureAcks.push(request.body); } });
  await uncertain.deliver({ ...item, id: 'uncertain' });
  assert.deepEqual(failureAcks[0], { status: 'failed', error: 'provider_send_failed_delivery_uncertain' });
  assert.throws(() => createBridge('http://example.com', 'secret', new AbortController().signal), /invalid_bridge_url/);
  log('selftest_passed');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv.includes('--selftest')) {
    await selftest();
  } else {
    try {
      try { loadEnvFile(fileURLToPath(new URL('../../.env', import.meta.url))); }
      catch (error) { if (error.code !== 'ENOENT') throw new Error('env_file_unreadable'); }
      await runWorker();
    } catch (error) {
      // Never emit SDK error objects: they can contain addresses or credentials.
      log(/^missing_[A-Z_]+$/.test(error.message) ? error.message : 'worker_failed');
      process.exitCode = 1;
    }
  }
}
