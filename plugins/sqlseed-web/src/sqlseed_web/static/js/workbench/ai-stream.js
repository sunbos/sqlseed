import {tr, serverText, UserFacingError} from '../i18n.js';
import '../i18n/messages/assistant.js';
import { httpErrorMessage } from "../api.js";
const stages = new Set(['context', 'model', 'validation', 'preview']);
const invalid = () => new UserFacingError(tr("assistant.stream.invalid"));
function responseError(body, status) {
  const detail = body?.detail;
  const message = body?.detail_key ? serverText(body, 'detail') : httpErrorMessage(detail, status);
  const error = new UserFacingError(message, {originalMessage: httpErrorMessage(detail, status, false, false)});
  error.status = status;
  error.detail = detail;
  error.code = detail?.code;
  error.messageKey = detail?.message_key || body?.detail_key;
  return error;
}

// A terminal result is required: an HTTP 200 or a progress event alone never
// makes suggestions reviewable. The caller owns epoch and modal lifecycle checks.
export async function requestAISuggestions(path, request, {
  signal,
  onProgress
} = {}) {
  const checkAbort = () => {
    if (signal?.aborted) {
      const error = new UserFacingError(tr("assistant.stream.cancelled"));
      error.name = 'AbortError';
      throw error;
    }
  };
  checkAbort();
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/x-ndjson'
    },
    body: JSON.stringify(request),
    signal
  });
  checkAbort();
  const streamed = response.headers?.get('Content-Type')?.includes('application/x-ndjson');
  if (!response.ok || !streamed) {
    const body = await response.json().catch(() => null);
    checkAbort();
    if (!response.ok) throw responseError(body, response.status);
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw invalid();
    return body;
  }
  if (!response.body?.getReader) throw invalid();
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = '';
  const cancel = () => {
    reader.cancel().catch(() => {});
  };
  signal?.addEventListener('abort', cancel, {
    once: true
  });
  function event(line) {
    let value;
    try {
      value = JSON.parse(line);
    } catch {
      throw invalid();
    }
    if (value?.type === 'progress' && stages.has(value.stage) && typeof value.message === 'string') {
      onProgress?.({
        type: 'progress',
        stage: value.stage,
        message: value.message,
        ...(typeof value.message_key === 'string' ? {
          message_key: value.message_key, message_params: value.message_params
        } : {})
      });
      return null;
    }
    if (value?.type === 'result' && value.result && typeof value.result === 'object' && !Array.isArray(value.result)) return value;
    if (value?.type === 'error' && typeof value.message === 'string') {
      const error = new UserFacingError(serverText(value), {originalMessage: value.message});
      error.code = value.code;
      error.status = value.status;
      error.messageKey = value.message_key;
      throw error;
    }
    throw invalid();
  }
  try {
    for (;;) {
      checkAbort();
      const {
        value,
        done
      } = await reader.read();
      checkAbort();
      const lines = decodedLines(done, value);
      const terminal = consumeLines(lines);
      if (terminal) return terminal.result;
      if (done) throw new UserFacingError(tr("assistant.stream.incomplete"));
    }
  } finally {
    signal?.removeEventListener('abort', cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  function consumeLines(lines) {
    for (const line of lines) {
      checkAbort();
      if (!line.trim()) continue;
      const terminal = event(line);
      if (terminal) return terminal;
    }
  }
  function decodedLines(done, value) {
    buffer += done ? decoder.decode() : decoder.decode(value, {
      stream: true
    });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    if (done && buffer.trim()) {
      lines.push(buffer);
      buffer = '';
    }
    return lines;
  }
}
