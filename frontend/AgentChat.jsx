import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import styles from "./agent-chat.css?inline";
import { renderMarkdown } from "./chat-markdown.js";
import { TeacherChat } from "./teacher-chat/TeacherChat.jsx";

const guides = [
  [
    "论文",
    "请进入「论文成果」页面，新建论文工作稿，填写论文信息并上传材料。核对内容后正式提交，即可进入审核流程。",
  ],
  [
    "审核",
    "请在材料详情中查看提交版本与审核记录。机构用户也可以进入「Agent 审核」查看任务状态、材料与报告；如被退回，请根据补正意见修改后重新提交。",
  ],
  [
    "任务",
    "请进入「培养任务」查看已发布任务、统计周期与截止时间。选择对应任务后填写年度报告，并在截止前正式提交。",
  ],
];

function Bubble({ role, text }) {
  const node = useRef(null);
  useLayoutEffect(() => {
    if (role === "assistant")
      node.current.replaceChildren(renderMarkdown(text));
  }, [role, text]);
  return (
    <div ref={node} className={`bubble ${role}`}>
      {role === "user" ? text : null}
    </div>
  );
}

export function AgentChat() {
  const host = useRef(null);
  const input = useRef(null);
  const launcher = useRef(null);
  const close = useRef(null);
  const guideContent = useRef(null);
  const [shadow, setShadow] = useState(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const [teacherSession, setTeacherSession] = useState(null);
  const [wide, setWide] = useState(false);

  useLayoutEffect(() => {
    const element = host.current;
    setShadow(element.shadowRoot || element.attachShadow({ mode: "open" }));
    const receive = (event) => {
      const text = event.detail?.content;
      if (typeof text === "string")
        setMessages((previous) => [...previous, { role: "assistant", text }]);
    };
    const sessionChanged = (event) => {
      const next = event.detail;
      const canAsk = ["teacher", "manager"].includes(next?.user?.role);
      setTeacherSession(canAsk ? next : null);
      setDraft("");
      setMessages([]);
      setOpen(false);
      setWide(false);
    };
    element.addEventListener("agent:reply", receive);
    window.addEventListener("innograd:session", sessionChanged);
    return () => {
      element.removeEventListener("agent:reply", receive);
      window.removeEventListener("innograd:session", sessionChanged);
    };
  }, []);

  useLayoutEffect(() => {
    if (guideContent.current && open)
      guideContent.current.scrollTop = guideContent.current.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    if (!teacherSession) return;
    const collapse = () => setOpen(false);
    window.addEventListener("innograd:open-portrait", collapse);
    return () => window.removeEventListener("innograd:open-portrait", collapse);
  }, [teacherSession]);

  useEffect(() => {
    if (open) (teacherSession ? close.current : input.current)?.focus();
  }, [open, teacherSession]);

  const toggle = useCallback(() => {
    if (open) launcher.current?.focus();
    setOpen((value) => !value);
  }, [open]);

  function submit(value) {
    const text = value.trim();
    if (!text) return;
    const guide = guides.find(([keyword]) => text.includes(keyword));
    const reply = guide
      ? `使用指引\n${guide[1]}`
      : "当前提供预设使用指引，尚未接入 AI 对话服务，无法查询个人数据或执行操作。你可以询问论文材料提交、审核进度或培养任务。";
    setMessages((previous) => [
      ...previous,
      { role: "user", text },
      { role: "assistant", text: reply },
    ]);
    setDraft("");
    input.current?.focus();
  }

  function enter(event) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      submit(draft);
    }
  }

  return (
    <div
      id="innograd-agent"
      ref={host}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          toggle();
        }
      }}
    >
      {shadow &&
        createPortal(
          <>
            <style>{styles}</style>
            <section
              className={`panel ${teacherSession ? "teacher-panel" : ""} ${teacherSession && wide ? "is-wide" : ""}`}
              id="agent-panel"
              role="dialog"
              aria-label="InnoGrad Agent 对话"
              hidden={!open}
            >
              <header>
                <div className="mark">✦</div>
                <div>
                  <strong>InnoGrad Agent</strong>
                  <small>
                    {teacherSession ? "论文成果查询" : "你的研究生成长助手"}
                  </small>
                </div>
                <button
                  ref={close}
                  onClick={toggle}
                  className="close"
                  aria-label="收起对话"
                >
                  ×
                </button>
              </header>
              {teacherSession ? (
                <TeacherChat
                  session={teacherSession}
                  open={open}
                  onWidthChange={setWide}
                />
              ) : (
                <>
                  <div className="content" ref={guideContent}>
                    <div hidden={messages.length > 0} className="welcome">
                      <div className="eyebrow">HERE TO HELP</div>
                      <h2>
                        你好，
                        <br />
                        有什么可以帮你？
                      </h2>
                      <p>
                        从材料提交到培养任务，
                        <br />
                        让每一步都有清晰的方向。
                      </p>
                      <div className="suggestions">
                        {[
                          "如何提交论文材料？",
                          "在哪里查看审核进度？",
                          "如何查看我的培养任务？",
                        ].map((question) => (
                          <button
                            type="button"
                            key={question}
                            onClick={() => submit(question)}
                          >
                            {question}
                            <span>↗</span>
                          </button>
                        ))}
                      </div>
                    </div>
                    <div
                      className="messages"
                      role="log"
                      aria-label="聊天消息"
                      aria-live="polite"
                    >
                      {messages.map((message, index) => (
                        <Bubble key={index} {...message} />
                      ))}
                    </div>
                  </div>
                  <footer>
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        submit(draft);
                      }}
                    >
                      <textarea
                        ref={input}
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={enter}
                        aria-label="输入消息"
                        placeholder="输入你的问题…"
                        maxLength="2000"
                        rows="1"
                      />
                      <button
                        className="send"
                        aria-label="发送消息"
                        disabled={!draft.trim()}
                      >
                        <svg viewBox="0 0 24 24">
                          <path d="m5 12 7-7 7 7M12 5v15" />
                        </svg>
                      </button>
                    </form>
                    <div className="note">
                      使用指引模式 · AI 对话服务暂未接入
                    </div>
                  </footer>
                </>
              )}
            </section>
            <button
              ref={launcher}
              onClick={toggle}
              className="launcher"
              aria-label={open ? "收起 Agent 助手" : "打开 Agent 助手"}
              aria-expanded={open}
              aria-controls="agent-panel"
            >
              <svg viewBox="0 0 24 24">
                <path d="M20 11.5a8.5 8.5 0 0 1-8.5 8.5H4l1-4A8.5 8.5 0 1 1 20 11.5Z" />
                <path d="M8 10h8M8 14h5" />
              </svg>
            </button>
          </>,
          shadow,
        )}
    </div>
  );
}
