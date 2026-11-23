import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { AgentChat } from "./AgentChat.jsx";

function DevelopmentConsole() {
  useEffect(() => {
    void import("./app.js");
  }, []);
  return (
    <>
      <header>
        <div>
          <span className="mark">研</span>
          <strong>研究生成长与审核</strong>
          <span className="badge">开发联调台 · v0.2</span>
        </div>
        <div id="identity"></div>
      </header>
      <main>
        <div
          style={{
            marginBottom: "20px",
            padding: "16px 20px",
            background: "#eaf3e8",
            border: "1px solid #d7e7d1",
            borderRadius: "10px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "15px",
          }}
        >
          <span>「InnoGrad」业务工作台 · 已接入真实登录、数据库和后台处理</span>
          <a
            href="/prototype/"
            style={{
              color: "#20775e",
              fontWeight: "600",
              whiteSpace: "nowrap",
            }}
          >
            进入业务工作台 →
          </a>
        </div>
        <section id="login" className="card narrow">
          <div className="eyebrow">GRADUATE LIFECYCLE</div>
          <h1>进入工作台</h1>
          <p>使用本地初始化命令生成的演示账号登录。</p>
          <form id="loginForm">
            <label>
              账号
              <input name="username" autoComplete="username" required />
            </label>
            <label>
              密码
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <button>登录</button>
          </form>
          <p className="muted">
            演示材料仅用于开发验证。已接入规则初审与可配置的校内模型接口，正式结论由教师复核。
          </p>
        </section>
        <section id="workspace" hidden>
          <div className="intro">
            <div>
              <div className="eyebrow">WORKSPACE</div>
              <h1 id="welcome">工作台</h1>
              <p>每次提交都有独立版本，每项决定都保留依据。</p>
            </div>
            <button id="refresh" className="secondary">
              刷新数据
            </button>
          </div>
          <div className="stats" id="stats"></div>
          <div className="grid">
            <aside>
              <section className="card">
                <h2>材料记录</h2>
                <div id="newPaper" hidden>
                  <button id="createPaper">新建论文申报</button>
                </div>
                <div id="records"></div>
              </section>
              <section className="card">
                <h2>年度任务</h2>
                <div id="tasks"></div>
              </section>
            </aside>
            <section>
              <div id="manager" className="card" hidden>
                <h2>发布年度任务</h2>
                <form id="taskForm">
                  <label>
                    任务名称
                    <input name="title" required defaultValue="年度报告" />
                  </label>
                  <label>
                    统计周期
                    <input
                      name="period"
                      placeholder="例如：2025—2026学年"
                      required
                    />
                  </label>
                  <label>
                    截止时间
                    <input name="deadline" type="datetime-local" required />
                  </label>
                  <label>
                    复核教师
                    <select name="reviewer_id" id="reviewerSelect"></select>
                  </label>
                  <div id="studentOptions"></div>
                  <button>发布任务</button>
                </form>
              </div>
              <section id="detail" className="card">
                <div className="empty">
                  从左侧选择材料，查看提交版本与审核记录。
                </div>
              </section>
            </section>
          </div>
        </section>
        <div id="message" role="status" aria-live="polite"></div>
      </main>
      <AgentChat />
    </>
  );
}

createRoot(document.getElementById("react-root")).render(
  <DevelopmentConsole />,
);
