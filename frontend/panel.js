const $ = (id) => document.getElementById(id);
const num = (n, d = 0) => Number(n).toLocaleString("es-CL", { maximumFractionDigits: d, minimumFractionDigits: d });
const escapar = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NOMBRES = {
  consulta: "Consulta", recopilando: "Recopilando datos", confirmando: "Esperando confirmación", registrada: "Registrada",
  modelo: "Modelo (Groq)", validacion_entrada: "Filtros de entrada", seudonimizacion: "Seudonimización", validacion_salida: "Revisión de salida",
  injection: "Prompt injection", fraude: "Fraude al seguro", datos_terceros: "Datos de terceros", limite_tasa: "Límite por minuto", tope_diario: "Tope diario", cupo_ip: "Cupo por persona", espera_publico: "Espera del público", fuga_instrucciones: "Fuga de instrucciones",
  muy_larga: "Mensaje muy largo", vacia: "Mensaje vacío",
};
const nombre = (k) => NOMBRES[k] || k;
let datos = null;

// --- Tooltip compartido -------------------------------------------------------------
function mostrar(html, x, y) {
  const t = $("tooltip");
  t.innerHTML = html; t.classList.remove("oculto");
  const r = t.getBoundingClientRect();
  t.style.left = Math.min(x + 14, innerWidth - r.width - 8) + "px";
  t.style.top = Math.max(8, y - r.height - 12) + "px";
}
const ocultar = () => $("tooltip").classList.add("oculto");

// --- KPI ------------------------------------------------------------------------------
function kpis(t) {
  const reg = t.embudo ? t.embudo.registrada : 0;
  const tiles = [
    ["Preguntas", num(t.preguntas), `${num(t.conversaciones)} conversaciones`],
    ["Latencia p50", `${num(t.latencia_p50_s, 1)} s`, "la mitad responde en menos"],
    ["Latencia p95", `${num(t.latencia_p95_s, 1)} s`, `máxima ${num(t.latencia_max_s, 1)} s`],
    ["Tasa de error", `${num(t.tasa_error * 100, 1)}%`, null, t.tasa_error === 0 ? ["var(--bueno)", "Sin errores"] : ["var(--critico)", "Revisar trazas"]],
    ["Bloqueadas por seguridad", num(t.bloqueadas), "no llegaron al modelo"],
    ["Reintentos del modelo", num(t.reintentos_modelo), "cuota por minuto de Groq (429)"],
    ["Tokens por pregunta", num(t.tokens_entrada_prom + t.tokens_salida_prom), `${num(t.llamadas_modelo_prom, 1)} llamadas al modelo`],
    ["Solicitudes registradas", num(reg), "conversaciones que llegaron al final"],
  ];
  $("kpis").innerHTML = tiles.map(([e, v, n, s]) => `<div class="tarjeta kpi"><div class="etiqueta">${e}</div><div class="valor">${v}</div>` +
    (s ? `<div class="estado"><i style="background:${s[0]}"></i>${s[1]}</div>` : `<div class="nota">${n}</div>`) + "</div>").join("");
}

// --- Barras horizontales (un solo tono: miden una cantidad, no distinguen series) -------
function barras(id, pares, unidad = "", ordenar = true) {
  const caja = $(id);
  const filas = Object.entries(pares || {}).filter(([, v]) => v > 0 || !ordenar);
  if (ordenar) filas.sort((a, b) => b[1] - a[1]);
  if (!filas.length || filas.every(([, v]) => !v)) { caja.innerHTML = '<div class="vacio">Sin datos todavía.</div>'; return; }
  const max = Math.max(...filas.map(([, v]) => v));
  caja.innerHTML = `<div class="barras">${filas.map(([k, v]) =>
    `<div class="nombre" title="${escapar(nombre(k))}">${escapar(nombre(k))}</div>
     <div class="pista" data-k="${escapar(nombre(k))}" data-v="${num(v, unidad ? 1 : 0)}${unidad}"><div class="barra" style="width:${max ? (v / max) * 100 : 0}%"></div></div>
     <div class="cifra">${num(v, unidad ? 1 : 0)}${unidad}</div>`).join("")}</div>`;
  caja.querySelectorAll(".pista").forEach((p) => {
    p.onmousemove = (e) => mostrar(`${p.dataset.k}<br><b>${p.dataset.v}</b>`, e.clientX, e.clientY);
    p.onmouseleave = ocultar;
  });
}

// --- Línea de latencia ---------------------------------------------------------------------
function latencia(serie, p95) {
  const caja = $("latencia");
  if (!serie.length) { caja.innerHTML = '<div class="vacio">Sin preguntas todavía.</div>'; return; }
  const W = Math.max(caja.clientWidth, 300), H = 240, m = { t: 12, r: 16, b: 28, l: 40 };
  const ancho = W - m.l - m.r, alto = H - m.t - m.b;
  const maxY = Math.max(5, Math.ceil(Math.max(...serie.map((d) => d.duracion_s), p95) / 5) * 5);
  const x = (i) => m.l + (serie.length === 1 ? ancho / 2 : (i / (serie.length - 1)) * ancho);
  const y = (v) => m.t + alto - (v / maxY) * alto;
  const ticks = [0, 1, 2, 3, 4].map((i) => (maxY / 4) * i);
  const hora = (f) => new Date(f).toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const camino = serie.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.duracion_s).toFixed(1)}`).join("");
  // Con muchas preguntas, solo se dibujan como punto las que tuvieron reintentos.
  const puntos = serie.map((d, i) => (serie.length <= 60 || d.reintentos) ?
    `<circle cx="${x(i)}" cy="${y(d.duracion_s)}" r="4" class="punto${d.reintentos ? " reintento" : ""}"/>` : "").join("");
  caja.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Latencia de ${serie.length} preguntas; p95 ${num(p95, 1)} segundos">
    ${ticks.map((v) => `<line class="linea-grilla" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${num(v)} s</text>`).join("")}
    <line class="linea-base" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>
    <line class="referencia" x1="${m.l}" x2="${W - m.r}" y1="${y(p95)}" y2="${y(p95)}"/>
    <text x="${W - m.r}" y="${y(p95) - 5}" text-anchor="end">p95 ${num(p95, 1)} s</text>
    <path class="serie" d="${camino}"/>${puntos}
    <text x="${m.l}" y="${H - 8}">${hora(serie[0].fecha)}</text>
    <text x="${W - m.r}" y="${H - 8}" text-anchor="end">${hora(serie[serie.length - 1].fecha)}</text>
    <line class="cruz oculto" id="cruz" y1="${m.t}" y2="${y(0)}"/>
    <rect id="zona" x="${m.l}" y="${m.t}" width="${ancho}" height="${alto}" fill="transparent"/>
  </svg>`;
  const zona = caja.querySelector("#zona"), cruz = caja.querySelector("#cruz");
  zona.onmousemove = (e) => {
    const r = zona.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (serie.length - 1));
    const d = serie[Math.max(0, Math.min(serie.length - 1, i))];
    cruz.setAttribute("x1", x(serie.indexOf(d))); cruz.setAttribute("x2", x(serie.indexOf(d)));
    cruz.classList.remove("oculto");
    mostrar(`${hora(d.fecha)} · ${escapar(d.seguro)}<br>Latencia <b>${num(d.duracion_s, 1)} s</b> · ${num(d.tokens)} tokens<br>` +
      `${d.llamadas_modelo} llamadas al modelo${d.reintentos ? `, <b>${d.reintentos} reintentos</b>` : ""}<br>` +
      `${d.estado === "bloqueado" ? "Bloqueada por seguridad" : "Etapa: " + escapar(nombre(d.etapa || "consulta"))}` +
      (d.herramientas.length ? `<br>${d.herramientas.map(escapar).join(", ")}` : ""), e.clientX, e.clientY);
  };
  zona.onmouseleave = () => { cruz.classList.add("oculto"); ocultar(); };
}

// --- Tabla por seguro ----------------------------------------------------------------------
function tabla(porSeguro) {
  const filas = Object.entries(porSeguro);
  if (!filas.length) { $("tabla").innerHTML = '<div class="vacio">Sin datos todavía.</div>'; return; }
  $("tabla").innerHTML = `<table><thead><tr><th>Seguro</th><th>Preguntas</th><th>p50</th><th>p95</th><th>Tokens</th><th>Reintentos</th><th>Error</th><th>Bloqueadas</th><th>Registradas</th></tr></thead><tbody>
    ${filas.map(([s, r]) => `<tr><td>${escapar(s)}</td><td>${num(r.preguntas)}</td><td>${num(r.latencia_p50_s, 1)} s</td><td>${num(r.latencia_p95_s, 1)} s</td>
      <td>${num(r.tokens_entrada_prom + r.tokens_salida_prom)}</td><td>${num(r.reintentos_modelo)}</td><td>${num(r.tasa_error * 100, 1)}%</td>
      <td>${num(r.bloqueadas)}</td><td>${num(r.embudo.registrada)}</td></tr>`).join("")}</tbody></table>`;
}

function pintar() {
  const t = datos.total;
  if (!t.preguntas) {
    $("kpis").innerHTML = '<div class="tarjeta kpi"><div class="etiqueta">Preguntas</div><div class="valor">0</div><div class="nota">Conversa en el chat para generar trazas.</div></div>';
    ["embudo", "herramientas", "tiempo", "bloqueos"].forEach((id) => barras(id, {}));
    latencia([], 0); tabla({}); return;
  }
  kpis(t);
  latencia(datos.serie, t.latencia_p95_s);
  barras("embudo", t.embudo, "", false);
  barras("herramientas", t.uso_herramientas);
  barras("tiempo", t.tiempo_por_etapa_s, " s");
  barras("bloqueos", t.bloqueos_por_categoria);
  tabla(datos.por_seguro);
}

async function cargar() {
  const seguro = $("seguro").value;
  try {
    const r = await fetch("/metricas" + (seguro ? `?seguro=${encodeURIComponent(seguro)}` : ""));
    if (!r.ok) throw new Error();
    datos = await r.json();
    if ($("seguro").options.length === 1 && !seguro) {
      Object.keys(datos.por_seguro).forEach((s) => $("seguro").add(new Option(s, s)));
    }
    pintar();
    $("actualizado").textContent = "Actualizado " + new Date().toLocaleTimeString("es-CL");
  } catch { $("actualizado").textContent = "No se pudieron leer las métricas."; }
}

$("seguro").onchange = cargar;
$("actualizar").onclick = cargar;
setInterval(() => { if ($("auto").checked && !document.hidden) cargar(); }, 15000);
let espera; addEventListener("resize", () => { clearTimeout(espera); espera = setTimeout(() => datos && pintar(), 150); });
cargar();
