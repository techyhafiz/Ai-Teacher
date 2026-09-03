/* AI Teacher — Setup screen logic */
'use strict';

const Setup = (() => {

  const $ = (id) => document.getElementById(id);

  let learners = [];
  let currentDoc = null;   // {doc_id, original_name, stats}

  async function init() {
    // tabs
    document.querySelectorAll('.tab').forEach(t => {
      t.onclick = () => switchTab(t.dataset.tab);
    });

    // learners
    await refreshLearners();
    $('learner-new').onclick = async () => {
      const name = $('learner-name').value.trim();
      if (!name) return toast('Enter a name first');
      const l = await API.createLearner(name, $('pref-language').value,
                                        $('pref-level').value);
      $('learner-name').value = '';
      await refreshLearners(l.id);
      toast(`Welcome, ${name}!`);
    };

    // upload
    const dz = $('dropzone');
    dz.onclick = () => $('file-input').click();
    $('dz-browse').onclick = (e) => { e.stopPropagation(); $('file-input').click(); };
    $('file-input').onchange = (e) => {
      if (e.target.files.length) handleFile(e.target.files[0]);
    };
    ['dragover', 'dragenter'].forEach(ev =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('drag'); }));
    dz.addEventListener('drop', (e) => {
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    $('doc-clear').onclick = () => {
      currentDoc = null;
      $('doc-info').classList.add('hidden');
      $('dropzone').classList.remove('hidden');
    };

    // start
    $('start-lesson').onclick = startLesson;
  }

  function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t =>
      t.classList.toggle('active', t.dataset.tab === tab));
    $('tab-topic').classList.toggle('hidden', tab !== 'topic');
    $('tab-upload').classList.toggle('hidden', tab !== 'upload');
  }

  async function refreshLearners(selectId) {
    learners = await API.listLearners();
    const sel = $('learner-select');
    sel.innerHTML = '<option value="">— select learner —</option>';
    for (const l of learners) {
      const o = document.createElement('option');
      o.value = l.id;
      o.textContent = `${l.name} (${l.level})`;
      sel.appendChild(o);
    }
    if (selectId) sel.value = selectId;
    else if (learners.length === 1) sel.value = learners[0].id;
  }

  async function handleFile(file) {
    const learnerId = requireLearner();
    if (!learnerId) return;
    showStatus(`Uploading & parsing "${file.name}"… (OCR + RAG ingest)`);
    try {
      const doc = await API.uploadDocument(file, learnerId,
        $('pref-language').value);
      currentDoc = doc;
      $('doc-name').textContent = '📄 ' + doc.original_name;
      $('doc-stats').textContent =
        `${doc.stats.sections} sections · ${Math.round(doc.stats.chars / 1000)}k chars` +
        (doc.stats.ocr_pages ? ` · ${doc.stats.ocr_pages} OCR pages` : '');
      $('doc-info').classList.remove('hidden');
      $('dropzone').classList.add('hidden');
      hideStatus();
      toast('Material ready — hit Start Lesson');
    } catch (e) {
      hideStatus();
      toast('Upload failed: ' + e.message);
    }
  }

  async function requireLearner() {
    let id = $('learner-select').value;
    if (id) return id;
    if (learners && learners.length > 0) {
      $('learner-select').value = learners[0].id;
      return learners[0].id;
    }
    // Auto-create default learner if none exists
    try {
      const l = await API.createLearner('Student', $('pref-language').value, $('pref-level').value);
      await refreshLearners(l.id);
      return l.id;
    } catch (e) {
      console.warn('Auto-create learner fallback:', e);
      return 'default_learner';
    }
  }

  async function startLesson() {
    const learnerId = await requireLearner();
    if (!learnerId) return;

    const language = $('pref-language').value;
    const level = $('pref-level').value;
    const timeBudget = $('pref-time').value;
    const persona = $('pref-teacher').value;

    const activeTab = document.querySelector('.tab.active').dataset.tab;
    let mode, topic, docId = null, docFocus = null;

    if (activeTab === 'topic') {
      topic = $('topic-input').value.trim();
      if (!topic) return toast('Type a topic to learn');
      mode = 'topic';
      if ($('path-toggle').checked) {
        return showLearningPath(topic, language, learnerId);
      }
    } else {
      if (!currentDoc) return toast('Upload a material first');
      topic = $('doc-focus').value.trim() || currentDoc.original_name;
      docId = currentDoc.doc_id;
      docFocus = $('doc-focus').value.trim() || null;
      mode = 'upload';
    }

    showStatus('Planning your personalized lesson…');
    try {
      const { session_id, plan } = await API.createSession({
        learner_id: learnerId, mode, topic, language, level,
        time_budget: timeBudget, doc_id: docId, doc_focus: docFocus, persona,
      });

      if (plan.kind === 'study_plan') {
        hideStatus();
        return showStudyPlan(plan);
      }

      // Fast-launch: capture segment 0 first so classroom starts with zero lag
      const seg0 = plan.segments[0];
      showStatus(`Preparing lesson: segment 1/${plan.segments.length} — "${seg0.concept || seg0.kind}"…`);
      try {
        await API.captureOne(session_id, { seg_id: seg0.seg_id, variant: 'main' });
      } catch (capErr) {
        console.warn('Segment 0 capture fallback:', capErr);
      }

      hideStatus();
      Classroom.start(session_id, {
        persona, language, learnerId,
      });

      // Capture remaining segments in background while student is listening to segment 0
      (async () => {
        for (let i = 1; i < plan.segments.length; i++) {
          const seg = plan.segments[i];
          try {
            await API.captureOne(session_id, { seg_id: seg.seg_id, variant: 'main' });
            console.info(`Captured segment ${i} in background:`, seg.concept);
          } catch (err) {
            console.warn(`Background capture for segment ${i} failed:`, err);
          }
        }
      })();
    } catch (e) {
      hideStatus();
      toast('Failed: ' + e.message);
      console.error(e);
    }
  }

  async function showLearningPath(topic, language, learnerId) {
    showStatus('Designing your learning path…');
    try {
      const path = await API.learningPath(topic, language, learnerId);
      hideStatus();
      // render path in a dialog with "start milestone 1" button
      const box = document.createElement('div');
      box.className = 'checkpoint-overlay';
      box.style.cssText = 'position:fixed;inset:0;background:rgba(12,8,5,.6);z-index:50;display:flex;align-items:center;justify-content:center;';
      const card = document.createElement('div');
      card.className = 'cp-card';
      card.innerHTML = `<div style="margin-bottom:14px;font-weight:800;font-size:20px;">
        🗺️ ${escapeHtml(path.path_title || topic)}</div>` +
        (path.milestones || []).map((m, i) => `
          <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px dashed #d8c9a8;">
            <div style="font-weight:800;color:#d97c2b;min-width:26px;">${i + 1}</div>
            <div><b>${escapeHtml(m.title)}</b><br>
            <span style="color:#6a5a44;font-size:13px;">${escapeHtml(m.description || '')}</span></div>
          </div>`).join('') +
        `<div style="margin-top:18px;display:flex;gap:10px;">
           <button class="btn primary" id="lp-start">Start milestone 1 →</button>
           <button class="btn ghost" id="lp-close">Close</button>
         </div>`;
      box.appendChild(card);
      document.body.appendChild(box);
      box.querySelector('#lp-close').onclick = () => box.remove();
      box.querySelector('#lp-start').onclick = () => {
        const m1 = (path.milestones || [])[0];
        box.remove();
        $('topic-input').value = m1 ? m1.title : topic;
        $('path-toggle').checked = false;
        startLesson();
      };
    } catch (e) {
      hideStatus();
      toast('Path generation failed: ' + e.message);
    }
  }

  function showStudyPlan(plan) {
    document.body.innerHTML = `
    <div style="max-width:900px;margin:40px auto;padding:0 20px;
      font-family:'Segoe UI',sans-serif;color:#f2e9dc;">
      <h1 style="color:#e8a33d;">📅 ${escapeHtml(plan.lesson_title || '7-Day Study Plan')}</h1>
      <p style="color:#b8a894;margin:8px 0 24px;">${escapeHtml(plan.weekly_goal || '')}</p>
      ${(plan.days || []).map(d => `
        <div style="background:#2d241e;border:1px solid #453930;border-radius:14px;
          padding:16px 20px;margin-bottom:12px;">
          <div style="font-weight:700;color:#e8a33d;">Day ${d.day} · ${escapeHtml(d.focus || '')}
            <span style="color:#b8a894;font-weight:400;">(${d.minutes || 0} min)</span></div>
          <ul style="margin:8px 0 0 22px;color:#d8c9b8;font-size:14px;line-height:1.6;">
            ${(d.activities || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}
          </ul>
          ${(d.revision_of || []).length ? `<div style="color:#b05a78;font-size:13px;margin-top:6px;">
            ↺ Revision: ${(d.revision_of || []).map(escapeHtml).join(', ')}</div>` : ''}
        </div>`).join('')}
      <div style="margin-top:20px;">
        <button onclick="location.reload()" class="btn primary">← Back</button>
      </div>
    </div>`;
  }

  // quick-start from report screen "learn next topic"
  async function quickStart(topic) {
    $('report-screen').classList.add('hidden');
    $('setup-screen').classList.remove('hidden');
    switchTab('topic');
    $('topic-input').value = topic;
    toast('Ready to start the next lesson — press Start Lesson');
  }

  // -----------------------------------------------------------------------

  function showStatus(text) {
    $('setup-status').classList.remove('hidden');
    $('setup-status-text').textContent = text;
    $('start-lesson').disabled = true;
  }

  function hideStatus() {
    $('setup-status').classList.add('hidden');
    $('start-lesson').disabled = false;
  }

  function toast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.remove('hidden');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add('hidden'), 3400);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }

  return { init, quickStart };
})();
