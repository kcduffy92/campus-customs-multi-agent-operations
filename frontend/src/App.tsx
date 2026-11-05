import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, API_URL } from "./api";
import { PixelText } from "./art/PixelText";
import { CHARACTERS } from "./characters";
import { AgentFeed } from "./components/AgentFeed";
import { AgentSummaries } from "./components/AgentSummaries";
import { ApprovalGate, type Decision, type DecisionOutcome } from "./components/ApprovalGate";
import { CashMeter } from "./components/CashMeter";
import { CommandNetwork } from "./components/CommandNetwork";
import { MissionSelect } from "./components/MissionSelect";
import { ResetDialog } from "./components/ResetDialog";
import { RunPanel } from "./components/RunPanel";
import { MISSIONS } from "./expected";
import { isHumanName, money, movesCash } from "./format";
import { soundForBatch } from "./liveSounds";
import { buildRunView, compareRoutes, latestRunId, summarize } from "./networkState";
import { play, setMuted as setSfxMuted } from "./sound/sfx";
import type { ApprovalRequest, ArcadeEvent, Cash, CharacterId, Health, ResolutionType, Ticket } from "./types";

const ACTIVE_MS = 1000;
const IDLE_MS = 3000;

function useReducedMotion() {
  const q = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const [reduced, setReduced] = useState(!!q?.matches);
  useEffect(() => {
    if (!q) return;
    const on = () => setReduced(q.matches);
    q.addEventListener?.("change", on);
    return () => q.removeEventListener?.("change", on);
  }, [q]);
  return reduced;
}

function mergeEvents(prev: ArcadeEvent[], incoming: ArcadeEvent[]) {
  if (!incoming.length) return prev;
  const seen = new Set(prev.map((e) => e.index));
  return [...prev, ...incoming.filter((e) => !seen.has(e.index))].sort((a, b) => a.index - b.index);
}

const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

interface Toast { id: number; text: string; tone: "ok" | "danger" | "info" }

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [prevBalance, setPrevBalance] = useState<number | null>(null);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [events, setEvents] = useState<ArcadeEvent[]>([]);
  const [epoch, setEpoch] = useState(0);
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [selected, setSelected] = useState(101);
  const [approver, setApprover] = useState(() => localStorage.getItem("arcade.approver") ?? "");
  const [muted, setMuted] = useState(true);
  const [starting, setStarting] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [agentInfo, setAgentInfo] = useState<CharacterId | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const cursor = useRef<number | null>(null);
  const active = useRef<string | null>(null);
  const lastBalance = useRef<number | null>(null);
  const reduced = useReducedMotion();

  const toast = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  useEffect(() => { localStorage.setItem("arcade.approver", approver); }, [approver]);

  const refreshData = useCallback(async () => {
    const [t, c, r] = await Promise.all([api.tickets(), api.cash(), api.approvals("all")]);
    setTickets(t);
    if (lastBalance.current !== null && lastBalance.current !== c.balance) setPrevBalance(lastBalance.current);
    lastBalance.current = c.balance;
    setCash(c);
    setRequests(r);
  }, []);

  const pollEvents = useCallback(async () => {
    const first = cursor.current === null;
    let got: ArcadeEvent[] = [];
    for (let page = 0; page < 10; page++) {
      const res = await api.events(cursor.current === null ? { limit: 1000 } : { since: cursor.current, limit: 500 });
      if (cursor.current !== null && res.next_cursor < cursor.current) {
        // The trail is shorter than where we were (a different backend or a new audit file): start over.
        cursor.current = null;
        setEvents([]);
        return pollEvents();
      }
      cursor.current = res.next_cursor;
      got = got.concat(res.events);
      active.current = res.active_run;
      setActiveRun(res.active_run);
      setEpoch(res.epoch);
      if (first || res.events.length < 500) break;
    }
    if (got.length) {
      setEvents((prev) => mergeEvents(prev, got));
      if (!first) {
        const s = soundForBatch(got);
        if (s) play(s);
      }
    }
    return got.length > 0;
  }, []);

  // Polling: events every second while a run is active, every three seconds otherwise.
  useEffect(() => {
    let stop = false;
    let timer = 0;
    let tick = 0;
    const loop = async () => {
      try {
        const changed = await pollEvents();
        if (tick === 0 || changed || active.current || tick % 3 === 0) await refreshData();
        if (tick % 10 === 0) setHealth(await api.health());
        setOffline(null);
      } catch (e) {
        setOffline(errText(e));
      }
      tick++;
      if (!stop) timer = window.setTimeout(loop, active.current ? ACTIVE_MS : IDLE_MS);
    };
    void loop();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [pollEvents, refreshData]);

  // Views for the selected ticket, built only from real events of this database's current epoch.
  const otherDbRuns = useMemo(
    () => new Set(events.filter((e) => e.kind === "run_started" && e.this_database === false).map((e) => e.run_id)),
    [events]);
  const mission = MISSIONS[selected];
  const runId = useMemo(() => latestRunId(events, selected, epoch), [events, selected, epoch]);
  const view = useMemo(() => buildRunView(events, selected, runId), [events, selected, runId]);
  const compare = useMemo(() => compareRoutes(mission.routes, view), [mission, view]);
  const ticketEvents = useMemo(
    () => events.filter((e) => e.epoch === epoch && e.ticket_id === selected && !otherDbRuns.has(e.run_id)),
    [events, epoch, selected, otherDbRuns]);
  const ticket = tickets.find((t) => t.id === selected);
  const pending = requests.filter((r) => r.status === "pending");
  const decided = requests.filter((r) => r.status !== "pending");
  const runningTicket = useMemo(
    () => (activeRun ? events.find((e) => e.kind === "run_started" && e.run_id === activeRun)?.ticket_id ?? null : null),
    [activeRun, events]);

  const startBlocked = offline ? "The backend is offline."
    : activeRun ? `A run is active${runningTicket ? ` on ticket ${runningTicket}` : ""}. One run at a time: all tickets share the same cash.`
    : ticket?.is_resolved ? "This ticket is resolved. Reset the database to run it again."
    : health && !health.portkey_key_configured ? "The backend has no PORTKEY_API_KEY, so agents cannot run."
    : null;

  const start = async () => {
    setStarting(true);
    try {
      const r = await api.startRun(selected);
      active.current = r.run_id;
      setActiveRun(r.run_id);
      play("mario.coin");
      toast(`Mission started: ${mission.name}. Watch the network.`, "info");
    } catch (e) {
      toast(errText(e), "danger");
    } finally {
      setStarting(false);
    }
  };

  const decide = async (r: ApprovalRequest, d: Decision): Promise<DecisionOutcome> => {
    const who = approver.trim();
    try {
      if (d === "approve") {
        const res = await api.approve(r.id, who, r.amount);
        const after = res.result?.balance_after as number | undefined;
        const message = movesCash(r)
          ? `Approved #${r.id}: ${money(r.amount)} paid. Checking is now ${money(after)}.`
          : `Approved #${r.id}: the discount is approved as an offer. No cash moved.`;
        toast(message, "ok");
        return { ok: true, message };
      }
      await api.reject(r.id, who);
      const message = `Rejected #${r.id}. No money moved.`;
      toast(message, "info");
      return { ok: true, message };
    } catch (e) {
      const message = `Not done: ${errText(e)}`;
      toast(message, "danger");
      return { ok: false, message };
    } finally {
      await Promise.allSettled([refreshData(), pollEvents()]);
    }
  };

  const resolve = async (note: string, resolutionType: ResolutionType): Promise<DecisionOutcome> => {
    try {
      await api.resolve(selected, approver.trim(), note, resolutionType);
      toast(`Ticket ${selected} marked resolved (${resolutionType}) by ${approver.trim()}.`, "ok");
      return { ok: true, message: `Ticket resolved (${resolutionType}) and recorded with your name.` };
    } catch (e) {
      return { ok: false, message: `Not resolved: ${errText(e)}` };
    } finally {
      await Promise.allSettled([refreshData(), pollEvents()]);
    }
  };

  const reset = async () => {
    try {
      const r = await api.reset(isHumanName(approver) ? approver.trim() : undefined);
      lastBalance.current = null;
      setPrevBalance(null);
      await Promise.allSettled([refreshData(), pollEvents()]);
      toast("Database reset to the original values.", "info");
      return { ok: true, message: `Reset done. Round ${r.epoch + 1} starts now.` };
    } catch (e) {
      return { ok: false, message: errText(e) };
    }
  };

  const toggleSound = () => {
    const next = !muted;
    setMuted(next);
    setSfxMuted(next);
    if (!next) play("mario.intro");
  };

  const onAgent = (id: CharacterId) => {
    setAgentInfo(id);
    play(CHARACTERS[id].sound);
  };

  const gateBlocked = offline ? "The backend is offline." : activeRun ? "Approvals open again when the current run finishes." : null;
  const resetBlocked = activeRun ? "An agent run is active. Wait for it to finish before resetting." : offline ? "The backend is offline." : null;

  return (
    <div className="app">
      <a className="skip" href="#board">Skip to the board</a>
      <header className="top">
        <div className="brand">
          <h1 className="sr-only">Campus Customs: Agent Arcade</h1>
          <PixelText text="CAMPUS CUSTOMS:" height={26} />
          <PixelText text="AGENT ARCADE" color="#ffd23f" shadow="#6b4a00" height={26} />
          <p className="tagline">Live desk · five agents · three tickets · a person holds the keys to the vault</p>
        </div>
        <div className="hud">
          <span className={`light ${offline ? "down" : "up"}`} role="status">
            {offline ? "BACKEND OFFLINE" : `ONLINE · ${health?.model ?? "…"}`}
          </span>
          {cash && <span className="hud-cash" aria-label={`Checking balance ${money(cash.balance)}`}>◆ {money(cash.balance)}</span>}
          <button type="button" className={`btn sound${muted ? "" : " on"}`} aria-pressed={!muted} onClick={toggleSound}>
            {muted ? "SOUND: OFF" : "SOUND: ON"}
          </button>
          <button type="button" className="btn ghost" onClick={() => setResetOpen(true)}>RESET</button>
        </div>
      </header>

      {offline && (
        <div className="banner danger" role="alert">
          {offline} <span className="muted">Retrying automatically · API {API_URL}</span>
        </div>
      )}

      <main id="board" className="board">
        <div className="col left">
          <MissionSelect tickets={tickets} selected={selected} onSelect={(id) => { setSelected(id); setAgentInfo(null); }}
            runningTicket={runningTicket} />
          <RunPanel ticket={ticket} mission={mission} view={view} compare={summarize(compare)}
            startBlocked={startBlocked} starting={starting} onStart={start} approverName={approver} onResolve={resolve} />
        </div>

        <div className="col center">
          <section className="panel network-panel pixel-box" aria-labelledby="net-title">
            <header className="panel-head">
              <h2 id="net-title">Command network · Ticket {selected}</h2>
              <span className="muted small">{view.status === "none" ? "Expected plan only (no run yet)" : view.label ?? "Live run"}</span>
            </header>
            <CommandNetwork mission={mission} view={view} compare={compare} reducedMotion={reduced} onAgentClick={onAgent}
              pendingIds={new Set(pending.map((r) => r.id))} />
            {agentInfo && (
              <p className="agent-info" aria-live="polite">
                <strong style={{ color: CHARACTERS[agentInfo].color }}>{CHARACTERS[agentInfo].name} · {CHARACTERS[agentInfo].role}.</strong>{" "}
                {CHARACTERS[agentInfo].resp}
              </p>
            )}
            <ul className="legend" aria-label="Line legend">
              <li><i className="lg lg-expected" />Expected</li>
              <li><i className="lg lg-conditional" />Expected if needed</li>
              <li><i className="lg lg-active" />Talking now</li>
              <li><i className="lg lg-completed" />Done (receiver's colour)</li>
              <li><i className="lg lg-failed" />Failed</li>
              <li><i className="lg lg-unexpected" />Not in the plan</li>
              <li><i className="lg lg-missed" />Planned, not used</li>
            </ul>
          </section>
          <AgentFeed events={ticketEvents} title={`Live agent feed · Ticket ${selected}`} />
        </div>

        <div className="col right">
          <CashMeter cash={cash} previousBalance={prevBalance} pending={pending} decided={decided} />
          <ApprovalGate requests={pending} balance={cash?.balance ?? null} approverName={approver} onApproverName={setApprover}
            onDecide={decide} disabledReason={gateBlocked} selectedTicket={selected} />
        </div>

        <div className="col wide">
          <AgentSummaries view={view} mission={mission} />
        </div>
      </main>

      <footer className="foot">
        <p>Homework 5 · Problem 8. Every animation comes from a real backend event; with no events, nothing moves.
          Money moves only when a named person approves at a gate. Names are recorded, not authenticated (classroom simulation).
          Character art and sounds are original placeholders.</p>
      </footer>

      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <p key={t.id} className={`toast t-${t.tone}`}>{t.text}</p>)}
      </div>

      <ResetDialog open={resetOpen} blocked={resetBlocked} onClose={() => setResetOpen(false)} onReset={reset} />
    </div>
  );
}
