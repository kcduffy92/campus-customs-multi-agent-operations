// The hierarchical command network from Problem 6, now driven by real events.
// Dashed lines = the Expected plan; solid/pulsing lines = what the agents actually did.
import { useEffect, useMemo, useRef, useState } from "react";
import { CHARACTERS, ORDER, label } from "../characters";
import type { Mission } from "../expected";
import { edgeKey, type RouteCompare, type RunView } from "../networkState";
import { Lock, Sprite } from "../art/sprites";
import type { CharacterId } from "../types";

const POS: Record<CharacterId, { x: number; y: number; w: number; h: number }> = {
  mario: { x: 500, y: 90, w: 170, h: 150 },
  crash: { x: 130, y: 410, w: 150, h: 150 },
  spyro: { x: 380, y: 410, w: 150, h: 150 },
  ryu: { x: 620, y: 410, w: 150, h: 150 },
  sonic: { x: 870, y: 410, w: 150, h: 150 },
};
const SPECIALISTS: CharacterId[] = ["crash", "spyro", "ryu", "sonic"];
type Pt = [number, number];

/** Circuit-style route: Boss links on separate lanes; neighbours straight across; others loop below. */
export function routePoints(a: CharacterId, b: CharacterId): Pt[] {
  const A = POS[a], B = POS[b];
  if (a === "mario") {
    const off = { crash: -60, spyro: -20, ryu: 20, sonic: 60, mario: 0 }[b];
    const bus = { crash: 225, sonic: 225, spyro: 275, ryu: 275, mario: 225 }[b];
    return [[500 + off, 165], [500 + off, bus], [B.x, bus], [B.x, 335]];
  }
  if (b === "mario") {
    return routePoints("mario", a).map(([x, y]): Pt => [x + 12, y === 165 || y === 335 ? y : y + 12]).reverse();
  }
  const ia = SPECIALISTS.indexOf(a), ib = SPECIALISTS.indexOf(b), dir = ib > ia ? 1 : -1;
  if (Math.abs(ia - ib) === 1) {
    const lane = dir > 0 ? 395 : 425;
    return [[A.x + 75 * dir, lane], [B.x - 75 * dir, lane]];
  }
  const depth = ({ "0-2": 528, "1-3": 556, "0-3": 584 } as Record<string, number>)[`${Math.min(ia, ib)}-${Math.max(ia, ib)}`];
  const o = dir > 0 ? -14 : 14, d2 = dir > 0 ? 0 : 8;
  return [[A.x + o, 485], [A.x + o, depth + d2], [B.x + o, depth + d2], [B.x + o, 485]];
}

function geometry(from: CharacterId, to: CharacterId) {
  const pts = routePoints(from, to);
  const last = pts[pts.length - 1], prev = pts[pts.length - 2];
  const dx = Math.sign(last[0] - prev[0]), dy = Math.sign(last[1] - prev[1]);
  const line = [...pts.slice(0, -1), [last[0] - dx * 10, last[1] - dy * 10] as Pt];
  const d = line.map((p, i) => `${i ? "L" : "M"}${p[0]} ${p[1]}`).join(" ");
  const px = -dy, py = dx, bx = last[0] - dx * 14, by = last[1] - dy * 14;
  const head = `${last[0]},${last[1]} ${bx + px * 8},${by + py * 8} ${bx - px * 8},${by - py * 8}`;
  const badge: Pt = pts.length === 2
    ? [(pts[0][0] + pts[1][0]) / 2, pts[0][1] + (pts[0][1] < 410 ? -24 : 24)]
    : [(pts[1][0] + pts[2][0]) / 2, pts[1][1]];
  const len = line.reduce((s, p, i) => (i ? s + Math.abs(p[0] - line[i - 1][0]) + Math.abs(p[1] - line[i - 1][1]) : 0), 0);
  const maxY = Math.max(...pts.map((p) => p[1]));
  return { d, head, badge, len, maxY };
}

const IDLE_TRACES: [CharacterId, CharacterId][] = [
  ["mario", "crash"], ["mario", "spyro"], ["mario", "ryu"], ["mario", "sonic"],
  ["crash", "spyro"], ["spyro", "ryu"], ["ryu", "sonic"],
];

const STATE_TAG: Record<string, string> = {
  working: "WORKING", done: "DONE", stopped: "STOPPED", out: "SITTING OUT", idle: "",
};

interface Props {
  mission: Mission;
  view: RunView;
  compare: Record<string, RouteCompare>;
  reducedMotion: boolean;
  pendingIds?: Set<number>; // approval requests still waiting for a person
  onAgentClick?: (id: CharacterId) => void;
}

export function CommandNetwork({ mission, view, compare, reducedMotion, pendingIds, onAgentClick }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  // On narrow screens the map scrolls sideways; start centred on Mario.
  useEffect(() => {
    const centre = () => {
      const el = scroller.current;
      if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
    };
    centre();
    window.addEventListener("resize", centre);
    return () => window.removeEventListener("resize", centre);
  }, [mission.ticketId]);
  const hasRun = view.status !== "none";
  const finished = hasRun && view.status !== "running";

  const edges = useMemo(() => {
    const keys = new Map<string, [CharacterId, CharacterId]>();
    const expectedKeys = new Set(mission.routes.map((r) => edgeKey(r.from, r.to)));
    for (const r of mission.routes) keys.set(edgeKey(r.from, r.to), [r.from, r.to]);
    for (const k of view.edgeOrder) {
      const [a, b] = k.split(">") as [CharacterId, CharacterId];
      keys.set(k, [a, b]);
    }
    for (const [a, b] of IDLE_TRACES) {
      const k = edgeKey(a, b), rev = edgeKey(b, a);
      if (!keys.has(k) && !keys.has(rev)) keys.set(k, [a, b]);
    }
    return [...keys.entries()].map(([k, [from, to]]) => ({
      key: k, from, to, geo: geometry(from, to),
      plan: mission.routes.find((r) => edgeKey(r.from, r.to) === k) ?? null,
      expected: expectedKeys.has(k),
      live: view.edges[k] ?? null,
      cmp: compare[k] ?? null,
    }));
  }, [mission, view.edges, view.edgeOrder, compare]);

  const H = edges.some((e) => e.geo.maxY > 500) ? 600 : 510;
  const chosen = edges.find((e) => e.key === selected) ?? null;

  const nodeState = (id: CharacterId) => {
    const n = view.nodes[id];
    if (hasRun) return n.state;
    return mission.out.includes(id) ? "planned-out" : "idle";
  };

  const describe = (e: (typeof edges)[number]) => {
    const parts = [`${CHARACTERS[e.from].short} → ${CHARACTERS[e.to].short}`];
    if (e.plan) parts.push(`Expected step ${e.plan.step}${e.plan.kind === "conditional" ? ` (${e.plan.condition})` : ""}`);
    else if (e.live) parts.push("Not in the plan");
    parts.push(e.live ? `Actual: ${e.live === "active" ? "in progress" : e.live}` : hasRun ? "Actual: not used" : "Actual: no run yet");
    return parts.join(" · ");
  };

  return (
    <div className="network">
      <div className="net-scroll" ref={scroller}>
        <div className={`net-stage${H > 510 ? " tall" : ""}`} style={{ aspectRatio: `1000 / ${H}` }}>
          <svg className="net-svg" viewBox={`0 0 1000 ${H}`} role="group" aria-label={`Delegation network for ticket ${mission.ticketId}`}>
            {edges.map((e) => {
              const cls = [
                "edge",
                e.live ? `s-${e.live}` : e.expected ? (finished ? "s-expected-dim" : "s-expected") : "s-idle",
                e.plan?.kind === "conditional" ? "conditional" : "",
                e.cmp === "missed" ? "missed" : "",
                e.cmp === "unexpected" ? "unexpected" : "",
                selected === e.key ? "selected" : "",
                !e.expected && !e.live && (mission.out.includes(e.from) || mission.out.includes(e.to)) ? "s-none" : "",
              ].filter(Boolean).join(" ");
              const interactive = e.expected || !!e.live;
              return (
                <g key={e.key} className={cls} style={{ ["--edge-color" as string]: CHARACTERS[e.to].lineColor ?? CHARACTERS[e.to].color }}
                  {...(interactive ? {
                    tabIndex: 0, role: "button", "aria-label": describe(e),
                    onClick: () => setSelected(e.key),
                    onKeyDown: (ev: React.KeyboardEvent) => {
                      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setSelected(e.key); }
                    },
                  } : {})}>
                  <path className="line" d={e.geo.d} />
                  <path className="hit" d={e.geo.d} />
                  <polygon className="head" points={e.geo.head} />
                  {e.live === "active" && (
                    <circle className="pulse" r={6} cx={reducedMotion ? e.geo.badge[0] : undefined} cy={reducedMotion ? e.geo.badge[1] : undefined}>
                      {!reducedMotion && <animateMotion path={e.geo.d} dur={`${Math.max(0.7, e.geo.len / 280).toFixed(2)}s`} repeatCount="indefinite" />}
                    </circle>
                  )}
                  {e.plan && (
                    <g className="badge" aria-hidden="true">
                      <rect x={e.geo.badge[0] - 13} y={e.geo.badge[1] - 13} width={26} height={26} />
                      <text x={e.geo.badge[0]} y={e.geo.badge[1] + 1}>{e.plan.step}</text>
                    </g>
                  )}
                  {e.plan?.kind === "conditional" && (
                    <text className="cond-label" x={e.geo.badge[0]} y={e.geo.badge[1] - 22} aria-hidden="true">IF NEEDED</text>
                  )}
                  {e.cmp === "unexpected" && (
                    <text className="cmp-label unexpected-label" x={e.geo.badge[0]} y={e.geo.badge[1] + 5} aria-hidden="true">NOT PLANNED</text>
                  )}
                  {e.cmp === "missed" && (
                    <text className="cmp-label missed-label" x={e.geo.badge[0]} y={e.geo.badge[1] + 30} aria-hidden="true">NOT USED</text>
                  )}
                </g>
              );
            })}
          </svg>

          {ORDER.map((id) => {
            const c = CHARACTERS[id], p = POS[id], n = view.nodes[id];
            const st = nodeState(id);
            const tag = st === "planned-out" ? "NOT EXPECTED" : STATE_TAG[st] ?? "";
            const lockShown = n.approvalsFiled.some((rid) => pendingIds?.has(rid));
            return (
              <button key={id} type="button" data-agent={id}
                className={`node n-${st}${view.current === id ? " n-current" : ""}`}
                style={{
                  ["--accent" as string]: c.color,
                  left: `${p.x / 10}%`, top: `${(p.y / H) * 100}%`, width: `${p.w / 10}%`, height: `${(p.h / H) * 100}%`,
                }}
                aria-label={`${label(id)}. ${tag || "Ready"}.${n.tool ? ` Using ${n.tool}.` : ""}${lockShown ? " Waiting for a person to approve its request." : ""} Click for a sound preview.`}
                onClick={() => onAgentClick?.(id)}>
                {n.tool && <span className="node-tool">{n.tool}</span>}
                <Sprite id={id} className="node-sprite" />
                <span className="node-name">{c.short}</span>
                <span className="node-role">{c.role}</span>
                {tag && <span className="node-tag">{tag}</span>}
                {lockShown && <span className="node-lock" title="Its request is waiting at the approval gate"><Lock size={16} /></span>}
              </button>
            );
          })}
        </div>
      </div>
      <p className="net-caption" aria-live="polite">
        {chosen ? <>{describe(chosen)}{chosen.plan && <><br /><span className="muted">Why: {chosen.plan.why}</span></>}</>
          : <span className="muted">Select a line to see who delegated to whom. Dashed = expected plan, solid = what really happened.</span>}
      </p>
    </div>
  );
}
