'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  ShieldCheck,
  FileText,
  FlaskConical,
  ArrowRight,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  LogIn,
  LayoutDashboard,
  Upload,
  Languages,
  LogOut,
  X,
  BookOpen,
  ClipboardCheck,
  MapPin,
  ExternalLink,
  RefreshCw,
  Mic,
  MicOff,
  History,
} from 'lucide-react';

const API = 'http://127.0.0.1:8000';

type View =
  | 'search'
  | 'compliance'
  | 'evidence'
  | 'labs'
  | 'documents'
  | 'history';

type SpeechRecognitionEventLike = Event & {
  results: {
    [index: number]: {
      [index: number]: { transcript: string; confidence?: number };
      isFinal?: boolean;
    };
    length: number;
  };
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
};

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

const copy: any = {
  en: {
    hero: 'From product description to BIS compliance.',
    sub: 'Evidence-backed standards discovery, guided compliance workflows, and a safer AI assistant.',
    placeholder: 'Describe your product or requirement...',
    analyze: 'Analyze',
    login: 'Login',
    register: 'Create account',
    admin: 'Admin Center',
    safe: 'Evidence-first AI',
    search: 'Find Standard',
    compliance: 'Compliance',
    evidence: 'Evidence',
    labs: 'Laboratories',
    documents: 'Documents',
    roadmap: 'Compliance roadmap',
  },
  hi: {
    hero: 'उत्पाद विवरण से BIS अनुपालन तक।',
    sub: 'साक्ष्य-आधारित मानक खोज और अनुपालन मार्गदर्शन।',
    placeholder: 'अपने उत्पाद या आवश्यकता का वर्णन करें...',
    analyze: 'विश्लेषण करें',
    login: 'लॉगिन',
    register: 'खाता बनाएँ',
    admin: 'एडमिन सेंटर',
    safe: 'साक्ष्य-आधारित AI',
    search: 'मानक खोजें',
    compliance: 'अनुपालन',
    evidence: 'साक्ष्य',
    labs: 'प्रयोगशालाएँ',
    documents: 'दस्तावेज़',
    roadmap: 'अनुपालन रोडमैप',
  },
  mr: {
    hero: 'उत्पादनाच्या वर्णनापासून BIS अनुपालनापर्यंत.',
    sub: 'पुराव्यावर आधारित मानक शोध आणि मार्गदर्शित अनुपालन.',
    placeholder: 'तुमच्या उत्पादनाचे किंवा गरजेचे वर्णन करा...',
    analyze: 'विश्लेषण करा',
    login: 'लॉगिन',
    register: 'खाते तयार करा',
    admin: 'अॅडमिन सेंटर',
    safe: 'पुरावा-आधारित AI',
    search: 'मानक शोध',
    compliance: 'अनुपालन',
    evidence: 'पुरावा',
    labs: 'प्रयोगशाळा',
    documents: 'दस्तऐवज',
    roadmap: 'अनुपालन रोडमॅप',
  },
};

const labDirectory = [
  {
    name: 'BIS-recognized laboratory discovery',
    category: 'Electrical / consumer products',
    location: 'Search by product category and city',
    note: 'Use the evidence returned by the backend to identify the applicable testing scope before selecting a laboratory.',
  },
  {
    name: 'Product testing workflow',
    category: 'Testing & certification',
    location: 'India',
    note: 'First identify the applicable Indian Standard, then map required tests and documentation.',
  },
  {
    name: 'Local testing partner',
    category: 'User-selected category',
    location: 'Your city',
    note: 'This Phase-1 view is intentionally evidence-safe and does not invent laboratory accreditation details.',
  },
];

export default function Home() {
  const [lang, setLang] = useState('en');
  const [view, setView] = useState<View>('search');
  const [query, setQuery] = useState('');
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<any>(null);

  const [error, setError] = useState('');
  const [admin, setAdmin] = useState(false);
  const [stats, setStats] = useState<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('');
  const [voiceError, setVoiceError] = useState('');
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const [history, setHistory] = useState<any[]>([]);
const [historyLoading, setHistoryLoading] = useState(false);

  const t = copy[lang];

  useEffect(() => {
    const tk = localStorage.getItem('bis_token');
    if (!tk) return;

    setToken(tk);
    fetch(`${API}/api/auth/me`, {
      headers: { Authorization: `Bearer ${tk}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then(setUser)
      .catch(() => {});
  }, []);

  function toggleVoiceSearch() {
    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }

    const Recognition =
      typeof window !== 'undefined'
        ? window.SpeechRecognition || window.webkitSpeechRecognition
        : undefined;

    if (!Recognition) {
      setVoiceError(
        lang === 'hi'
          ? 'इस ब्राउज़र में voice search उपलब्ध नहीं है। Chrome या Edge का उपयोग करें।'
          : lang === 'mr'
            ? 'या ब्राउझरमध्ये voice search उपलब्ध नाही. Chrome किंवा Edge वापरा.'
            : 'Voice search is not available in this browser. Please use Chrome or Edge.'
      );
      return;
    }

    const recognition = new Recognition();
    recognition.lang = lang === 'hi' ? 'hi-IN' : lang === 'mr' ? 'mr-IN' : 'en-IN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    setVoiceError('');
    setVoiceStatus(
      lang === 'hi'
        ? 'बोलिए…'
        : lang === 'mr'
          ? 'बोला…'
          : 'Listening…'
    );

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = 0; i < event.results.length; i += 1) {
        transcript += event.results[i]?.[0]?.transcript || '';
      }

      const cleaned = transcript.trim();
      if (cleaned) {
        setQuery(cleaned);
        setVoiceStatus(cleaned);

        const lastResult = event.results[event.results.length - 1];
        // Keep the final transcript in the search box. The user explicitly
        // submits it with the Analyze button so the same NVIDIA-backed API
        // path is used for typed and voice queries.
        if (lastResult?.isFinal) {
          setVoiceStatus('');
        }
      }
    };

    recognition.onerror = (event) => {
      setIsListening(false);
      recognitionRef.current = null;

      const messages: Record<string, string> = {
        'not-allowed':
          lang === 'hi'
            ? 'माइक्रोफ़ोन की अनुमति दें और फिर कोशिश करें।'
            : lang === 'mr'
              ? 'मायक्रोफोनची परवानगी द्या आणि पुन्हा प्रयत्न करा.'
              : 'Allow microphone access and try again.',
        'no-speech':
          lang === 'hi'
            ? 'आवाज़ नहीं मिली। फिर से बोलें।'
            : lang === 'mr'
              ? 'आवाज ऐकू आली नाही. पुन्हा बोला.'
              : 'No speech was detected. Please try again.',
        network:
          lang === 'hi'
            ? 'Speech service/network error हुआ।'
            : lang === 'mr'
              ? 'Speech service/network त्रुटी आली.'
              : 'Speech service/network error occurred.',
      };

      setVoiceError(messages[event.error || ''] || (event.error || 'Voice recognition failed.'));
      setVoiceStatus('');
    };

    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
      setVoiceStatus('');
    };

    recognitionRef.current = recognition;
    recognition.start();
  }

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
    };
  }, []);

  async function analyze(nextQuery = query, fromVoice = false) {
    if (!nextQuery.trim()) {
      setError('Please describe a product or requirement first.');
      return;
    }

    setLoading(true);
    setError('');
    setNotice('');

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 210000);

    try {
      const endpoint = fromVoice ? '/api/voice/search' : '/api/compliance/analyze';
      let r: Response;
      for (let attempt = 1; attempt <= 8; attempt++) {
        r = await fetch(`${API}${endpoint}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            ...(fromVoice ? { transcript: nextQuery } : { query: nextQuery }),
            language: lang,
          }),
          signal: controller.signal,
        });
        if (r.status !== 503 || attempt === 8) break;
        setError(`NVIDIA AI is temporarily busy. Automatically retrying (${attempt}/8)…`);
        await new Promise(resolve => window.setTimeout(resolve, 12000));
      }

      const raw = await r.text();
      let j: any;
      try {
        j = raw ? JSON.parse(raw) : {};
      } catch {
        j = { detail: raw || 'Backend returned an invalid response.' };
      }

      if (!r.ok) {
        throw new Error(j.detail || 'Compliance analysis failed.');
      }

      setQuery(nextQuery);
      setData(j);
      setView('search');
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setError('The analysis took too long. Check the backend terminal for the NVIDIA error and make sure your NVIDIA API key/model are valid.');
      } else {
        setError(e.message || 'Backend is not reachable. Start FastAPI on port 8000.');
      }
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  }
  async function loadHistory() {
  if (!token) {
    setShowAuth(true);
    return;
  }

  setHistoryLoading(true);
  setError('');

  try {
    const r = await fetch(`${API}/api/compliance/history`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    const j = await r.json();

    if (!r.ok) {
      throw new Error(j.detail || 'Unable to load query history.');
    }

    setHistory(j.history || []);
    setView('history');
  } catch (e: any) {
    setError(e.message || 'Unable to load query history.');
  } finally {
    setHistoryLoading(false);
  }
}

  async function loadAdmin() {
    if (!token) {
      window.location.href = '/login';
      return;
    }

    try {
      const r = await fetch(`${API}/api/admin/overview`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!r.ok) throw new Error('Admin access required.');

      setStats(await r.json());
      setAdmin(true);
      setView('documents');
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function upload() {
    if (!file || !token) {
      setError('Login as an administrator and choose a PDF first.');
      return;
    }

    const fd = new FormData();
    fd.append('file', file);

    try {
      setError('');
      setNotice('');
      const r = await fetch(`${API}/api/admin/documents/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });

      const j = await r.json();

      if (!r.ok) throw new Error(j.detail || 'Upload failed.');

      setFile(null);
      setNotice('Document uploaded and indexed successfully.');
      await loadAdmin();
    } catch (e: any) {
      setError(e.message || 'Document upload failed.');
    }
  }

  function logout() {
    localStorage.removeItem('bis_token');
    setToken(null);
    setUser(null);
    setAdmin(false);
    setStats(null);
    setNotice('Logged out.');
  }

  const result = data?.results?.[0];

  const checks = useMemo(
    () => [
      ['Product/category overlap', !!result],
      ['Indexed source match', !!result?.source],
      ['Version metadata', !!result?.version],
    ],
    [result]
  );

  return (
    <main className="min-h-screen overflow-hidden bg-[#07111F] text-white">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_15%_5%,rgba(37,99,235,.22),transparent_30%),radial-gradient(circle_at_85%_15%,rgba(6,182,212,.12),transparent_28%)]" />

      <nav className="relative mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-5 md:px-8">
        <button
          onClick={() => setView('search')}
          className="flex items-center gap-3 text-left"
        >
          <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 shadow-xl shadow-blue-500/20">
            <ShieldCheck size={21} />
          </div>
          <div>
            <b>BIS Intelligence</b>
            <div className="text-[11px] text-slate-400">
              SIH26107 • Standards Navigator
            </div>
          </div>
        </button>

        <div className="hidden items-center gap-2 lg:flex">
          {[
            ['search', t.search, Search],
            ['compliance', t.compliance, ClipboardCheck],
            ['evidence', t.evidence, FileText],
            ['labs', t.labs, FlaskConical],
             ['history', 'History', History],
            ['documents', t.documents, BookOpen],
          ].map(([id, label, Icon]: any) => (
            <button
              key={id}
              onClick={() => {
  if (id === 'history') {
    loadHistory();
  } else {
    setView(id as View);
  }
}}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                view === id
                  ? 'bg-white/10 text-white'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none"
          >
            <option value="en">EN</option>
            <option value="hi">हिं</option>
            <option value="mr">मर</option>
          </select>

          {user?.role === 'ADMIN' && (
            <button
              onClick={loadAdmin}
              className="hidden items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm md:flex"
            >
              <LayoutDashboard size={16} />
              {t.admin}
            </button>
          )}

          {user ? (
            <button
              onClick={logout}
              title="Logout"
              className="rounded-xl border border-white/10 bg-white/5 p-2"
            >
              <LogOut size={16} />
            </button>
          ) : (
            <button
              onClick={() => { window.location.href = '/login'; }}
              className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-900"
            >
              <LogIn size={15} className="mr-1 inline" />
              {t.login}
            </button>
          )}
        </div>
      </nav>

      <section className="relative mx-auto max-w-7xl px-5 pb-20 pt-10 md:px-8 md:pt-16">
        {view === 'search' && (
          <>
            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              className="max-w-4xl"
            >
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-400/10 px-4 py-2 text-sm text-blue-200">
                <Sparkles size={15} />
                {t.safe}
              </div>

              <h1 className="text-5xl font-black leading-[1.05] tracking-tight md:text-7xl">
                {t.hero}
              </h1>

              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
                {t.sub}
              </p>
            </motion.div>

            <div className="mt-10 max-w-5xl rounded-3xl border border-white/10 bg-white/[.06] p-3 shadow-2xl shadow-blue-950/30 backdrop-blur-xl">
              <div className="flex flex-col gap-3 md:flex-row">
                <div className="flex flex-1 items-center gap-3 rounded-2xl bg-black/20 px-4">
                  <Search className="text-slate-400" size={21} />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && analyze()}
                    placeholder={t.placeholder}
                    className="w-full bg-transparent py-4 outline-none placeholder:text-slate-500"
                    aria-label={t.placeholder}
                  />
                  <button
                    type="button"
                    onClick={toggleVoiceSearch}
                    className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl transition ${
                      isListening
                        ? 'bg-red-500/20 text-red-300 ring-1 ring-red-400/40'
                        : 'bg-cyan-400/10 text-cyan-300 hover:bg-cyan-400/20'
                    }`}
                    title={isListening ? 'Stop voice search' : 'Start voice search'}
                    aria-label={isListening ? 'Stop voice search' : 'Start voice search'}
                  >
                    {isListening ? <MicOff size={20} /> : <Mic size={20} />}
                  </button>
                </div>

                <button
                  onClick={() => analyze()}
                  disabled={loading}
                  className="flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-blue-600 to-indigo-500 px-7 py-4 font-semibold shadow-lg shadow-blue-600/20 disabled:opacity-50"
                >
                  {loading ? 'Retrieving…' : t.analyze}
                  <ArrowRight size={18} />
                </button>
              </div>
            </div>

            {(voiceStatus || voiceError) && (
              <div
                className={`mt-3 rounded-2xl border p-3 text-sm ${
                  voiceError
                    ? 'border-red-400/20 bg-red-400/10 text-red-200'
                    : 'border-cyan-400/20 bg-cyan-400/10 text-cyan-200'
                }`}
              >
                <div className="flex items-center gap-2">
                  {voiceError ? <MicOff size={16} /> : <Mic size={16} />}
                  <span>{voiceError || voiceStatus}</span>
                </div>
              </div>
            )}

            {error && (
              <div className="mt-4 rounded-2xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200">
                {error}
              </div>
            )}

            {notice && (
              <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
                {notice}
              </div>
            )}

            {!data ? (
              <div className="mt-8 grid gap-4 md:grid-cols-4">
                {[
                  [Search, t.search, 'Product → Standard', 'search'],
                  [ClipboardCheck, t.compliance, 'Build a compliance roadmap', 'compliance'],
                  [FileText, t.evidence, 'Source-backed answers', 'evidence'],
                  [FlaskConical, t.labs, 'Testing discovery', 'labs'],
                ].map(([Icon, title, text, target]: any) => (
                  <button
                    key={title}
                    onClick={() => setView(target)}
                    className="group rounded-2xl border border-white/10 bg-white/[.04] p-5 text-left transition hover:-translate-y-1 hover:bg-white/[.07]"
                  >
                    <Icon size={20} className="text-cyan-300" />
                    <div className="mt-4 font-semibold">{title}</div>
                    <div className="mt-1 text-sm text-slate-400">{text}</div>
                    <div className="mt-5 text-xs text-cyan-300 opacity-0 transition group-hover:opacity-100">
                      Open module →
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <Result data={data} checks={checks} />
            )}
          </>
        )}

        {view === 'compliance' && (
          <ModuleShell
            icon={ClipboardCheck}
            title="Compliance Workspace"
            subtitle="Turn a product description into an evidence-backed compliance checklist."
          >
            <div className="grid gap-5 lg:grid-cols-[1fr_.8fr]">
              <div className="rounded-3xl border border-white/10 bg-white/[.05] p-6">
                <div className="text-sm text-slate-400">Product / requirement</div>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t.placeholder}
                  className="mt-3 min-h-40 w-full rounded-2xl border border-white/10 bg-black/20 p-4 outline-none placeholder:text-slate-500"
                />
                <button
                  onClick={() => analyze()}
                  disabled={loading}
                  className="mt-4 flex items-center gap-2 rounded-2xl bg-gradient-to-r from-blue-600 to-indigo-500 px-6 py-3 font-semibold disabled:opacity-50"
                >
                  {loading ? 'Analyzing…' : 'Generate compliance roadmap'}
                  <ArrowRight size={17} />
                </button>
              </div>

              <div className="rounded-3xl border border-white/10 bg-white/[.05] p-6">
                <div className="text-sm font-semibold">Workflow</div>
                <div className="mt-5 space-y-3">
                  {[
                    'Identify likely Indian Standard',
                    'Check available evidence',
                    'Show confidence and source metadata',
                    'Generate next-step roadmap',
                  ].map((x, i) => (
                    <div key={x} className="flex gap-3 rounded-xl bg-black/20 p-3 text-sm text-slate-300">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-blue-500/15 text-blue-300">
                        {i + 1}
                      </span>
                      {x}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {data && <div className="mt-5"><Result data={data} checks={checks} /></div>}
          </ModuleShell>
        )}

        {view === 'evidence' && (
          <ModuleShell
            icon={FileText}
            title="Evidence Explorer"
            subtitle="Inspect the source metadata behind the latest analysis."
          >
            {!data ? (
              <EmptyState
                icon={Search}
                title="No analysis yet"
                text="Run an analysis first. The evidence panel will then show the matched standard, source metadata, section and page information."
                action="Go to Find Standard"
                onClick={() => setView('search')}
              />
            ) : (
              <EvidencePanel data={data} />
            )}
          </ModuleShell>
        )}

        {view === 'labs' && (
          <ModuleShell
            icon={FlaskConical}
            title="Laboratory Discovery"
            subtitle="A safe starting point for mapping standards to testing workflows."
          >
            <div className="mb-5 rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-200">
              <AlertTriangle size={16} className="mr-2 inline" />
              Phase 1 deliberately avoids inventing accreditation, addresses or certification claims. A production version should connect this module to an authoritative laboratory directory/API.
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {labDirectory.map((lab) => (
                <div key={lab.name} className="rounded-3xl border border-white/10 bg-white/[.05] p-6">
                  <div className="grid h-11 w-11 place-items-center rounded-2xl bg-cyan-400/10 text-cyan-300">
                    <FlaskConical size={21} />
                  </div>
                  <h3 className="mt-5 font-bold">{lab.name}</h3>
                  <div className="mt-2 text-sm text-cyan-300">{lab.category}</div>
                  <div className="mt-3 flex items-center gap-2 text-sm text-slate-400">
                    <MapPin size={15} />
                    {lab.location}
                  </div>
                  <p className="mt-4 text-sm leading-6 text-slate-400">{lab.note}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 rounded-3xl border border-white/10 bg-white/[.05] p-6">
              <h3 className="font-semibold">Use the current analysis</h3>
              <p className="mt-2 text-sm text-slate-400">
                {result?.standard
                  ? `Current matched standard: ${result.standard}. Use its evidence to determine the required test scope.`
                  : 'Run an analysis to attach a matched standard to this workflow.'}
              </p>
              <button
                onClick={() => setView('search')}
                className="mt-4 flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm"
              >
                Open analysis <ExternalLink size={15} />
              </button>
            </div>
          </ModuleShell>
        )}
{view === 'history' && (
  <ModuleShell
    icon={History}
    title="Query History"
    subtitle="Review your previous BIS standard searches and analysis results."
  >
    {historyLoading ? (
      <div className="rounded-3xl border border-white/10 bg-white/[.05] p-8 text-center">
        <div className="text-slate-300">Loading history...</div>
      </div>
    ) : history.length === 0 ? (
      <EmptyState
        icon={History}
        title="No history yet"
        text="Your BIS standard searches will appear here after you run an analysis."
        action="Go to Find Standard"
        onClick={() => setView('search')}
      />
    ) : (
      <div className="space-y-4">
        {history.map((item) => (
          <div
            key={item.id}
            className="rounded-3xl border border-white/10 bg-white/[.05] p-6"
          >
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="flex gap-4">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-blue-500/10 text-blue-300">
                  <Search size={20} />
                </div>

                <div>
                  <h3 className="font-semibold text-white">
                    {item.query}
                  </h3>

                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-lg bg-blue-400/10 px-2 py-1 text-blue-300">
                      {item.intent}
                    </span>

                    <span className="rounded-lg bg-emerald-400/10 px-2 py-1 text-emerald-300">
                      {item.confidence}
                    </span>
                  </div>
                </div>
              </div>

              <div className="text-xs text-slate-500">
                {new Date(item.created_at).toLocaleString()}
              </div>
            </div>
          </div>
        ))}
      </div>
    )}
  </ModuleShell>
)}
        {view === 'documents' && (
          <ModuleShell
            icon={BookOpen}
            title="Knowledge & Documents"
            subtitle="Manage the evidence layer and inspect ingestion status."
          >
            {!admin ? (
              <div className="rounded-3xl border border-white/10 bg-white/[.05] p-8">
                <div className="flex items-start gap-4">
                  <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-blue-500/10 text-blue-300">
                    <BookOpen />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold">Admin knowledge center</h3>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                      Document ingestion is protected by the backend admin role. Sign in with an administrator account to upload BIS PDFs and view indexing statistics.
                    </p>
                    <button
                      onClick={loadAdmin}
                      className="mt-5 rounded-xl bg-blue-600 px-5 py-3 font-semibold"
                    >
                      Open Admin Center
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <AdminPanel
                stats={stats}
                file={file}
                setFile={setFile}
                upload={upload}
                refresh={loadAdmin}
              />
            )}
          </ModuleShell>
        )}
      </section>


    </main>
  );
}

function ModuleShell({ icon: Icon, title, subtitle, children }: any) {
  return (
    <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }}>
      <div className="mb-8 flex items-start gap-4">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-cyan-400/10 text-cyan-300">
          <Icon />
        </div>
        <div>
          <div className="text-xs uppercase tracking-[.2em] text-cyan-300">
            BIS Intelligence
          </div>
          <h1 className="mt-2 text-4xl font-black md:text-5xl">{title}</h1>
          <p className="mt-3 max-w-2xl text-slate-400">{subtitle}</p>
        </div>
      </div>
      {children}
    </motion.div>
  );
}

function EmptyState({ icon: Icon, title, text, action, onClick }: any) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/[.05] p-10 text-center">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-blue-500/10 text-blue-300">
        <Icon />
      </div>
      <h3 className="mt-5 text-xl font-bold">{title}</h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">{text}</p>
      <button onClick={onClick} className="mt-5 rounded-xl bg-blue-600 px-5 py-3 font-semibold">
        {action}
      </button>
    </div>
  );
}

function EvidencePanel({ data }: any) {
  const r = data?.results?.[0];
  const evidence = r?.evidence?.[0];

  if (!r) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="No evidence found"
        text="The backend did not return a standard result for this query."
        action="Run another analysis"
        onClick={() => {}}
      />
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1.15fr_.85fr]">
      <div className="rounded-3xl border border-white/10 bg-white/[.05] p-7">
        <div className="text-sm text-slate-400">Matched standard</div>
        <h2 className="mt-2 text-2xl font-bold">{r.standard || 'Unspecified'}</h2>
        <p className="mt-2 text-slate-300">{r.title}</p>

        <div className="mt-6 rounded-2xl border border-blue-400/20 bg-blue-400/5 p-5">
          <div className="flex items-center gap-2 font-semibold">
            <FileText size={17} />
            Evidence
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            {evidence?.text || 'No evidence text returned.'}
          </p>
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-white/[.05] p-7">
        <div className="flex items-center gap-2 text-emerald-300">
          <ShieldCheck size={18} />
          Confidence: {data.confidence || 'UNKNOWN'}
        </div>

        <div className="mt-6 space-y-3 text-sm">
          <Meta label="Section" value={evidence?.section} />
          <Meta label="Page" value={evidence?.page} />
          <Meta label="Source type" value={r.source?.type} />
          <Meta label="Verified" value={String(r.source?.verified)} />
          <Meta label="Version" value={r.version} />
          <Meta label="Retrieval match" value={`${r.retrieval_match ?? 0}%`} />
        </div>

        <div className="mt-6 rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4 text-xs leading-5 text-amber-200">
          <AlertTriangle size={15} className="mb-2" />
          Verify current applicability with official BIS sources before making a certification or compliance decision.
        </div>
      </div>
    </div>
  );
}

function Meta({ label, value }: any) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl bg-black/20 p-3">
      <span className="text-slate-400">{label}</span>
      <span className="text-right text-slate-200">{value || '—'}</span>
    </div>
  );
}


function GroundingSources({ sources }: { sources?: any[] }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="text-sm font-semibold text-slate-200">BIS evidence sources</div>
      <div className="mt-2 space-y-2">
        {sources.slice(0, 6).map((source: any, i: number) => (
          <a key={`${source.url}-${i}`} href={source.url} target="_blank" rel="noreferrer" className="block text-xs text-blue-300 hover:underline">
            {source.title || source.url}
          </a>
        ))}
      </div>
    </div>
  );
}

function Result({ data, checks }: any) {
  if (data?.status === 'general_answer') {
    return (
      <div className="mt-8 space-y-4">
        <div className="rounded-3xl border border-violet-400/20 bg-violet-400/5 p-7">
          <div className="flex items-center gap-2 font-semibold text-violet-200">
            <Sparkles size={18} />
            NVIDIA general guidance
          </div>
          <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-200">
            {data.nvidia_answer}
          </div>
          <GroundingSources sources={data.grounding_sources} />
        </div>
        <div className="rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-100">
          <div className="flex gap-2"><AlertTriangle size={18} className="shrink-0" />{data.message}</div>
        </div>
      </div>
    );
  }

  if (data?.status === 'insufficient_evidence') {
    return (
      <div className="mt-8 space-y-4">
        <div className="rounded-3xl border border-amber-400/20 bg-amber-400/5 p-7">
          <div className="flex gap-3 text-amber-200">
            <AlertTriangle />
            <div>
              <h2 className="font-bold">Insufficient authoritative evidence</h2>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                {data.message}
              </p>
            </div>
          </div>
        </div>
        {data?.nvidia_answer && (
          <div className="rounded-3xl border border-violet-400/20 bg-violet-400/5 p-7">
            <div className="flex items-center gap-2 font-semibold text-violet-200">
              <Sparkles size={18} />
              NVIDIA general guidance
            </div>
            <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-200">
              {data.nvidia_answer}
            </div>
            <GroundingSources sources={data.grounding_sources} />
          </div>
        )}
      </div>
    );
  }

  const r = data?.results?.[0];

  if (!r) {
    return (
      <div className="mt-8 rounded-3xl border border-white/10 bg-white/[.05] p-7">
        No structured result was returned by the backend.
      </div>
    );
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        className="mt-8 grid gap-5 lg:grid-cols-[1.2fr_.8fr]"
      >
        <div className="rounded-3xl border border-white/10 bg-white/[.06] p-7 backdrop-blur-xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-sm text-slate-400">
                Potentially applicable standard
              </div>
              <h2 className="mt-1 text-2xl font-bold">
                {r.standard || 'Unspecified standard'}
              </h2>
              <p className="mt-2 text-slate-300">{r.title}</p>
            </div>

            <span className="rounded-xl bg-emerald-400/10 px-3 py-2 text-sm text-emerald-300">
              {r.retrieval_match ?? 0}% retrieval match
            </span>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            {checks.map(([label, ok]: any) => (
              <div
                key={label}
                className="flex items-center gap-2 rounded-xl bg-black/20 p-3 text-sm text-slate-300"
              >
                <CheckCircle2
                  size={16}
                  className={ok ? 'text-emerald-400' : 'text-slate-500'}
                />
                {label}
              </div>
            ))}
          </div>

          {data?.nvidia_answer && (
            <div className="mt-5 rounded-2xl border border-violet-400/20 bg-violet-400/5 p-5">
              <div className="flex items-center gap-2 font-semibold text-violet-200">
                <Sparkles size={17} />
                NVIDIA answer
              </div>
              <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-200">
                {data.nvidia_answer}
              </div>
              <GroundingSources sources={data.grounding_sources} />
            </div>
          )}

          <div className="mt-5 rounded-2xl border border-blue-400/20 bg-blue-400/5 p-5">
            <div className="flex items-center gap-2 font-semibold">
              <FileText size={17} />
              Evidence
            </div>
            <div className="mt-3 text-sm text-slate-300">
              {r.evidence?.[0]?.text || 'No evidence text returned.'}
            </div>
            <div className="mt-4 text-xs text-slate-400">
              Section: {r.evidence?.[0]?.section || '—'} • Page:{' '}
              {r.evidence?.[0]?.page || '—'} • Source:{' '}
              {r.source?.type || '—'} • Verified:{' '}
              {String(r.source?.verified)}
            </div>
          </div>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/[.06] p-7">
          <div className="flex items-center gap-2 text-emerald-300">
            <ShieldCheck size={19} />
            Confidence: {data.confidence || 'UNKNOWN'}
          </div>

          <div className="mt-6 text-sm font-semibold">Compliance roadmap</div>

          <div className="mt-4 space-y-3">
            {(data.answer?.roadmap || []).map((x: string, i: number) => (
              <div key={`${x}-${i}`} className="flex gap-3 rounded-xl bg-black/20 p-3 text-sm">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-blue-500/15 text-blue-300">
                  {i + 1}
                </span>
                {x}
              </div>
            ))}
          </div>

          <div className="mt-5 rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4 text-xs leading-5 text-amber-200">
            <AlertTriangle size={15} className="mb-2" />
            {data.answer?.disclaimer ||
              'Prototype information. Verify current applicability with official BIS sources.'}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

function AdminPanel({ stats, file, setFile, upload, refresh }: any) {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Documents', stats?.documents],
          ['Current', stats?.current_documents],
          ['Queries', stats?.queries],
          ['Low confidence', stats?.low_confidence_queries],
        ].map(([label, value]: any) => (
          <div key={label} className="rounded-2xl border border-white/10 bg-black/20 p-5">
            <div className="text-sm text-slate-400">{label}</div>
            <div className="mt-2 text-3xl font-black">{value ?? 0}</div>
          </div>
        ))}
      </div>

      <div className="rounded-3xl border border-dashed border-white/15 bg-white/[.04] p-6">
        <div className="flex items-center gap-3">
          <Upload className="text-cyan-300" />
          <div>
            <div className="font-semibold">Ingest BIS PDF</div>
            <div className="text-sm text-slate-400">
              Upload an authoritative document for the backend ingestion pipeline.
            </div>
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row">
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="flex-1 rounded-xl border border-white/10 bg-black/20 p-3 text-sm"
          />
          <button
            onClick={upload}
            className="rounded-xl bg-blue-600 px-5 py-3 font-semibold"
          >
            Upload & index
          </button>
          <button
            onClick={refresh}
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-3"
            title="Refresh"
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
