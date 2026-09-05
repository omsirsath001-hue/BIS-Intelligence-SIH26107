'use client';

import { FormEvent, useEffect, useState } from 'react';
import { ArrowLeft, Eye, EyeOff, LogIn, ShieldCheck, UserPlus } from 'lucide-react';

const API = 'http://127.0.0.1:8000';

type Mode = 'login' | 'register';

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [language, setLanguage] = useState('en');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('bis_token');
    if (token) {
      // Keep the login page useful if the user deliberately visits it.
      // Do not redirect automatically; this prevents surprising navigation.
    }
  }, []);

  function switchMode(next: Mode) {
    setMode(next);
    setError('');
    setNotice('');
    setPassword('');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setNotice('');

    if (!email.trim() || !password) {
      setError('Please enter your email and password.');
      return;
    }

    if (mode === 'register' && password.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }

    setLoading(true);

    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const response = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password, language }),
      });

      let data: any = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (!response.ok) {
        throw new Error(data?.detail || 'Authentication failed.');
      }

      localStorage.setItem('bis_token', data.token);

      setNotice(mode === 'login' ? 'Login successful. Redirecting…' : 'Account created. Redirecting…');
      setPassword('');

      // Give the user a moment to see the success state, then return home.
      setTimeout(() => {
        window.location.href = '/';
      }, 400);
    } catch (err: any) {
      setError(err?.message || 'Unable to connect to the backend.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#06111F] text-white">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -left-40 -top-40 h-96 w-96 rounded-full bg-blue-600/10 blur-3xl" />
        <div className="absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-cyan-500/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-screen max-w-6xl items-center justify-center px-5 py-10">
        <div className="grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-white/[.04] shadow-2xl backdrop-blur-xl lg:grid-cols-[1.05fr_.95fr]">
          <section className="hidden p-10 lg:flex lg:flex-col lg:justify-between xl:p-14">
            <div>
              <a href="/" className="inline-flex items-center gap-3 text-sm text-slate-300 hover:text-white">
                <ArrowLeft size={16} />
                Back to BIS Intelligence
              </a>

              <div className="mt-20 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 shadow-xl shadow-blue-500/20">
                <ShieldCheck size={28} />
              </div>

              <div className="mt-6 text-xs uppercase tracking-[.2em] text-cyan-300">SIH26107</div>
              <h1 className="mt-3 text-5xl font-black leading-tight">Secure access to your BIS workspace.</h1>
              <p className="mt-5 max-w-md leading-7 text-slate-400">
                Sign in to manage your workspace, access protected compliance tools, and use administrator document features when authorized.
              </p>
            </div>

            <div className="text-sm text-slate-500">Evidence-first AI • Standards Navigator</div>
          </section>

          <section className="p-6 sm:p-9 xl:p-12">
            <div className="mb-8 flex items-center justify-between">
              <a href="/" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white lg:hidden">
                <ArrowLeft size={16} /> Home
              </a>
              <div className="ml-auto flex rounded-xl border border-white/10 bg-black/10 p-1">
                <button
                  type="button"
                  onClick={() => switchMode('login')}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === 'login' ? 'bg-white text-slate-900' : 'text-slate-400 hover:text-white'}`}
                >
                  Login
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('register')}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === 'register' ? 'bg-white text-slate-900' : 'text-slate-400 hover:text-white'}`}
                >
                  Register
                </button>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-blue-500/10 text-blue-300">
                  {mode === 'login' ? <LogIn size={21} /> : <UserPlus size={21} />}
                </div>
                <div>
                  <h2 className="text-3xl font-black">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    {mode === 'login' ? 'Sign in to continue to your BIS workspace.' : 'Create a secure user account for BIS Intelligence.'}
                  </p>
                </div>
              </div>

              <form onSubmit={submit} className="mt-8 space-y-4">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-300">Email</span>
                  <input
                    value={email}
                    onChange={(e) => { setEmail(e.target.value); setError(''); }}
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-4 outline-none transition focus:border-blue-400/50 focus:ring-2 focus:ring-blue-500/10"
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-300">Password</span>
                  <div className="relative">
                    <input
                      value={password}
                      onChange={(e) => { setPassword(e.target.value); setError(''); }}
                      type={showPassword ? 'text' : 'password'}
                      autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                      placeholder="Enter your password"
                      className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-4 pr-12 outline-none transition focus:border-blue-400/50 focus:ring-2 focus:ring-blue-500/10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </label>

                {mode === 'register' && (
                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-slate-300">Language</span>
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-[#0B172A] px-4 py-4 outline-none focus:border-blue-400/50"
                    >
                      <option value="en">English</option>
                      <option value="hi">Hindi</option>
                      <option value="mr">Marathi</option>
                    </select>
                  </label>
                )}

                {error && (
                  <div role="alert" className="rounded-2xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">
                    {error}
                  </div>
                )}

                {notice && (
                  <div role="status" className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200">
                    {notice}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-2xl bg-gradient-to-r from-blue-600 to-indigo-500 py-4 font-semibold shadow-lg shadow-blue-600/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Create account'}
                </button>
              </form>

              <p className="mt-6 text-center text-sm text-slate-400">
                {mode === 'login' ? "Don't have an account?" : 'Already have an account?'}{' '}
                <button
                  type="button"
                  onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
                  className="font-semibold text-blue-300 hover:text-blue-200"
                >
                  {mode === 'login' ? 'Create a new account' : 'Login'}
                </button>
              </p>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
