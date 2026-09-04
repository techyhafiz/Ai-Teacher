/* AI Teacher — API client (all backend calls go through here) */
'use strict';

const API = (() => {

  const base = '';   // same origin — FastAPI serves web/ at /

  async function jfetch(url, opts) {
    const r = await fetch(base + url, opts);
    if (!r.ok) {
      let msg = r.statusText;
      try { const j = await r.json(); msg = j.detail || msg; } catch (e) {}
      throw new Error(`API ${r.status}: ${msg}`);
    }
    return r;
  }

  async function getJSON(url) {
    const r = await jfetch(url);
    return r.json();
  }

  async function postJSON(url, body) {
    const r = await jfetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return r.json();
  }

  // ---- public API --------------------------------------------------------

  return {
    // learners
    listLearners: () => getJSON('/api/learners'),
    getLearner: (id) => getJSON(`/api/learners/${id}`),
    createLearner: (name, language, level) =>
      postJSON('/api/learners', { name, language, level }),

    // documents
    uploadDocument: async (file, learnerId, languageHint, onProgress) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('learner_id', learnerId);
      fd.append('language_hint', languageHint);
      const r = await new Promise((res, rej) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload');
        xhr.upload.onprogress = (e) => {
          if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) res(xhr.responseText);
          else rej(new Error(`Upload failed: ${xhr.status} ${xhr.responseText}`));
        };
        xhr.onerror = () => rej(new Error('Network error during upload'));
        xhr.send(fd);
      });
      return JSON.parse(r);
    },

    // sessions + planning
    createSession: (body) => postJSON('/api/sessions', body),
    getSession: (id) => getJSON(`/api/sessions/${id}`),

    // capture
    captureAll: (sessionId, variant) =>
      postJSON(`/api/sessions/${sessionId}/capture?variant=${variant || 'main'}`, {}),
    captureOne: (sessionId, body) =>
      postJSON(`/api/sessions/${sessionId}/capture-one`, body),
    listPerformances: (sessionId) =>
      getJSON(`/api/performances/${sessionId}`),
    performanceAudioUrl: (sessionId, wavName) =>
      `${base}/api/performances/${sessionId}/${wavName}`,
    generateSlide: (sessionId, body) =>
      postJSON(`/api/sessions/${sessionId}/slide`, body),

    // checkpoints / brain
    checkpoint: (sessionId, body) =>
      postJSON(`/api/sessions/${sessionId}/checkpoint`, body),
    regen: (sessionId, body) =>
      postJSON(`/api/sessions/${sessionId}/regen`, body),

    // quiz + report
    quizAnswer: (sessionId, body) =>
      postJSON(`/api/sessions/${sessionId}/quiz`, body),
    makeReport: (sessionId) =>
      postJSON(`/api/sessions/${sessionId}/report`, {}),

    // learning path
    learningPath: (topic, language, learnerId) =>
      postJSON('/api/learning-path', { topic, language, learner_id: learnerId }),

    // metrics
    metrics: () => getJSON('/api/metrics'),
  };
})();
