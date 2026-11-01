import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DeliverySnapshot } from "./api";
import {
  deliveryIndicator,
  DeliveryDetails,
} from "./components/DeliveryStatus";
import { setLocale } from "./i18n";

function snapshot(overrides: Partial<DeliverySnapshot> = {}): DeliverySnapshot {
  return {
    projectId: "current-project",
    available: true,
    checkedAt: "2026-10-26T10:00:00Z",
    state: "synced",
    scope: "connected-workspaces",
    pendingCount: 0,
    blockedCount: 0,
    interruptedCount: 0,
    syncedCount: 12,
    discoveryComplete: true,
    items: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  setLocale("en");
});

describe("Agent delivery status", () => {
  it("requires an affirmative complete check before saying synced", () => {
    expect(deliveryIndicator(snapshot())).toBe("synced");
    expect(deliveryIndicator(null)).toBe("unknown");
    expect(deliveryIndicator(snapshot(), true)).toBe("unknown");
    expect(deliveryIndicator(snapshot({ available: false }))).toBe("unknown");
    expect(deliveryIndicator(snapshot({ discoveryComplete: false }))).toBe(
      "unknown",
    );
    expect(deliveryIndicator(snapshot({ discoveryComplete: undefined }))).toBe(
      "unknown",
    );
    expect(deliveryIndicator(snapshot({ state: "unknown" }))).toBe("unknown");
  });

  it("keeps a last-known backlog visible despite a newer discovery failure or successful page save", () => {
    expect(deliveryIndicator(snapshot({ pendingCount: 2 }), true)).toBe(
      "pending",
    );
    expect(
      deliveryIndicator(snapshot({ blockedCount: 1, pendingCount: 2 })),
    ).toBe("blocked");
    expect(deliveryIndicator(snapshot({ interruptedCount: 1 }))).toBe(
      "blocked",
    );
  });

  it("distinguishes workspace saves, failed records and interrupted records without offering to retry unfinished work", () => {
    setLocale("en");
    const state = snapshot({
      state: "blocked",
      pendingCount: 1,
      blockedCount: 1,
      interruptedCount: 1,
      items: [
        {
          taskId: "ready-1",
          title: "Frozen result",
          state: "pending",
          attempts: 0,
          lastError: null,
        },
        {
          taskId: "ready-2",
          title: "Needs reference repair",
          state: "blocked",
          attempts: 3,
          lastError: {
            code: "reference_unresolved",
            message: "Missing run: run-17",
          },
        },
        {
          taskId: "unfinished",
          title: "Interrupted experiment",
          state: "interrupted",
          attempts: 0,
          lastError: null,
        },
      ],
    });
    const html = renderToStaticMarkup(
      createElement(DeliveryDetails, {
        snapshot: state,
        fetchError: "",
        workspaceError: "",
        busy: false,
        retrying: null,
        retryError: "",
        onRetry() {},
        onRefresh() {},
      }),
    );
    expect(html).toContain("Workspace saved");
    expect(html).toContain("Connected workspaces");
    expect(html).toContain("reference_unresolved");
    expect(html).toContain("Missing run: run-17");
    expect(html.match(/>Retry delivery<\/button>/g)).toHaveLength(2);
    expect(html).toContain("Retry ready records");
    const unfinished = html.slice(html.indexOf("delivery-item-interrupted"));
    expect(unfinished.split("</article>")[0]).not.toContain("<button");
    expect(html).not.toContain("have been delivered");
  });

  it("names blocked dependencies and offers delivery of the prerequisite without rerunning research", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryDetails, {
        snapshot: snapshot({
          state: "blocked",
          blockedCount: 1,
          items: [
            {
              taskId: "dependent",
              title: "Dependent finding",
              state: "blocked",
              attempts: 4,
              lastError: { code: "not_found", message: "Prerequisite missing" },
              waitingFor: [
                {
                  taskId: "earlier",
                  nodeId: "node-earlier",
                  title: "Original condition diagnosis",
                },
              ],
              nextAttemptAt: "2026-10-29T10:00:00Z",
            },
          ],
        }),
        fetchError: "",
        workspaceError: "",
        busy: false,
        retrying: null,
        retryError: "",
        onRetry() {},
        onRefresh() {},
      }),
    );
    expect(html).toContain("Waiting for an earlier record");
    expect(html).toContain("Original condition diagnosis");
    expect(html).toContain("Deliver earlier record");
    expect(html).toContain("Next retry");
    expect(html).not.toContain("node-earlier");
  });

  it("distinguishes permanent repair from timed retry while retaining a manual recheck", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryDetails, {
        snapshot: snapshot({
          state: "blocked",
          blockedCount: 1,
          items: [
            {
              taskId: "bad-origin",
              title: "Source reference",
              state: "blocked",
              attempts: 2,
              retryable: false,
              nextAttemptAt: "2026-10-29T10:00:00Z",
              lastError: {
                code: "reference_unresolved",
                message: "Source missing",
              },
            },
          ],
        }),
        fetchError: "",
        workspaceError: "",
        busy: false,
        retrying: null,
        retryError: "",
        onRetry() {},
        onRefresh() {},
      }),
    );
    expect(html).toContain("Needs repair");
    expect(html).toContain("Check delivery again");
    expect(html).toContain("Source missing");
    expect(html).not.toContain("Next retry");
  });

  it("shows current check, save and retry errors instead of a success confirmation", () => {
    const html = renderToStaticMarkup(
      createElement(DeliveryDetails, {
        snapshot: snapshot(),
        fetchError: "Queue unreadable",
        workspaceError: "Offline",
        busy: false,
        retrying: null,
        retryError: "Repair failed",
        onRetry() {},
        onRefresh() {},
      }),
    );
    expect(html).toContain("Queue unreadable");
    expect(html).toContain("Offline");
    expect(html).toContain("Repair failed");
    expect(html).not.toContain("have been delivered");
    expect(html).not.toContain("Workspace saved");
  });

  it("targets the selected project's delivery endpoint, forwards cancellation and retries frozen records rather than execution", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => snapshot() });
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    await api.deliveryStatus("study / one", controller.signal);
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/projects/study%20%2F%20one/delivery-status",
    );
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
    await api.retryDelivery("study / one", "frozen-task", controller.signal);
    expect(fetch.mock.calls[1][0]).toBe(
      "/api/projects/study%20%2F%20one/delivery/retry",
    );
    expect(fetch.mock.calls[1][1].method).toBe("POST");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      taskId: "frozen-task",
    });
    await api.retryDelivery("study / one");
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({});
    expect(
      fetch.mock.calls.every(([url]) => !String(url).includes("execution")),
    ).toBe(true);
  });
});
