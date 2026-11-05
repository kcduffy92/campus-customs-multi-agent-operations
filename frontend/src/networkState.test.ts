import { describe, expect, it } from "vitest";
import { MISSIONS } from "./expected";
import { buildRunView, compareRoutes, latestRunId, summarize } from "./networkState";
import { rentRun } from "./test/fixtures";
import type { ArcadeEvent } from "./types";

describe("buildRunView", () => {
  it("shows nothing at all when there are no events", () => {
    const v = buildRunView([], 102, latestRunId([], 102, 0));
    expect(v.status).toBe("none");
    expect(Object.keys(v.edges)).toHaveLength(0);
    expect(Object.values(v.nodes).every((n) => n.state === "idle")).toBe(true);
  });

  it("highlights the agent currently working and pulses the active delegation", () => {
    const events = rentRun({ finished: false }).slice(0, 9); // Spyro just started and used get_cash_balance
    const v = buildRunView(events, 102, "run-102");
    expect(v.status).toBe("running");
    expect(v.current).toBe("spyro");
    expect(v.nodes.spyro.state).toBe("working");
    expect(v.nodes.spyro.tool).toBe("get_cash_balance");
    expect(v.edges["mario>ryu"]).toBe("active");
    expect(v.edges["ryu>spyro"]).toBe("active");
    expect(v.nodes.crash.state).toBe("idle"); // not dimmed until the run ends
  });

  it("marks finished delegations, summaries, tools, approval requests and agents who sat out", () => {
    const v = buildRunView(rentRun(), 102, "run-102");
    expect(v.status).toBe("completed");
    expect(v.edges).toEqual({ "mario>ryu": "completed", "ryu>spyro": "completed" });
    expect(v.edgeOrder).toEqual(["mario>ryu", "ryu>spyro"]);
    expect(v.nodes.spyro).toMatchObject({ state: "done", said: "Queued $2,400 rent for approval.", approvalsFiled: [1] });
    expect(v.nodes.spyro.tools).toEqual(["get_cash_balance", "request_rent_payment"]);
    expect(v.nodes.crash.state).toBe("out");
    expect(v.nodes.sonic.state).toBe("out");
    expect(v.usage?.total_tokens).toBe(20937);
    expect(v.current).toBeNull();
  });

  it("shows a failed delegation in red and never claims an unfinished agent is done", () => {
    const events = rentRun({ finished: false }).slice(0, 8);
    events.push(
      { ...events[6], index: 50, kind: "delegation_failed", reason: "refused" },
      { ...events[0], index: 51, kind: "run_finished", status: "error", error: "boom" },
    );
    const v = buildRunView(events, 102, "run-102");
    expect(v.edges["ryu>spyro"]).toBe("failed");
    expect(v.edges["mario>ryu"]).toBe("failed"); // still active when the run ended
    expect(v.nodes.spyro.state).toBe("stopped");
    expect(v.status).toBe("error");
  });
});

describe("latestRunId", () => {
  it("ignores runs from another database and from before a reset", () => {
    const old = rentRun({ runId: "old", epoch: 0 });
    const other = rentRun({ runId: "isolated", epoch: 1 }).map((e) => (e.kind === "run_started" ? { ...e, this_database: false } : e));
    expect(latestRunId([...old, ...other], 102, 1)).toBeNull();
    const fresh = rentRun({ runId: "fresh", epoch: 1 });
    expect(latestRunId([...old, ...other, ...fresh], 102, 1)).toBe("fresh");
    expect(latestRunId(fresh, 101, 1)).toBeNull();
  });
});

describe("compareRoutes", () => {
  it("matches the Problem 6 plan for ticket 102", () => {
    const s = summarize(compareRoutes(MISSIONS[102].routes, buildRunView(rentRun(), 102, "run-102")));
    expect(s).toEqual({ matched: ["mario>ryu", "ryu>spyro"], missed: [], unexpected: [], pending: [] });
  });

  it("flags unexpected routes and, only after the run ends, missed ones", () => {
    // Ticket 103's plan is Mario -> Crash, Mario -> Spyro, Mario -> Sonic. Here Crash hands off to Spyro.
    const base = rentRun({ finished: false }).slice(0, 2).map((e) => ({ ...e, ticket_id: 103 }));
    const mk = (kind: string, from: "boss" | "inventory", fc: "mario" | "crash", to: "inventory" | "accounting", tc: "crash" | "spyro", index: number): ArcadeEvent =>
      ({ ...base[0], index, kind, action: kind, agent: from, character: fc, to_agent: to, to_character: tc });
    const running = [...base, mk("delegation_started", "boss", "mario", "inventory", "crash", 10),
      mk("delegation_started", "inventory", "crash", "accounting", "spyro", 11)];
    const mid = compareRoutes(MISSIONS[103].routes, buildRunView(running, 103, "run-102"));
    expect(mid["mario>crash"]).toBe("matched");
    expect(mid["crash>spyro"]).toBe("unexpected");
    expect(mid["mario>spyro"]).toBe("pending");
    const ended = [...running, { ...base[0], index: 12, kind: "run_finished", status: "completed" }];
    const end = summarize(compareRoutes(MISSIONS[103].routes, buildRunView(ended, 103, "run-102")));
    expect(end.missed.sort()).toEqual(["mario>sonic", "mario>spyro"]);
    expect(end.unexpected).toEqual(["crash>spyro"]);
  });
});
