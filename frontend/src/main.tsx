import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router";

import { router } from "@/routes/router";
import "@/index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root container missing in index.html");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
