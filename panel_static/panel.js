"use strict";

/* Panel de control del bot Jorge.
   Sin build step y sin dependencias: el bot es un proceso Python de un solo
   fichero con un único mantenedor, y una toolchain de JS es una cosa más que
   se puede romper cuando nadie la está mirando. */

const $ = (sel) => document.querySelector(sel);
const api = async (ruta, opciones) => {
  const r = await fetch(ruta, Object.assign({ headers: { "Content-Type": "application/json" } }, opciones));
  if (!r.ok) throw new Error(`${ruta} → HTTP ${r.status}`);
  return r.json();
};

const num = (v, dec = 2) =>
  (v === null || v === undefined || Number.isNaN(v)) ? "—"
    : Number(v).toLocaleString("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec });
const firmado = (v, dec = 2) => (v > 0 ? "+" : "") + num(v, dec);

function duracion(segundos) {
  if (segundos === null || segundos === undefined) return "—";
  const s = Math.floor(segundos);
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.floor(s / 60)} min`;
  if (s < 172800) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

const filaPar = (k, v, color) =>
  `<div class="par"><span class="lbl">${k}</span><span class="m" style="font-size:13px;color:${color || "var(--texto)"}">${v}</span></div>`;

/* ── estado en vivo ───────────────────────────────────────────────────── */

function pintarSalud(salud) {
  const caja = $("#salud");
  const estado = salud ? salud.estado : "sin_conexion";
  caja.dataset.estado = estado;

  const etiquetas = {
    ok: "DATOS OK", viejo: "DATOS VIEJOS", ciego: "SIN DATOS",
    sin_datos: "SIN DATOS", arrancando: "ARRANCANDO", sin_conexion: "PANEL SIN CONEXIÓN",
  };
  $("#salud-etiqueta").textContent = etiquetas[estado] || estado.toUpperCase();

  // Un bot que no recibe velas no puede presentarse como sano, y la edad del
  // último dato se enseña SIEMPRE: es la cifra que faltaba durante los 20 días.
  document.body.dataset.datos = (estado === "ok") ? "vivos" : "muertos";

  if (!salud) { $("#salud-detalle").textContent = "sin respuesta del bot"; return; }
  const partes = [`última vela hace ${duracion(salud.edad_segundos)}`];
  if (salud.fallos_seguidos) partes.push(`${salud.fallos_seguidos} fallos seguidos`);
  if (salud.fetches_ok) partes.push(`${salud.fetches_ok} fetches ok`);
  $("#salud-detalle").textContent = partes.join(" · ");
  $("#salud-extra").textContent = salud.ultimo_error && estado !== "ok" ? salud.ultimo_error : "";
}

function pintarEstado(e) {
  pintarSalud(e.salud);

  $("#chip-modo").textContent = e.modo === "real" ? "DINERO REAL" : "PAPER";
  $("#chip-modo").classList.toggle("real", e.modo === "real");
  $("#id-symbol").textContent = e.symbol || "—";
  $("#id-config").textContent = `máx ${e.max_positions} pos · sesión ${e.sesion[0]}:00–${e.sesion[1]}:00 UTC`;
  $("#id-reloj").textContent = (e.ahora_utc || "").replace("T", " ").slice(0, 19) + " UTC";

  const a = e.analisis || {};
  $("#mkt-precio").textContent = a.precio !== undefined ? num(a.precio) : "—";
  $("#mkt-detalle").innerHTML = [
    filaPar("ADX", a.adx !== undefined ? num(a.adx, 1) : "—"),
    filaPar("HTF", a.htf_range_pos !== undefined ? `${num(a.htf_range_pos, 2)} ${a.htf_label || ""}` : "—"),
    filaPar("Killzone", a.killzone || "—"),
    filaPar("Score long", a.score_long !== undefined ? `${a.score_long} / ${a.score_max || 13}` : "—"),
    filaPar("Score short", a.score_short !== undefined ? `${a.score_short} / ${a.score_max || 13}` : "—"),
  ].join("");

  const c = e.capital || {};
  $("#cap-equity").textContent = num(c.equity);
  const perdiendo = (c.variacion || 0) < 0;
  $("#cap-variacion").innerHTML =
    `<span style="color:${perdiendo ? "var(--rojo)" : "var(--verde)"}">${firmado(c.variacion)}</span>` +
    ` <span style="color:var(--texto-3)">· inicial ${num(c.inicial)}</span>`;
  $("#cap-detalle").innerHTML = [
    filaPar("PnL hoy", firmado(c.pnl_hoy), (c.pnl_hoy || 0) < 0 ? "var(--rojo)" : "var(--texto-2)"),
    filaPar("Objetivo diario", `+${num(c.objetivo_diario)}`, "var(--texto-3)"),
    filaPar("Límite diario", `−${num(c.limite_diario)}`, "var(--texto-3)"),
    filaPar("Posiciones", `${(e.posiciones || []).length} / ${e.max_positions}`),
  ].join("");

  const pausado = e.pausado_manual;
  $("#btn-pausa-txt").textContent = pausado ? "REANUDAR" : "PAUSAR APERTURAS";
  $("#btn-pausa").className = "ancho" + (pausado ? " verde" : "");
  $("#btn-pausa").dataset.pausado = pausado ? "1" : "0";

  if (!$("#zona-cierre").dataset.armado) pintarCierreDesarmado();
}

/* ── cierre en dos pasos ──────────────────────────────────────────────── */

function pintarCierreDesarmado() {
  const z = $("#zona-cierre");
  delete z.dataset.armado;
  z.innerHTML = `<button class="ancho peligro" id="btn-armar">CERRAR POSICIONES</button>`;
  $("#btn-armar").onclick = async () => {
    const r = await api("/api/cerrar/armar", { method: "POST" });
    pintarCierreArmado(r);
  };
}

function pintarCierreArmado(r) {
  const z = $("#zona-cierre");
  z.dataset.armado = "1";
  const cuantas = (r.posiciones || []).length;
  z.innerHTML = `
    <div class="confirmacion">
      <div class="m" style="font-size:12px;color:var(--rojo);font-weight:600;margin-bottom:4px">CONFIRMAR CIERRE</div>
      <div class="m" style="font-size:11px;color:#b08286;line-height:1.5;margin-bottom:11px">
        ${cuantas} posición(es) a mercado. Irreversible. Caduca en <span id="cuenta-atras">${r.caduca_en_segundos}</span> s.
      </div>
      <div style="display:flex;gap:8px">
        <button class="peligro-solido" style="flex-grow:1" id="btn-confirmar">CERRAR AHORA</button>
        <button class="fantasma" id="btn-cancelar">CANCELAR</button>
      </div>
    </div>`;

  let quedan = r.caduca_en_segundos;
  const reloj = setInterval(() => {
    quedan -= 1;
    const nodo = $("#cuenta-atras");
    if (!nodo) return clearInterval(reloj);
    nodo.textContent = quedan;
    if (quedan <= 0) { clearInterval(reloj); pintarCierreDesarmado(); }
  }, 1000);

  $("#btn-cancelar").onclick = () => { clearInterval(reloj); pintarCierreDesarmado(); };
  $("#btn-confirmar").onclick = async () => {
    clearInterval(reloj);
    const res = await api("/api/cerrar/confirmar", { method: "POST", body: JSON.stringify({ token: r.token }) });
    alert(res.ok ? `Cerrado: ${res.cerrados.join(", ") || "nada abierto"}` : `Error: ${(res.errores || [res.error]).join(" · ")}`);
    pintarCierreDesarmado();
    refrescarTodo();
  };
}

/* ── puntería ─────────────────────────────────────────────────────────── */

function pintarMetricas(m) {
  const wr = m.win_rate_pct || 0;
  const be = m.breakeven_win_rate_pct || 0;
  const alcanza = wr >= be && be > 0;

  $("#pt-n").textContent = m.closed_trades;
  $("#pt-wr").textContent = num(wr, 1) + "%";
  $("#pt-wr").style.color = alcanza ? "var(--verde)" : "var(--rojo)";
  $("#pt-be").textContent = be ? num(be, 1) + "%" : "—";
  $("#pt-deficit").textContent = be ? `${firmado(wr - be, 1)} pts` : "—";
  $("#pt-deficit").style.color = alcanza ? "var(--verde)" : "var(--rojo)";
  $("#pt-nota").textContent = m.closed_trades < 30
    ? `muestra corta — con ${m.closed_trades} trades un solo resultado mueve la conclusión`
    : "";

  const color = alcanza ? "var(--verde)" : "var(--rojo)";
  $("#pt-escala").innerHTML = `
    <div class="via"></div>
    <div class="deficit" style="left:${Math.min(wr, be)}%;width:${Math.abs(be - wr)}%"></div>
    <div class="logrado" style="width:${wr}%;background:${color}"></div>
    <div class="marca" style="left:${wr}%;background:var(--texto)"></div>
    <div class="marca" style="left:${be}%;background:var(--texto-3)"></div>`;

  const x = m.exits || {};
  const tarjeta = (k, v, col, nota) =>
    `<div class="celda"><div class="lbl" style="margin-bottom:8px">${k}</div>
     <div class="m" style="font-size:20px;color:${col}">${v}</div>
     <div class="m" style="font-size:10px;color:var(--texto-3);margin-top:5px">${nota}</div></div>`;

  $("#kpis").innerHTML = [
    tarjeta("Profit factor", num(m.profit_factor, 2), m.profit_factor >= 1 ? "var(--verde)" : "var(--rojo)",
            m.profit_factor >= 1 ? "gana más de lo que pierde" : `pierde ${num(1 / (m.profit_factor || 1), 2)} por cada 1 ganado`),
    tarjeta("Neto", firmado(m.net_pnl_usdt), m.net_pnl_usdt >= 0 ? "var(--verde)" : "var(--rojo)",
            `USDT · ${m.wins}G / ${m.losses}P`),
    tarjeta("Ratio ganancia/pérdida", num(m.payoff_ratio, 2), m.payoff_ratio >= 1 ? "var(--verde)" : "var(--rojo)",
            `media ${firmado(m.avg_win_usdt)} contra ${num(m.avg_loss_usdt)}`),
    tarjeta("Salidas parciales", `${x.wins || 0}G / ${x.losses || 0}P`, "var(--texto-2)",
            "eventos sueltos — los TP salen a trozos y el stop entero"),
    tarjeta("Sin cierre", String(m.open_unclosed || 0), (m.open_unclosed ? "var(--ambar)" : "var(--texto-2)"),
            "trades abiertos sin salida registrada"),
    tarjeta("Eventos", String(m.total_events), "var(--texto-2)", "filas en el journal"),
  ].join("");
}

/* ── parámetros ───────────────────────────────────────────────────────── */

let paramBase = {}, paramSpec = {}, paramActual = {};

async function cargarParametros() {
  const r = await api("/api/parametros");
  paramSpec = r.spec;
  paramBase = Object.assign({}, r.valores);
  paramActual = Object.assign({}, r.valores);
  pintarParametros();
}

function pintarParametros() {
  const grupos = {};
  for (const [clave, spec] of Object.entries(paramSpec)) (grupos[spec.grupo] ||= []).push([clave, spec]);

  $("#lista-parametros").innerHTML = Object.entries(grupos).map(([grupo, filas]) => `
    <div style="border-bottom:1px solid var(--linea)">
      <div style="padding:15px 24px 8px 24px"><span class="lbl">${grupo}</span></div>
      ${filas.map(([clave, spec]) => {
        const val = paramActual[clave];
        const sucio = Number(val) !== Number(paramBase[clave]);
        return `<div class="param ${sucio ? "sucio" : ""}" data-clave="${clave}">
          <div>
            <div class="m" style="font-size:13px">${spec.etiqueta}</div>
            <div class="m" style="font-size:10px;color:var(--texto-4);margin-top:2px">${clave}${
              sucio ? ` · era ${paramBase[clave]}` : ""}</div>
          </div>
          <div class="stepper">
            <button data-dir="-1">−</button>
            <input type="text" inputmode="decimal" value="${val ?? ""}">
            <button data-dir="1">+</button>
          </div>
          <span class="alcance ${spec.alcance}">${spec.alcance.toUpperCase()}</span>
        </div>`;
      }).join("")}
    </div>`).join("");

  $("#lista-parametros").querySelectorAll(".param").forEach((fila) => {
    const clave = fila.dataset.clave, spec = paramSpec[clave];
    const input = fila.querySelector("input");
    fila.querySelectorAll("button[data-dir]").forEach((b) => {
      b.onclick = () => {
        const paso = Number(spec.paso) * Number(b.dataset.dir);
        const bruto = Number(paramActual[clave] || 0) + paso;
        // Redondeo explícito: sumar 0.5 en coma flotante produce 20.499999…
        const val = Math.min(spec.max, Math.max(spec.min, Math.round(bruto * 1000) / 1000));
        paramActual[clave] = spec.tipo === "int" ? Math.round(val) : val;
        pintarParametros();
      };
    });
    input.onchange = () => {
      const val = Number(input.value);
      if (Number.isNaN(val)) return pintarParametros();
      paramActual[clave] = Math.min(spec.max, Math.max(spec.min, spec.tipo === "int" ? Math.round(val) : val));
      pintarParametros();
    };
  });

  const sucios = Object.keys(paramSpec).filter((k) => Number(paramActual[k]) !== Number(paramBase[k]));
  $("#btn-aplicar").hidden = sucios.length === 0;
  $("#btn-descartar").hidden = sucios.length === 0;
  $("#param-estado").textContent = sucios.length
    ? `${sucios.length} sin aplicar — el bot sigue operando con los valores anteriores`
    : "Sin cambios pendientes — el proceso corre con estos valores";
  $("#param-estado").style.color = sucios.length ? "var(--ambar)" : "var(--texto-3)";
}

/* ── análisis ─────────────────────────────────────────────────────────── */

function pintarEquity(puntos, inicial) {
  const caja = $("#grafico-equity");
  if (!puntos.length) { caja.innerHTML = `<div class="m" style="color:var(--texto-3);padding:20px 0">Sin trades cerrados todavía.</div>`; return; }

  const serie = [inicial].concat(puntos.map((p) => p.equity));
  const W = 880, H = 200, pad = 24;
  const min = Math.min(...serie), max = Math.max(...serie);
  const span = (max - min) || 1;
  const x = (i) => pad + (i * (W - pad * 2)) / Math.max(1, serie.length - 1);
  const y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);

  const linea = serie.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const acaba = serie[serie.length - 1];
  const color = acaba >= inicial ? "#3f9e52" : "#e5484d";

  caja.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;display:block" preserveAspectRatio="none">
      <line x1="${pad}" y1="${y(inicial)}" x2="${W - pad}" y2="${y(inicial)}" stroke="#3c4553" stroke-width="1" stroke-dasharray="3 4"></line>
      <polyline points="${linea}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline>
      ${serie.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="#0a0c0f" stroke="${color}" stroke-width="2"></circle>`).join("")}
      <text x="${pad + 5}" y="${y(inicial) - 7}" fill="#7c8694" font-family="IBM Plex Mono,monospace" font-size="10">${num(inicial)} inicial</text>
      <text x="${W - pad}" y="${y(acaba) + (acaba >= inicial ? -10 : 18)}" fill="${color}" font-family="IBM Plex Mono,monospace" font-size="11" text-anchor="end">${num(acaba)}</text>
    </svg>`;
}

function pintarCortes(cortes) {
  const titulos = { regime: "Por régimen", score: "Por score de entrada", killzone: "Por killzone", side: "Por lado" };
  const umbral = Number(($("#pt-be").textContent || "0").replace("%", "").replace(",", ".")) || 0;

  $("#cortes").innerHTML = Object.entries(titulos).map(([campo, titulo]) => {
    const filas = cortes[campo] || [];
    return `<div class="celda">
      <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px">
        <span class="lbl">${titulo}</span>
        <span class="m" style="font-size:10px;color:var(--texto-4)">umbral ${num(umbral, 1)}%</span>
      </div>
      ${filas.map((f) => {
        const color = f.win_rate_pct >= umbral ? "var(--verde)" : "var(--rojo)";
        return `<div style="margin-bottom:13px">
          <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:4px">
            <span class="m" style="font-size:12px">${f.clave}</span>
            <span style="display:flex;gap:8px;align-items:baseline">
              <span class="m" style="font-size:12px;color:${color}">${num(f.win_rate_pct, 1)}%</span>
              <span class="m" style="font-size:10px;color:${f.muestra_corta ? "var(--ambar)" : "var(--texto-3)"}">n=${f.n}</span>
            </span>
          </div>
          <div class="barra-cortes">
            <div class="relleno-barra" style="width:${f.win_rate_pct}%;background:${color}"></div>
            <div class="umbral" style="left:${umbral}%"></div>
          </div>
          <div class="m" style="font-size:10px;color:var(--texto-4);margin-top:3px">${firmado(f.neto)} USDT</div>
        </div>`;
      }).join("") || `<span class="m" style="font-size:12px;color:var(--texto-3)">sin datos</span>`}
    </div>`;
  }).join("");
}

function pintarTrades(trades) {
  const clase = (ev) => ev.startsWith("hard_stop") ? "stop" : ev.startsWith("lock_exit") ? "lock" : "tp";

  $("#tabla-trades").innerHTML = trades.slice().reverse().map((t) => {
    const abierto = Number(t.tamano_abierto) || 1;
    const tramos = (t.salidas || []).map((ev) => {
      const ancho = Math.max(6, (100 / Math.max(1, (t.salidas || []).length)));
      return `<div class="tramo ${clase(ev)}" style="width:${ancho}%">${ev}</div>`;
    });
    if (!t.cerrado) tramos.push(`<div class="tramo abierto" style="flex-grow:1">sin cerrar</div>`);

    const pnl = t.cerrado ? firmado(t.pnl_usdt) : "—";
    const colorPnl = !t.cerrado ? "var(--texto-4)" : (t.pnl_usdt >= 0 ? "var(--verde)" : "var(--rojo)");
    const score = (t.score === null || t.score === undefined || t.score === "") ? "—" : t.score;

    return `<tr class="${t.cerrado ? "" : "sin-cerrar"}">
      <td class="m">${String(t.abierto_utc || "").replace("T", " ").slice(0, 16)}</td>
      <td class="m" style="color:${t.side === "long" ? "var(--cian)" : "var(--ambar)"}">${String(t.side || "").toUpperCase()}</td>
      <td class="m" style="color:${Number(score) >= 6 ? "var(--verde)" : "var(--rojo)"}">${score}</td>
      <td class="m" style="color:var(--texto-2)">${t.killzone || "—"}</td>
      <td><div class="cascada">${tramos.join("")}</div></td>
      <td class="m" style="text-align:right;font-size:13px;color:${colorPnl}">${pnl}</td>
    </tr>`;
  }).join("");
}

/* ── arranque ─────────────────────────────────────────────────────────── */

async function refrescarTodo() {
  try {
    const [m, t] = await Promise.all([api("/api/metricas"), api("/api/trades")]);
    pintarMetricas(m);
    pintarEquity(t.equity || [], (t.equity && t.equity.length) ? t.equity[0].equity - t.equity[0].pnl : 0);
    pintarCortes(t.cortes || {});
    pintarTrades(t.trades || []);
  } catch (e) {
    console.error("refresco fallido", e);
  }
}

document.querySelectorAll(".pestanas button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".pestanas button").forEach((o) => o.setAttribute("aria-selected", String(o === b)));
    document.querySelectorAll(".vista").forEach((v) => { v.hidden = v.id !== b.dataset.vista; });
  };
});

$("#btn-pausa").onclick = async () => {
  const pausado = $("#btn-pausa").dataset.pausado === "1";
  pintarEstado(Object.assign(await api("/api/pausa", { method: "POST", body: JSON.stringify({ pausado: !pausado }) }),
                             await api("/api/estado")));
};
$("#btn-aplicar").onclick = async () => {
  const cambios = {};
  for (const k of Object.keys(paramSpec)) if (Number(paramActual[k]) !== Number(paramBase[k])) cambios[k] = paramActual[k];
  const r = await api("/api/parametros", { method: "POST", body: JSON.stringify({ cambios }) });
  if (Object.keys(r.rechazados || {}).length) alert("Rechazados:\n" + JSON.stringify(r.rechazados, null, 2));
  await cargarParametros();
};
$("#btn-descartar").onclick = () => { paramActual = Object.assign({}, paramBase); pintarParametros(); };

// SSE: el bot empuja su estado. Si el flujo se cae, la franja lo dice en rojo
// en vez de quedarse enseñando la última foto como si siguiera viva.
function conectarFlujo() {
  const flujo = new EventSource("/api/stream");
  flujo.onmessage = (ev) => { try { pintarEstado(JSON.parse(ev.data)); } catch (e) { console.error(e); } };
  flujo.onerror = () => { pintarSalud(null); flujo.close(); setTimeout(conectarFlujo, 5000); };
}

api("/api/estado").then(pintarEstado).catch(() => pintarSalud(null));
cargarParametros();
refrescarTodo();
conectarFlujo();
setInterval(refrescarTodo, 60000);
