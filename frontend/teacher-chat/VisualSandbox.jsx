import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppRenderer } from "@mcp-ui/client";
import {
  buildAllowlist,
  buildSandboxDocument,
  buildVisualData,
  parseSandboxMessage,
  sandboxProxyUrl,
} from "./visual-runtime.js";

const sandboxConfig = {
  url: sandboxProxyUrl,
  permissions: "allow-scripts",
};
const hostInfo = { name: "InnoGrad", version: "1.0.0" };
const hostCapabilities = { message: {} };

function clampHeight(value) {
  const height = Number(value);
  if (!Number.isFinite(height)) return 40;
  return Math.min(1200, Math.max(40, Math.round(height)));
}

export function VisualSandbox({
  visual,
  results,
  onOpen,
  onDrilldown,
  onAsk,
  fallback,
}) {
  const [phase, setPhase] = useState("loading");
  const [height, setHeight] = useState(40);
  const channelId = useMemo(
    () =>
      `visual-${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`,
    [],
  );
  const allowlist = useMemo(() => buildAllowlist(results), [results]);
  const frameHost = useRef(null);
  const document = useMemo(
    () =>
      buildSandboxDocument({
        channelId,
        html: visual.html,
        data: buildVisualData(results),
      }),
    [channelId, results, visual.html],
  );
  const phaseRef = useRef("loading");
  const callbacks = useRef({ onOpen, onDrilldown, onAsk });
  callbacks.current = { onOpen, onDrilldown, onAsk };

  const fail = useCallback(() => {
    phaseRef.current = "fallback";
    setPhase("fallback");
  }, []);

  useEffect(() => {
    phaseRef.current = "loading";
    setPhase("loading");
    setHeight(40);
    const timer = window.setTimeout(() => {
      if (phaseRef.current === "loading") fail();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [document, fail]);

  useLayoutEffect(() => {
    const host = frameHost.current;
    if (!host) return undefined;
    const restrictFrame = () => {
      const iframe = host.querySelector("iframe");
      if (iframe) iframe.setAttribute("sandbox", "allow-scripts");
    };
    restrictFrame();
    const observer = new MutationObserver(restrictFrame);
    observer.observe(host, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [document]);

  function handleMessage(params) {
    const text = params?.content?.find?.((item) => item.type === "text")?.text;
    if (!text) return;
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return;
    }
    if (message?.channelId !== channelId) return;
    if (message.type === "error") {
      fail();
      return;
    }
    if (phaseRef.current === "fallback") return;
    if (message.type === "resize" || message.type === "ready") {
      if (!Number.isFinite(message.height) || message.height < 24)
        return fail();
      setHeight(clampHeight(message.height));
      if (message.type === "ready") {
        phaseRef.current = "ready";
        setPhase("ready");
      }
      return;
    }
    if (message.type === "intent" || message.type === "prompt") {
      handleAction(message);
      return;
    }
  }

  useEffect(() => {
    const receive = (event) => {
      if (event.data?.jsonrpc !== "2.0" || event.data.method !== "ui/message")
        return;
      const iframe = frameHost.current?.querySelector("iframe");
      if (!iframe || event.source !== iframe.contentWindow) return;
      handleMessage(event.data.params);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [channelId, allowlist]);

  function handleAction(action) {
    const verified = parseSandboxMessage(action, channelId, allowlist);
    if (!verified) return;
    if (verified.type === "open_submission")
      callbacks.current.onOpen?.("submission", verified.submissionId);
    if (verified.type === "open_portrait")
      callbacks.current.onOpen?.("portrait", verified.studentId);
    if (verified.type === "drilldown")
      callbacks.current.onDrilldown?.(
        verified.runId,
        verified.patch,
        verified.label,
      );
    if (verified.type === "ask") callbacks.current.onAsk?.(verified.message);
  }

  if (phase === "fallback")
    return <div className="visual-fallback">{fallback}</div>;

  return (
    <div className={`visual-sandbox visual-sandbox-${phase}`}>
      {phase === "loading" ? (
        <div className="visual-loading-shimmer" aria-label="正在加载可视化" />
      ) : null}
      {phase === "ready" && visual.title ? (
        <div className="visual-title">{visual.title}</div>
      ) : null}
      <div
        className="visual-frame"
        ref={frameHost}
        style={{ height: `${height}px` }}
      >
        <AppRenderer
          html={document}
          toolName="innograd-visual"
          sandbox={sandboxConfig}
          hostInfo={hostInfo}
          onError={fail}
          hostCapabilities={hostCapabilities}
        />
      </div>
      {phase === "ready" ? (
        <details className="visual-evidence-toggle">
          <summary>查看核验依据与附件</summary>
          {fallback}
        </details>
      ) : null}
    </div>
  );
}
