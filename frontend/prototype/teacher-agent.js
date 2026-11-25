import { createElement } from "react";
import { createRoot } from "react-dom/client";

export function mountConversation(element, api) {
  const root = createRoot(element);
  const session = { api };
  let revision = 0;
  const refresh = async () => {
    const { TeacherChat } = await import("../teacher-chat/TeacherChat.jsx");
    root.render(
      createElement(TeacherChat, {
        key: ++revision,
        session,
        open: true,
        onWidthChange: (wide) =>
          element.closest(".panel")?.classList.toggle("is-wide", wide),
      }),
    );
  };
  void refresh();
  return refresh;
}
