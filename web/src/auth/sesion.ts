/**
 * Sesión de la Administradora (F0007): Hosted UI de Cognito con authorization code + PKCE.
 *
 * - Los tokens viven solo en memoria (nunca en localStorage ni en cookies legibles desde JavaScript). Al recargar la
 *   página se pasa de nuevo por Cognito, que recuerda la sesión y devuelve a la app sin pedir la clave.
 * - Lo único que sobrevive a la redirección es el verificador PKCE, el `state` y la ruta a la que volver, en
 *   sessionStorage. No sirven sin el código de un solo uso que entrega Cognito.
 * - La API recibe el ID token en `Authorization: Bearer` (trae el nombre de la persona: queda como autora).
 */

export interface ConfigAuth {
  modo: "cognito" | "desactivada";
  dominio: string;
  client_id: string;
  region: string;
}

interface Tokens {
  id: string;
  refresh: string | null;
  expira: number; // ms epoch
}

const CLAVE_PKCE = "hlf_pkce";
let tokens: Tokens | null = null;
let alVencer: (() => void) | null = null;

/** Lo llama api.ts ante un 401: la sesión venció o fue revocada. */
export function sesionVencida() {
  tokens = null;
  alVencer?.();
}

export function registrarAlVencer(f: () => void) {
  alVencer = f;
}

export function cabeceraAuth(): Record<string, string> {
  return tokens ? { Authorization: `Bearer ${tokens.id}` } : {};
}

export function tieneSesion(): boolean {
  return tokens !== null && tokens.expira > Date.now();
}

export function expiraEn(): number {
  return tokens ? tokens.expira - Date.now() : 0;
}

export async function cargarConfig(): Promise<ConfigAuth> {
  const r = await fetch("/api/auth/config");
  if (!r.ok) throw new Error(`No se pudo leer la configuración del login (${r.status})`);
  return r.json();
}

// -- PKCE ----------------------------------------------------------------------------------------------
function base64url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function aleatorio(n = 32): string {
  return base64url(crypto.getRandomValues(new Uint8Array(n)));
}

async function desafio(verificador: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verificador));
  return base64url(new Uint8Array(hash));
}

function retorno(): string {
  return `${window.location.origin}/`;
}

function leerPkce(): { verificador: string; state: string; volver: string } | null {
  try {
    const v = sessionStorage.getItem(CLAVE_PKCE);
    return v ? JSON.parse(v) : null;
  } catch {
    return null;
  }
}

/** Lleva al Hosted UI de Cognito. Al volver, `completarLogin` canjea el código por los tokens. */
export async function iniciarLogin(cfg: ConfigAuth): Promise<never> {
  const verificador = aleatorio(48);
  const state = aleatorio(16);
  const volver = window.location.pathname + window.location.search;
  try {
    sessionStorage.setItem(CLAVE_PKCE, JSON.stringify({ verificador, state, volver }));
  } catch {
    throw new Error("El navegador no permite guardar la sesión de inicio (sessionStorage bloqueado).");
  }
  const p = new URLSearchParams({
    response_type: "code",
    client_id: cfg.client_id,
    redirect_uri: retorno(),
    scope: "openid email profile",
    state,
    code_challenge: await desafio(verificador),
    code_challenge_method: "S256",
  });
  window.location.assign(`${cfg.dominio}/oauth2/authorize?${p}`);
  return new Promise<never>(() => {}); // la página se va
}

async function pedirTokens(cfg: ConfigAuth, cuerpo: Record<string, string>): Promise<Tokens> {
  const r = await fetch(`${cfg.dominio}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: cfg.client_id, ...cuerpo }),
  });
  if (!r.ok) throw new Error(`Cognito rechazó el inicio de sesión (${r.status})`);
  const t = await r.json();
  return { id: t.id_token, refresh: t.refresh_token ?? null, expira: Date.now() + (t.expires_in ?? 3600) * 1000 };
}

/** Si la URL trae el código de Cognito, lo canjea y limpia la URL. Devuelve si quedó una sesión. */
export async function completarLogin(cfg: ConfigAuth): Promise<boolean> {
  const q = new URLSearchParams(window.location.search);
  const codigo = q.get("code");
  if (q.get("error")) throw new Error(q.get("error_description") || q.get("error") || "Error de inicio de sesión");
  if (!codigo) return false;
  const pkce = leerPkce();
  sessionStorage.removeItem(CLAVE_PKCE);
  if (!pkce || pkce.state !== q.get("state")) throw new Error("El inicio de sesión no coincide con esta pestaña. Intenta de nuevo.");
  const previo = tokens?.refresh ?? null;
  tokens = await pedirTokens(cfg, {
    grant_type: "authorization_code", code: codigo, redirect_uri: retorno(), code_verifier: pkce.verificador,
  });
  tokens.refresh = tokens.refresh ?? previo;
  window.history.replaceState(null, "", pkce.volver || "/");
  return true;
}

/** Renueva el ID token con el refresh token (en memoria). False si no se pudo: hay que volver a iniciar sesión. */
export async function renovar(cfg: ConfigAuth): Promise<boolean> {
  if (!tokens?.refresh) return false;
  try {
    const nuevos = await pedirTokens(cfg, { grant_type: "refresh_token", refresh_token: tokens.refresh });
    tokens = { ...nuevos, refresh: nuevos.refresh ?? tokens.refresh };
    return true;
  } catch {
    return false;
  }
}

export function cerrarSesion(cfg: ConfigAuth) {
  tokens = null;
  const p = new URLSearchParams({ client_id: cfg.client_id, logout_uri: retorno() });
  window.location.assign(`${cfg.dominio}/logout?${p}`);
}

/** Nombre de la persona según el ID token (solo para mostrar: la API es la que verifica la firma). */
export function nombreEnToken(): string | null {
  if (!tokens) return null;
  try {
    const carga = JSON.parse(atob(tokens.id.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return carga.name || carga.email || carga["cognito:username"] || null;
  } catch {
    return null;
  }
}
