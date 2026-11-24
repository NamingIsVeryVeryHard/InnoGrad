import chartSource from "../node_modules/chart.js/dist/chart.umd.min.js?raw";

const policy = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
  "script-src 'unsafe-inline'",
  "img-src data:",
  "frame-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
  "webrtc 'block'",
].join("; ");

function serialize(value) {
  return JSON.stringify(value)
    .replaceAll("<", "\\u003c")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
}

function startGuest(channel, data) {
  const post = parent.postMessage.bind(parent);
  const send = (message) => post({ ...message, channel }, "*");
  const getAction = new WeakMap();

  function freeze(value) {
    if (value && typeof value === "object") {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
    return value;
  }

  for (const run of data.runs) {
    for (const group of ["breakdown", "metrics"]) {
      run[group].forEach((row, index) => {
        if (row.drilldownPatch) {
          getAction.set(row.drilldownPatch, {
            type: "drilldown",
            runId: run.runId,
            group,
            index,
          });
        }
      });
    }
  }
  const lookup = getAction.get.bind(getAction);
  let clicked = false;
  const schedule = setTimeout.bind(window);
  window.addEventListener(
    "click",
    (event) => {
      if (event.isTrusted) {
        clicked = true;
        schedule(() => (clicked = false), 0);
      }
    },
    true,
  );
  function act(action) {
    if (!clicked || !action) return;
    clicked = false;
    send(action);
  }

  Object.defineProperties(window, {
    __INNOGRAD_DATA__: { value: freeze(data) },
    innograd: {
      value: Object.freeze({
        openSubmission: (id) => act({ type: "open_submission", id }),
        openPortrait: (id) => act({ type: "open_portrait", id }),
        drilldown: (runId, patch) => {
          const action = lookup(patch);
          if (action?.runId === runId) act({ ...action });
        },
        ask: (message) => act({ type: "ask", message }),
      }),
    },
    RTCPeerConnection: { value: undefined },
    webkitRTCPeerConnection: { value: undefined },
  });

  window.addEventListener("error", () => send({ type: "error" }));
  window.addEventListener("unhandledrejection", () => send({ type: "error" }));
  document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("ig-root");
    const report = (type) =>
      send({ type, height: Math.ceil(root.getBoundingClientRect().height) });
    requestAnimationFrame(() => {
      report("ready");
      new ResizeObserver(() => report("resize")).observe(root);
    });
  });
}

function startWrapper(channel, guestDocument) {
  const guest = document.createElement("iframe");
  guest.title = "交互式论文查询结果";
  guest.dataset.visualGuest = "";
  guest.sandbox = "allow-scripts";
  guest.referrerPolicy = "no-referrer";
  guest.srcdoc = guestDocument;
  document.body.append(guest);

  window.addEventListener("message", (event) => {
    if (
      event.source !== guest.contentWindow ||
      event.origin !== "null" ||
      event.data?.channel !== channel
    ) {
      return;
    }
    if (
      !["ready", "resize", "error"].includes(event.data.type) &&
      !navigator.userActivation.isActive
    ) {
      return;
    }
    parent.postMessage(event.data, "*");
  });
}

export function buildVisualDocument({ html, channel, data }) {
  const guest = `<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<style>
  :root {
    --ig-accent: #8e233c;
    --ig-bg: #fff;
    --ig-surface: #f8f4f5;
    --ig-border: #e9dfe2;
    --ig-text: #282326;
    --ig-muted: #685c62;
    --ig-radius: 8px;
    color: var(--ig-text);
    background: var(--ig-bg);
    font: 14px/1.55 -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; }
  body { margin: 0; overflow-wrap: anywhere; }
  #ig-root { display: flow-root; padding: clamp(10px, 3vw, 20px); }
  button, input, textarea, select { font: inherit; }
  button, summary { cursor: pointer; }
  :focus-visible { outline: 2px solid var(--ig-accent); outline-offset: 2px; }
  canvas, svg, img { max-inline-size: 100%; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  }
</style>
<script>(${startGuest})(${serialize(channel)},${serialize(data)})</script>
<script>${chartSource}</script>
<body><main id="ig-root">${html}</main></body>
</html>`;
  return `<!doctype html>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${policy}">
<style>
  html, body { height: 100%; margin: 0; overflow: hidden; }
  iframe { display: block; width: 100%; height: 100%; border: 0; }
</style>
<body><script>(${startWrapper})(${serialize(channel)},${serialize(guest)})</script></body>`;
}
