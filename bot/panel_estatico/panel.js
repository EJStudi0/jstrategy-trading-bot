"use strict";
// Panel del bot. Todo lo que viene del servidor se pinta con textContent:
// nunca se interpreta como HTML.

const CLAVE = "bot_jorge_token";
const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";

const fmtEntero = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0, useGrouping: "always" });
const fmtDinero = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: "always" });
const fmtDia = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
const fmtMomento = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });

const EXPLICA = {
  auto: "El bot decide: sigue la tendencia y cubre la parte de la base que haga falta.",
  pausa: "No opera. Las posiciones se quedan exactamente como están.",
  neutral: "Toda la base está cubierta: el precio ya no mueve el patrimonio, y no se ha vendido nada.",
  fuera: "Todo en USDT: base vendida y coberturas cerradas.",
};

let token = null;
let puntos = [];

// ── acceso ────────────────────────────────────────────────────────────────────

function leerToken() {
  // Se admite en el fragmento (#token=…) o, por los enlaces antiguos, en ?token=…
  const frag = new URLSearchParams(location.hash.replace(/^#/, ""));
  const consulta = new URLSearchParams(location.search);
  const dado = frag.get("token") || consulta.get("token");
  if (dado) {
    try { localStorage.setItem(CLAVE, dado); } catch (e) { /* modo privado */ }
    history.replaceState(null, "", location.pathname);   // fuera de la barra y del historial
    return dado;
  }
  try { return localStorage.getItem(CLAVE); } catch (e) { return null; }
}

function pedirToken(mensaje) {
  $("panel").hidden = true;
  $("acceso").hidden = false;
  $("acceso-error").textContent = mensaje || "";
  $("campo-token").focus();
}

async function api(ruta, cuerpo) {
  const opciones = { headers: { Authorization: "Bearer " + token }, cache: "no-store" };
  if (cuerpo !== undefined) {
    opciones.method = "POST";
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo);
  }
  const r = await fetch(ruta, opciones);
  if (r.status === 401) {
    try { localStorage.removeItem(CLAVE); } catch (e) { /* nada */ }
    token = null;
    pedirToken("El token no es correcto.");
    throw new Error("401");
  }
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || ("Error " + r.status));
  return datos;
}

// ── utilidades de pintado ─────────────────────────────────────────────────────

function pct(x, decimales) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return (x * 100).toFixed(decimales === undefined ? 0 : decimales).replace(".", ",") + " %";
}
function conSigno(x, texto) { return (x > 0 ? "+" : x < 0 ? "−" : "") + texto; }
function celda(fila, texto, clase) {
  const td = document.createElement("td");
  td.textContent = texto;
  if (clase) td.className = clase;
  fila.appendChild(td);
  return td;
}
function precio(x) {
  if (!x) return "—";
  const decimales = x >= 1000 ? 0 : x >= 10 ? 2 : 4;
  return new Intl.NumberFormat("es-ES", { minimumFractionDigits: decimales, maximumFractionDigits: decimales, useGrouping: "always" }).format(x);
}

// ── estado ────────────────────────────────────────────────────────────────────

function pintarEstado(e) {
  $("patrimonio").textContent = fmtDinero.format(e.patrimonio);
  const g = $("ganancia");
  const flecha = e.ganancia > 0 ? "▲ " : e.ganancia < 0 ? "▼ " : "";
  g.textContent = flecha + conSigno(e.ganancia, fmtDinero.format(Math.abs(e.ganancia))) + " USDT (" +
    conSigno(e.ganancia_pct, Math.abs(e.ganancia_pct).toFixed(2).replace(".", ",")) + " %) desde el inicio";
  g.dataset.signo = e.ganancia > 0 ? "sube" : e.ganancia < 0 ? "baja" : "";

  const base = e.exposicion_base || 0;
  const cubierto = base > 0 ? Math.max(0, 1 - e.exposicion_neta / base) : 0;
  $("f-neto").textContent = pct(e.exposicion_neta);
  $("f-base").textContent = pct(base);
  $("f-cubierto").textContent = base > 0 ? pct(cubierto) : "—";
  $("f-usdt").textContent = fmtEntero.format(e.usdt);
  $("f-financiacion").textContent = conSigno(e.financiacion, fmtDinero.format(Math.abs(e.financiacion)));
  $("f-comisiones").textContent = fmtDinero.format(e.comisiones);

  const s = $("salud");
  const textos = { ok: "Datos al día", viejo: "Datos con retraso", ciego: "Sin datos del mercado", arrancando: "Arrancando" };
  s.dataset.estado = e.salud.estado;
  s.textContent = (textos[e.salud.estado] || e.salud.estado) + (e.salud.mercado ? " · " + e.salud.mercado : "");

  document.querySelectorAll(".mando").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mando === e.mando)));
  $("mando-explica").textContent = EXPLICA[e.mando] || "";

  const cuerpo = document.querySelector("#tabla-monedas tbody");
  cuerpo.replaceChildren();
  for (const m of e.monedas) {
    const tr = document.createElement("tr");
    celda(tr, m.simbolo.replace(/USDT$/, ""), "moneda");
    const td = document.createElement("td");
    td.appendChild(medidor(m.puntuacion));
    tr.appendChild(td);
    celda(tr, pct(m.base, 1), "num solo-ancho");
    celda(tr, m.base > 0 ? pct(Math.max(0, m.cobertura / m.base)) : "—", "num");
    celda(tr, pct(m.neto, 1), "num");
    celda(tr, precio(m.precio), "num precio");
    cuerpo.appendChild(tr);
  }

  const d = e.decision || {};
  $("decision").textContent = d.utc
    ? "Última decisión: " + fmtMomento.format(new Date(d.utc)) + " UTC · " + (d.operaciones || 0) +
      " operaciones · riesgo previsto de la cartera " + pct(d.vol_prevista) + " anual"
    : "Aún no ha decidido: está esperando datos.";

  pintarAjustes(e);
  const avisos = e.avisos || [];
  $("avisos").hidden = avisos.length === 0;
  const lista = $("lista-avisos");
  lista.replaceChildren();
  for (const a of avisos) {
    const li = document.createElement("li");
    li.textContent = fmtMomento.format(new Date(a.utc)) + " — " + a.texto;
    lista.appendChild(li);
  }
  $("actualizado").textContent = "Actualizado " + new Date().toLocaleTimeString("es-ES");
}

function medidor(valor) {
  const caja = document.createElement("div");
  caja.className = "medidor";
  const pista = document.createElement("div");
  pista.className = "pista";
  const numero = document.createElement("span");
  numero.className = "numero";
  if (valor === null || valor === undefined) {
    numero.textContent = "—";
  } else {
    const barra = document.createElement("div");
    barra.className = "barra " + (valor >= 0 ? "pos" : "neg");
    barra.style.width = (Math.min(1, Math.abs(valor)) * 50).toFixed(1) + "%";
    pista.appendChild(barra);
    numero.textContent = conSigno(valor, Math.abs(valor).toFixed(2).replace(".", ","));
    caja.title = valor > 0.33 ? "Alcista" : valor < -0.33 ? "Bajista" : "Sin tendencia clara";
  }
  caja.append(pista, numero);
  return caja;
}

// ── ajustes ───────────────────────────────────────────────────────────────────

let ajustesPintados = false;
function pintarAjustes(e) {
  if (ajustesPintados) return;      // no pisar lo que el usuario está moviendo
  ajustesPintados = true;
  const form = $("form-ajustes");
  form.replaceChildren();
  for (const [clave, lim] of Object.entries(e.ajustables)) {
    const caja = document.createElement("div");
    caja.className = "ajuste";
    const etiqueta = document.createElement("label");
    etiqueta.htmlFor = "aj-" + clave;
    const nombre = document.createElement("span");
    nombre.textContent = lim.etiqueta;
    const salida = document.createElement("output");
    etiqueta.append(nombre, salida);
    const control = document.createElement("input");
    control.type = "range";
    control.id = "aj-" + clave;
    control.name = clave;
    control.min = lim.min; control.max = lim.max; control.step = lim.paso;
    control.value = e.ajustes[clave];
    const mostrar = () => {
      const v = Number(control.value);
      salida.textContent = lim.formato === "x" ? "×" + v.toFixed(2).replace(".", ",") : pct(v);
    };
    control.addEventListener("input", mostrar);
    mostrar();
    caja.append(etiqueta, control);
    form.appendChild(caja);
  }
  const boton = document.createElement("button");
  boton.type = "submit";
  boton.className = "boton";
  boton.textContent = "Guardar el riesgo";
  form.appendChild(boton);
}

$("form-ajustes").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cambios = {};
  for (const c of ev.target.querySelectorAll("input[type=range]")) cambios[c.name] = Number(c.value);
  const estado = $("ajustes-estado");
  try {
    await api("/api/ajustes", cambios);
    estado.textContent = "Guardado. Se aplica en la próxima decisión (cada 4 horas).";
  } catch (e) {
    if (e.message !== "401") estado.textContent = "No se guardó: " + e.message;
  }
});

// ── mando ─────────────────────────────────────────────────────────────────────

document.querySelectorAll(".mando").forEach((b) => b.addEventListener("click", async () => {
  const pedido = b.dataset.mando;
  const error = $("mando-error");
  error.textContent = "";
  try {
    let r = await api("/api/mando", { mando: pedido });
    if (r.confirmar) {
      if (!confirm("Salir a USDT vende TODA la base y cierra las coberturas ahora. ¿Seguro?")) return;
      r = await api("/api/mando", { mando: pedido, confirmacion: r.confirmar });
    }
    await refrescar(true);
  } catch (e) {
    if (e.message !== "401") error.textContent = "No se pudo: " + e.message;
  }
}));

// ── operaciones ───────────────────────────────────────────────────────────────

function pintarOperaciones(filas) {
  const cuerpo = document.querySelector("#tabla-operaciones tbody");
  cuerpo.replaceChildren();
  $("sin-operaciones").hidden = filas.length > 0;
  const motivos = { vela: "Decisión de la vela", mando_neutral: "Cubrir todo", mando_fuera: "Salir a USDT",
                    mando_auto: "Vuelta a automático", reponer_garantia: "Reponer garantía" };
  for (const f of filas) {
    const tr = document.createElement("tr");
    celda(tr, fmtMomento.format(new Date(f.utc)), "suave");
    celda(tr, String(f.simbolo).replace(/USDT$/, ""), "moneda");
    const que = f.pata === "contado"
      ? (f.lado === "compra" ? "Compra base" : "Vende base")
      : (f.lado === "venta" ? "Sube cobertura" : "Baja cobertura");
    celda(tr, que);
    celda(tr, fmtDinero.format(Number(f.nocional)), "num");
    celda(tr, precio(Number(f.precio)), "num solo-ancho");
    celda(tr, motivos[f.motivo] || f.motivo, "suave solo-ancho");
    cuerpo.appendChild(tr);
  }
}

// ── gráfica del patrimonio ────────────────────────────────────────────────────

function nodo(nombre, atributos) {
  const n = document.createElementNS(SVG, nombre);
  for (const [k, v] of Object.entries(atributos || {})) n.setAttribute(k, v);
  return n;
}

function marcasLimpias(min, max, cuantas) {
  const bruto = (max - min) / cuantas;
  const potencia = Math.pow(10, Math.floor(Math.log10(bruto)));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) || potencia * 10;
  const marcas = [];
  for (let v = Math.ceil(min / paso) * paso; v <= max + 1e-9; v += paso) marcas.push(v);
  return marcas;
}

function dibujarGrafica() {
  const caja = $("grafica");
  caja.replaceChildren();
  if (puntos.length < 2) {
    const p = document.createElement("p");
    p.className = "vacia";
    p.textContent = "La curva aparece cuando haya un par de horas de historia.";
    caja.appendChild(p);
    return;
  }
  const W = Math.max(280, caja.clientWidth), H = 220;
  const m = { izq: 8, der: 62, arr: 14, aba: 24 };
  const xs = puntos.map((p) => Date.parse(p.utc));
  const ys = puntos.map((p) => p.patrimonio);
  let yMin = Math.min(...ys), yMax = Math.max(...ys);
  const holgura = Math.max((yMax - yMin) * 0.15, yMax * 0.002);
  yMin -= holgura; yMax += holgura;
  const X = (t) => m.izq + (t - xs[0]) / Math.max(1, xs[xs.length - 1] - xs[0]) * (W - m.izq - m.der);
  const Y = (v) => m.arr + (yMax - v) / (yMax - yMin) * (H - m.arr - m.aba);

  const svg = nodo("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: "0",
    "aria-label": `Patrimonio de ${fmtDinero.format(ys[0])} a ${fmtDinero.format(ys[ys.length - 1])} USDT. Flechas izquierda y derecha para recorrerlo.` });

  for (const v of marcasLimpias(yMin, yMax, 3)) {
    svg.appendChild(nodo("line", { class: "rejilla", x1: m.izq, x2: W - m.der, y1: Y(v), y2: Y(v) }));
    const t = nodo("text", { class: "marca", x: W - m.der + 8, y: Y(v) + 4 });
    t.textContent = fmtEntero.format(v);
    svg.appendChild(t);
  }
  svg.appendChild(nodo("line", { class: "base", x1: m.izq, x2: W - m.der, y1: H - m.aba, y2: H - m.aba }));
  const nMarcas = W < 480 ? 3 : 5;
  for (let i = 0; i < nMarcas; i++) {
    const t0 = xs[0] + (xs[xs.length - 1] - xs[0]) * i / (nMarcas - 1);
    const t = nodo("text", { class: "marca", x: X(t0), y: H - 6,
      "text-anchor": i === 0 ? "start" : i === nMarcas - 1 ? "end" : "middle" });
    t.textContent = fmtDia.format(new Date(t0));
    svg.appendChild(t);
  }

  const trazo = xs.map((x, i) => (i ? "L" : "M") + X(x).toFixed(1) + " " + Y(ys[i]).toFixed(1)).join(" ");
  svg.appendChild(nodo("path", { class: "area", d: `${trazo} L${X(xs[xs.length - 1]).toFixed(1)} ${H - m.aba} L${X(xs[0]).toFixed(1)} ${H - m.aba} Z` }));
  svg.appendChild(nodo("path", { class: "linea", d: trazo }));

  const fin = xs.length - 1;
  svg.appendChild(nodo("circle", { class: "punto", cx: X(xs[fin]), cy: Y(ys[fin]), r: 4 }));

  // Capa de lectura: una mira vertical que salta al punto más cercano.
  const mira = nodo("line", { class: "mira", y1: m.arr, y2: H - m.aba, visibility: "hidden" });
  const foco = nodo("circle", { class: "punto", r: 4, visibility: "hidden" });
  svg.append(mira, foco);
  const globo = document.createElement("div");
  globo.className = "globo";
  globo.hidden = true;
  let actual = fin;

  function mostrar(i) {
    actual = Math.max(0, Math.min(fin, i));
    const x = X(xs[actual]), y = Y(ys[actual]);
    mira.setAttribute("x1", x); mira.setAttribute("x2", x); mira.setAttribute("visibility", "visible");
    foco.setAttribute("cx", x); foco.setAttribute("cy", y); foco.setAttribute("visibility", "visible");
    globo.replaceChildren();
    const valor = document.createElement("strong");
    valor.textContent = fmtDinero.format(ys[actual]) + " USDT";
    const pie = document.createElement("span");
    const clave = document.createElement("span");
    clave.className = "clave";
    pie.append(clave, document.createTextNode(fmtMomento.format(new Date(xs[actual])) + " UTC · expuesto " + pct(puntos[actual].neto)));
    globo.append(valor, pie);
    globo.hidden = false;
    const escala = caja.clientWidth / W;
    const ancho = globo.offsetWidth;
    let izq = x * escala + 12;
    if (izq + ancho > caja.clientWidth) izq = x * escala - ancho - 12;
    globo.style.transform = `translate(${Math.max(0, izq)}px, ${Math.max(0, y * escala - 46)}px)`;
  }
  function ocultar() {
    mira.setAttribute("visibility", "hidden");
    foco.setAttribute("visibility", "hidden");
    globo.hidden = true;
  }
  function masCercano(clientX) {
    const r = svg.getBoundingClientRect();
    const x = (clientX - r.left) / r.width * W;
    let mejor = 0, dist = Infinity;
    for (let i = 0; i <= fin; i++) {
      const d = Math.abs(X(xs[i]) - x);
      if (d < dist) { dist = d; mejor = i; }
    }
    return mejor;
  }
  svg.addEventListener("pointermove", (ev) => mostrar(masCercano(ev.clientX)));
  svg.addEventListener("pointerleave", ocultar);
  svg.addEventListener("focus", () => mostrar(actual));
  svg.addEventListener("blur", ocultar);
  svg.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { mostrar(actual - 1); ev.preventDefault(); }
    else if (ev.key === "ArrowRight") { mostrar(actual + 1); ev.preventDefault(); }
    else if (ev.key === "Escape") { ocultar(); }
  });
  caja.append(svg, globo);
}

function pintarTablaPatrimonio() {
  const cuerpo = document.querySelector("#tabla-patrimonio tbody");
  cuerpo.replaceChildren();
  const porDia = new Map();     // el último valor de cada día
  for (const p of puntos) porDia.set(p.utc.slice(0, 10), p);
  for (const [dia, p] of [...porDia.entries()].reverse().slice(0, 60)) {
    const tr = document.createElement("tr");
    celda(tr, fmtDia.format(new Date(dia + "T00:00:00Z")));
    celda(tr, fmtDinero.format(p.patrimonio), "num");
    celda(tr, pct(p.neto), "num");
    cuerpo.appendChild(tr);
  }
}

// ── ciclo ─────────────────────────────────────────────────────────────────────

let ultimoLento = 0;
async function refrescar(todo) {
  if (!token) return;
  try {
    pintarEstado(await api("/api/estado"));
    $("acceso").hidden = true;
    $("panel").hidden = false;
    if (todo || Date.now() - ultimoLento > 60000) {
      ultimoLento = Date.now();
      const [serie, ops] = await Promise.all([api("/api/patrimonio"), api("/api/operaciones?n=40")]);
      puntos = serie;
      dibujarGrafica();
      pintarTablaPatrimonio();
      pintarOperaciones(ops);
    }
  } catch (e) {
    if (e.message !== "401") {
      const s = $("salud");
      s.dataset.estado = "ciego";
      s.textContent = "El panel no llega al bot";
    }
  }
}

$("form-token").addEventListener("submit", (ev) => {
  ev.preventDefault();
  token = $("campo-token").value.trim();
  $("campo-token").value = "";
  try { localStorage.setItem(CLAVE, token); } catch (e) { /* modo privado */ }
  refrescar(true);
});
$("salir").addEventListener("click", () => {
  try { localStorage.removeItem(CLAVE); } catch (e) { /* nada */ }
  token = null;
  pedirToken("");
});

let redibujo = null;
window.addEventListener("resize", () => { clearTimeout(redibujo); redibujo = setTimeout(dibujarGrafica, 150); });

token = leerToken();
if (token) refrescar(true); else pedirToken("");
setInterval(() => refrescar(false), 15000);
