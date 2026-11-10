// Panel del bot. Lee el estado con el token en una cabecera (nunca en cookies) y lo pinta.
// Todo lo que viene del servidor se escribe con textContent: nunca se interpreta como HTML.

import * as f from "./formato.js";
import * as g from "./graficas.js";

const CLAVE = "bot_jorge_token";
const PREF = "bot_jorge_pref";
const $ = (id) => document.getElementById(id);
const ZONA = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const VISTAS = { resumen: "Resumen", ganancias: "Ganancias", monedas: "Monedas", mando: "Mando" };
const NOMBRES = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", BNB: "BNB", XRP: "XRP", DOGE: "Dogecoin",
                  ADA: "Cardano", AVAX: "Avalanche", LINK: "Chainlink", LTC: "Litecoin" };
const MANDOS = {
  auto: { nombre: "Automático", confirma: "El bot vuelve a decidir solo: sigue la tendencia y cubre lo que haga falta. Puede operar ahora mismo." },
  pausa: { nombre: "En pausa", confirma: "El bot deja de operar. Las posiciones se quedan exactamente como están." },
  neutral: { nombre: "Todo cubierto", confirma: "Cubre ahora el 100 % de la base sin vender nada. Paga las comisiones de las coberturas que falten." },
  fuera: { nombre: "Fuera, en USDT", confirma: "Vende TODA la base y cierra las coberturas ahora mismo. Para volver a operar, elige Automático." },
};
const MOTIVOS = { vela: "Decisión de la vela", mando_neutral: "Cubrir todo", mando_fuera: "Salir a USDT",
                  mando_auto: "Vuelta a automático", reponer_garantia: "Reponer garantía" };

const datos = { e: null, ganancias: null, curva: [], curvaHoras: null, mercado: null, operaciones: [], recibido: 0 };
const marcas = { lento: 0, curva: 0, mercado: 0 };
const vista = { mesCal: null, diaElegido: null, opsVisibles: 5, ajustesPintados: false, error: false,
                lotesAbiertos: new Set(), lotesCerrados: new Set() };
let token = null;
let pref = leerPref();

// ── preferencias de este aparato ──────────────────────────────────────────────

function leerPref() {
  const base = { vista: "resumen", tema: "auto", horas: 168, vsBtc: false, dias: 30 };
  let guardadas = {};
  try { guardadas = JSON.parse(localStorage.getItem(PREF) || "{}") || {}; } catch (e) { /* modo privado */ }
  const p = { ...base, ...guardadas };
  if (!(p.vista in VISTAS)) p.vista = base.vista;
  if (!["auto", "claro", "oscuro"].includes(p.tema)) p.tema = "auto";
  if (![24, 168, 720, 0].includes(p.horas)) p.horas = base.horas;
  if (![14, 30, 90, 0].includes(p.dias)) p.dias = base.dias;
  p.vsBtc = p.vsBtc === true;
  return p;
}

function guardarPref() {
  try { localStorage.setItem(PREF, JSON.stringify(pref)); } catch (e) { /* modo privado */ }
}

function aplicarTema() {
  if (pref.tema === "auto") delete document.documentElement.dataset.tema;
  else document.documentElement.dataset.tema = pref.tema;
  marcarSegmentado($("tema"), pref.tema);
}

// ── acceso ────────────────────────────────────────────────────────────────────

function leerToken() {
  // Se admite en el fragmento (#token=…, que no viaja al servidor) o, por enlaces antiguos, en ?token=…
  const frag = new URLSearchParams(location.hash.replace(/^#/, ""));
  const consulta = new URLSearchParams(location.search);
  if (frag.get("vista") in VISTAS) pref.vista = frag.get("vista");
  if (["auto", "claro", "oscuro"].includes(frag.get("tema"))) pref.tema = frag.get("tema");
  const dado = frag.get("token") || consulta.get("token");
  if (location.hash || location.search) history.replaceState(null, "", location.pathname);
  if (dado) {
    try { localStorage.setItem(CLAVE, dado); } catch (e) { /* modo privado */ }
    return dado;
  }
  try { return localStorage.getItem(CLAVE); } catch (e) { return null; }
}

function pedirToken(mensaje) {
  $("app").hidden = true;
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
  const respuesta = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(respuesta.detail || "Error " + r.status);
  return respuesta;
}

// ── utilidades de pintado ─────────────────────────────────────────────────────

function poner(id, texto, signo) {
  const n = $(id);
  if (!n) return;
  n.textContent = texto;
  if (signo !== undefined) {
    if (signo) n.dataset.signo = signo; else delete n.dataset.signo;
  }
}

function marcarSegmentado(caja, valor) {
  for (const b of caja.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.valor === String(valor)));
}

function icono(nombre) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icono");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-" + nombre);
  svg.appendChild(use);
  return svg;
}

const base = (s) => String(s).replace(/USDT$/, "");
const ocupada = (caja) => caja.matches(":hover, :focus-within");
const nivelActual = () => (datos.e && datos.e.niveles ? datos.e.niveles[datos.e.nivel] : null);

/** Lo que el nivel ganó de media en la prueba, en dólares al día con el patrimonio de hoy. */
function alDia(pctAnual, patrimonio, dias = 365) {
  return patrimonio * (Math.pow(1 + pctAnual / 100, 1 / dias) - 1);
}

function diasDelAnio(anio, hasta) {
  const fin = String(anio) === hasta.slice(0, 4) ? f.fechaLocal(hasta) : new Date(Number(anio) + 1, 0, 1);
  return Math.round((fin - new Date(Number(anio), 0, 1)) / 864e5);
}

function filasReparto(r) {
  if (!r || !f.valido(r.financiacion)) return [];
  return [
    { valor: f.dinero(r.mercado, { signo: true }), etiqueta: "mercado", suave: true },
    { valor: f.dinero(r.financiacion, { signo: true }), etiqueta: "financiación", suave: true },
    { valor: f.dinero(-r.comisiones, { signo: true }), etiqueta: "comisiones", suave: true },
  ];
}

// ── barra, avisos y pie ───────────────────────────────────────────────────────

function pintarBarra() {
  const e = datos.e;
  const s = $("salud");
  if (vista.error) {
    s.dataset.estado = "ciego";
    s.textContent = "Sin conexión con el bot";
    return;
  }
  if (!e) return;
  const textos = { ok: "Datos al día", viejo: "Datos con retraso", ciego: "Sin datos del mercado", arrancando: "Arrancando" };
  s.dataset.estado = e.salud.estado;
  s.textContent = (textos[e.salud.estado] || e.salud.estado) + (e.salud.mercado ? " · " + e.salud.mercado : "");

  const avisos = e.avisos || [];
  const caja = $("avisos");
  caja.hidden = avisos.length === 0;
  caja.replaceChildren();
  for (const a of avisos.slice().reverse()) {
    const p = g.el("p", "aviso");
    p.append(icono("aviso"), g.el("span", "", a.texto), g.el("time", "", f.cuando(a.utc)));
    caja.appendChild(p);
  }
}

function pintarPie() {
  poner("actualizado", datos.recibido ? "Actualizado " + f.haceCuanto(Date.now() - datos.recibido) : "—");
  poner("zona-pie", "Horas de tu zona (" + ZONA + ")");
}

// ── resumen ───────────────────────────────────────────────────────────────────

function frase(e) {
  if (e.mando === "pausa") return "En pausa: no opera y las posiciones se quedan como están.";
  if (e.mando === "fuera") return "Todo en USDT: sin monedas ni coberturas. Vuelve a Automático para operar.";
  if (e.mando === "neutral") return "Todo cubierto a mano: el precio no mueve tu patrimonio. Lo que gana sale de la financiación de las coberturas.";
  const expuestas = e.monedas.filter((m) => (m.neto || 0) > 0.002);
  if (!expuestas.length) {
    return "Cubierto del todo: ninguna moneda tiene la tendencia a favor. El precio casi no mueve tu patrimonio y lo que gana sale de la financiación de las coberturas.";
  }
  const nombres = expuestas.map((m) => base(m.simbolo)).join(", ");
  return `Expuesto un ${f.pctFraccion(e.exposicion_neta)} al mercado en ${expuestas.length === 1 ? "una moneda" : expuestas.length + " monedas"} con la tendencia a favor (${nombres}). El resto está cubierto.`;
}

function kpi(id, r, sub) {
  if (!r) { poner(id, "—", ""); poner(id + "-sub", sub || ""); return; }
  poner(id, f.dinero(r.ganancia, { signo: true }), f.signoDe(r.ganancia));
  poner(id + "-sub", (f.valido(r.pct) ? f.pct(r.pct, 2, true) : "") + (sub ? " · " + sub : ""));
}

function pintarKpis(prefijo) {
  const gn = datos.ganancias;
  const s = gn ? gn.resumen : null;
  const fin = s && s.hoy && f.valido(s.hoy.financiacion) ? f.dinero(s.hoy.financiacion, { signo: true }) + " de financiación" : "";
  kpi(prefijo + "-hoy", s && s.hoy, fin);
  kpi(prefijo + "-semana", s && s.semana, "desde el lunes");
  kpi(prefijo + "-mes", s && s.mes, s && s.mes ? f.mesLargo(f.fechaLocal(s.mes.clave)).split(" ")[0] : "");
}

function pintarResumen() {
  const e = datos.e;
  if (!e) return;
  const texto = f.cifra(e.patrimonio, 2);
  const coma = texto.lastIndexOf(",");
  poner("pat-entero", coma > 0 ? texto.slice(0, coma) : texto);
  poner("pat-decimales", coma > 0 ? texto.slice(coma) : "");
  const flecha = e.ganancia > 0.005 ? "▲ " : e.ganancia < -0.005 ? "▼ " : "";
  poner("pat-delta", `${flecha}${f.dinero(e.ganancia, { signo: true })} (${f.pct(e.ganancia_pct, 2, true)}) desde el inicio`,
        f.signoDe(e.ganancia));
  const inicio = e.creada_utc ? " el " + f.dia(new Date(e.creada_utc)) : "";
  poner("pat-nota", `Empezó con ${f.dinero(e.capital_inicial)}${inicio}. Mercado real, dinero ficticio.`);
  poner("frase", frase(e));

  pintarKpis("k");
  const s = datos.ganancias && datos.ganancias.resumen;
  if (s && f.valido(s.media_dia)) {
    poner("k-media", f.dinero(s.media_dia, { signo: true }), f.signoDe(s.media_dia));
    const n = s.dias_completos;
    poner("k-media-sub", `${n} ${n === 1 ? "día completo" : "días completos"}` + (n < 7 ? " · aún pocos para fiarse" : ""));
  } else {
    poner("k-media", "—", "");
    poner("k-media-sub", "Hace falta un día completo");
  }

  // Cartera
  const baseFr = Math.max(0, e.exposicion_base || 0);
  const neto = Math.max(0, e.exposicion_neta || 0);
  const expuesta = Math.min(baseFr, neto);
  const cubierta = Math.max(0, baseFr - expuesta);
  const efectivo = Math.max(0, 1 - baseFr);
  const partes = [
    { nombre: "Base cubierta", valor: cubierta, color: "var(--serie-1)" },
    { nombre: "Base expuesta", valor: expuesta, color: "var(--serie-2)" },
    { nombre: "USDT y garantía", valor: efectivo, color: "var(--serie-3)" },
  ];
  g.segmentos($("barra-cartera"), partes);
  const leyenda = $("leyenda-cartera");
  leyenda.replaceChildren();
  for (const p of partes) {
    const li = g.el("li");
    const clave = g.el("span", "clave cuadro");
    clave.style.background = p.color;
    li.append(clave, g.el("span", "", p.nombre), g.el("strong", "", f.dinero(p.valor * e.patrimonio, { decimales: 0 })));
    leyenda.appendChild(li);
  }
  poner("d-neto", f.pctFraccion(e.exposicion_neta, 1));
  poner("d-cubierto", baseFr > 0 ? f.pctFraccion(cubierta / baseFr) : "—");
  poner("d-fin", f.dinero(e.financiacion, { signo: true }), f.signoDe(e.financiacion));
  poner("d-com", f.dinero(e.comisiones));
  poner("d-garantia", f.valido(e.colchon_margen) ? f.pctFraccion(e.colchon_margen) : "—");

  // Próxima decisión
  const n = nivelActual();
  poner("c-modo", (MANDOS[e.mando] || {}).nombre + (e.mando === "auto" ? " · " + (n ? n.nombre : "a medida") : ""));
  pintarCuenta();
}

function pintarCuenta() {
  const e = datos.e;
  if (!e) return;
  const prox = e.proxima_decision_utc ? Date.parse(e.proxima_decision_utc) : null;
  const horas = parseInt(e.intervalo, 10) || 4;
  if (!prox) {
    poner("c-cuenta", "Esperando datos");
    $("c-barra").style.width = "0%";
  } else {
    const falta = prox - Date.now();
    poner("c-cuenta", falta > 0 ? "en " + f.duracion(falta) : "ahora, al llegar la vela");
    const hecho = 1 - Math.max(0, Math.min(1, falta / (horas * 36e5)));
    $("c-barra").style.width = (hecho * 100).toFixed(1) + "%";
  }
  const ultima = e.decision_vela_utc ? f.cuando(e.decision_vela_utc) : null;
  const ops = e.decision && f.valido(e.decision.operaciones) ? ` con ${e.decision.operaciones} ${e.decision.operaciones === 1 ? "operación" : "operaciones"}` : "";
  poner("c-nota", `Decide al cerrar cada vela de ${horas} horas.` + (ultima ? ` La última, ${ultima}${ops}.` : "")
        + (e.mando === "pausa" ? " En pausa no opera aunque toque." : ""));
}

function puntosCurva() {
  const e = datos.e;
  const puntos = datos.curva.map((p) => ({ t: Date.parse(p.utc), v: p.patrimonio, neto: p.neto, btc: p.btc }));
  if (e && f.valido(e.patrimonio)) {
    const btc = e.monedas && e.monedas[0] ? e.monedas[0].precio : null;
    puntos.push({ t: Date.parse(e.utc), v: e.patrimonio, neto: Math.max(0, e.exposicion_neta), btc });
  }
  return puntos.filter((p) => f.valido(p.t)).sort((a, b) => a.t - b.t);
}

function pintarCurva(forzar) {
  const caja = $("grafica-curva");
  if (!forzar && ocupada(caja)) return;
  const puntos = puntosCurva();
  const comparar = pref.vsBtc;
  $("leyenda-curva").hidden = !comparar;
  g.curva(caja, puntos, { modo: comparar ? "comparar" : "valor" });
  const cuerpo = document.querySelector("#tabla-curva tbody");
  cuerpo.replaceChildren();
  for (const p of puntos.slice(-48).reverse()) {
    const tr = document.createElement("tr");
    tr.append(g.el("td", "suave", f.cuando(p.t)), g.el("td", "num", f.dinero(p.v)),
              g.el("td", "num", f.pctFraccion(p.neto, 1)), g.el("td", "num solo-ancho", f.valido(p.btc) ? f.cifra(p.btc, 0) : "—"));
    cuerpo.appendChild(tr);
  }
}

// ── ganancias ─────────────────────────────────────────────────────────────────

function itemDia(r, clave, hoy) {
  const fecha = f.fechaLocal(clave);
  if (!r) return { clave, fecha, valor: null, titulo: f.diaSemanaCorto(fecha), filas: [{ valor: "Sin datos", etiqueta: "" }] };
  return {
    clave, fecha, valor: r.ganancia, parcial: clave === hoy,
    titulo: f.diaSemanaCorto(fecha) + (clave === hoy ? " · hoy, en curso" : ""),
    filas: [{ valor: f.dinero(r.ganancia, { signo: true }), etiqueta: f.pct(r.pct, 2, true),
              clase: f.signoDe(r.ganancia) }, ...filasReparto(r)],
  };
}

function pintarGanancias(forzar) {
  const gn = datos.ganancias;
  const e = datos.e;
  if (!gn || !e) return;
  pintarKpis("g");
  kpi("g-total", gn.resumen.total, "desde el " + f.dia(new Date(gn.inicio_utc)));

  // Barras por día: días seguidos, con hueco donde no hubo datos.
  const porDia = new Map(gn.dias.map((d) => [d.fecha, d]));
  const hoy = gn.hoy_fecha;
  const primero = gn.dias.length ? gn.dias[0].fecha : hoy;
  const claves = [];
  for (let d = f.fechaLocal(primero); f.claveDia(d) <= hoy; d.setDate(d.getDate() + 1)) claves.push(f.claveDia(d));
  const visibles = pref.dias ? claves.slice(-pref.dias) : claves;
  const n = nivelActual();
  const ref = n ? alDia(n.anual_pct, e.patrimonio) : null;
  const caja = $("grafica-dias");
  if (forzar || !ocupada(caja)) {
    g.barras(caja, visibles.map((c) => itemDia(porDia.get(c), c, hoy)), {
      referencia: ref, etiquetaReferencia: ref ? `lo medido ≈ ${f.dinero(ref, { signo: true })}/día` : "",
      nombre: "Ganancia por día",
    });
  }
  poner("dias-nota", "Verde, días que ganó; rojo, días que perdió. La barra de hoy, más clara, sigue abierta."
        + (n ? ` La línea discontinua es lo que el nivel ${n.nombre} ganó de media al día en la prueba, con tu patrimonio de hoy.` : ""));
  const cuerpo = document.querySelector("#tabla-dias tbody");
  cuerpo.replaceChildren();
  for (const d of gn.dias.slice().reverse().slice(0, 120)) {
    const tr = document.createElement("tr");
    tr.append(g.el("td", "", f.diaSemanaCorto(f.fechaLocal(d.fecha))),
              celdaSigno(f.dinero(d.ganancia, { signo: true }), d.ganancia),
              g.el("td", "num suave", f.pct(d.pct, 2, true)),
              g.el("td", "num", f.valido(d.financiacion) ? f.dinero(d.financiacion, { signo: true }) : "—"),
              g.el("td", "num solo-ancho", f.valido(d.comisiones) ? f.dinero(d.comisiones) : "—"),
              g.el("td", "num solo-ancho", f.valido(d.mercado) ? f.dinero(d.mercado, { signo: true }) : "—"));
    cuerpo.appendChild(tr);
  }

  pintarMedido(n, ref);
  pintarCalendario();
  pintarMeses(forzar);
}

function celdaSigno(texto, valor) {
  const td = g.el("td", "num fuerte", texto);
  const s = f.signoDe(valor);
  if (s) td.dataset.signo = s;
  return td;
}

function pintarMedido(n, ref) {
  const e = datos.e;
  const s = datos.ganancias.resumen;
  poner("m-nivel", n ? n.nombre : "A medida");
  if (n) {
    poner("m-medido", f.dinero(ref, { signo: true }), "");
    poner("m-medido-sub", `${f.pct(n.anual_pct, 1, true)} al año · ${n.meses_positivos_pct} % de meses en positivo`);
  } else {
    poner("m-medido", "—", "");
    poner("m-medido-sub", "El riesgo a medida no se midió");
  }
  if (f.valido(s.media_dia)) {
    poner("m-real", f.dinero(s.media_dia, { signo: true }), f.signoDe(s.media_dia));
    poner("m-real-sub", `${s.dias_completos} ${s.dias_completos === 1 ? "día completo" : "días completos"} · ${s.dias_positivos} en positivo`);
  } else {
    poner("m-real", "—", "");
    poner("m-real-sub", "Aún sin días completos");
  }
  const cuerpo = document.querySelector("#tabla-anios tbody");
  cuerpo.replaceChildren();
  const hasta = (e.niveles_periodo && e.niveles_periodo.hasta) || "2026-11-09";
  if (n && n.por_anio) {
    for (const [anio, pctAnio] of Object.entries(n.por_anio)) {
      const tr = document.createElement("tr");
      const parcial = anio === hasta.slice(0, 4);
      tr.append(g.el("td", "", anio + (parcial ? " (hasta " + f.dia(f.fechaLocal(hasta)) + ")" : "")),
                celdaSigno(f.pct(pctAnio, 1, true), pctAnio),
                g.el("td", "num", f.dinero(alDia(pctAnio, e.patrimonio, diasDelAnio(anio, hasta)), { signo: true })));
      cuerpo.appendChild(tr);
    }
  }
  const pocos = s.dias_completos < 30;
  poner("m-nota", (n ? `La media esconde rachas: mira la diferencia entre años. ` : "")
        + (pocos ? "Con menos de un mes de simulación todavía no se puede comparar; lo que vale es que, mes a mes, lo real se parezca a lo medido."
                 : "Lo que vale es que, mes a mes, lo real se parezca a lo medido."));
}

function pintarCalendario() {
  const gn = datos.ganancias;
  if (!gn) return;
  const hoy = gn.hoy_fecha;
  if (!vista.mesCal) vista.mesCal = hoy.slice(0, 7);
  if (!vista.diaElegido) vista.diaElegido = hoy;
  const [anio, mes] = vista.mesCal.split("-").map(Number);
  const porDia = new Map(gn.dias.map((d) => [d.fecha, d]));
  const primerDia = gn.dias.length ? gn.dias[0].fecha : hoy;
  g.calendario($("calendario"), {
    anio, mes: mes - 1, porDia, hoy, primerDia, elegido: vista.diaElegido,
    alElegir: (clave) => { vista.diaElegido = clave; pintarCalendario(); },
  });
  const totalMes = gn.meses.find((m) => m.clave === vista.mesCal);
  const titulo = f.mesLargo(new Date(anio, mes - 1, 1));
  poner("cal-mes", titulo.charAt(0).toUpperCase() + titulo.slice(1));
  $("cal-antes").disabled = vista.mesCal <= primerDia.slice(0, 7);
  $("cal-despues").disabled = vista.mesCal >= hoy.slice(0, 7);

  const det = $("cal-detalle");
  det.replaceChildren();
  const d = porDia.get(vista.diaElegido);
  const fecha = f.fechaLocal(vista.diaElegido);
  const cab = g.el("p", "cal-detalle-cab");
  cab.append(g.el("span", "", f.diaSemana(fecha) + (vista.diaElegido === hoy ? " (hoy)" : "")));
  if (d) {
    const v = g.el("strong", "", f.dinero(d.ganancia, { signo: true }));
    if (f.signoDe(d.ganancia)) v.dataset.signo = f.signoDe(d.ganancia);
    cab.appendChild(v);
  }
  det.appendChild(cab);
  if (d && f.valido(d.financiacion)) {
    det.appendChild(g.el("p", "nota", `Financiación ${f.dinero(d.financiacion, { signo: true })} · comisiones ${f.dinero(-d.comisiones, { signo: true })} · mercado ${f.dinero(d.mercado, { signo: true })}`));
  } else if (!d) {
    det.appendChild(g.el("p", "nota", "Sin datos de ese día."));
  }
  if (totalMes) {
    det.appendChild(g.el("p", "nota", `Todo el mes: ${f.dinero(totalMes.ganancia, { signo: true })} (${f.pct(totalMes.pct, 2, true)}) · ${totalMes.dias_positivos} de ${totalMes.dias} días en positivo`));
  }
  pintarOrigen(totalMes, titulo);
}

function pintarOrigen(m, titulo) {
  const caja = $("origen");
  caja.replaceChildren();
  poner("o-periodo", titulo ? titulo : "");
  if (!m) { caja.appendChild(g.el("p", "vacia", "Sin datos en este mes.")); return; }
  if (!f.valido(m.financiacion)) {
    caja.appendChild(g.el("p", "vacia", "A algún día de este mes le falta el reparto (fotos de antes de guardarlo)."));
    return;
  }
  const partes = [
    { nombre: "Mercado", valor: m.mercado },
    { nombre: "Financiación", valor: m.financiacion },
    { nombre: "Comisiones", valor: -m.comisiones },
  ];
  const tope = Math.max(0.01, ...partes.map((p) => Math.abs(p.valor)), Math.abs(m.ganancia));
  for (const p of [...partes, { nombre: "Total", valor: m.ganancia, total: true }]) {
    const fila = g.el("div", "origen-fila" + (p.total ? " total" : ""));
    const pista = g.el("div", "origen-pista");
    const barra = g.el("div", "origen-barra " + (p.valor >= 0 ? "pos" : "neg"));
    barra.style.width = (Math.abs(p.valor) / tope * 50).toFixed(1) + "%";
    pista.appendChild(barra);
    const v = g.el("strong", "num", f.dinero(p.valor, { signo: true }));
    if (f.signoDe(p.valor)) v.dataset.signo = f.signoDe(p.valor);
    fila.append(g.el("span", "", p.nombre), pista, v);
    caja.appendChild(fila);
  }
}

function pintarMeses(forzar) {
  const gn = datos.ganancias;
  const caja = $("grafica-meses");
  if (forzar || !ocupada(caja)) {
    g.barras(caja, gn.meses.map((m) => {
      const fecha = f.fechaLocal(m.clave + "-01");
      return {
        clave: m.clave, fecha, valor: m.ganancia, parcial: m.clave === gn.hoy_fecha.slice(0, 7),
        titulo: f.mesLargo(fecha) + (m.clave === gn.hoy_fecha.slice(0, 7) ? " · en curso" : ""),
        filas: [{ valor: f.dinero(m.ganancia, { signo: true }), etiqueta: f.pct(m.pct, 2, true), clase: f.signoDe(m.ganancia) },
                { valor: `${m.dias_positivos} de ${m.dias}`, etiqueta: "días en positivo", suave: true }, ...filasReparto(m)],
      };
    }), { formatoX: (t) => f.mesCorto(t), alto: 170, nombre: "Ganancia por mes" });
  }
  const cuerpo = document.querySelector("#tabla-meses tbody");
  cuerpo.replaceChildren();
  for (const m of gn.meses.slice().reverse()) {
    const tr = document.createElement("tr");
    const t = f.mesLargo(f.fechaLocal(m.clave + "-01"));
    tr.append(g.el("td", "", t.charAt(0).toUpperCase() + t.slice(1)),
              celdaSigno(f.dinero(m.ganancia, { signo: true }), m.ganancia),
              g.el("td", "num suave", f.pct(m.pct, 2, true)),
              g.el("td", "num", `${m.dias_positivos} de ${m.dias}`),
              g.el("td", "num solo-ancho", f.valido(m.financiacion) ? f.dinero(m.financiacion, { signo: true }) : "—"),
              g.el("td", "num solo-ancho", f.valido(m.comisiones) ? f.dinero(m.comisiones) : "—"),
              g.el("td", "num solo-ancho", m.mejor ? `${f.dia(f.fechaLocal(m.mejor.fecha))}, ${f.dinero(m.mejor.ganancia, { signo: true })}` : "—"));
    cuerpo.appendChild(tr);
  }
}

// ── monedas y operaciones ─────────────────────────────────────────────────────

function etiquetaTendencia(p) {
  if (!f.valido(p)) return "Sin lectura";
  return p > 0.33 ? "Alcista" : p < -0.33 ? "Bajista" : "Sin tendencia clara";
}

function pintarMonedas() {
  const e = datos.e;
  if (!e) return;
  const mercado = new Map(((datos.mercado && datos.mercado.monedas) || []).map((m) => [m.simbolo, m]));
  const btc = e.monedas[0];
  const btcFavor = btc && f.valido(btc.puntuacion) && btc.puntuacion > 0;
  const lista = $("lista-monedas");
  lista.replaceChildren();
  let expuestas = 0, alcistas = 0;
  for (const m of e.monedas) {
    const s = base(m.simbolo);
    if ((m.neto || 0) > 0.002) expuestas++;
    if (f.valido(m.puntuacion) && m.puntuacion > 0.33) alcistas++;
    const fila = g.el("div", "moneda");
    fila.setAttribute("role", "listitem");

    const id = g.el("div", "m-id");
    const nombre = g.el("span", "m-nombre");
    nombre.append(g.el("strong", "", s), g.el("small", "", NOMBRES[s] || s));
    id.append(g.el("span", "avatar", s.slice(0, 4)), nombre);

    const mk = mercado.get(m.simbolo);
    const serie = mk ? [...mk.c, ...(f.valido(m.precio) ? [m.precio] : [])] : [];
    const cambio = serie.length > 1 ? serie.at(-1) / serie[0] - 1 : null;
    const precio = g.el("div", "m-precio");
    const decimales = m.precio >= 1000 ? 0 : m.precio >= 10 ? 2 : 4;
    precio.append(g.el("strong", "num", f.valido(m.precio) ? f.cifra(m.precio, decimales) : "—"));
    const cambioEl = g.el("small", "num", f.valido(cambio) ? f.pctFraccion(cambio, 1, true) + " en 7 d" : "");
    if (f.signoDe(cambio, 0.0005)) cambioEl.dataset.signo = f.signoDe(cambio, 0.0005);
    precio.appendChild(cambioEl);

    const spark = g.el("div", "m-spark");
    spark.appendChild(g.minilinea(serie, { signo: f.signoDe(cambio, 0.0005) }));

    const tend = g.el("div", "m-tendencia");
    const lectura = g.el("div", "m-lectura");
    lectura.append(g.el("span", "m-etiqueta", etiquetaTendencia(m.puntuacion)));
    if (m.simbolo !== btc.simbolo && f.valido(m.puntuacion) && m.puntuacion > 0 && !btcFavor) {
      const frenada = g.el("span", "insignia", "frenada por BTC");
      frenada.title = "Bitcoin no está a favor: las demás no suben exposición";
      lectura.appendChild(frenada);
    }
    tend.append(g.medidor(m.puntuacion), lectura);

    const rel = g.el("div", "m-relojes");
    rel.appendChild(g.relojes(m.relojes));
    if (m.relojes) {
      const favor = [...m.relojes.cruces, ...m.relojes.rupturas].filter((v) => v > 0).length;
      rel.appendChild(g.el("small", "", `${favor} de ${m.relojes.cruces.length + m.relojes.rupturas.length} a favor`));
    }

    const pos = g.el("div", "m-posicion");
    const valor = (m.valor_base || 0);
    const cubre = m.base > 0 ? Math.min(1, Math.max(0, m.cobertura / m.base)) : 0;
    const cab = g.el("div", "m-pos-cab");
    cab.append(g.el("strong", "num", f.dinero(valor, { decimales: 0 })),
               g.el("small", "", m.base > 0 ? (cubre > 0.995 ? "cubierta del todo" : `${f.pctFraccion(cubre)} cubierta`) : "sin base"));
    const barra = g.el("div", "m-pos-barra");
    if (m.base > 0) {
      const a = g.el("span", "cubierta"); a.style.flexGrow = String(cubre);
      const b = g.el("span", "expuesta"); b.style.flexGrow = String(1 - cubre);
      if (cubre > 0.001) barra.appendChild(a);
      if (cubre < 0.999) barra.appendChild(b);
    }
    barra.setAttribute("aria-label", `${f.pctFraccion(cubre)} cubierta, ${f.pctFraccion(1 - cubre)} expuesta`);
    pos.append(cab, barra);

    fila.append(id, precio, spark, tend, rel, pos);
    lista.appendChild(fila);
  }
  poner("monedas-resumen", `${alcistas} de ${e.monedas.length} en tendencia alcista · ${expuestas} con exposición · Bitcoin ${btcFavor ? "a favor" : "en contra o sin tendencia"}`);
}

function pintarOperaciones() {
  const caja = $("lista-operaciones");
  caja.replaceChildren();
  // Una decisión son varias operaciones seguidas con el mismo motivo y casi a la vez.
  const lotes = [];
  for (const o of datos.operaciones) {
    const t = Date.parse(o.utc);
    const ultimo = lotes.at(-1);
    if (!ultimo || ultimo.motivo !== o.motivo || Math.abs(ultimo.t - t) > 10000) {
      lotes.push({ clave: o.utc + "|" + o.motivo, t, utc: o.utc, motivo: o.motivo, filas: [] });
    }
    lotes.at(-1).filas.push(o);
  }
  if (!lotes.length) {
    caja.appendChild(g.el("p", "vacia", "Todavía no hay operaciones."));
    $("mas-operaciones").hidden = true;
    poner("ops-resumen", "");
    return;
  }
  poner("ops-resumen", `${datos.operaciones.length} operaciones recientes, en ${lotes.length} ${lotes.length === 1 ? "decisión" : "decisiones"}`);
  lotes.slice(0, vista.opsVisibles).forEach((lote, i) => {
    const d = g.el("details", "lote");
    // Abierta o cerrada como la dejó quien mira; si no la ha tocado, la última abierta si es corta.
    d.open = vista.lotesAbiertos.has(lote.clave) ||
      (!vista.lotesCerrados.has(lote.clave) && i === 0 && lote.filas.length <= 8);
    d.addEventListener("toggle", () => {
      (d.open ? vista.lotesAbiertos : vista.lotesCerrados).add(lote.clave);
      (d.open ? vista.lotesCerrados : vista.lotesAbiertos).delete(lote.clave);
    });
    const sum = document.createElement("summary");
    const comision = lote.filas.reduce((s, o) => s + Number(o.comision || 0), 0);
    const nocional = lote.filas.reduce((s, o) => s + Number(o.nocional || 0), 0);
    sum.append(g.el("span", "lote-cuando", f.cuando(lote.utc)),
               g.el("span", "lote-motivo", MOTIVOS[lote.motivo] || lote.motivo),
               g.el("span", "lote-n", `${lote.filas.length} ${lote.filas.length === 1 ? "operación" : "operaciones"}`),
               g.el("span", "lote-coste num", `${f.dinero(nocional, { decimales: 0 })} movidos · ${f.dinero(comision)} de comisión`));
    d.appendChild(sum);
    const ul = g.el("ul", "lote-lista");
    for (const o of lote.filas) {
      const li = document.createElement("li");
      const que = o.pata === "contado" ? (o.lado === "compra" ? "Compra base" : "Vende base")
                                       : (o.lado === "venta" ? "Sube cobertura" : "Baja cobertura");
      const pr = Number(o.precio);
      li.append(g.el("strong", "", base(o.simbolo)), g.el("span", "", que),
                g.el("span", "num", f.dinero(Number(o.nocional))),
                g.el("span", "num suave", "a " + f.cifra(pr, pr >= 1000 ? 0 : pr >= 10 ? 2 : 4)));
      ul.appendChild(li);
    }
    d.appendChild(ul);
    caja.appendChild(d);
  });
  $("mas-operaciones").hidden = lotes.length <= vista.opsVisibles;
}

// ── mando y riesgo ────────────────────────────────────────────────────────────

function confirmar({ titulo, texto, si = "Sí", peligro = false }) {
  const d = $("dialogo");
  poner("dialogo-titulo", titulo);
  poner("dialogo-texto", texto);
  const b = $("dialogo-si");
  b.textContent = si;
  b.classList.toggle("peligro", peligro);
  b.classList.toggle("primario", !peligro);
  return new Promise((resolver) => {
    d.addEventListener("close", () => resolver(d.returnValue === "si"), { once: true });
    d.returnValue = "";
    d.showModal();
  });
}

function pintarMando() {
  const e = datos.e;
  if (!e) return;
  for (const b of document.querySelectorAll(".opcion")) b.setAttribute("aria-checked", String(b.dataset.mando === e.mando));
  const caja = $("niveles");
  if (caja.childElementCount === 0) {
    for (const [clave, n] of Object.entries(e.niveles || {})) {
      const b = g.el("button", "nivel");
      b.type = "button";
      b.dataset.nivel = clave;
      b.setAttribute("role", "radio");
      b.addEventListener("click", () => elegirNivel(clave));
      caja.appendChild(b);
    }
  }
  const riesgos = Object.values(e.niveles || {});
  for (const b of caja.children) {
    const n = e.niveles[b.dataset.nivel];
    const i = riesgos.indexOf(n);
    b.setAttribute("aria-checked", String(b.dataset.nivel === e.nivel));
    b.replaceChildren();
    const cab = g.el("span", "nivel-cab");
    const puntos = g.el("span", "nivel-puntos");
    puntos.setAttribute("aria-hidden", "true");
    for (let k = 0; k < riesgos.length; k++) puntos.appendChild(g.el("span", k <= i ? "lleno" : ""));
    cab.append(g.el("strong", "", n.nombre), puntos);
    const dia = alDia(n.anual_pct, e.patrimonio);
    const anios = Object.entries(n.por_anio || {}).map(([a, p]) => `${a}: ${f.pct(p, 1, true)}`).join(" · ");
    b.append(cab,
             g.el("span", "nivel-dia", "≈ " + f.dinero(dia, { signo: true }) + " al día"),
             g.el("span", "nivel-dato", `${f.pct(n.anual_pct, 1, true)} al año`),
             caidaNivel(n, e.patrimonio),
             g.el("span", "nivel-dato", `${n.meses_positivos_pct} % de meses en positivo`),
             g.el("span", "nivel-anios", anios));
  }
  const n = nivelActual();
  poner("nivel-estado", n ? `Ahora: ${n.nombre}. Un cambio se aplica en la próxima decisión (cada ${parseInt(e.intervalo, 10) || 4} horas).`
                          : "Ahora: riesgo puesto a medida con el ajuste fino; no coincide con ningún nivel medido.");
  pintarAjustes(e);
}

function caidaNivel(n, patrimonio) {
  const linea = g.el("span", "nivel-dato", `peor caída ${f.pct(n.caida_pct, 1)} `);
  linea.appendChild(g.el("span", "sin-cortes", `(≈ ${f.dinero(patrimonio * n.caida_pct / 100, { decimales: 0 })})`));
  return linea;
}

async function elegirNivel(clave) {
  const e = datos.e;
  const n = e.niveles[clave];
  if (clave === e.nivel) return;
  const si = await confirmar({
    titulo: `¿Pasar al nivel ${n.nombre}?`,
    texto: `En la prueba ganó ${f.pct(n.anual_pct, 1, true)} al año (≈ ${f.dinero(alDia(n.anual_pct, e.patrimonio), { signo: true })} al día con tu patrimonio) y su peor caída fue del ${f.pct(n.caida_pct, 1)} (≈ ${f.dinero(e.patrimonio * n.caida_pct / 100, { decimales: 0 })}). Se aplica en la próxima decisión.`,
    si: "Cambiar a " + n.nombre,
  });
  if (!si) return;
  try {
    await api("/api/ajustes", n.ajustes);
    vista.ajustesPintados = false;
    poner("nivel-estado", `Nivel ${n.nombre} guardado. Se aplica en la próxima decisión.`);
    await refrescar({ todo: true });
  } catch (err) {
    if (err.message !== "401") poner("nivel-estado", "No se guardó: " + err.message);
  }
}

function pintarAjustes(e) {
  if (vista.ajustesPintados) return;      // no pisar lo que se está moviendo
  vista.ajustesPintados = true;
  const form = $("form-ajustes");
  form.replaceChildren();
  for (const [clave, lim] of Object.entries(e.ajustables)) {
    const caja = g.el("div", "ajuste");
    const etiqueta = g.el("label");
    etiqueta.htmlFor = "aj-" + clave;
    const salida = document.createElement("output");
    etiqueta.append(g.el("span", "", lim.etiqueta), salida);
    const control = document.createElement("input");
    control.type = "range";
    control.id = "aj-" + clave;
    control.name = clave;
    control.min = lim.min; control.max = lim.max; control.step = lim.paso;
    control.value = e.ajustes[clave];
    const mostrar = () => {
      const v = Number(control.value);
      salida.textContent = lim.formato === "x" ? "×" + f.cifra(v, 2) : f.pctFraccion(v);
    };
    control.addEventListener("input", mostrar);
    mostrar();
    caja.append(etiqueta, control);
    form.appendChild(caja);
  }
  const boton = g.el("button", "boton", "Guardar el riesgo");
  boton.type = "submit";
  form.appendChild(boton);
}

// ── vistas ────────────────────────────────────────────────────────────────────

function mostrarVista(nombre, { enfocar = false } = {}) {
  pref.vista = nombre;
  guardarPref();
  for (const s of document.querySelectorAll(".vista")) s.hidden = s.dataset.vista !== nombre;
  for (const b of document.querySelectorAll(".nav-boton")) {
    if (b.dataset.ir === nombre) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
  poner("titulo-vista", VISTAS[nombre]);
  document.title = VISTAS[nombre] + " · Bot Jorge";
  pintarVista(true);
  if (enfocar) window.scrollTo({ top: 0 });
}

function pintarVista(forzar) {
  if (!datos.e) return;
  pintarBarra();
  pintarPie();
  if (pref.vista === "resumen") { pintarResumen(); pintarCurva(forzar); }
  else if (pref.vista === "ganancias") pintarGanancias(forzar);
  else if (pref.vista === "monedas") { pintarMonedas(); pintarOperaciones(); }
  else if (pref.vista === "mando") pintarMando();
}

// ── ciclo de datos ────────────────────────────────────────────────────────────

async function refrescar({ todo = false } = {}) {
  if (!token) return;
  try {
    datos.e = await api("/api/estado");
    datos.recibido = Date.now();
    vista.error = false;
    $("acceso").hidden = true;
    $("app").hidden = false;
    const ahora = Date.now();
    const tareas = [];
    // Las ganancias van con cada estado, para que «hoy» y el patrimonio digan lo mismo.
    tareas.push(api("/api/ganancias?zona=" + encodeURIComponent(ZONA)).then((r) => { datos.ganancias = r; }));
    if (todo || ahora - marcas.lento > 60e3) {
      marcas.lento = ahora;
      tareas.push(api("/api/operaciones?n=200").then((r) => { datos.operaciones = r; }));
    }
    if (todo || ahora - marcas.curva > 300e3 || datos.curvaHoras !== pref.horas) {
      marcas.curva = ahora;
      const horas = pref.horas;
      tareas.push(api("/api/patrimonio?horas=" + horas).then((r) => { datos.curva = r; datos.curvaHoras = horas; }));
    }
    if (todo || ahora - marcas.mercado > 300e3) {
      marcas.mercado = ahora;
      tareas.push(api("/api/mercado").then((r) => { datos.mercado = r; }));
    }
    await Promise.all(tareas);
    pintarVista(todo);
  } catch (err) {
    if (err.message !== "401") {
      vista.error = true;
      pintarBarra();
    }
  }
}

// ── eventos ───────────────────────────────────────────────────────────────────

function conectar() {
  $("form-token").addEventListener("submit", (ev) => {
    ev.preventDefault();
    token = $("campo-token").value.trim();
    $("campo-token").value = "";
    try { localStorage.setItem(CLAVE, token); } catch (e) { /* modo privado */ }
    refrescar({ todo: true });
  });
  $("salir").addEventListener("click", async () => {
    if (!await confirmar({ titulo: "¿Olvidar el token aquí?", texto: "Este aparato dejará de ver el panel hasta que vuelvas a escribirlo. El bot sigue funcionando igual.", si: "Olvidarlo" })) return;
    try { localStorage.removeItem(CLAVE); } catch (e) { /* nada */ }
    token = null;
    pedirToken("");
  });
  for (const b of document.querySelectorAll(".nav-boton")) b.addEventListener("click", () => mostrarVista(b.dataset.ir, { enfocar: true }));

  const curvaHoras = $("curva-horas");
  marcarSegmentado(curvaHoras, pref.horas);
  curvaHoras.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    pref.horas = Number(b.dataset.valor);
    guardarPref();
    marcarSegmentado(curvaHoras, pref.horas);
    refrescar();
  });
  const vs = $("vs-btc");
  vs.checked = pref.vsBtc;
  vs.addEventListener("change", () => { pref.vsBtc = vs.checked; guardarPref(); pintarCurva(true); });

  const rango = $("dias-rango");
  marcarSegmentado(rango, pref.dias);
  rango.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    pref.dias = Number(b.dataset.valor);
    guardarPref();
    marcarSegmentado(rango, pref.dias);
    pintarGanancias(true);
  });
  const moverMes = (paso) => {
    const [a, m] = vista.mesCal.split("-").map(Number);
    const d = new Date(a, m - 1 + paso, 1);
    vista.mesCal = f.claveDia(d).slice(0, 7);
    pintarCalendario();
  };
  $("cal-antes").addEventListener("click", () => moverMes(-1));
  $("cal-despues").addEventListener("click", () => moverMes(1));

  $("mas-operaciones").addEventListener("click", () => { vista.opsVisibles += 10; pintarOperaciones(); });

  for (const b of document.querySelectorAll(".opcion")) {
    b.addEventListener("click", async () => {
      const pedido = b.dataset.mando;
      const e = datos.e;
      if (!e || pedido === e.mando) return;
      poner("mando-error", "");
      const m = MANDOS[pedido];
      const si = await confirmar({ titulo: pedido === "fuera" ? "¿Salir a USDT?" : `¿Cambiar a «${b.querySelector("strong").textContent}»?`,
                                   texto: m.confirma, si: pedido === "fuera" ? "Sí, salir a USDT" : "Cambiar", peligro: pedido === "fuera" });
      if (!si) return;
      try {
        let r = await api("/api/mando", { mando: pedido });
        if (r.confirmar) r = await api("/api/mando", { mando: pedido, confirmacion: r.confirmar });
        await refrescar({ todo: true });
      } catch (err) {
        if (err.message !== "401") poner("mando-error", "No se pudo: " + err.message);
      }
    });
  }

  $("form-ajustes").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const cambios = {};
    for (const c of ev.target.querySelectorAll("input[type=range]")) cambios[c.name] = Number(c.value);
    try {
      await api("/api/ajustes", cambios);
      poner("ajustes-estado", "Guardado. Se aplica en la próxima decisión.");
      await refrescar({ todo: true });
    } catch (err) {
      if (err.message !== "401") poner("ajustes-estado", "No se guardó: " + err.message);
    }
  });

  const tema = $("tema");
  tema.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    pref.tema = b.dataset.valor;
    guardarPref();
    aplicarTema();
    pintarVista(true);           // las gráficas toman los colores del tema nuevo
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => pintarVista(true));

  // Cada gráfica se repinta cuando cambia el tamaño de su caja: ventana, columnas o una tabla abierta.
  const tamanos = new Map();
  let redibujo = null;
  const observador = new ResizeObserver((entradas) => {
    let cambio = false;
    for (const en of entradas) {
      const { width, height } = en.contentRect;
      const antes = tamanos.get(en.target) || { width: 0, height: 0 };
      if (Math.abs(antes.width - width) > 1 || Math.abs(antes.height - height) > 1) cambio = true;
      tamanos.set(en.target, { width, height });
    }
    if (!cambio) return;
    clearTimeout(redibujo);
    redibujo = setTimeout(() => pintarVista(true), 120);
  });
  for (const id of ["grafica-curva", "grafica-dias", "grafica-meses"]) observador.observe($(id));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refrescar(); });
}

// ── arranque ──────────────────────────────────────────────────────────────────

token = leerToken();
aplicarTema();
conectar();
mostrarVista(pref.vista);
if (token) refrescar({ todo: true }); else pedirToken("");
setInterval(() => { if (!document.hidden) refrescar(); }, 15000);
setInterval(() => { if (!document.hidden) { pintarPie(); pintarCuenta(); } }, 1000);
