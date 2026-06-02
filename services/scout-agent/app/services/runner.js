// 在 Playwright page.evaluate 里运行：单条 XHR 真打，返回原始结果（不算 verdict，verdict 在 Python 侧）。
// 入参 req = {method, url, body?, retry?, inter_delay_ms?}
// 返回 {status, ct, len, parsed|null, firstChars, error?, attempts}
async (req) => {
  const maxRetry = Math.max(1, req.retry || 3);
  const interDelay = req.inter_delay_ms || 1000;
  let last = null;
  let attempts = 0;
  for (let attempt = 1; attempt <= maxRetry; attempt++) {
    attempts = attempt;
    last = await new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      try { xhr.open(req.method || 'GET', req.url, true); }
      catch (e) { return resolve({ error: 'open error: ' + String(e), status: 0 }); }
      xhr.timeout = 15000;
      xhr.setRequestHeader('Accept', 'application/json');
      if ((req.method || 'GET').toUpperCase() === 'POST') {
        xhr.setRequestHeader('Content-Type', 'application/json');
      }
      xhr.onload = () => {
        const text = xhr.responseText || '';
        let parsed = null;
        try { parsed = JSON.parse(text.replace(/^[﻿\s]+/, '')); } catch (e) {}
        resolve({
          status: xhr.status,
          ct: xhr.getResponseHeader('content-type') || '',
          len: text.length,
          parsed,
          firstChars: text.slice(0, 250),
        });
      };
      xhr.onerror = () => resolve({ error: 'xhr network error', status: xhr.status || 0 });
      xhr.ontimeout = () => resolve({ error: 'timeout', status: 0 });
      try {
        if ((req.method || 'GET').toUpperCase() === 'POST' && req.body) xhr.send(JSON.stringify(req.body));
        else xhr.send();
      } catch (e) { resolve({ error: 'send error: ' + String(e), status: 0 }); }
    });
    const code = last.parsed && (last.parsed.code ?? last.parsed.Code ?? last.parsed.errno);
    const needRetry = last.error || last.status === 0 || last.status >= 500 || code === 500 || code === '500';
    if (!needRetry || attempt >= maxRetry) break;
    await new Promise((r) => setTimeout(r, interDelay));
  }
  return { ...last, attempts };
};
