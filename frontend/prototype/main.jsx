import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { AgentChat } from "../AgentChat.jsx";

function CampusWorkspace() {
  useEffect(() => {
    void import("./app.js");
  }, []);
  return (
    <>
      <div id="app"></div>
      <dialog id="dialog" aria-labelledby="dialog-title"></dialog>
      <div id="toast" role="status" aria-live="polite"></div>
      <AgentChat />
    </>
  );
}

createRoot(document.getElementById("react-root")).render(<CampusWorkspace />);
