import React, { useEffect, useMemo, useRef, useState } from "react";
import { buildVisualData, resolveVisualAction } from "./visual-data.js";
import { buildVisualDocument } from "./visual-runtime.js";

export function VisualSandbox({
  visual,
  sources,
  onOpen,
  onDrilldown,
  onAsk,
  fallback,
}) {
  const [phase, setPhase] = useState("loading");
  const [height, setHeight] = useState(40);
  const [chartSource, setChartSource] = useState("");
  const frameRef = useRef(null);
  const activePhase = useRef("loading");
  const actions = useRef(null);
  actions.current = { onOpen, onDrilldown, onAsk };
  const [channel] = useState(() =>
    crypto.getRandomValues(new Uint32Array(4)).join("-"),
  );
  const data = useMemo(() => buildVisualData(sources), [sources]);
  const srcDoc = useMemo(
    () =>
      chartSource &&
      buildVisualDocument({ html: visual.html, channel, data, chartSource }),
    [visual.html, channel, data, chartSource],
  );

  useEffect(() => {
    let active = true;
    import("../node_modules/chart.js/dist/chart.umd.min.js?raw").then(
      ({ default: source }) => {
        if (active) setChartSource(source);
      },
      () => {
        if (active) {
          activePhase.current = "fallback";
          setPhase("fallback");
        }
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    function changePhase(next) {
      activePhase.current = next;
      setPhase(next);
    }

    const timeout = window.setTimeout(() => {
      if (activePhase.current === "loading") changePhase("fallback");
    }, 2500);
    function receive(event) {
      if (
        activePhase.current === "fallback" ||
        event.source !== frameRef.current?.contentWindow ||
        event.origin !== "null" ||
        event.data?.channel !== channel
      ) {
        return;
      }
      const message = event.data;
      if (message.type === "error") {
        changePhase("fallback");
      } else if (message.type === "ready" || message.type === "resize") {
        if (!Number.isFinite(message.height) || message.height < 24) {
          if (message.type === "ready") changePhase("fallback");
          return;
        }
        setHeight(Math.min(1800, Math.ceil(message.height)));
        if (message.type === "ready") changePhase("ready");
      } else if (
        activePhase.current === "ready" &&
        navigator.userActivation.isActive
      ) {
        const action = resolveVisualAction(message, data, sources);
        if (action?.type === "open")
          actions.current.onOpen?.(action.target, action.id);
        if (action?.type === "drilldown")
          actions.current.onDrilldown?.(
            action.runId,
            action.patch,
            action.label,
          );
        if (action?.type === "ask") actions.current.onAsk?.(action.message);
      }
    }
    window.addEventListener("message", receive);
    return () => {
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
    };
  }, [channel, data, sources]);

  if (phase === "fallback")
    return <div className="visual-fallback">{fallback}</div>;

  return (
    <div className={`visual-sandbox visual-sandbox-${phase}`}>
      {phase === "loading" && (
        <p className="visual-loading" role="status">
          正在加载可视化…
        </p>
      )}
      {srcDoc && (
        <div className="visual-frame" style={{ height }}>
          <iframe
            ref={frameRef}
            title={visual.title || "论文查询可视化"}
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            srcDoc={srcDoc}
            tabIndex={phase === "loading" ? -1 : undefined}
          />
        </div>
      )}
      {phase === "ready" && (
        <details className="visual-evidence-toggle">
          <summary>查看查询依据与附件</summary>
          {fallback}
        </details>
      )}
    </div>
  );
}
