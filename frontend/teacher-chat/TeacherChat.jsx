import React, { useLayoutEffect, useRef, useState } from "react";
import {
  Analysis,
  Clarification,
  Followups,
  ResultCard,
  titleFromQuery,
} from "./ResultBlocks.jsx";
import { runIdsFor, useTeacherConversation } from "./useTeacherConversation.js";
import { VisualSandbox } from "./VisualSandbox.jsx";

const starterQuestions = [
  "今年论文发表情况",
  "今年博士生已发表论文",
  "查看待审核论文材料",
];

function openTarget(type, id) {
  if (typeof id !== "string" || !/^[A-Za-z0-9-]+$/.test(id)) return;
  if (type === "submission") {
    window.dispatchEvent(
      new CustomEvent("innograd:open-submission", {
        detail: { submissionId: id },
      }),
    );
  } else if (type === "portrait") {
    window.dispatchEvent(
      new CustomEvent("innograd:open-portrait", { detail: { studentId: id } }),
    );
  }
}

function Turn({ turn, results, canReplay, latest, available, submit, replay }) {
  if (turn.access_revoked) {
    return (
      <article className="teacher-turn" data-turn-id={turn.id}>
        <div className="bubble assistant">
          查询范围已变更，本轮内容不可查看。
        </div>
      </article>
    );
  }

  const runIds = runIdsFor(turn);
  const query = turn.resolved_query || results[0]?.applied_query;
  const turnPrompt = JSON.stringify(turn.clarification);
  const message = ["", "筛选查询", "更新筛选条件"].includes(
    turn.user_message?.trim() ?? "",
  )
    ? titleFromQuery(query, "查看筛选结果")
    : turn.user_message;
  const resultCards = results.map((result) => (
    <ResultCard
      key={result.query_run_id}
      result={
        result.clarification &&
        JSON.stringify(result.clarification) === turnPrompt
          ? { ...result, clarification: null }
          : result
      }
      query={result.applied_query || turn.resolved_query}
      onDrilldown={(patch, label) =>
        submit({
          mode: "drilldown_patch",
          parent_run_id: result.query_run_id,
          patch,
          label,
        })
      }
      onAction={submit}
      onOpen={openTarget}
      showAnalysis={!turn.analysis}
    />
  ));

  return (
    <article className="teacher-turn" data-turn-id={turn.id}>
      {message ? <div className="bubble user">{message}</div> : null}
      {turn.pending ? (
        <div className="bubble assistant loading-indicator">
          正在查询论文资料…
        </div>
      ) : (
        <div className="bubble assistant">
          {turn.analysis ? (
            <Analysis
              text={turn.analysis}
              runIds={results.map((result) => result.query_run_id)}
            />
          ) : null}
          {turn.analysisNotice ? (
            <p className="analysis-notice">{turn.analysisNotice}</p>
          ) : null}
          {turn.clarification ? (
            <Clarification prompt={turn.clarification} onAction={submit} />
          ) : null}
          {turn.visual && results.length ? (
            <VisualSandbox
              visual={turn.visual}
              results={results}
              onOpen={openTarget}
              onDrilldown={(runId, patch, label) =>
                submit({
                  mode: "drilldown_patch",
                  parent_run_id: runId,
                  patch,
                  label,
                })
              }
              onAsk={submit}
              fallback={resultCards}
            />
          ) : (
            resultCards
          )}
          {canReplay && runIds.length ? (
            <button
              type="button"
              className="replay-button"
              disabled={!available}
              onClick={() => replay(turn.id)}
            >
              查看本轮结果
            </button>
          ) : null}
          {!results.length && turn.status === "failed" ? (
            <p>本轮查询失败。</p>
          ) : null}
          {latest && results.length ? (
            <Followups result={results.at(-1)} onAction={submit} />
          ) : null}
        </div>
      )}
    </article>
  );
}

export function TeacherChat({ session, open, onWidthChange }) {
  const {
    turns,
    cards,
    selectedId,
    summaries,
    draft,
    setDraft,
    activity,
    available,
    status,
    scrollTarget,
    select,
    refresh,
    submit,
    replay,
  } = useTeacherConversation(session, open);
  const [wide, setWide] = useState(false);
  const contentRef = useRef(null);
  const messagesRef = useRef(null);
  const latest = turns.findLast(
    (turn) => !turn.pending && !turn.access_revoked,
  );

  useLayoutEffect(() => {
    setWide(false);
  }, [session]);

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!open || !content) return;
    const messages = messagesRef.current;
    const target = scrollTarget?.turnId
      ? Array.from(messages.children).find(
          (turn) => turn.dataset.turnId === scrollTarget.turnId,
        )
      : messages.lastElementChild;
    content.scrollTop = target
      ? content.scrollTop +
        target.getBoundingClientRect().top -
        content.getBoundingClientRect().top
      : 0;
  }, [open, scrollTarget]);

  function send(event) {
    event.preventDefault();
    submit(draft);
  }

  return (
    <div className={`teacher-chat ${wide ? "is-wide" : ""}`}>
      <div className="teacher-toolbar">
        <label className="conversation-picker">
          <span className="sr-only">最近对话</span>
          <select
            value={selectedId ?? ""}
            onChange={(event) => select(event.target.value)}
          >
            <option value="">新对话</option>
            {selectedId && !summaries.some((item) => item.id === selectedId) ? (
              <option value={selectedId}>当前对话</option>
            ) : null}
            {summaries.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title || "论文查询"} · {item.turn_count || 0}轮
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="toolbar-button" onClick={refresh}>
          刷新对话
        </button>
        <button
          type="button"
          className="toolbar-button width-toggle"
          onClick={() => {
            setWide(!wide);
            onWidthChange?.(!wide);
          }}
          aria-label={wide ? "恢复默认宽度" : "展开宽浮窗"}
        >
          {wide ? "恢复默认宽度" : "展开宽浮窗"}
        </button>
      </div>
      <div className="teacher-content" ref={contentRef}>
        {available && !turns.length ? (
          <div className="teacher-welcome">
            <h2>你好，今天想查哪类论文成果？</h2>
            <p>可以从年度统计、学生范围或发表状态开始查询。</p>
            <div className="starter-questions">
              {starterQuestions.map((question) => (
                <button
                  type="button"
                  key={question}
                  onClick={() => submit(question)}
                >
                  {question}
                  <span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <div
          className="teacher-messages"
          role="log"
          aria-label="论文查询对话"
          ref={messagesRef}
        >
          {turns.map((turn) => (
            <Turn
              key={turn.id}
              turn={turn}
              results={cards.get(turn.id) || []}
              canReplay={!cards.has(turn.id)}
              latest={turn.id === latest?.id}
              available={available}
              submit={submit}
              replay={replay}
            />
          ))}
        </div>
        {activity === "loading" || activity === "replaying" ? (
          <p className="teacher-status" role="status">
            {status}
          </p>
        ) : null}
      </div>
      <footer className="teacher-footer">
        {!activity && status ? (
          <p className="teacher-status" role="status">
            {status}
          </p>
        ) : null}
        <form onSubmit={send}>
          <textarea
            aria-label="你的问题"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              )
                send(event);
            }}
            disabled={!available}
            maxLength={2000}
            rows={1}
            placeholder="输入论文查询问题…"
          />
          <button
            type="submit"
            className="send"
            aria-label={turns.length ? "发送追问" : "发送问题"}
            disabled={!available || !draft.trim()}
          >
            <span aria-hidden="true">↑</span>
          </button>
        </form>
      </footer>
    </div>
  );
}
