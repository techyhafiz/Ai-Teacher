/**
 * AI Teacher 3D Avatar Engine
 * High-performance Three.js & GLTF avatar engine with multi-band formant
 * audio analysis, Oculus visemes, ARKit blendshapes, and phonetic coarticulation.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// Oculus & ARKit Viseme mappings for English & Multilingual syllables
const PHONEME_VISEME_MAP = {
  'a': 'viseme_aa', 'e': 'viseme_E', 'i': 'viseme_I', 'o': 'viseme_O', 'u': 'viseme_U',
  'b': 'viseme_PP', 'p': 'viseme_PP', 'm': 'viseme_PP',
  'f': 'viseme_FF', 'v': 'viseme_FF',
  't': 'viseme_DD', 'd': 'viseme_DD', 'n': 'viseme_DD', 'l': 'viseme_DD',
  'k': 'viseme_kk', 'g': 'viseme_kk', 'c': 'viseme_kk', 'q': 'viseme_kk',
  's': 'viseme_SS', 'z': 'viseme_SS',
  'r': 'viseme_RR', 'w': 'viseme_U',
  'j': 'viseme_CH', 'h': 'viseme_aa', 'y': 'viseme_I',
  ' ': 'viseme_sil'
};

export class Avatar3DEngine {
  constructor(container, options = {}) {
    this.container = container;
    this.options = Object.assign({
      cameraView: 'upper', // 'upper' | 'head' | 'full'
      idleMove: true,
      shadows: true,
      lipSyncSensitivity: 1.25, // Expressive mouth movement multiplier
      lipSyncMaxOpen: 0.82,     // Hard cap on how wide the mouth can open (0..1) — lower = calmer
    }, options);

    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.model = null;
    this.morphMeshes = [];
    this.headBone = null;
    this.neckBone = null;
    this.spineBone = null;

    // Audio & Lip-sync State
    this.audioCtx = null;
    this.analyser = null;
    this.freqData = null;
    this.isSpeaking = false;
    this.speechSource = null;
    this.audioPeakEnergy = 0.15;

    // Active Viseme Weights (smoothed)
    this.visemeWeights = {
      viseme_aa: 0,
      viseme_E: 0,
      viseme_I: 0,
      viseme_O: 0,
      viseme_U: 0,
      viseme_PP: 0,
      viseme_FF: 0,
      viseme_DD: 0,
      viseme_kk: 0,
      viseme_SS: 0,
      viseme_CH: 0,
      viseme_RR: 0,
      viseme_sil: 1,
      mouthOpen: 0,
      jawOpen: 0,
      mouthPucker: 0,
      mouthFunnel: 0,
      mouthStretch: 0,
      mouthLowerDown: 0,
      mouthUpperUp: 0,
    };

    // Phonetic Timed Queue for text speech fallback
    this.phoneticQueue = [];
    this.phoneticStartTime = 0;

    // Animation states
    this.animId = null;
    this.clock = new THREE.Clock();
    this.breathPhase = 0;
    this.blinkValue = 0;
    this.nextBlinkTime = 0;
    this.isBlinking = false;
    this.currentMood = 'neutral';
    this.moodInfluences = { smile: 0, thoughtful: 0, surprised: 0 };

    this._initScene();
  }

  _initScene() {
    const W = this.container.clientWidth || 400;
    const H = this.container.clientHeight || 500;

    // 1. Scene
    this.scene = new THREE.Scene();

    // 2. Camera: Centered on avatar face and upper bust
    this.camera = new THREE.PerspectiveCamera(28, W / H, 0.1, 100);
    this.camera.position.set(0, 1.58, 1.15);

    // 3. WebGL Renderer
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(W, H);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.innerHTML = '';
    this.container.appendChild(this.renderer.domElement);

    // 4. Orbit Controls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.target.set(0, 1.56, 0);
    this.controls.minDistance = 0.4;
    this.controls.maxDistance = 5.0;

    // 5. Studio Lighting
    const ambientLight = new THREE.AmbientLight(0xffeedd, 1.5);
    this.scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.3);
    keyLight.position.set(1.2, 2.5, 2.0);
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xaaccff, 1.1);
    fillLight.position.set(-1.5, 1.8, 1.5);
    this.scene.add(fillLight);

    const rimLight = new THREE.DirectionalLight(0xffaa44, 1.6);
    rimLight.position.set(0, 2.5, -2.0);
    this.scene.add(rimLight);

    // 6. Resize Observer
    this.resizeObserver = new ResizeObserver(() => this._onResize());
    this.resizeObserver.observe(this.container);

    // 7. Start Animation Loop
    this.nextBlinkTime = performance.now() + 2000;
    this._animate();
  }

  _onResize() {
    if (!this.container || !this.renderer || !this.camera) return;
    const W = this.container.clientWidth || 400;
    const H = this.container.clientHeight || 500;
    this.camera.aspect = W / H;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(W, H);
  }

  async loadModel(url, onProgress = null) {
    return new Promise((resolve, reject) => {
      const loader = new GLTFLoader();
      loader.load(
        url,
        (gltf) => {
          if (this.model) {
            this.scene.remove(this.model);
            this.model = null;
          }

          this.model = gltf.scene;
          this.morphMeshes = [];
          this.headBone = null;
          this.neckBone = null;
          this.spineBone = null;
          this.leftArmBone = null;
          this.rightArmBone = null;
          this.leftForeArmBone = null;
          this.rightForeArmBone = null;
          this.leftHandBone = null;
          this.rightHandBone = null;
          this.leftShoulderBone = null;
          this.rightShoulderBone = null;

          // Collect morph target meshes and skeleton bones
          this.model.traverse((child) => {
            if (child.isMesh && child.morphTargetDictionary && child.morphTargetInfluences) {
              this.morphMeshes.push(child);
            }
            if (child.isBone || child.type === 'Bone') {
              const name = child.name.toLowerCase();
              if (name.includes('head') && !name.includes('top') && !name.includes('mesh')) this.headBone = child;
              else if (name.includes('neck')) this.neckBone = child;
              else if (name.includes('spine') && !this.spineBone) this.spineBone = child;
              else if (name.includes('leftarm') || name.includes('arm_l') || name.includes('arm.l')) this.leftArmBone = child;
              else if (name.includes('rightarm') || name.includes('arm_r') || name.includes('arm.r')) this.rightArmBone = child;
              else if (name.includes('leftforearm') || name.includes('forearm_l') || name.includes('forearm.l')) this.leftForeArmBone = child;
              else if (name.includes('rightforearm') || name.includes('forearm_r') || name.includes('forearm.r')) this.rightForeArmBone = child;
              else if (name.includes('lefthand') || name.includes('hand_l') || name.includes('hand.l')) this.leftHandBone = child;
              else if (name.includes('righthand') || name.includes('hand_r') || name.includes('hand.r')) this.rightHandBone = child;
              else if (name.includes('leftshoulder') || name.includes('shoulder_l')) this.leftShoulderBone = child;
              else if (name.includes('rightshoulder') || name.includes('shoulder_r')) this.rightShoulderBone = child;
            }
          });

          // Apply natural relaxed standing posture (eliminates T-pose / hands broad)
          this._applyTeacherPose();

          this.scene.add(this.model);
          this.setCameraView(this.options.cameraView);
          resolve(gltf);
        },
        (xhr) => {
          if (onProgress && xhr.total > 0) {
            onProgress(xhr.loaded / xhr.total);
          }
        },
        (err) => reject(err)
      );
    });
  }

  _applyTeacherPose() {
    // Human-like relaxed standing teacher pose
    // Rotates arms down along the torso in clean resting posture
    if (this.leftArmBone) {
      this.leftArmBone.rotation.set(0.12, 0.0, 1.28);
    }
    if (this.rightArmBone) {
      this.rightArmBone.rotation.set(0.12, 0.0, -1.28);
    }
    if (this.leftForeArmBone) {
      this.leftForeArmBone.rotation.set(0, 0, 0);
    }
    if (this.rightForeArmBone) {
      this.rightForeArmBone.rotation.set(0, 0, 0);
    }
    if (this.leftHandBone) {
      this.leftHandBone.rotation.set(0, 0, 0);
    }
    if (this.rightHandBone) {
      this.rightHandBone.rotation.set(0, 0, 0);
    }
    if (this.leftShoulderBone) {
      this.leftShoulderBone.rotation.set(0, 0, 0.04);
    }
    if (this.rightShoulderBone) {
      this.rightShoulderBone.rotation.set(0, 0, -0.04);
    }
  }

  setCameraView(view) {
    this.options.cameraView = view;
    if (!this.camera || !this.controls) return;

    if (view === 'head') {
      this.camera.position.set(0, 1.66, 0.72);
      this.controls.target.set(0, 1.63, 0);
    } else if (view === 'full') {
      this.camera.position.set(0, 1.1, 2.8);
      this.controls.target.set(0, 0.95, 0);
    } else { // Upper bust / classroom
      this.camera.position.set(0, 1.58, 1.15);
      this.controls.target.set(0, 1.56, 0);
    }
    this.controls.update();
  }

  setMood(mood) {
    this.currentMood = mood;
  }

  setSensitivity(val) {
    this.options.lipSyncSensitivity = parseFloat(val) || 1.2;
  }

  _getAudioContext() {
    if (!this.audioCtx) {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (this.audioCtx.state === 'suspended') this.audioCtx.resume();
    return this.audioCtx;
  }

  attachAudioSource(sourceNode) {
    if (!sourceNode) return;
    try {
      // CRITICAL: Always use the source node's own AudioContext to prevent cross-context connect errors!
      const actx = sourceNode.context || this._getAudioContext();
      if (actx.state === 'suspended') {
        actx.resume().catch(() => {});
      }
      this.analyser = actx.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.5; // Balanced: responsive but not jittery
      this.freqData = new Uint8Array(this.analyser.frequencyBinCount);
      sourceNode.connect(this.analyser);
      console.info('Successfully attached audio source to 3D avatar lipsync analyser');
    } catch (e) {
      console.warn('Cross-context audio connect error, fallback:', e);
    }
    this.isSpeaking = true;
  }

  setSpeaking(speaking) {
    this.isSpeaking = speaking;
    if (!speaking) {
      this.phoneticQueue = [];
      Object.keys(this.visemeWeights).forEach(k => {
        this.visemeWeights[k] = (k === 'viseme_sil' ? 1.0 : 0.0);
      });
    }
  }

  /**
   * Play an audio URL (e.g. sample WAV) through WebAudio with 100% sync
   */
  async playVoiceSample(url, onEnd = null) {
    try {
      const actx = this._getAudioContext();
      if (this.speechSource) {
        try { this.speechSource.stop(); } catch (e) {}
      }

      const resp = await fetch(url);
      const arrayBuf = await resp.arrayBuffer();
      const audioBuf = await actx.decodeAudioData(arrayBuf);

      this.speakAudio(audioBuf, onEnd);
    } catch (e) {
      console.error('Failed to play voice sample:', e);
      this.setSpeaking(false);
      if (onEnd) onEnd();
    }
  }

  /**
   * High-fidelity audio buffer playback with real-time formant frequency analysis
   */
  speakAudio(audioBuffer, onEnd = null) {
    const actx = this._getAudioContext();
    if (this.speechSource) {
      try { this.speechSource.stop(); } catch (e) {}
    }

    const src = actx.createBufferSource();
    src.buffer = audioBuffer;
    src.connect(actx.destination);
    this.attachAudioSource(src);

    src.onended = () => {
      this.setSpeaking(false);
      if (onEnd) onEnd();
    };

    src.start();
    this.speechSource = src;
  }

  /**
   * Text-driven speech with phonetic syllable queue
   */
  speakText(text, onEnd = null) {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();

    // 1. Build timed phonetic viseme sequence from syllables
    const queue = [];
    const cleanText = text.toLowerCase().replace(/[^a-z0-9\s]/g, '');
    const words = cleanText.split(/\s+/).filter(Boolean);

    let currentTime = 0;
    const avgCharDuration = 65; // ms per character

    for (const word of words) {
      for (let i = 0; i < word.length; i++) {
        const ch = word[i];
        const nextCh = word[i + 1] || '';
        
        let viseme = 'viseme_aa';
        if (ch === 's' && nextCh === 'h') { viseme = 'viseme_CH'; i++; }
        else if (ch === 'c' && nextCh === 'h') { viseme = 'viseme_CH'; i++; }
        else if (ch === 't' && nextCh === 'h') { viseme = 'viseme_TH'; i++; }
        else if (ch === 'e' && nextCh === 'e') { viseme = 'viseme_I'; i++; }
        else if (ch === 'o' && nextCh === 'o') { viseme = 'viseme_U'; i++; }
        else {
          viseme = PHONEME_VISEME_MAP[ch] || 'viseme_aa';
        }

        const dur = (viseme === 'viseme_PP' || viseme === 'viseme_FF' ? 55 : (viseme.includes('viseme_') ? 85 : 65));
        queue.push({
          viseme: viseme,
          start: currentTime,
          end: currentTime + dur,
          intensity: (viseme === 'viseme_PP' ? 0.9 : 0.95),
        });
        currentTime += dur;
      }
      // Space pause between words
      queue.push({
        viseme: 'viseme_sil',
        start: currentTime,
        end: currentTime + 55,
        intensity: 0.2,
      });
      currentTime += 55;
    }

    this.phoneticQueue = queue;
    this.phoneticStartTime = performance.now();
    this.isSpeaking = true;

    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.pitch = 1.0;

    u.onend = () => {
      this.setSpeaking(false);
      if (onEnd) onEnd();
    };

    window.speechSynthesis.speak(u);
  }

  /**
   * Set target value across all morph target meshes
   */
  _applyMorph(targetName, value) {
    const val = Math.max(0, Math.min(1.0, value));
    for (const mesh of this.morphMeshes) {
      const dict = mesh.morphTargetDictionary;
      const influences = mesh.morphTargetInfluences;
      if (!dict || !influences) continue;

      if (dict[targetName] !== undefined) {
        influences[dict[targetName]] = val;
      } else {
        const lower = targetName.toLowerCase();
        for (const [name, idx] of Object.entries(dict)) {
          if (name.toLowerCase() === lower) {
            influences[idx] = val;
            break;
          }
        }
      }
    }
  }

  _animate() {
    this.animId = requestAnimationFrame(() => this._animate());
    const delta = this.clock.getDelta();
    const now = performance.now();

    // -------------------------------------------------------------
    // 1. Lip-Sync: Multi-Band Acoustic Formant & Viseme Engine
    // -------------------------------------------------------------
    const targets = {
      viseme_aa: 0, viseme_E: 0, viseme_I: 0, viseme_O: 0, viseme_U: 0,
      viseme_PP: 0, viseme_FF: 0, viseme_DD: 0, viseme_kk: 0, viseme_SS: 0,
      viseme_CH: 0, viseme_RR: 0, viseme_sil: 1,
      mouthOpen: 0, jawOpen: 0, mouthPucker: 0, mouthFunnel: 0,
      mouthStretch: 0, mouthLowerDown: 0, mouthUpperUp: 0,
    };

    const sensitivity = this.options.lipSyncSensitivity || 1.25;

    if (this.analyser && this.freqData && this.isSpeaking) {
      this.analyser.getByteFrequencyData(this.freqData);
      
      // Band 1: Base / Vocal Cords (100 - 350 Hz) -> bins 1-4
      let eBase = 0;
      for (let i = 1; i <= 4; i++) eBase += this.freqData[i];
      eBase /= (4 * 255);

      // Band 2: F1 (Jaw / Open Vowels: 350 - 900 Hz) -> bins 5-11
      let eF1 = 0;
      for (let i = 5; i <= 11; i++) eF1 += this.freqData[i];
      eF1 /= (7 * 255);

      // Band 3: F2 (Lip Spread / Vowel Quality: 900 - 2400 Hz) -> bins 12-28
      let eF2 = 0;
      for (let i = 12; i <= 28; i++) eF2 += this.freqData[i];
      eF2 /= (17 * 255);

      // Band 4: F3 (Consonants / Sibilants: 2400 - 5500 Hz) -> bins 29-64
      let eF3 = 0;
      for (let i = 29; i <= Math.min(64, this.freqData.length - 1); i++) eF3 += this.freqData[i];
      eF3 /= (35 * 255);

      const totalEnergy = (eBase * 0.2 + eF1 * 0.45 + eF2 * 0.25 + eF3 * 0.1);
      this.audioPeakEnergy = Math.max(0.12, this.audioPeakEnergy * 0.98, totalEnergy);
      const normalizedEnergy = Math.min(1.0, (totalEnergy / Math.max(0.08, this.audioPeakEnergy * 0.75)) * sensitivity);

      if (totalEnergy > 0.03) {
        targets.viseme_sil = 0;

        // ONE coherent "openness" value drives the mouth. We deliberately do NOT
        // stack a full-strength vowel viseme on top of a wide jawOpen+mouthOpen
        // (that combo was the "weird" over-gaping mouth). The visemes below only
        // *accent* the shape, scaled down and proportional to `open`.
        const maxOpen = this.options.lipSyncMaxOpen || 0.82;
        const open = Math.min(maxOpen, normalizedEnergy);
        targets.jawOpen = open * 0.55;   // human-scaled jaw
        targets.mouthOpen = open * 0.45;

        // Gentle vowel accent from formant ratios (small, proportional to open)
        if (eF1 > eF2 * 1.2) {
          // Open vowel 'ah'
          targets.viseme_aa = open * 0.45;
        } else if (eF2 > eF1 * 1.05) {
          // Front vowel 'ee / eh'
          targets.viseme_E = open * 0.40;
          targets.mouthStretch = open * 0.30;
        } else {
          // Back vowel 'oh / oo'
          targets.viseme_O = open * 0.40;
          targets.mouthPucker = open * 0.25;
        }

        // Light sibilant hiss (s / f / ch) — subtle, never a full shape
        if (eF3 > 0.15 && eF3 > eF1 * 0.7) {
          targets.viseme_SS = Math.min(0.30, eF3 * 0.8);
        }

        // Plosive lip closure (p / b / m): briefly shut the mouth completely
        if (totalEnergy < 0.10 && eBase > 0.05) {
          targets.viseme_PP = 0.6;
          targets.jawOpen = 0;
          targets.mouthOpen = 0;
          targets.viseme_aa = 0; targets.viseme_E = 0; targets.viseme_O = 0;
        }
      } else {
        targets.viseme_sil = 1.0;
      }
    } else if (this.isSpeaking && this.phoneticQueue.length > 0) {
      // Text phonetic queue fallback
      const elapsed = now - this.phoneticStartTime;
      const active = this.phoneticQueue.find(p => elapsed >= p.start && elapsed <= p.end);

      if (active) {
        targets.viseme_sil = 0;
        const v = active.viseme;
        targets[v] = active.intensity * sensitivity;
        if (v === 'viseme_aa' || v === 'viseme_O') {
          targets.mouthOpen = 0.92;
          targets.jawOpen = 0.85;
          targets.mouthLowerDown = 0.70;
        } else if (v === 'viseme_E' || v === 'viseme_I') {
          targets.mouthOpen = 0.55;
          targets.mouthStretch = 0.75;
          targets.mouthLowerDown = 0.40;
        } else if (v === 'viseme_PP') {
          targets.mouthOpen = 0;
          targets.jawOpen = 0;
          targets.viseme_PP = 0.9;
        } else {
          targets.mouthOpen = 0.45;
          targets.jawOpen = 0.35;
        }
      } else if (elapsed > (this.phoneticQueue[this.phoneticQueue.length - 1]?.end || 0)) {
        this.setSpeaking(false);
      }
    }

    // Coarticulation Smoothing (attack & decay)
    const attackSpeed = 0.45; // Eased attack — reaches the shape without twitching
    const decaySpeed = 0.22;  // Smooth natural release
    for (const [key, targetVal] of Object.entries(targets)) {
      const current = this.visemeWeights[key] || 0;
      const speed = targetVal > current ? attackSpeed : decaySpeed;
      this.visemeWeights[key] += (targetVal - current) * speed;
      this._applyMorph(key, this.visemeWeights[key]);
    }

    // Bilateral Lip Controls
    this._applyMorph('mouthStretchLeft', this.visemeWeights.mouthStretch || 0);
    this._applyMorph('mouthStretchRight', this.visemeWeights.mouthStretch || 0);
    this._applyMorph('mouthLowerDownLeft', this.visemeWeights.mouthLowerDown || 0);
    this._applyMorph('mouthLowerDownRight', this.visemeWeights.mouthLowerDown || 0);
    this._applyMorph('mouthUpperUpLeft', this.visemeWeights.mouthUpperUp || 0);
    this._applyMorph('mouthUpperUpRight', this.visemeWeights.mouthUpperUp || 0);

    // -------------------------------------------------------------
    // 2. Natural Blinking Logic
    // -------------------------------------------------------------
    if (now > this.nextBlinkTime) {
      this.isBlinking = true;
      this.blinkValue += 0.28;
      if (this.blinkValue >= 1) {
        this.blinkValue = 1;
        this.nextBlinkTime = now + 2800 + Math.random() * 3200;
      }
    } else if (this.isBlinking) {
      this.blinkValue -= 0.28;
      if (this.blinkValue <= 0) {
        this.blinkValue = 0;
        this.isBlinking = false;
      }
    }
    this._applyMorph('eyeBlinkLeft', this.blinkValue);
    this._applyMorph('eyeBlinkRight', this.blinkValue);
    this._applyMorph('eyesClosed', this.blinkValue);

    // -------------------------------------------------------------
    // 3. Mood / Expression Blendshapes
    // -------------------------------------------------------------
    const targetSmile = this.currentMood === 'happy' ? 0.75 : (this.currentMood === 'neutral' ? 0.2 : 0);
    const targetThoughtful = this.currentMood === 'thoughtful' ? 0.65 : 0;
    const targetSurprised = this.currentMood === 'surprised' ? 0.85 : 0;

    this.moodInfluences.smile += (targetSmile - this.moodInfluences.smile) * 0.1;
    this.moodInfluences.thoughtful += (targetThoughtful - this.moodInfluences.thoughtful) * 0.1;
    this.moodInfluences.surprised += (targetSurprised - this.moodInfluences.surprised) * 0.1;

    this._applyMorph('mouthSmile', this.moodInfluences.smile);
    this._applyMorph('mouthSmileLeft', this.moodInfluences.smile);
    this._applyMorph('mouthSmileRight', this.moodInfluences.smile);
    this._applyMorph('browInnerUp', this.moodInfluences.thoughtful + this.moodInfluences.surprised);
    this._applyMorph('browDownLeft', this.moodInfluences.thoughtful * 0.5);
    this._applyMorph('browDownRight', this.moodInfluences.thoughtful * 0.5);

    // -------------------------------------------------------------
    // 4. Idle Organic Breathing & Natural Teacher Gestures
    // -------------------------------------------------------------
    if (this.options.idleMove) {
      this.breathPhase += 0.035;
      const breath = Math.sin(this.breathPhase);

      // Spine & Torso Breathing
      if (this.spineBone) {
        this.spineBone.rotation.x = Math.sin(this.breathPhase * 0.8) * 0.012;
        this.spineBone.rotation.y = Math.sin(this.breathPhase * 0.5) * 0.010;
      }
      if (this.neckBone) {
        this.neckBone.rotation.y = Math.sin(this.breathPhase * 0.6) * 0.015;
      }

      // Head Tilts and Speech Nodding
      if (this.headBone) {
        const talkNod = this.isSpeaking ? Math.sin(this.breathPhase * 2.5) * 0.045 : 0;
        this.headBone.rotation.x = 0.02 + breath * 0.015 + talkNod;
        this.headBone.rotation.y = Math.sin(this.breathPhase * 0.7) * 0.025;
        this.headBone.rotation.z = Math.sin(this.breathPhase * 0.5) * 0.01;
      }

      // Natural Teaching Posture & Subtle Breathing Sway
      if (this.leftArmBone) {
        this.leftArmBone.rotation.z = 1.28 + Math.sin(this.breathPhase * 0.8) * 0.015;
      }
      if (this.rightArmBone) {
        this.rightArmBone.rotation.z = -1.28 - Math.sin(this.breathPhase * 0.8) * 0.015;
      }
      if (this.leftForeArmBone) {
        this.leftForeArmBone.rotation.set(0, 0, 0);
      }
      if (this.rightForeArmBone) {
        this.rightForeArmBone.rotation.set(0, 0, 0);
      }
    }

    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }

  dispose() {
    if (this.animId) cancelAnimationFrame(this.animId);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    if (this.speechSource) try { this.speechSource.stop(); } catch (e) {}
    if (this.renderer && this.renderer.domElement) {
      this.renderer.domElement.remove();
    }
  }
}
