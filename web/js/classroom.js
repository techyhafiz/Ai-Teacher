/* AI Teacher — Classroom controller
 * Playback engine: cached performance audio drives TalkingHead lipsync +
 * timeline events (whiteboard visuals) fire at exact timestamps.
 * Checkpoints: full-duplex live voice or typed answers via the WS relay.
 * Recording: canvas + audio -> MediaRecorder -> WebM download.
 */
'use strict';

const Classroom = (() => {

  const $ = (id) => document.getElementById(id);

  let state = {
    sessionId: null,
    plan: null,
    performances: [],      // sorted by seg_id
    persona: 'Aarav Sir',
    language: 'en',
    learnerId: null,
    segIndex: 0,
    attempt: 1,
    usedVariants: [],
    playing: false,
    audioEl: null,
    timeline: [],
    tStart: 0,
    tlTimer: null,
    mode: 'lesson',        // lesson | checkpoint | quiz | regen
    quizIndex: 0,
    consecutivePerfect: 0,
    recorder: null,
    recChunks: [],
    liveWs: null,
    audioCtx: null,
    liveQueue: [],
    micStream: null,
    audioPlayer: null,     // AudioWorklet player for live teacher audio
  };

  // ------------------------------------------------------------------
  // init / start lesson
  // ------------------------------------------------------------------

  async function start(sessionId, opts) {
    try {
      await startInner(sessionId, opts);
    } catch (e) {
      console.error('Classroom failed to start:', e);
      toast('Classroom error: ' + e.message + ' — check console (F12)');
      alert('Classroom failed: ' + e.message + '\n\nOpen the console (F12) and share the red error with the developer.');
    }
  }

  async function startInner(sessionId, opts) {
    state.sessionId = sessionId;
    state.persona = opts.persona || 'Aarav Sir';
    state.language = opts.language || 'en';
    state.learnerId = opts.learnerId;
    state.consecutivePerfect = 0;

    // show classroom
    $('setup-screen').classList.add('hidden');
    $('classroom-screen').classList.remove('hidden');

    // init whiteboard + avatar
    Whiteboard.init($('whiteboard'));
    await initAvatar();

    // load plan + performances
    const s = await API.getSession(sessionId);
    state.plan = JSON.parse(s.plan || '{}');
    $('classroom-title').textContent = state.plan.lesson_title || state.plan.topic || 'Lesson';
    updateLangPill();
    $('persona-name').textContent = state.persona;
    $('seg-progress-label').textContent = `0/${state.plan.segments.length}`;

    const perfs = await API.listPerformances(sessionId);
    state.performances = perfs.performances.filter(p => p.variant === 'main')
      .sort((a, b) => a.seg_id - b.seg_id);

    // reasoning badge from session events
    const events = s.events || [];
    for (const ev of events) {
      if (ev.type === 'plan') {
        addReasoning('📋 Lesson planned', `${ev.payload.segments} segments · ${ev.payload.language} · ${ev.payload.time_budget}`);
      }
    }

    // buttons
    $('btn-play-pause').onclick = togglePlay;
    $('btn-raise-hand').onclick = raiseHand;
    $('reasoning-badge').onclick = toggleReasoningPanel;
    $('rp-close').onclick = toggleReasoningPanel;
    $('cp-mic').onclick = startVoiceAnswer;
    $('cp-stop').onclick = finishVoiceAnswer;
    $('cp-send').onclick = sendTypedAnswer;
    $('cp-text').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendTypedAnswer();
    });

    // start recording the session video
    startRecording();

    // GO
    playSegment(0);
  }

  // ------------------------------------------------------------------
  // avatar (High-Fidelity 2D Animated Teacher + TalkingHead 3D Upgrade)
  // ------------------------------------------------------------------

  const RPM_AVATARS = {
    'Aarav Sir': './avatars/aarav.glb',
    "Meera Ma'am": './avatars/meera.glb',
    'Professor Bheem': './avatars/bheem.glb',
  };

  let talkingHead = null;
  let audioCtx = null;

  function getAudioCtx() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }

  // High-Fidelity 2D Animated Teacher Avatar Engine
  const TeacherAvatar2D = (() => {
    let canvas = null, ctx = null;
    let animId = null;
    let analyser = null;
    let freqData = null;
    let isSpeaking = false;
    let breathPhase = 0;
    let blinkValue = 0; // 0 = open, 1 = closed
    let nextBlinkTime = 0;
    let isBlinking = false;
    let glanceX = 0; // -1 (whiteboard) to 0 (front)
    let nextGlanceTime = 0;
    let mouthEnergy = 0;
    let activePersona = 'Aarav Sir';

    function init(container, persona) {
      activePersona = persona || 'Aarav Sir';
      container.innerHTML = '';
      canvas = document.createElement('canvas');
      canvas.id = 'teacher-avatar-canvas';
      canvas.style.cssText = 'width:100%;height:100%;display:block;border-radius:12px;';
      container.appendChild(canvas);
      ctx = canvas.getContext('2d');
      resize();
      window.addEventListener('resize', resize);
      nextBlinkTime = performance.now() + 2000;
      nextGlanceTime = performance.now() + 4000;
      if (animId) cancelAnimationFrame(animId);
      animate();
    }

    function resize() {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(200, (rect.width || 300) * dpr);
      canvas.height = Math.max(300, (rect.height || 450) * dpr);
    }

    function attachAudioSource(sourceNode) {
      try {
        const actx = getAudioCtx();
        analyser = actx.createAnalyser();
        analyser.fftSize = 128;
        analyser.smoothingTimeConstant = 0.5;
        freqData = new Uint8Array(analyser.frequencyBinCount);
        sourceNode.connect(analyser);
        isSpeaking = true;
      } catch (e) {
        console.warn('Analyser connect failed:', e);
      }
    }

    function pushAudioEnergy(energy) {
      mouthEnergy = Math.max(mouthEnergy, energy);
      isSpeaking = energy > 0.05;
    }

    function setSpeaking(speaking) {
      isSpeaking = speaking;
      if (!speaking) mouthEnergy = 0;
    }

    function update() {
      const now = performance.now();
      breathPhase += 0.035;

      // Audio analysis for mouth movement
      if (analyser && freqData && isSpeaking) {
        analyser.getByteFrequencyData(freqData);
        let sum = 0;
        const count = Math.min(16, freqData.length);
        for (let i = 1; i < count; i++) sum += freqData[i];
        const targetEnergy = Math.min(1.0, (sum / count) / 120);
        mouthEnergy += (targetEnergy - mouthEnergy) * 0.45;
      } else if (!isSpeaking) {
        mouthEnergy += (0 - mouthEnergy) * 0.25;
      }

      // Blinking logic
      if (now > nextBlinkTime) {
        isBlinking = true;
        blinkValue += 0.2;
        if (blinkValue >= 1) {
          blinkValue = 1;
          nextBlinkTime = now + 2500 + Math.random() * 3500;
        }
      } else if (isBlinking) {
        blinkValue -= 0.2;
        if (blinkValue <= 0) {
          blinkValue = 0;
          isBlinking = false;
        }
      }

      // Glance logic (glancing at blackboard when speaking)
      if (now > nextGlanceTime) {
        glanceX = isSpeaking && Math.random() > 0.4 ? 0.6 : 0.0;
        nextGlanceTime = now + 3000 + Math.random() * 4000;
      }
    }

    function draw() {
      if (!ctx || !canvas) return;
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      // 1. Studio Background with Spotlight
      const bgGrad = ctx.createRadialGradient(W * 0.5, H * 0.35, 20, W * 0.5, H * 0.5, H * 0.65);
      bgGrad.addColorStop(0, '#382b22');
      bgGrad.addColorStop(1, '#17120e');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, W, H);

      // Speaking halo glow
      if (isSpeaking && mouthEnergy > 0.1) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(W * 0.5, H * 0.4, W * 0.42, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(232, 163, 61, ${Math.min(0.22, mouthEnergy * 0.25)})`;
        ctx.fill();
        ctx.restore();
      }

      const breathY = Math.sin(breathPhase) * 4;
      const headTilt = isSpeaking ? Math.sin(breathPhase * 1.5) * 0.03 : 0;
      const headX = W * 0.5;
      const headY = H * 0.42 + breathY;
      const headR = Math.min(W, H) * 0.23;

      // 2. Teacher Torso & Outfit
      ctx.save();
      const torsoY = headY + headR * 0.8;
      if (activePersona === "Meera Ma'am") {
        // Saree & Blouse
        ctx.fillStyle = '#8b263e'; // Maroon Saree
        ctx.beginPath();
        ctx.moveTo(headX - headR * 1.6, H);
        ctx.quadraticCurveTo(headX - headR * 1.1, torsoY, headX - headR * 0.4, torsoY);
        ctx.lineTo(headX + headR * 0.4, torsoY);
        ctx.quadraticCurveTo(headX + headR * 1.1, torsoY, headX + headR * 1.6, H);
        ctx.fill();
        // Golden Zari Border
        ctx.strokeStyle = '#d4af37';
        ctx.lineWidth = 6;
        ctx.beginPath();
        ctx.moveTo(headX - headR * 0.8, H);
        ctx.lineTo(headX + headR * 0.2, torsoY + 10);
        ctx.stroke();
      } else if (activePersona === "Professor Bheem") {
        // Professorial Tweed Blazer + Tie
        ctx.fillStyle = '#4a3728'; // Tweed Blazer
        ctx.beginPath();
        ctx.moveTo(headX - headR * 1.6, H);
        ctx.quadraticCurveTo(headX - headR * 1.1, torsoY, headX - headR * 0.4, torsoY);
        ctx.lineTo(headX + headR * 0.4, torsoY);
        ctx.quadraticCurveTo(headX + headR * 1.1, torsoY, headX + headR * 1.6, H);
        ctx.fill();
        // Shirt & Tie
        ctx.fillStyle = '#f5efe6';
        ctx.beginPath();
        ctx.moveTo(headX - headR * 0.3, torsoY);
        ctx.lineTo(headX + headR * 0.3, torsoY);
        ctx.lineTo(headX, torsoY + headR * 0.6);
        ctx.fill();
        ctx.fillStyle = '#991b1b'; // Crimson Tie
        ctx.beginPath();
        ctx.moveTo(headX - 6, torsoY + 8);
        ctx.lineTo(headX + 6, torsoY + 8);
        ctx.lineTo(headX + 10, H);
        ctx.lineTo(headX - 10, H);
        ctx.fill();
      } else {
        // Aarav Sir: Smart Blue Collared Shirt
        ctx.fillStyle = '#1e3a8a'; // Royal Navy Shirt
        ctx.beginPath();
        ctx.moveTo(headX - headR * 1.6, H);
        ctx.quadraticCurveTo(headX - headR * 1.1, torsoY, headX - headR * 0.4, torsoY);
        ctx.lineTo(headX + headR * 0.4, torsoY);
        ctx.quadraticCurveTo(headX + headR * 1.1, torsoY, headX + headR * 1.6, H);
        ctx.fill();
        // Collar
        ctx.fillStyle = '#3b82f6';
        ctx.beginPath();
        ctx.moveTo(headX - headR * 0.35, torsoY);
        ctx.lineTo(headX, torsoY + headR * 0.3);
        ctx.lineTo(headX + headR * 0.35, torsoY);
        ctx.lineTo(headX, torsoY + 12);
        ctx.fill();
      }
      ctx.restore();

      // 3. Neck
      ctx.save();
      ctx.fillStyle = activePersona === "Meera Ma'am" ? '#c98a58' : '#d49b6a';
      ctx.fillRect(headX - headR * 0.25, headY + headR * 0.6, headR * 0.5, headR * 0.4);
      ctx.restore();

      // 4. Head, Face, Hair & Glasses
      ctx.save();
      ctx.translate(headX, headY);
      ctx.rotate(headTilt);

      // Skin Tone Head Oval
      const skinColor = activePersona === "Meera Ma'am" ? '#c98a58' : (activePersona === "Professor Bheem" ? '#be8252' : '#d49b6a');
      ctx.fillStyle = skinColor;
      ctx.beginPath();
      ctx.ellipse(0, 0, headR * 0.75, headR * 0.95, 0, 0, Math.PI * 2);
      ctx.fill();

      // Hair
      if (activePersona === "Meera Ma'am") {
        ctx.fillStyle = '#1a1410';
        ctx.beginPath();
        ctx.arc(0, -headR * 0.25, headR * 0.85, Math.PI * 0.8, Math.PI * 2.2);
        ctx.fill();
        // Red Bindi
        ctx.fillStyle = '#dc2626';
        ctx.beginPath();
        ctx.arc(0, -headR * 0.18, 3.5, 0, Math.PI * 2);
        ctx.fill();
      } else if (activePersona === "Professor Bheem") {
        // Grey/Silver Touched Professorial Hair
        ctx.fillStyle = '#64748b';
        ctx.beginPath();
        ctx.arc(0, -headR * 0.3, headR * 0.88, Math.PI * 0.75, Math.PI * 2.25);
        ctx.fill();
      } else {
        // Aarav Sir: Modern Neat Hair
        ctx.fillStyle = '#1e1b18';
        ctx.beginPath();
        ctx.arc(0, -headR * 0.35, headR * 0.82, Math.PI * 0.8, Math.PI * 2.2);
        ctx.fill();
      }

      // Eyebrows
      ctx.strokeStyle = activePersona === "Professor Bheem" ? '#475569' : '#1e1b18';
      ctx.lineWidth = 3.5;
      const browLift = isSpeaking ? -3 : 0;
      ctx.beginPath();
      ctx.moveTo(-headR * 0.45, -headR * 0.2 + browLift);
      ctx.quadraticCurveTo(-headR * 0.25, -headR * 0.28 + browLift, -headR * 0.1, -headR * 0.2 + browLift);
      ctx.moveTo(headR * 0.1, -headR * 0.2 + browLift);
      ctx.quadraticCurveTo(headR * 0.25, -headR * 0.28 + browLift, headR * 0.45, -headR * 0.2 + browLift);
      ctx.stroke();

      // Eyes & Eyelids (with Blinking + Glance)
      const eyeY = -headR * 0.08;
      const eyeSpacing = headR * 0.28;
      const eyeW = headR * 0.18;
      const eyeH = headR * 0.12 * (1 - blinkValue);

      if (blinkValue < 0.9) {
        // Left & Right Eye Whites
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.ellipse(-eyeSpacing, eyeY, eyeW, eyeH, 0, 0, Math.PI * 2);
        ctx.ellipse(eyeSpacing, eyeY, eyeW, eyeH, 0, 0, Math.PI * 2);
        ctx.fill();

        // Pupils
        const pupilXOffset = glanceX * 5;
        ctx.fillStyle = '#1c1917';
        ctx.beginPath();
        ctx.arc(-eyeSpacing + pupilXOffset, eyeY, eyeH * 0.7, 0, Math.PI * 2);
        ctx.arc(eyeSpacing + pupilXOffset, eyeY, eyeH * 0.7, 0, Math.PI * 2);
        ctx.fill();

        // Eye Catchlights
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(-eyeSpacing + pupilXOffset + 2, eyeY - 2, 2, 0, Math.PI * 2);
        ctx.arc(eyeSpacing + pupilXOffset + 2, eyeY - 2, 2, 0, Math.PI * 2);
        ctx.fill();
      } else {
        // Closed Eye Slits
        ctx.strokeStyle = '#3e2d20';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(-eyeSpacing - eyeW, eyeY);
        ctx.lineTo(-eyeSpacing + eyeW, eyeY);
        ctx.moveTo(eyeSpacing - eyeW, eyeY);
        ctx.lineTo(eyeSpacing + eyeW, eyeY);
        ctx.stroke();
      }

      // Glasses (Aarav Sir & Professor Bheem)
      if (activePersona !== "Meera Ma'am") {
        ctx.strokeStyle = activePersona === "Professor Bheem" ? '#d4af37' : '#0f172a';
        ctx.lineWidth = 2.5;
        ctx.strokeRect(-eyeSpacing - eyeW * 1.2, eyeY - eyeW * 0.8, eyeW * 2.4, eyeW * 1.6);
        ctx.strokeRect(eyeSpacing - eyeW * 1.2, eyeY - eyeW * 0.8, eyeW * 2.4, eyeW * 1.6);
        // Bridge
        ctx.beginPath();
        ctx.moveTo(-eyeSpacing + eyeW * 1.2, eyeY);
        ctx.lineTo(eyeSpacing - eyeW * 1.2, eyeY);
        ctx.stroke();
      }

      // Nose
      ctx.strokeStyle = 'rgba(100, 60, 30, 0.4)';
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(0, -headR * 0.05);
      ctx.lineTo(4, headR * 0.18);
      ctx.lineTo(-4, headR * 0.18);
      ctx.stroke();

      // Mouth Lip-Sync Animation
      const mouthY = headR * 0.42;
      const openAmount = Math.max(2, mouthEnergy * 24);
      const mouthWidth = 24 + mouthEnergy * 14;

      if (mouthEnergy > 0.08) {
        // Open Speaking Mouth
        ctx.fillStyle = '#581c1c';
        ctx.beginPath();
        ctx.ellipse(0, mouthY, mouthWidth * 0.5, openAmount * 0.5, 0, 0, Math.PI * 2);
        ctx.fill();
        // Teeth hint
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(-mouthWidth * 0.28, mouthY - openAmount * 0.45, mouthWidth * 0.56, Math.min(4, openAmount * 0.3));
        // Lips Outline
        ctx.strokeStyle = '#a84e4e';
        ctx.lineWidth = 2;
        ctx.stroke();
      } else {
        // Friendly Gentle Smile
        ctx.strokeStyle = '#6b2d2d';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(-12, mouthY - 2);
        ctx.quadraticCurveTo(0, mouthY + 5, 12, mouthY - 2);
        ctx.stroke();
      }

      ctx.restore();

      // 5. Teacher Persona Badge & Speaking Chip
      ctx.save();
      ctx.fillStyle = isSpeaking ? '#e8a33d' : '#8c7b6d';
      ctx.font = '700 13px "Segoe UI", sans-serif';
      ctx.textAlign = 'center';
      const label = isSpeaking ? '🔊 Speaking...' : '🎓 ' + activePersona;
      ctx.fillText(label, W * 0.5, H - 16);
      ctx.restore();
    }

    function animate() {
      update();
      draw();
      animId = requestAnimationFrame(animate);
    }

    return {
      init,
      attachAudioSource,
      pushAudioEnergy,
      setSpeaking,
      resize,
    };
  })();

  let avatar3D = null;

  async function initAvatar() {
    let tries = 0;
    while (!window.Avatar3DEngine && tries < 30) {
      await new Promise(r => setTimeout(r, 50));
      tries++;
    }

    if (window.Avatar3DEngine) {
      try {
        const container = $('talkinghead');
        container.innerHTML = '';
        avatar3D = new window.Avatar3DEngine(container, {
          cameraView: 'upper',
          idleMove: true,
        });
        const url = RPM_AVATARS[state.persona] || RPM_AVATARS['Aarav Sir'];
        await avatar3D.loadModel(url);
        console.info('Loaded 3D Avatar into classroom:', url);
        return true;
      } catch (e) {
        console.warn('3D avatar load failed, falling back to 2D TeacherAvatar:', e);
      }
    }

    // Fallback if 3D context or WebGL fails
    TeacherAvatar2D.init($('talkinghead'), state.persona);
    return true;
  }

  // ------------------------------------------------------------------
  // playback engine (cached performance audio -> TalkingHead speakAudio)
  // ------------------------------------------------------------------

  // fetch + decode the performance WAV once; cache by wav_name
  const audioBufCache = new Map();

  async function loadPerformanceAudio(wavName) {
    if (audioBufCache.has(wavName)) return audioBufCache.get(wavName);
    const url = API.performanceAudioUrl(state.sessionId, wavName);
    const r = await fetch(url);
    if (!r.ok) throw new Error(`audio fetch ${r.status}`);
    const ab = await r.arrayBuffer();
    const buf = await getAudioCtx().decodeAudioData(ab);
    audioBufCache.set(wavName, buf);
    return buf;
  }

  /**
   * Build word timings for speakAudio from the spoken transcript:
   * distribute words proportionally across the audio duration, with
   * extra slack at [PAUSE] gaps (visual draw moments).
   */
  function wordsForLipsync(transcript, durationSec) {
    const words = (transcript || '').trim().split(/\s+/).filter(Boolean);
    if (!words.length || !durationSec) {
      return { words: [], wtimes: [], wdurations: [] };
    }
    const total = words.reduce((a, w) => a + w.length + 1, 0);
    const wtimes = [], wdurations = [];
    let t = 0;
    for (const w of words) {
      const d = ((w.length + 1) / total) * durationSec * 1000;
      wtimes.push(Math.round(t));
      wdurations.push(Math.round(d));
      t += d;
    }
    return { words, wtimes, wdurations };
  }

  async function playSegment(segIndex) {
    if (segIndex >= state.plan.segments.length) {
      return startQuiz();
    }
    state.segIndex = segIndex;
    state.attempt = 1;
    state.usedVariants = ['main'];

    const seg = state.plan.segments[segIndex];
    const perf = state.performances.find(p => p.seg_id === seg.seg_id);
    $('seg-progress-fill').style.width =
      `${100 * (segIndex) / state.plan.segments.length}%`;
    $('seg-progress-label').textContent =
      `${segIndex + 1}/${state.plan.segments.length}`;

    if (perf) {
      await playPerformance(perf, () => afterSegment(seg));
    } else {
      await playLiveSegment(seg, () => afterSegment(seg));
    }
  }

  function playLiveSegment(seg, onDone) {
    return new Promise((resolve) => {
      Whiteboard.clear();
      const script = (seg.script && (seg.script.main || seg.script.simpler)) || 'Welcome to this lesson!';
      const visuals = seg.visuals || [];

      // Calculate estimated speech duration: ~2.3 words per sec
      const words = script.split(/\s+/).filter(Boolean);
      const estDuration = Math.max(6, Math.min(60, words.length / 2.3));

      // Build timeline from visuals
      state.timeline = visuals.map((v, i) => {
        const afterSent = v.after_sentence || (i + 1);
        const t = Math.min(estDuration - 0.8, Math.max(0.6, (afterSent / Math.max(1, visuals.length + 1)) * estDuration));
        return {
          t: t,
          tool: v.tool,
          args: v.args,
          fired: false
        };
      });

      state.playing = true;
      setPlayIcon();
      setupSubtitles(script);
      state.tStart = performance.now();
      scheduleTimeline();

      const finish = () => {
        state.playing = false;
        setPlayIcon();
        stopSubtitles();
        TeacherAvatar2D.setSpeaking(false);
        if (avatar3D) avatar3D.setSpeaking(false);
        onDone?.();
        resolve();
      };

      if (avatar3D && typeof avatar3D.speakText === 'function') {
        TeacherAvatar2D.setSpeaking(true);
        avatar3D.speakText(script, finish);
      } else {
        TeacherAvatar2D.setSpeaking(true);
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel();
          const u = new SpeechSynthesisUtterance(script);
          u.rate = 1.0;
          u.onend = finish;
          u.onerror = finish;
          window.speechSynthesis.speak(u);
        } else {
          setTimeout(finish, estDuration * 1000);
        }
      }
    });
  }

  function playPerformance(perf, onDone) {
    return new Promise(async (resolve) => {
      Whiteboard.clear();
      state.timeline = (perf.timeline || []).map(e => ({ ...e, fired: false }));
      state.playing = true;
      setPlayIcon();
      setupSubtitles(perf.transcript || '');

      let buf;
      try {
        buf = await loadPerformanceAudio(perf.wav_name);
      } catch (e) {
        console.error('audio load failed', e);
        toast('Audio missing — skipping segment');
        state.playing = false;
        setPlayIcon();
        stopSubtitles();
        onDone?.();
        resolve();
        return;
      }

      const { words, wtimes, wdurations } =
        wordsForLipsync(perf.transcript, perf.duration || buf.duration);

      // timeline clock starts when audio actually starts
      const startClock = () => {
        state.tStart = performance.now();
        scheduleTimeline();
      };

      // wire audio end
      const finish = () => {
        state.playing = false;
        setPlayIcon();
        stopSubtitles();
        TeacherAvatar2D.setSpeaking(false);
        if (avatar3D) avatar3D.setSpeaking(false);
        onDone?.();
        resolve();
      };

      // Play audio buffer through WebAudio and drive real-time 3D/2D lipsync
      const src = getAudioCtx().createBufferSource();
      src.buffer = buf;
      src.connect(getAudioCtx().destination);
      if (avatar3D) avatar3D.attachAudioSource(src);
      TeacherAvatar2D.attachAudioSource(src);
      src.onended = () => finish();
      startClock();
      src.start();
      state.currentAudio = { buf, wtimes, duration: buf.duration, src };
    });
  }

  function scheduleTimeline() {
    cancelAnimationFrame(state.tlTimer);
    const tick = () => {
      if (!state.playing) return;
      const t = (performance.now() - state.tStart) / 1000;
      for (const e of state.timeline) {
        if (!e.fired && t >= e.t) {
          e.fired = true;
          if (e.valid !== false) {
            Whiteboard.execute(e.tool, e.args);
            fireSubtitlesPause(800);
          }
        }
      }
      state.tlTimer = requestAnimationFrame(tick);
    };
    state.tlTimer = requestAnimationFrame(tick);
  }

  function togglePlay() {
    if (state.mode === 'checkpoint' || state.mode === 'quiz') return;
    if (state.playing) {
      if (talkingHead) talkingHead.pauseSpeaking();
      state.currentAudio?.src?.stop?.();
      state.playing = false;
    } else {
      if (talkingHead) talkingHead.startSpeaking();
      state.currentAudio?.src?.start?.();
      state.playing = true;
      state.tStart = performance.now() - 0; // best-effort resume
      scheduleTimeline();
    }
    setPlayIcon();
  }

  function setPlayIcon() {
    $('btn-play-pause').textContent = state.playing ? '⏸' : '▶';
  }

  // ------------------------------------------------------------------
  // subtitles
  // ------------------------------------------------------------------

  let subTimer = null;
  let subSentences = [];

  function setupSubtitles(text) {
    const el = $('subtitles');
    el.textContent = '';
    subSentences = text.split(/(?<=[।.!?])\s+/).filter(Boolean);
    let i = 0;
    // We sync subtitles to audio roughly by proportion; the visual pauses
    // add slack, so we re-sync per segment durations.
    let nextAt = performance.now();
    clearInterval(subTimer);
    subTimer = setInterval(() => {
      if (!state.playing) return;
      if (performance.now() >= nextAt) {
        if (i < subSentences.length) {
          el.textContent = subSentences[i];
          const dur = Math.max(1800, subSentences[i].length * 78);
          nextAt = performance.now() + dur;
          i++;
        } else {
          el.textContent = '';
        }
      }
    }, 250);
  }

  function fireSubtitlesPause(ms) {
    // brief flash on visual change
    const el = $('subtitles');
    el.style.opacity = '0.55';
    setTimeout(() => { el.style.opacity = '1'; }, ms);
  }

  function stopSubtitles() {
    clearInterval(subTimer);
    $('subtitles').textContent = '';
  }

  // ------------------------------------------------------------------
  // after a segment ends: checkpoint or next
  // ------------------------------------------------------------------

  function afterSegment(seg) {
    if (seg.checkpoint && seg.checkpoint.question) {
      openCheckpoint(seg);
    } else {
      playSegment(state.segIndex + 1);
    }
  }

  function openCheckpoint(seg) {
    state.mode = 'checkpoint';
    const cp = seg.checkpoint;
    $('cp-kind').textContent = 'CHECKPOINT';
    document.querySelector('.cp-card').classList.remove('quiz');
    $('cp-question').textContent = cp.question;
    $('cp-options').innerHTML = '';
    $('cp-hint').classList.add('hidden');
    $('cp-live').classList.add('hidden');
    $('cp-answering').classList.remove('hidden');
    $('cp-text').value = '';
    state.currentCheckpoint = {
      seg,
      question: cp.question,
      expected: cp.expected_answer,
      options: cp.options || null,
      answerIndex: cp.answer_index ?? null,
      hint: cp.hint,
      type: cp.question_type,
    };

    // MCQ checkpoints render as clickable options
    if (cp.question_type === 'mcq' && cp.options) {
      renderCpOptions(cp.options, (idx) => {
        submitAnswer(cp.options[idx]);
      });
      $('cp-answering').style.display = 'none';
    } else {
      $('cp-answering').style.display = '';
    }
    $('checkpoint-overlay').classList.remove('hidden');

    // teacher asks the question aloud via live session? We keep it simple:
    // the question is on the board; student answers by voice/typing.
  }

  function renderCpOptions(options, onPick) {
    const box = $('cp-options');
    box.innerHTML = '';
    options.forEach((opt, i) => {
      const b = document.createElement('button');
      b.className = 'cp-option';
      b.textContent = opt;
      b.onclick = () => {
        box.querySelectorAll('.cp-option').forEach(x =>
          x.classList.remove('selected'));
        b.classList.add('selected');
        setTimeout(() => onPick(i), 350);
      };
      box.appendChild(b);
    });
  }

  async function submitAnswer(answer) {
    const cp = state.currentCheckpoint;
    if (!cp) return;
    $('cp-answering').querySelectorAll('button,input').forEach(el =>
      el.disabled = true);

    const result = await API.checkpoint(state.sessionId, {
      seg_id: cp.seg.seg_id,
      concept: cp.seg.concept,
      question: cp.question,
      expected_answer: cp.expected,
      student_answer: answer,
      attempt: state.attempt,
      language: state.language,
    });

    addReasoning(
      result.verdict === 'correct' ? '✅ Correct — advancing' :
        `❌ ${result.verdict} — ${result.teaching_move}`,
      result.misconception ?
        `${result.misconception}: ${result.misconception_explanation || ''}` :
        result.teacher_reply);

    if (result.teaching_move === 'advance' || result.teaching_move === 'go_deeper') {
      if (result.verdict === 'correct' && result.score >= 0.9) {
        state.consecutivePerfect++;
        if (state.consecutivePerfect >= 2 &&
            state.segIndex + 2 < state.plan.segments.length) {
          addReasoning('⏭ Skipping ahead', 'Two perfect answers in a row — this concept is solid.');
          state.consecutivePerfect = 0;
          closeCheckpoint();
          return playSegment(state.segIndex + 2);
        }
      } else {
        state.consecutivePerfect = 0;
      }
      closeCheckpoint();
      playSegment(state.segIndex + 1);
    } else if (result.teaching_move === 'skip_ahead') {
      closeCheckpoint();
      playSegment(state.segIndex + 2);
    } else {
      // re_explain / simplify — with a live regen targeted at the misconception
      state.consecutivePerfect = 0;
      await doReExplain(cp, result);
    }
  }

  function closeCheckpoint() {
    $('checkpoint-overlay').classList.add('hidden');
    state.mode = 'lesson';
    $('cp-answering').querySelectorAll('button,input').forEach(el =>
      el.disabled = false);
  }

  // ------------------------------------------------------------------
  // re-explanation flow (adaptive teaching)
  // ------------------------------------------------------------------

  async function doReExplain(cp, result) {
    const seg = cp.seg;

    // 1) try pre-planned variants first (fast path)
    let variant = null;
    if (result.teaching_move === 'simplify' && !state.usedVariants.includes('simpler')) {
      variant = 'simpler';
    } else if (result.teaching_move === 'go_deeper') {
      variant = 'deeper';
    }

    if (variant) {
      state.usedVariants.push(variant);
      state.attempt++;
      closeCheckpoint();
      // capture the variant performance now (with 'thinking' status)
      showThinking('Re-explaining with a ' + variant + ' approach…');
      try {
        const perf = await API.captureOne(state.sessionId, {
          seg_id: seg.seg_id, variant,
        });
        // insert into local performance list and replay
        state.performances = state.performances.filter(p =>
          !(p.seg_id === seg.seg_id && p.variant === variant));
        state.performances.push(perf);
        const prevMain = state.performances.find(p =>
          p.seg_id === seg.seg_id && p.variant === 'main');
        await playVariant(perf);
        // re-check with the same checkpoint after re-explaining
        state.attempt = state.attempt;
        openCheckpoint(seg);
      } catch (e) {
        console.error(e);
        toast('Re-explanation failed: ' + e.message);
      } finally {
        hideThinking();
      }
      return;
    }

    // 2) live regen (misconception-targeted) — new script + new checkpoint
    state.attempt++;
    showThinking('Preparing a different explanation…');
    try {
      const mainPerf = state.performances.find(p =>
        p.seg_id === seg.seg_id && p.variant === 'main');
      const regen = await API.regen(state.sessionId, {
        seg_id: seg.seg_id,
        concept: seg.concept,
        original_script: (seg.script && seg.script.main) || '',
        misconception: result.misconception || 'not_understood',
        misconception_explanation: result.misconception_explanation || '',
        student_answer: state.lastAnswer || '',
        question: cp.question,
        used_variants: state.usedVariants,
        language: state.language,
      });
      // capture the regen performance
      const perf = await API.captureOne(state.sessionId, {
        seg_id: seg.seg_id,
        variant: 'regen',
        script_override: regen.script,
        visuals_override: regen.visuals || [],
      });
      state.performances.push(perf);
      closeCheckpoint();
      await playVariant(perf);
      // new checkpoint question from the regen
      if (regen.new_checkpoint && regen.new_checkpoint.question) {
        seg.checkpoint = regen.new_checkpoint;
      }
      openCheckpoint(seg);
    } catch (e) {
      console.error(e);
      toast('Re-explanation failed: ' + e.message);
      closeCheckpoint();
      playSegment(state.segIndex + 1);   // don't trap the student
    } finally {
      hideThinking();
    }
  }

  async function playVariant(perf) {
    await playPerformance(perf, null);
  }

  // ------------------------------------------------------------------
  // voice answers (live WS)
  // ------------------------------------------------------------------

  function openLiveWs(init, onAudio, onTranscript, onInputTranscript,
                     onToolCall, onTurnComplete, onError, onDone) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(
      `${proto}://${location.host}/api/ws/live/${state.sessionId}`);
    const handlers = { onAudio, onTranscript, onInputTranscript, onToolCall,
                       onTurnComplete, onError, onDone };
    ws.onopen = () => ws.send(JSON.stringify(init));
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.type === 'audio') handlers.onAudio?.(d.data);
      else if (d.type === 'transcript') handlers.onTranscript?.(d.text);
      else if (d.type === 'input_transcript') handlers.onInputTranscript?.(d.text);
      else if (d.type === 'tool_call') handlers.onToolCall?.(d);
      else if (d.type === 'turn_complete') handlers.onTurnComplete?.(d);
      else if (d.type === 'error') handlers.onError?.(d.message);
      else if (d.type === 'interrupted') handlers.onTurnComplete?.(d);
    };
    ws.onclose = () => handlers.onDone?.();
    ws.onerror = () => handlers.onError?.('WebSocket error');
    return ws;
  }

  async function startVoiceAnswer() {
    const cp = state.currentCheckpoint;
    if (!cp) return;
    $('cp-live').classList.remove('hidden');
    $('cp-answering').classList.add('hidden');
    $('cp-live-status').textContent = 'connecting…';
    $('cp-live-transcript').textContent = '';

    try {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      toast('Microphone permission denied — type your answer instead.');
      $('cp-live').classList.add('hidden');
      $('cp-answering').classList.remove('hidden');
      return;
    }

    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    state.audioCtx = audioCtx;
    await audioCtx.resume();
    const source = audioCtx.createMediaStreamSource(state.micStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(audioCtx.destination);

    // teacher speech streams through TalkingHead (lipsync + audio) — or a
    // plain PCM queue player when the avatar is unavailable
    let pcmFallback = null;
    if (talkingHead) {
      await talkingHead.streamStart({ sampleRate: 24000 }, () => {
        $('cp-live-status').textContent = '💬 teacher is responding…';
      }, () => { });
    } else {
      const pctx = new (window.AudioContext || window.webkitAudioContext)();
      await pctx.resume();
      let nextT = 0;
      pcmFallback = {
        push(b64) {
          const buf = new Int16Array(b64.length / 2);
          for (let i = 0; i < b64.length; i += 2) {
            buf[i / 2] = b64.charCodeAt(i) | (b64.charCodeAt(i + 1) << 8);
          }
          const f = new Float32Array(buf.length);
          for (let i = 0; i < buf.length; i++) f[i] = buf[i] / 32768;
          const ab = pctx.createBuffer(1, f.length, 24000);
          ab.copyToChannel(f, 0);
          const src = pctx.createBufferSource();
          src.buffer = ab;
          src.connect(pctx.destination);
          TeacherAvatar2D.attachAudioSource(src);
          if (nextT < pctx.currentTime) nextT = pctx.currentTime + 0.05;
          src.start(nextT);
          nextT += ab.duration;
        },
        stop() {
          try {
            pctx.close();
            TeacherAvatar2D.setSpeaking(false);
          } catch (e) {}
        },
      };
    }

    function pcmToBytes(b64) {
      const bin = atob(b64);
      const buf = new Int16Array(bin.length / 2);
      for (let i = 0; i < bin.length; i += 2) {
        buf[i / 2] = bin.charCodeAt(i) | (bin.charCodeAt(i + 1) << 8);
      }
      return buf;
    }

    let finalTranscript = '';
    state.liveWs = openLiveWs(
      { mode: 'checkpoint', seg_id: cp.seg.seg_id, concept: cp.seg.concept,
        question: cp.question, expected_answer: cp.expected,
        language: state.language, persona: state.persona },
      (b64) => {
        // teacher audio chunk -> avatar stream (lipsync'd) or fallback player
        if (talkingHead) talkingHead.streamAudio({ audio: pcmToBytes(b64) });
        else pcmFallback.push(b64);
      },
      (t) => { },                                        // teacher speech text
      (t) => {
        finalTranscript += ' ' + t;
        $('cp-live-transcript').textContent = 'You: ' + finalTranscript.trim();
      },
      (call) => {
        if (call.name === 'ask_whiteboard') Whiteboard.execute('draw_diagram', call.args);
        if (call.name === 'evaluate_student') state.liveEval = call.args;
        if (call.name === 'switch_language') {
          setLanguage(call.args.language, false);
        }
      },
      () => { },
      (msg) => { $('cp-live-status').textContent = '⚠ ' + msg; },
      async () => {
        // conversation done — cleanup
        try { talkingHead?.streamStop?.(); } catch (e) {}
        try { pcmFallback?.stop?.(); } catch (e) {}
        try { state.micStream.getTracks().forEach(t => t.stop()); } catch (e) {}
        try { processor.disconnect(); source.disconnect(); } catch (e) {}
        try { audioCtx.close(); } catch (e) {}
        // submit whatever the student said as the answer for gating/records
        const said = finalTranscript.trim();
        closeLiveUi();
        if (said) {
          state.lastAnswer = said;
          await submitAnswer(said);
        } else {
          // no speech captured — reopen text input
          openCheckpoint(cp.seg);
        }
      });

    $('cp-live-status').textContent = '🎤 listening — speak now';

    processor.onaudioprocess = (e) => {
      if (!state.liveWs || state.liveWs.readyState !== 1) return;
      const d = e.inputBuffer.getChannelData(0);
      const pcm16 = new Int16Array(d.length);
      for (let i = 0; i < d.length; i++) {
        const s = Math.max(-1, Math.min(1, d[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      };
      // downsample 48k->24k
      const half = Math.floor(pcm16.length / 2);
      const ds = new Int16Array(half);
      for (let i = 0; i < half; i++) ds[i] = pcm16[i * 2];
      state.liveWs.send(JSON.stringify({
        type: 'student_audio', data: arrayBufferToB64(ds.buffer) }));
    };

    // send end-of-audio after silence detection would be complex; instead
    // the student taps "Done speaking" (push-to-talk style confirmation)
  }

  function finishVoiceAnswer() {
    if (state.liveWs && state.liveWs.readyState === 1) {
      state.liveWs.send(JSON.stringify({ type: 'end' }));
    }
  }

  function closeLiveUi() {
    $('cp-live').classList.add('hidden');
  }

  async function sendTypedAnswer() {
    const txt = $('cp-text').value.trim();
    if (!txt) return;
    state.lastAnswer = txt;
    $('cp-text').value = '';
    await submitAnswer(txt);
  }

  // ------------------------------------------------------------------
  // raise hand (open live Q&A anytime)
  // ------------------------------------------------------------------

  function raiseHand() {
    if (state.mode === 'checkpoint' || state.mode === 'quiz') return;
    // pause playback if speaking
    if (state.playing) { talkingHead.pauseSpeaking(); state.playing = false; setPlayIcon(); }
    state.mode = 'raisehand';
    state.freeQuestion = true;
    const seg = state.plan.segments[state.segIndex] || { seg_id: 0, concept: state.plan.topic };
    // free-form live Q&A: no gating, no grading
    state.currentCheckpoint = {
      seg,
      question: 'What would you like to ask?',
      expected: '',
      free: true,
    };
    // reuse the live voice UI directly
    startVoiceAnswerFree();
  }

  async function startVoiceAnswerFree() {
    // like startVoiceAnswer but no submitAnswer at the end
    const cp = state.currentCheckpoint;
    $('cp-kind').textContent = 'ASK THE TEACHER';
    document.querySelector('.cp-card').classList.remove('quiz');
    $('cp-question').textContent = 'Ask anything — the lesson will continue after.';
    $('cp-options').innerHTML = '';
    $('cp-answering').style.display = 'none';
    $('checkpoint-overlay').classList.remove('hidden');

    try {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      toast('Microphone unavailable.');
      closeCheckpoint();
      state.mode = 'lesson';
      return;
    }
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await audioCtx.resume();
    const source = audioCtx.createMediaStreamSource(state.micStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(audioCtx.destination);

    let pcmFallback = null;
    if (talkingHead) {
      await talkingHead.streamStart({ sampleRate: 24000 }, () => {}, () => {});
    } else {
      const pctx = new (window.AudioContext || window.webkitAudioContext)();
      await pctx.resume();
      let nextT = 0;
      pcmFallback = {
        push(b64) {
          const buf = new Int16Array(b64.length / 2);
          for (let i = 0; i < b64.length; i += 2) {
            buf[i / 2] = b64.charCodeAt(i) | (b64.charCodeAt(i + 1) << 8);
          }
          const f = new Float32Array(buf.length);
          for (let i = 0; i < buf.length; i++) f[i] = buf[i] / 32768;
          const ab = pctx.createBuffer(1, f.length, 24000);
          ab.copyToChannel(f, 0);
          const src = pctx.createBufferSource();
          src.buffer = ab;
          src.connect(pctx.destination);
          if (nextT < pctx.currentTime) nextT = pctx.currentTime + 0.05;
          src.start(nextT);
          nextT += ab.duration;
        },
        stop() { try { pctx.close(); } catch (e) {} },
      };
    }

    function pcmToBytes(b64) {
      const bin = atob(b64);
      const buf = new Int16Array(bin.length / 2);
      for (let i = 0; i < bin.length; i += 2) {
        buf[i / 2] = bin.charCodeAt(i) | (bin.charCodeAt(i + 1) << 8);
      }
      return buf;
    }

    let said = '';
    state.liveWs = openLiveWs(
      { mode: 'raise_hand', seg_id: cp.seg.seg_id, concept: cp.seg.concept,
        question: 'free Q&A — student asks, teacher answers',
        expected_answer: '', language: state.language, persona: state.persona },
      (b64) => {
        if (talkingHead) talkingHead.streamAudio({ audio: pcmToBytes(b64) });
        else pcmFallback.push(b64);
      },
      (t) => {},
      (t) => { said += ' ' + t; },
      (call) => {
        if (call.name === 'ask_whiteboard') Whiteboard.execute('draw_diagram', call.args);
        if (call.name === 'switch_language') setLanguage(call.args.language, false);
      },
      () => {},
      (msg) => toast('⚠ ' + msg),
      async () => {
        try { talkingHead?.streamStop?.(); } catch (e) {}
        try { pcmFallback?.stop?.(); } catch (e) {}
        try { state.micStream.getTracks().forEach(t => t.stop()); } catch (e) {}
        try { processor.disconnect(); source.disconnect(); audioCtx.close(); } catch (e) {}
        $('checkpoint-overlay').classList.add('hidden');
        state.mode = 'lesson';
        addReasoning('🤚 Student asked a question',
          (said.trim() || '').slice(0, 140));
        // resume the lesson where it paused
        playSegment(state.segIndex);
      });

    // mic pipeline
    processor.onaudioprocess = (e) => {
      if (!state.liveWs || state.liveWs.readyState !== 1) return;
      const d = e.inputBuffer.getChannelData(0);
      const pcm16 = new Int16Array(d.length);
      for (let i = 0; i < d.length; i++) {
        const s = Math.max(-1, Math.min(1, d[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      const half = Math.floor(pcm16.length / 2);
      const ds = new Int16Array(half);
      for (let i = 0; i < half; i++) ds[i] = pcm16[i * 2];
      state.liveWs.send(JSON.stringify({
        type: 'student_audio', data: arrayBufferToB64(ds.buffer) }));
    };
    // no explicit stop button in free mode: end via turn-complete silence
    // or the Done button if present
    $('cp-live').classList.remove('hidden');
    $('cp-live-status').textContent = '🎤 listening — tap Done when your question is answered';
    $('cp-stop').onclick = () => {
      if (state.liveWs && state.liveWs.readyState === 1) {
        state.liveWs.send(JSON.stringify({ type: 'end' }));
      }
    };
  }

  // ------------------------------------------------------------------
  // quiz
  // ------------------------------------------------------------------

  async function startQuiz() {
    state.mode = 'quiz';
    const quiz = state.plan.quiz || [];
    state.quizIndex = 0;
    state.quizData = quiz;
    if (!quiz.length) return finishLesson();
    askQuizQuestion();
  }

  async function askQuizQuestion() {
    const q = state.quizData[state.quizIndex];
    if (!q) return finishLesson();
    const card = document.querySelector('.cp-card');
    card.classList.add('quiz');
    $('cp-kind').textContent = `QUIZ ${state.quizIndex + 1}/${state.quizData.length}`;
    $('cp-question').textContent = q.q;
    $('cp-options').innerHTML = '';
    $('cp-answering').style.display = q.options ? 'none' : '';
    if (q.options) {
      renderCpOptions(q.options, (i) => submitQuizAnswer(q, q.options[i], i));
    } else {
      $('cp-text').value = '';
      $('cp-send').onclick = () => submitQuizAnswer(q, $('cp-text').value, null);
      $('cp-text').onkeydown = (e) => {
        if (e.key === 'Enter') submitQuizAnswer(q, $('cp-text').value, null);
      };
    }
    $('checkpoint-overlay').classList.remove('hidden');
  }

  async function submitQuizAnswer(q, answer, idx) {
    const r = await API.quizAnswer(state.sessionId, {
      question: q.q,
      expected_answer: q.expected_answer || '',
      student_answer: String(idx != null ? idx : answer),
      concept: q.concept,
      options: q.options || null,
      answer_index: q.answer_index ?? null,
      points: q.points || 1.0,
    });
    addReasoning(
      r.correct ? '✅ Quiz correct' : '❌ Quiz incorrect',
      `${q.concept}: ${r.explanation || ''}`);
    state.quizIndex++;
    setTimeout(askQuizQuestion, 400);
  }

  // ------------------------------------------------------------------
  // finish -> report
  // ------------------------------------------------------------------

  async function finishLesson() {
    showThinking('Preparing your learning report…');
    try {
      const report = await API.makeReport(state.sessionId);
      hideThinking();
      showReport(report);
    } catch (e) {
      hideThinking();
      toast('Report generation failed: ' + e.message);
    }
  }

  function showReport(report) {
    stopRecording();
    $('classroom-screen').classList.add('hidden');
    $('report-screen').classList.remove('hidden');
    $('report-score').textContent =
      report.score_pct != null ? `${Math.round(report.score_pct)}%` : '—';
    $('report-questions').textContent =
      `${report.correct}/${report.questions} quiz answers correct`;
    $('report-topic').textContent = report.topic;
    fillList('report-strong', report.strong_areas);
    fillList('report-weak', report.needs_improvement);
    fillList('report-misconceptions', report.misconceptions);
    fillList('report-recs', report.recommendations);
    fillList('report-homework', report.homework);
    $('report-summary').textContent = report.summary || '';

    $('report-next').onclick = () => {
      // start a new lesson on the recommended next topic
      const topic = report.next_topic || state.plan.topic;
      location.hash = '';
      Setup.quickStart(topic);
    };
    $('report-home').onclick = () => {
      location.reload();
    };
    $('report-download-video').onclick = downloadRecording;
  }

  function fillList(id, items) {
    const ul = $(id);
    ul.innerHTML = '';
    (items || []).forEach(t => {
      const li = document.createElement('li');
      li.textContent = t;
      ul.appendChild(li);
    });
    if (!(items || []).length) {
      const li = document.createElement('li');
      li.textContent = '—';
      ul.appendChild(li);
    }
  }

  // ------------------------------------------------------------------
  // session recording (WebM)
  // ------------------------------------------------------------------

  function startRecording() {
    try {
      const stage = document.querySelector('.classroom-stage');
      const canvasStream = captureStageCanvas();
      if (!canvasStream) return;
      const mix = new AudioContext();
      const dest = mix.createMediaStreamDestination();
      // mix all audio elements via MediaElementSource won't work across
      // elements loaded later; simplest: record canvas video only, plus
      // system audio via getDisplayMedia is not guaranteed. We record the
      // canvas + a live gain node fed by the live WS audio.
      const stream = new MediaStream([
        ...canvasStream.getVideoTracks(),
      ]);
      state.recorder = new MediaRecorder(stream, {
        mimeType: pickMime(), videoBitsPerSecond: 4_500_000,
      });
      state.recChunks = [];
      state.recorder.ondataavailable = (e) => {
        if (e.data.size) state.recChunks.push(e.data);
      };
      state.recorder.onstop = () => {
        // chunks kept; download happens via the report-screen button
      };
      state.recorder.start(1000);
      $('rec-dot').classList.remove('hidden');
    } catch (e) {
      console.warn('Recording not available:', e);
    }
  }

  function captureStageCanvas() {
    // Composite the whole classroom stage onto an offscreen canvas.
    const stage = document.querySelector('.classroom-stage');
    const w = stage.clientWidth, h = stage.clientHeight;
    const out = document.createElement('canvas');
    out.width = w; out.height = h;
    const octx = out.getContext('2d');
    const videoEl = $('talkinghead').querySelector('video') ||
                   $('talkinghead').querySelector('canvas');
    const board = $('whiteboard');
    function frame() {
      octx.fillStyle = '#1a1512';
      octx.fillRect(0, 0, w, h);
      try {
        if (videoEl) {
          // avatar column ~300px
          const vw = 300, vh = videoEl.videoHeight ?
            (videoEl.videoHeight / videoEl.videoWidth) * vw : h;
          octx.drawImage(videoEl, 0, 0, vw, Math.min(h, vh));
        }
        if (board) octx.drawImage(board, 300, 0, w - 300, h);
      } catch (e) { /* drawImage may fail on tainted canvas */ }
      requestAnimationFrame(frame);
    }
    frame();
    return out.captureStream(30);
  }

  function pickMime() {
    const candidates = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8',
                        'video/webm'];
    for (const m of candidates) {
      if (MediaRecorder.isTypeSupported(m)) return m;
    }
    return '';
  }

  function stopRecording() {
    if (state.recorder && state.recorder.state !== 'inactive') {
      try { state.recorder.stop(); } catch (e) {}   // onstop keeps chunks
    }
    $('rec-dot').classList.add('hidden');
  }

  function downloadRecording() {
    if (state.recorder && state.recorder.state !== 'inactive') {
      stopRecording();
      toast('Finishing recording… use the button again in a moment.');
      return;
    }
    if (!state.recChunks.length) {
      toast('No recording captured in this session.');
      return;
    }
    const blob = new Blob(state.recChunks, { type: pickMime() || 'video/webm' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ai-teacher-lesson-${state.sessionId}.webm`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // ------------------------------------------------------------------
  // language switching
  // ------------------------------------------------------------------

  function setLanguage(lang, reRender) {
    state.language = lang;
    updateLangPill();
    if (reRender) {
      toast('Re-rendering remaining lesson in the new language…');
      // simplest robust approach: re-plan + re-capture remaining segments
      // (planner is fast; capture is the cost) — offer via toast for demo
    }
  }

  function updateLangPill() {
    $('lang-pill').textContent =
      { en: 'EN', hi: 'हिं', hinglish: 'HINGLISH' }[state.language] || 'EN';
  }

  // ------------------------------------------------------------------
  // reasoning badge
  // ------------------------------------------------------------------

  function addReasoning(decision, why) {
    const entry = document.createElement('div');
    entry.className = 'rp-entry';
    entry.innerHTML = `<div class="rp-time">${new Date().toLocaleTimeString()}</div>
      <div class="rp-decision ${/^[✅⏭]/.test(decision) ? 'ok' :
        (/^[❌]/.test(decision) ? 'warn' : '')}">${escapeHtml(decision)}</div>
      <div class="rp-why">${escapeHtml(why || '')}</div>`;
    $('rp-body').prepend(entry);
  }

  function toggleReasoningPanel() {
    $('reasoning-panel').classList.toggle('hidden');
  }

  // ------------------------------------------------------------------
  // misc ui
  // ------------------------------------------------------------------

  function showThinking(text) {
    const t = $('toast');
    t.textContent = '⏳ ' + text;
    t.classList.remove('hidden');
  }

  function hideThinking() {
    $('toast').classList.add('hidden');
  }

  function toast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.remove('hidden');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add('hidden'), 3200);
  }

  function arrayBufferToB64(buf) {
    const bin = new Uint8Array(buf);
    let s = '';
    const chunk = 0x8000;
    for (let i = 0; i < bin.length; i += chunk) {
      s += String.fromCharCode.apply(null, bin.subarray(i, i + chunk));
    }
    return btoa(s);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }

  return { start, setLanguage, toast };
})();
