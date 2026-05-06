import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react';
import { API_ENDPOINTS, getAuthHeaders } from './api-config';
import { useAuth } from './auth-context';

declare global {
  interface Window {
    SpeechRecognition?: any;
    webkitSpeechRecognition?: any;
  }
}

interface StartOpts {
  jobId: string;
  language: string;
  deviceId?: string;
  initialTranscript?: string;
}

interface Ctx {
  /** id of the job we are currently recording for, null if idle */
  activeJobId: string | null;
  /** committed transcript for the active job */
  transcript: string;
  /** in-flight interim words */
  interim: string;
  /** mic VU level 0..1 */
  vuLevel: number;
  /** whether SpeechRecognition is actively listening */
  listening: boolean;
  /** language of the current session */
  language: string;
  /** start (or resume) recording for a job */
  start: (opts: StartOpts) => Promise<void>;
  /** pause + tear down recognition (transcript stays in DB & memory) */
  stop: () => Promise<void>;
  /** replace transcript text (used for manual edits on the job page) */
  setTranscript: (next: string | ((prev: string) => string)) => void;
  /** update recognition language without losing transcript */
  setLanguage: (lang: string) => void;
  /** switch microphone */
  changeDevice: (deviceId: string) => Promise<void>;
  /** snapshot save right now (best-effort, non-blocking error) */
  flushSave: () => Promise<void>;
  /** speech api availability */
  speechSupported: boolean;
}

const VoiceRecordingContext = createContext<Ctx | null>(null);

const AUTOSAVE_MS = 8000;

export function VoiceRecordingProvider({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  const tokenRef = useRef<string | null>(token);
  useEffect(() => { tokenRef.current = token; }, [token]);

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [transcript, _setTranscriptState] = useState('');
  const [interim, setInterim] = useState('');
  const [vuLevel, setVuLevel] = useState(0);
  const [listening, setListening] = useState(false);
  const [language, _setLanguageState] = useState('hi-IN');

  // refs that survive re-renders
  const recogRef = useRef<any>(null);
  const wantListeningRef = useRef(false);
  const transcriptRef = useRef('');
  const lastSavedTranscriptRef = useRef('');
  const activeJobIdRef = useRef<string | null>(null);
  const languageRef = useRef('hi-IN');
  const deviceIdRef = useRef<string | undefined>(undefined);
  // Idempotency lock — multiple stop() callers (e.g. indicator X and editor
  // Stop button) coalesce onto the same in-flight teardown.
  const stopPromiseRef = useRef<Promise<void> | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const vuRafRef = useRef<number | null>(null);

  const speechSupported = typeof window !== 'undefined' && (
    !!window.SpeechRecognition || !!window.webkitSpeechRecognition
  );

  const setTranscript = useCallback((next: string | ((prev: string) => string)) => {
    _setTranscriptState(prev => {
      const val = typeof next === 'function' ? (next as any)(prev) : next;
      transcriptRef.current = val;
      return val;
    });
  }, []);

  const setLanguage = useCallback((lang: string) => {
    languageRef.current = lang;
    _setLanguageState(lang);
    // If listening, restart recognition with new lang
    if (recogRef.current && wantListeningRef.current) {
      try { recogRef.current.stop(); } catch { /* ignore */ }
      // onend handler will rebuild with the new languageRef value
    }
  }, []);

  const stopMicStream = useCallback(() => {
    if (vuRafRef.current) cancelAnimationFrame(vuRafRef.current);
    vuRafRef.current = null;
    micStreamRef.current?.getTracks().forEach(t => t.stop());
    micStreamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    setVuLevel(0);
  }, []);

  const startVuMeter = useCallback(async (deviceId?: string) => {
    stopMicStream();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
    micStreamRef.current = stream;
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyserRef.current = analyser;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      setVuLevel(Math.sqrt(sum / data.length));
      vuRafRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, [stopMicStream]);

  const buildRecognition = useCallback(() => {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) throw new Error('Speech recognition not supported in this browser');
    const recog = new Ctor();
    recog.continuous = true;
    recog.interimResults = true;
    recog.lang = languageRef.current;

    recog.onresult = (event: any) => {
      let finalChunk = '';
      let interimChunk = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) finalChunk += result[0].transcript;
        else interimChunk += result[0].transcript;
      }
      if (finalChunk) {
        setTranscript(prev => (prev + ' ' + finalChunk).replace(/\s+/g, ' ').trimStart());
      }
      setInterim(interimChunk);
    };

    recog.onerror = (e: any) => {
      // 'no-speech' / 'audio-capture' are recoverable; rely on onend auto-restart
      if (e.error === 'no-speech' || e.error === 'audio-capture') return;
      console.warn('Speech recognition error', e);
    };

    recog.onend = () => {
      setInterim('');
      // Auto-restart while user wants it on (handles long silences and lang swap)
      if (wantListeningRef.current && recogRef.current === recog) {
        try {
          const next = buildRecognition();
          recogRef.current = next;
          next.start();
        } catch { /* ignore */ }
      } else {
        setListening(false);
      }
    };

    return recog;
  }, [setTranscript]);

  const start = useCallback(async ({ jobId, language: lang, deviceId, initialTranscript }: StartOpts) => {
    if (!speechSupported) {
      throw new Error('Voice typing requires Chrome or Edge desktop browser.');
    }
    // If switching to a new job, stop the previous session first
    if (activeJobIdRef.current && activeJobIdRef.current !== jobId) {
      await stopInternal();
    }

    activeJobIdRef.current = jobId;
    setActiveJobId(jobId);
    languageRef.current = lang;
    _setLanguageState(lang);
    deviceIdRef.current = deviceId;

    if (typeof initialTranscript === 'string') {
      transcriptRef.current = initialTranscript;
      lastSavedTranscriptRef.current = initialTranscript;
      _setTranscriptState(initialTranscript);
    }

    if (!micStreamRef.current) {
      await startVuMeter(deviceId);
    }

    wantListeningRef.current = true;
    const recog = buildRecognition();
    recogRef.current = recog;
    recog.start();
    setListening(true);
  }, [speechSupported, startVuMeter, buildRecognition]);

  const stopInternal = useCallback(async () => {
    // Signal to the auto-restart logic in onend that we don't want to relaunch.
    wantListeningRef.current = false;

    // Capture the job id BEFORE we tear down — needed for the
    // status='awaiting_review' PATCH that finalises the server-side
    // lifecycle. Doing this here means the indicator's X button and the
    // editor's Stop button have IDENTICAL effects.
    const finalisingJobId = activeJobIdRef.current;

    // Web Speech API delivers any in-flight final chunks AFTER stop() but BEFORE
    // onend fires. We must await onend so transcriptRef contains the late-final
    // text BEFORE we flushSave (otherwise we lose the trailing words).
    const recog = recogRef.current;
    if (recog) {
      await new Promise<void>((resolve) => {
        let settled = false;
        const finish = () => { if (!settled) { settled = true; resolve(); } };
        // Override onend with our resolver (the auto-restart branch is gated
        // on wantListeningRef which is now false, so it won't relaunch).
        recog.onend = () => { setInterim(''); setListening(false); finish(); };
        try { recog.stop(); } catch { finish(); }
        // Hard timeout — some browsers occasionally drop onend.
        setTimeout(finish, 1500);
      });
    }
    recogRef.current = null;
    setListening(false);
    setInterim('');
    stopMicStream();

    // Best-effort final save BEFORE we drop the active job reference,
    // otherwise flushSaveInternal would early-out.
    await flushSaveInternal();

    // Flip the server-side lifecycle to awaiting_review now that recording
    // is truly over. Best-effort — non-fatal if it 4xx's (e.g. job already
    // moved past recording).
    if (finalisingJobId) {
      try {
        await fetch(API_ENDPOINTS.voiceTyping.update(finalisingJobId), {
          method: 'PATCH',
          headers: getAuthHeaders(tokenRef.current || undefined),
          body: JSON.stringify({ status: 'awaiting_review' }),
        });
      } catch (e) {
        console.warn('voice-typing stop: status PATCH failed (non-fatal)', e);
      }
    }

    // Release the active session so a different job can take over cleanly.
    activeJobIdRef.current = null;
    setActiveJobId(null);
    transcriptRef.current = '';
    lastSavedTranscriptRef.current = '';
    _setTranscriptState('');
  }, [stopMicStream]);

  const stop = useCallback(async () => {
    // Idempotent: concurrent callers (indicator X + editor Stop button)
    // coalesce to the same in-flight teardown.
    if (stopPromiseRef.current) {
      return stopPromiseRef.current;
    }
    const p = (async () => {
      try { await stopInternal(); }
      finally { stopPromiseRef.current = null; }
    })();
    stopPromiseRef.current = p;
    return p;
  }, [stopInternal]);

  const changeDevice = useCallback(async (deviceId: string) => {
    deviceIdRef.current = deviceId;
    if (!micStreamRef.current && !wantListeningRef.current) return;
    const wasListening = wantListeningRef.current;
    if (wasListening) {
      try { recogRef.current?.stop(); } catch { /* ignore */ }
    }
    await startVuMeter(deviceId);
    if (wasListening) {
      const recog = buildRecognition();
      recogRef.current = recog;
      try { recog.start(); } catch { /* ignore */ }
    }
  }, [startVuMeter, buildRecognition]);

  const flushSaveInternal = useCallback(async () => {
    const jobId = activeJobIdRef.current;
    if (!jobId) return;
    const text = transcriptRef.current;
    if (text === lastSavedTranscriptRef.current) return;
    const tk = tokenRef.current;
    try {
      const resp = await fetch(API_ENDPOINTS.voiceTyping.update(jobId), {
        method: 'PATCH',
        headers: getAuthHeaders(tk || undefined),
        body: JSON.stringify({ transcriptText: text, language: languageRef.current }),
      });
      if (resp.ok) {
        lastSavedTranscriptRef.current = text;
      }
    } catch (e) {
      console.warn('Voice typing autosave failed', e);
    }
  }, []);

  const flushSave = useCallback(() => flushSaveInternal(), [flushSaveInternal]);

  // Autosave loop while there is an active job (works across page navigation)
  useEffect(() => {
    if (!activeJobId) return;
    const id = window.setInterval(() => { flushSaveInternal(); }, AUTOSAVE_MS);
    return () => window.clearInterval(id);
  }, [activeJobId, flushSaveInternal]);

  // Final save on tab unload
  useEffect(() => {
    const onBeforeUnload = () => {
      const jobId = activeJobIdRef.current;
      if (!jobId) return;
      const text = transcriptRef.current;
      if (text === lastSavedTranscriptRef.current) return;
      // navigator.sendBeacon is not authenticated easily; fall back to fetch keepalive.
      try {
        fetch(API_ENDPOINTS.voiceTyping.update(jobId), {
          method: 'PATCH',
          headers: getAuthHeaders(tokenRef.current || undefined),
          body: JSON.stringify({ transcriptText: text, language: languageRef.current }),
          keepalive: true,
        });
      } catch { /* ignore */ }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  const value: Ctx = {
    activeJobId,
    transcript,
    interim,
    vuLevel,
    listening,
    language,
    start,
    stop,
    setTranscript,
    setLanguage,
    changeDevice,
    flushSave,
    speechSupported,
  };

  return (
    <VoiceRecordingContext.Provider value={value}>
      {children}
    </VoiceRecordingContext.Provider>
  );
}

export function useVoiceRecording(): Ctx {
  const ctx = useContext(VoiceRecordingContext);
  if (!ctx) throw new Error('useVoiceRecording must be used within VoiceRecordingProvider');
  return ctx;
}
