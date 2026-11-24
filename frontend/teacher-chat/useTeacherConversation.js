import { useCallback, useLayoutEffect, useRef, useState } from "react";

const conversationsPath = "/teacher-agent/conversations";
const conversationPath = (id) =>
  `${conversationsPath}/${encodeURIComponent(id)}`;
const emptyHistory = { conversation: null, turns: [], cards: new Map() };

function uniqueResults(results, legacy) {
  const seen = new Set();
  return (results ?? (legacy ? [legacy] : [])).filter((result) => {
    if (!result?.query_run_id || seen.has(result.query_run_id)) return false;
    seen.add(result.query_run_id);
    return true;
  });
}

export function runIdsFor(turn) {
  return [
    ...new Set(turn.run_ids ?? (turn.run_id ? [turn.run_id] : [])),
  ].filter(Boolean);
}

function revokedTurn({ id, turn_index }) {
  return { id, turn_index, access_revoked: true };
}

function legacyPrompt(result) {
  return result?.query_run_id ? undefined : result?.clarification;
}

function readHistory(detail) {
  const turns = (detail.turns || []).map((turn) =>
    turn.access_revoked ? revokedTurn(turn) : turn,
  );
  const latest = turns.at(-1);
  const cards = new Map();
  if (latest && !latest.access_revoked) {
    const prompt = legacyPrompt(detail.latest_result);
    if (!latest.clarification && prompt) {
      turns[turns.length - 1] = {
        ...latest,
        clarification: prompt,
      };
    }
    cards.set(
      latest.id,
      uniqueResults(detail.latest_results, detail.latest_result),
    );
  }
  return { conversation: detail.conversation, turns, cards };
}

async function getHistory(request, id) {
  return readHistory(await request(conversationPath(id)));
}

export function useTeacherConversation(session, open) {
  const { api } = session;
  const [history, setHistory] = useState(emptyHistory);
  const [selectedId, setSelectedId] = useState(null);
  const [summaries, setSummaries] = useState([]);
  const [draft, setDraft] = useState("");
  const [activity, setActivity] = useState("");
  const [status, setStatus] = useState("");
  const [scrollTarget, setScrollTarget] = useState(null);
  const scopeRef = useRef(null);

  const run = useCallback(
    async (kind, message, work, replace = false) => {
      const scope = scopeRef.current;
      if (!scope || (scope.controller && !replace)) return;
      scope.controller?.abort();
      const controller = new AbortController();
      const { signal } = controller;
      scope.controller = controller;
      setActivity(kind);
      setStatus(message);
      async function request(path, options) {
        signal.throwIfAborted();
        const data = await api(path, { cache: "no-store", ...options, signal });
        signal.throwIfAborted();
        return data;
      }
      try {
        await work(scope, request, signal);
        if (!signal.aborted) setStatus("");
      } catch (error) {
        if (!signal.aborted) setStatus(error.message || "请求失败，请重试。");
      } finally {
        if (scope.controller === controller) {
          scope.controller = null;
          if (!signal.aborted) setActivity("");
        }
      }
    },
    [api],
  );

  const load = useCallback(
    ({ list = false, selected } = {}) =>
      run(
        "loading",
        "正在读取最近对话…",
        async (scope, request, signal) => {
          setHistory(emptyHistory);
          if (selected !== undefined) {
            if (!selected && scope.selected !== "") scope.createKey = null;
            scope.selected = selected;
            setSelectedId(selected);
            setDraft("");
          }
          if (list) {
            const conversations = await request(conversationsPath);
            const paper = (conversations || []).filter(
              (item) => item.active_domain === "paper",
            );
            setSummaries(paper);
            scope.selected ??= paper[0]?.id ?? "";
            setSelectedId(scope.selected);
          }
          if (scope.selected) {
            const fresh = await getHistory(request, scope.selected);
            signal.throwIfAborted();
            setHistory(fresh);
            setSummaries((previous) =>
              previous.some((item) => item.id === fresh.conversation.id)
                ? previous.map((item) =>
                    item.id === fresh.conversation.id
                      ? fresh.conversation
                      : item,
                  )
                : [fresh.conversation, ...previous],
            );
          }
          setScrollTarget({});
        },
        true,
      ),
    [run],
  );

  useLayoutEffect(() => {
    if (scopeRef.current?.session !== session) {
      scopeRef.current = {
        session,
        selected: undefined,
        controller: null,
        createKey: null,
        lastWrite: null,
      };
      setSelectedId(null);
      setSummaries([]);
      setDraft("");
    }
    const scope = scopeRef.current;
    if (!open) {
      setHistory(emptyHistory);
      setSummaries([]);
      setActivity("");
      setStatus("");
      return;
    }
    void load({ list: true });
    return () => {
      scope.controller?.abort();
      scope.controller = null;
    };
  }, [load, open, session]);

  const available =
    open &&
    !activity &&
    (selectedId === "" || history.conversation?.id === selectedId);

  const submit = (input) => {
    const text = typeof input === "string" ? input.trim() : "";
    if (!available || (!text && input?.mode !== "drilldown_patch")) return;
    const displayText = text || input.label || "查看筛选结果";
    const payload = text ? { mode: "natural_language", message: text } : input;
    void run("submitting", "", async (scope, request, signal) => {
      let active = history.conversation;
      let write;
      let writeConfirmed = false;
      setHistory((previous) => ({
        ...previous,
        turns: [
          ...previous.turns,
          {
            id: "pending",
            turn_index: previous.turns.length + 1,
            user_message: displayText,
            pending: true,
          },
        ],
      }));
      setScrollTarget({});

      try {
        if (!active) {
          scope.createKey ||= crypto.randomUUID();
          active = await request(conversationsPath, {
            method: "POST",
            key: scope.createKey,
            body: JSON.stringify({ domain: "paper" }),
          });
          scope.createKey = null;
          scope.selected = active.id;
          setSelectedId(active.id);
          setHistory((previous) => ({ ...previous, conversation: active }));
          setSummaries((previous) => [
            active,
            ...previous.filter((item) => item.id !== active.id),
          ]);
        }
        const path = `${conversationPath(active.id)}/turns`;
        const signature = JSON.stringify([path, payload]);
        if (scope.lastWrite?.signature !== signature) {
          scope.lastWrite = {
            signature,
            key: crypto.randomUUID(),
            body: JSON.stringify({
              expected_lock_version: active.lock_version,
              input: payload,
            }),
          };
        }
        write = scope.lastWrite;
        const reply = await request(path, {
          method: "POST",
          key: write.key,
          body: write.body,
        });
        writeConfirmed = true;
        const needsHistory =
          reply.conversation_lock_version !== active.lock_version + 1 ||
          history.turns.some((turn) => turn.id === reply.turn.id);
        if (needsHistory) {
          const fresh = await getHistory(request, active.id);
          signal.throwIfAborted();
          const savedIndex = fresh.turns.findIndex(
            (item) => item.id === reply.turn.id,
          );
          const saved = fresh.turns[savedIndex];
          if (saved && reply.turn.access_revoked) {
            fresh.turns[savedIndex] = revokedTurn(saved);
            fresh.cards.delete(saved.id);
          } else if (
            saved &&
            !saved.access_revoked &&
            !fresh.cards.has(saved.id)
          ) {
            fresh.cards.set(
              saved.id,
              uniqueResults(reply.results, reply.result),
            );
          }
          setHistory(fresh);
          setSummaries((previous) => [
            fresh.conversation,
            ...previous.filter((item) => item.id !== active.id),
          ]);
          scope.lastWrite = null;
          if (text)
            setDraft((previous) => (previous.trim() === text ? "" : previous));
          setScrollTarget({ turnId: saved?.id });
          return;
        }
        const turn = reply.turn.access_revoked
          ? revokedTurn(reply.turn)
          : {
              ...reply.turn,
              user_message: displayText,
              analysis: reply.analysis ?? reply.turn.analysis,
              analysisNotice: reply.analysis_notice,
              clarification:
                reply.turn.clarification ?? legacyPrompt(reply.result),
            };
        const conversation = {
          ...active,
          lock_version: reply.conversation_lock_version,
          turn_count: Math.max(active.turn_count || 0, turn.turn_index),
          updated_at:
            reply.turn.turn_index >= (active.turn_count || 0)
              ? (reply.turn.created_at ?? active.updated_at)
              : active.updated_at,
        };
        scope.lastWrite = null;
        setHistory((previous) => {
          const turns = previous.turns.filter((item) => !item.pending);
          const saved = turns.findIndex((item) => item.id === turn.id);
          if (saved < 0) turns.push(turn);
          else turns[saved] = turn;
          const cards = new Map(previous.cards);
          if (turn.access_revoked) cards.delete(turn.id);
          else cards.set(turn.id, uniqueResults(reply.results, reply.result));
          return { conversation, turns, cards };
        });
        setSummaries((previous) => [
          conversation,
          ...previous.filter((item) => item.id !== conversation.id),
        ]);
        if (text)
          setDraft((previous) => (previous.trim() === text ? "" : previous));
        setScrollTarget({});
      } catch (error) {
        if (signal.aborted) throw error;
        if (!writeConfirmed && error.status >= 400 && error.status < 500) {
          if (write) scope.lastWrite = null;
          else scope.createKey = null;
        }
        setHistory(emptyHistory);
        if (active && error.status !== 401) {
          const fresh = await getHistory(request, active.id).catch(() => null);
          if (fresh && !signal.aborted) {
            setHistory(fresh);
            setSummaries((previous) =>
              previous.map((item) =>
                item.id === active.id ? fresh.conversation : item,
              ),
            );
            setScrollTarget({});
          }
        }
        throw error;
      }
    });
  };

  const replay = (turnId) => {
    if (!available || !history.conversation) return;
    void run(
      "replaying",
      "正在读取本轮结果…",
      async (scope, request, signal) => {
        setHistory(emptyHistory);
        const fresh = await getHistory(request, scope.selected);
        signal.throwIfAborted();
        const turn = fresh.turns.find((item) => item.id === turnId);
        if (!turn || turn.access_revoked || fresh.cards.has(turnId)) {
          setHistory(fresh);
          setScrollTarget({ turnId: turn?.id });
          return;
        }
        try {
          const ids = runIdsFor(turn);
          const outcomes = await Promise.allSettled(
            ids.map((id) =>
              request(`/teacher-agent/runs/${encodeURIComponent(id)}`),
            ),
          );
          signal.throwIfAborted();
          const errors = outcomes
            .filter((outcome) => outcome.status === "rejected")
            .map((outcome) => outcome.reason);
          const error =
            errors.find(({ status }) => status === 401 || status === 403) ??
            errors.find(({ status }) => status === 404) ??
            errors[0];
          if (error) throw error;
          fresh.cards.set(
            turnId,
            uniqueResults(
              outcomes.flatMap(({ value }, index) =>
                value?.query_run_id === ids[index] ? [value] : [],
              ),
            ),
          );
          setHistory(fresh);
          setScrollTarget({ turnId });
        } catch (error) {
          if (signal.aborted) throw error;
          if (error.status === 404) {
            fresh.turns = fresh.turns.map((item) =>
              item.id === turnId ? revokedTurn(item) : item,
            );
            fresh.cards.delete(turnId);
          }
          if (error.status !== 401 && error.status !== 403) {
            setHistory(fresh);
            setScrollTarget({ turnId });
          }
          throw error;
        }
      },
    );
  };

  return {
    ...history,
    selectedId,
    summaries,
    draft,
    setDraft,
    activity,
    available,
    status,
    scrollTarget,
    select: (id) => load({ selected: id }),
    refresh: () => load({ list: true }),
    submit,
    replay,
  };
}
