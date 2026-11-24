const CORREDOR = new URLSearchParams(location.search).get("corredor") || "demo";
const ETAPAS = [["consulta", "Consulta"], ["recopilando", "Datos"], ["confirmando", "Confirmación"], ["registrada", "Registrada"]];
const SUGERENCIAS = {
  vehiculo: ["Me chocaron, ¿qué hago?", "¿Cuál es el deducible y cuánto es en pesos?", "Quiero cotizar para mi auto"],
  hogar: ["¿Cubre daños por agua?", "¿Cómo denuncio un robo?", "Quiero cotizar"],
};
const $ = (id) => document.getElementById(id);
let seguros = [], actual = null, conversacion = null, enviando = false;

// localStorage puede fallar (modo privado): la app funciona igual, solo no recuerda.
const guardar = (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch {} };
const leer = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const claveConv = () => `conv:${CORREDOR}:${actual.id}`;

const escapar = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Markdown mínimo y seguro: primero se escapa todo el HTML.
function markdown(texto) {
  const lineas = escapar(texto).split("\n"), html = [];
  let lista = null;
  const cerrar = () => { if (lista) { html.push(lista === "table" ? "</tbody></table></div>" : `</${lista}>`); lista = null; } };
  const celdas = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  for (const l of lineas) {
    if (/^\s*\|.*\|\s*$/.test(l)) {  // tablas: | a | b |
      if (/^\s*\|[\s:|-]+\|\s*$/.test(l)) continue;  // la fila |---|---|
      if (lista !== "table") {
        cerrar(); lista = "table";
        html.push(`<div class="tabla-msg"><table><thead><tr>${celdas(l).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`);
      } else html.push(`<tr>${celdas(l).map((c) => `<td>${c}</td>`).join("")}</tr>`);
      continue;
    }
    const vineta = l.match(/^\s*[-*•]\s+(.*)/), num = l.match(/^\s*\d+[.)]\s+(.*)/);
    if (vineta || num) {
      const tipo = vineta ? "ul" : "ol";
      if (lista !== tipo) { cerrar(); html.push(`<${tipo}>`); lista = tipo; }
      html.push(`<li>${(vineta || num)[1]}</li>`);
    } else { cerrar(); if (l.trim()) html.push(`<p>${l}</p>`); }
  }
  cerrar();
  return html.join("").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

function agregar(rol, texto, extra = {}) {
  $("mensajes").querySelector(".bienvenida")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${rol}` + (extra.clase ? ` ${extra.clase}` : "");
  if (rol === "cliente") div.textContent = texto; else div.innerHTML = markdown(texto);
  if (extra.meta) {
    const m = document.createElement("div");
    m.className = "meta" + ($("detalles").checked ? "" : " oculto");
    m.textContent = extra.meta;
    div.appendChild(m);
  }
  $("mensajes").appendChild(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
  return div;
}

function pintarEtapa(etapa, numero) {
  const i = Math.max(0, ETAPAS.findIndex(([id]) => id === etapa));
  $("etapas").innerHTML = ETAPAS.map(([id, nombre], j) =>
    `<li class="${j < i || (j === i && id === "registrada") ? "hecha" : ""} ${j === i ? "actual" : ""}" ${j === i ? 'aria-current="step"' : ""}><b>${j < i || id === "registrada" && j === i ? "✓" : j + 1}</b>${nombre}</li>`).join("");
  $("numero").textContent = numero ? `Solicitud ${numero}` : "";
  $("numero").classList.toggle("oculto", !numero);
}

function bienvenida() {
  const opciones = SUGERENCIAS[actual.id] || ["¿Qué cubre este seguro?", "¿Qué no cubre?", "Quiero cotizar"];
  $("mensajes").innerHTML = `<div class="bienvenida"><h2>${escapar(actual.nombre)}</h2><p>${escapar(actual.descripcion)}</p>
    <div class="sugerencias">${opciones.map((s) => `<button class="boton" type="button">${escapar(s)}</button>`).join("")}</div></div>`;
  $("mensajes").querySelectorAll(".sugerencias button").forEach((b) => b.onclick = () => enviar(b.textContent));
}

async function elegir(id) {
  actual = seguros.find((s) => s.id === id) || seguros[0];
  document.querySelectorAll(".seguro").forEach((b) => b.setAttribute("aria-current", b.dataset.id === actual.id));
  $("selector").value = actual.id;
  $("titulo").textContent = actual.nombre;
  guardar(`seguro:${CORREDOR}`, actual.id);
  conversacion = leer(claveConv());
  pintarEtapa("consulta");
  bienvenida();
  if (!conversacion) return;
  try {  // retoma la conversación guardada en el servidor
    const r = await fetch(`/corredores/${CORREDOR}/seguros/${actual.id}/conversaciones/${conversacion}`);
    if (r.status === 401) return pedirSesion("Tu sesión venció. Vuelve a ingresar.");
    if (!r.ok) throw new Error();
    const datos = await r.json();
    if (datos.mensajes.length) {
      $("mensajes").innerHTML = "";
      datos.mensajes.forEach((m) => agregar(m.rol, m.texto));
    }
    pintarEtapa(datos.etapa, datos.numero);
  } catch { conversacion = null; guardar(claveConv(), null); }
}

async function enviar(texto) {
  texto = texto.trim();
  if (!texto || enviando) return;
  enviando = true; $("enviar").disabled = true;
  agregar("cliente", texto);
  $("texto").value = ""; ajustar();
  const espera = agregar("asistente", "");
  espera.innerHTML = '<span class="escribiendo" aria-label="Escribiendo"><i></i><i></i><i></i></span>';
  try {
    const r = await fetch(`/corredores/${CORREDOR}/seguros/${actual.id}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje: texto, conversacion }),
    });
    const datos = await r.json();
    espera.remove();
    if (r.status === 401) { pedirSesion("Tu sesión venció. Vuelve a ingresar."); return; }
    if (!r.ok) throw new Error(typeof datos.detail === "string" ? datos.detail : "No pude enviar el mensaje.");
    conversacion = datos.conversacion; guardar(claveConv(), conversacion);
    const meta = `traza ${datos.trace_id} · ${datos.duracion_s.toLocaleString("es-CL")} s · ${datos.tokens.toLocaleString("es-CL")} tokens · etapa ${datos.etapa}` +
      (datos.estado === "bloqueado" ? ` · bloqueada (${datos.categoria})` : "");
    agregar("asistente", datos.respuesta, { meta, clase: datos.estado === "bloqueado" ? "bloqueado" : "" });
    pintarEtapa(datos.etapa, datos.numero);
  } catch (e) {
    espera.remove();
    agregar("asistente", e.message || "No pude conectarme con el servidor.", { clase: "error" });
  } finally {
    enviando = false; $("enviar").disabled = false; $("texto").focus();
  }
}

function ajustar() { const t = $("texto"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; }

$("formulario").onsubmit = (e) => { e.preventDefault(); enviar($("texto").value); };
$("texto").addEventListener("input", ajustar);
$("texto").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar($("texto").value); } });
$("selector").onchange = (e) => elegir(e.target.value);
$("detalles").onchange = (e) => { document.querySelectorAll(".meta").forEach((m) => m.classList.toggle("oculto", !e.target.checked)); guardar("detalles", e.target.checked ? "1" : null); };
$("nueva").onclick = () => { guardar(claveConv(), null); elegir(actual.id); };
$("detalles").checked = leer("detalles") === "1";

// --- Sesión (microservicio de usuarios: /usuarios/...) ---------------------------------
// La cookie de sesión es HttpOnly: este código no la ve; solo pregunta /usuarios/yo.
let modo = "entrar";

function pedirSesion(aviso = "") {
  $("acceso").classList.remove("oculto");
  document.querySelector(".app").classList.add("oculto");
  ["usuario", "salir", "nueva"].forEach((id) => $(id).classList.add("oculto"));
  $("acceso-error").textContent = aviso;
  $("acceso-correo").focus();
}

function cambiarModo(nuevo) {
  modo = nuevo;
  $("tab-entrar").setAttribute("aria-selected", modo === "entrar");
  $("tab-registro").setAttribute("aria-selected", modo === "registro");
  $("campo-nombre").classList.toggle("oculto", modo !== "registro");
  $("acceso-contrasena").autocomplete = modo === "registro" ? "new-password" : "current-password";
  $("acceso-enviar").textContent = modo === "registro" ? "Crear cuenta" : "Iniciar sesión";
  $("acceso-error").textContent = "";
}

const detalle = (datos, codigo) => typeof datos?.detail === "string" ? datos.detail
  : codigo === 422 ? "Revisa los datos: un correo válido y una contraseña de al menos 8 caracteres."
  : "No pude conectarme con el servidor.";

async function postear(url, cuerpo) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(detalle(datos, r.status));
  return datos;
}

$("tab-entrar").onclick = () => cambiarModo("entrar");
$("tab-registro").onclick = () => cambiarModo("registro");
$("form-acceso").onsubmit = async (e) => {
  e.preventDefault();
  const correo = $("acceso-correo").value.trim(), contrasena = $("acceso-contrasena").value;
  $("acceso-enviar").disabled = true; $("acceso-error").textContent = "";
  try {
    if (modo === "registro") await postear("/usuarios/registro", { correo, nombre: $("acceso-nombre").value.trim(), contrasena });
    await postear("/usuarios/login", { correo, contrasena });
    location.reload();
  } catch (error) { $("acceso-error").textContent = error.message; }
  finally { $("acceso-enviar").disabled = false; }
};
$("salir").onclick = async () => { await fetch("/usuarios/logout", { method: "POST" }).catch(() => {}); location.reload(); };

async function revisarSesion() {
  try {
    const r = await fetch("/usuarios/yo");
    if (r.status === 401) { pedirSesion(); return false; }
    if (r.ok) {
      const yo = await r.json();
      $("usuario").textContent = yo.rol === "corredor" ? `${yo.nombre} (corredor)` : yo.nombre;
      ["usuario", "salir"].forEach((id) => $(id).classList.remove("oculto"));
    }
  } catch {}  // sin servicio de usuarios (otra configuración): el chat sigue como antes
  return true;
}

(async () => {
  if (!(await revisarSesion())) return;
  try {
    const r = await fetch(`/corredores/${CORREDOR}/seguros`);
    if (!r.ok) throw new Error();
    seguros = await r.json();
  } catch { $("titulo").textContent = "No se pudo cargar la lista de seguros."; return; }
  $("seguros").innerHTML = seguros.map((s) => `<button class="seguro" type="button" data-id="${escapar(s.id)}"><strong>${escapar(s.nombre)}</strong><span>${escapar(s.descripcion)}</span></button>`).join("");
  $("selector").innerHTML = seguros.map((s) => `<option value="${escapar(s.id)}">${escapar(s.nombre)}</option>`).join("");
  document.querySelectorAll(".seguro").forEach((b) => b.onclick = () => elegir(b.dataset.id));
  elegir(leer(`seguro:${CORREDOR}`));
})();
