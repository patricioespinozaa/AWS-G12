import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ProveedorSesion } from "./auth/ProveedorSesion";
import { ProveedorApp } from "./contexto";
import "./estilos.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ProveedorSesion>
        <ProveedorApp>
          <App />
        </ProveedorApp>
      </ProveedorSesion>
    </BrowserRouter>
  </React.StrictMode>,
);
