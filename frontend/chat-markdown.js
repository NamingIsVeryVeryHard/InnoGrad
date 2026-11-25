import { Marked, marked } from "./vendor/marked.js";
import DOMPurify from "./vendor/purify.js";

const controlledMarkdown = new Marked({
  renderer: {
    html({ text }) {
      return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    },
    link({ tokens }) {
      return this.parser.parseInline(tokens);
    },
    image({ text }) {
      return this.html({ text });
    },
  },
});

// Build an allowlisted fragment; never insert backend HTML directly.
export function renderMarkdown(text, { controlled = false } = {}) {
  const parser = controlled ? controlledMarkdown : marked;
  const fragment = DOMPurify.sanitize(
    parser.parse(String(text), { gfm: true, breaks: true }),
    {
      RETURN_DOM_FRAGMENT: true,
      FORBID_TAGS: controlled ? ["a", "img"] : [],
      ALLOWED_TAGS: [
        "p",
        "br",
        "strong",
        "em",
        "del",
        "blockquote",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "code",
        "a",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
      ],
      ALLOWED_ATTR: [
        "href",
        "src",
        "alt",
        "title",
        "start",
        "colspan",
        "rowspan",
      ],
    },
  );
  for (const element of fragment.querySelectorAll("a, img")) {
    const image = element.tagName === "IMG";
    const attribute = image ? "src" : "href";
    const raw = element.getAttribute(attribute);
    let safe = false;
    try {
      const url = new URL(raw || "", document.baseURI);
      safe =
        Boolean(raw) &&
        (["http:", "https:"].includes(url.protocol) ||
          (!image && url.protocol === "mailto:"));
    } catch {
      /* Invalid URLs remain inactive. */
    }
    if (!safe) {
      element.removeAttribute(attribute);
      if (image)
        element.replaceWith(
          document.createTextNode(element.alt || "图片地址不可用"),
        );
      continue;
    }
    if (image) {
      element.loading = "lazy";
      element.referrerPolicy = "no-referrer";
      element.addEventListener(
        "error",
        () => {
          element.replaceWith(
            document.createTextNode(`[图片加载失败：${element.alt || "图片"}]`),
          );
        },
        { once: true },
      );
    } else {
      element.target = "_blank";
      element.rel = "noopener noreferrer";
    }
  }
  return fragment;
}
