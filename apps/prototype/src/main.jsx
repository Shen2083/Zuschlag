import React from "react";
import { createRoot } from "react-dom/client";
import ZuschlagApp from "../ZuschlagApp.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ZuschlagApp />
  </React.StrictMode>
);
