// Gráficas del panel en SVG, sin librerías. Cada una pinta en su caja y trae su capa de lectura:
// mira o globo al pasar el dedo o el ratón, y flechas del teclado con el foco puesto.
// Todo texto se pone con textContent: nada que venga del servidor se interpreta como HTML.

import * as f from "./formato.js";

const SVG = "http://www.w3.org/2000/svg";
const HORA = 3600e3;
const DIA = 24 * HORA;
const movimientoReducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function nodo(nombre, attrs = {}, padre) {
  const n = document.createElementNS(SVG, nombre);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v);
  }
  if (padre) padre.appendChild(n);
  return n;
}

export function el(etiqueta, clase, contenido) {
  const e = document.createElement(etiqueta);
  if (clase) e.className = clase;
  if (contenido !== undefined && contenido !== null) e.textContent = contenido;
  return e;
}

function texto(padre, x, y, contenido, clase, ancla) {
  const t = nodo("text", { x: r1(x), y: r1(y), class: clase, "text-anchor": ancla }, padre);
  t.textContent = contenido;
  return t;
}

const r1 = (x) => Math.round(x * 10) / 10;

export function vacio(caja, mensaje) {
  caja.replaceChildren(el("p", "vacia", mensaje));
}

/** Marcas redondas entre min y max (1, 2, 2,5 o 5 por potencia de diez). */
export function marcasLimpias(min, max, cuantas = 4) {
  if (!(max > min)) return [min];
  const bruto = (max - min) / cuantas;
  const potencia = Math.pow(10, Math.floor(Math.log10(bruto)));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) || potencia * 10;
  const marcas = [];
  for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-9; v += paso) {
    marcas.push(Math.abs(v) < paso * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return marcas;
}

/** Los decimales que hacen falta para escribir todas las marcas sin redondearlas. */
function decimalesDe(marcas) {
  for (let d = 0; d < 4; d++) {
    const k = Math.pow(10, d);
    if (marcas.every((v) => Math.abs(v * k - Math.round(v * k)) < 1e-6)) return d;
  }
  return 3;
}

/** Marcas de tiempo alineadas a horas, días o meses locales, unas cada ~90 px. */
export function marcasTiempo(t0, t1, ancho) {
  const deseadas = Math.max(2, Math.floor(ancho / 84));
  const lapso = Math.max(1, t1 - t0);
  const pasos = [
    { ms: HORA }, { ms: 2 * HORA }, { ms: 3 * HORA }, { ms: 6 * HORA }, { ms: 12 * HORA },
    { dias: 1 }, { dias: 2 }, { dias: 7 }, { dias: 14 }, { meses: 1 }, { meses: 3 }, { meses: 6 }, { meses: 12 },
  ];
  const dura = (p) => p.ms || (p.dias ? p.dias * DIA : p.meses * 30.4 * DIA);
  const paso = pasos.find((p) => lapso / dura(p) <= deseadas + 1) || pasos[pasos.length - 1];
  const marcas = [];
  const d = new Date(t0);
  if (paso.ms) {
    const h = paso.ms / HORA;
    d.setMinutes(0, 0, 0);
    d.setHours(Math.ceil((d.getHours() + (d.getTime() < t0 ? 1 : 0)) / h) * h);
    for (let i = 0; i < 400 && d.getTime() <= t1; i++) {
      if (d.getTime() >= t0) marcas.push(d.getTime());
      d.setHours(d.getHours() + h);
    }
  } else if (paso.dias) {
    d.setHours(0, 0, 0, 0);
    if (d.getTime() < t0) d.setDate(d.getDate() + 1);
    if (paso.dias >= 7) while (d.getDay() !== 1) d.setDate(d.getDate() + 1);
    for (let i = 0; i < 400 && d.getTime() <= t1; i++) {
      marcas.push(d.getTime());
      d.setDate(d.getDate() + paso.dias);
    }
  } else {
    d.setDate(1);
    d.setHours(0, 0, 0, 0);
    if (d.getTime() < t0) d.setMonth(d.getMonth() + 1);
    while (d.getMonth() % paso.meses !== 0) d.setMonth(d.getMonth() + 1);
    for (let i = 0; i < 400 && d.getTime() <= t1; i++) {
      marcas.push(d.getTime());
      d.setMonth(d.getMonth() + paso.meses);
    }
  }
  const variosAnios = new Date(t0).getFullYear() !== new Date(t1).getFullYear();
  const formato = paso.ms
    ? (t) => (new Date(t).getHours() === 0 ? f.dia(t) : f.hora(t))
    : paso.dias ? (t) => f.dia(t) : (t) => (variosAnios ? f.mesAnio(t) : f.mesCorto(t));
  return { marcas, formato };
}

/** Trazo de una serie; los huecos (null) cortan la línea. */
function trazo(xs, ys, X, Y) {
  let d = "", fuera = true;
  for (let i = 0; i < xs.length; i++) {
    if (!f.valido(ys[i])) { fuera = true; continue; }
    d += (fuera ? "M" : "L") + r1(X(xs[i])) + " " + r1(Y(ys[i]));
    fuera = false;
  }
  return d;
}

function buscarCercano(xs, x) {
  let lo = 0, hi = xs.length - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (xs[m] < x) lo = m; else hi = m;
  }
  return Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
}

// ── globo (la lectura al pasar) ───────────────────────────────────────────────

class Globo {
  constructor(caja) {
    this.caja = caja;
    this.el = el("div", "globo");
    this.el.hidden = true;
    this.el.setAttribute("role", "status");
    caja.appendChild(this.el);
  }

  /** filas: [{valor, etiqueta, color, forma}] — el valor manda, la etiqueta acompaña. */
  mostrar(x, y, titulo, filas) {
    const g = this.el;
    g.replaceChildren();
    if (titulo) g.appendChild(el("p", "globo-titulo", titulo));
    for (const fila of filas) {
      const linea = el("div", "globo-fila" + (fila.suave ? " suave" : ""));
      if (fila.color) {
        const clave = el("span", "clave " + (fila.forma || "linea"));
        clave.style.background = fila.color;
        linea.appendChild(clave);
      }
      const valor = el("strong", fila.clase || "", fila.valor);
      linea.append(valor, el("span", "", fila.etiqueta || ""));
      g.appendChild(linea);
    }
    g.hidden = false;
    const ancho = g.offsetWidth, alto = g.offsetHeight, total = this.caja.clientWidth;
    let izq = x + 14;
    if (izq + ancho > total - 4) izq = x - ancho - 14;
    izq = Math.max(0, Math.min(izq, total - ancho));
    const arriba = Math.max(0, y - alto - 12);
    g.style.transform = `translate(${Math.round(izq)}px, ${Math.round(arriba)}px)`;
  }

  ocultar() { this.el.hidden = true; }
}

/** Conecta puntero y teclado a una función `mostrar(i)` sobre `n` posiciones. */
function lectura(svg, { n, indiceDesdeX, mostrar, ocultar, inicial }) {
  let actual = inicial ?? n - 1;
  let temporizador = null;
  const ir = (i) => { actual = Math.max(0, Math.min(n - 1, i)); mostrar(actual); };
  svg.addEventListener("pointermove", (ev) => {
    clearTimeout(temporizador);
    const r = svg.getBoundingClientRect();
    ir(indiceDesdeX((ev.clientX - r.left) / r.width * svg.viewBox.baseVal.width));
  });
  svg.addEventListener("pointerdown", (ev) => {
    const r = svg.getBoundingClientRect();
    ir(indiceDesdeX((ev.clientX - r.left) / r.width * svg.viewBox.baseVal.width));
  });
  svg.addEventListener("pointerleave", (ev) => {
    // Con el dedo, la lectura se queda un momento después de soltar.
    clearTimeout(temporizador);
    temporizador = setTimeout(ocultar, ev.pointerType === "touch" ? 2500 : 0);
  });
  svg.addEventListener("focus", () => ir(actual));
  svg.addEventListener("blur", ocultar);
  svg.addEventListener("keydown", (ev) => {
    const salto = ev.shiftKey ? 10 : 1;
    if (ev.key === "ArrowLeft") { ir(actual - salto); ev.preventDefault(); }
    else if (ev.key === "ArrowRight") { ir(actual + salto); ev.preventDefault(); }
    else if (ev.key === "Home") { ir(0); ev.preventDefault(); }
    else if (ev.key === "End") { ir(n - 1); ev.preventDefault(); }
    else if (ev.key === "Escape") ocultar();
  });
}

// ── curva de patrimonio ───────────────────────────────────────────────────────

/**
 * puntos: [{t, v, neto, btc}] en orden. modo "valor" (en dólares) o "comparar" (en % desde el
 * primer punto, con Bitcoin de contexto en gris). Debajo, la exposición al mercado en su propia
 * franja: dos medidas distintas no comparten eje.
 */
export function curva(caja, puntos, { modo = "valor" } = {}) {
  caja.replaceChildren();
  if (puntos.length < 2) {
    vacio(caja, "La curva aparece en cuanto haya un par de horas de historia.");
    return;
  }
  const W = Math.max(280, Math.floor(caja.clientWidth));
  const estrecho = W < 560;
  const izq = 2, der = estrecho ? 58 : 70, arriba = 14;
  const sep = 34, altoF = estrecho ? 44 : 56, abajo = 26;
  // Ocupa el alto que le dé su caja (en el escritorio se estira al de la columna de al lado).
  const altoP = Math.max(estrecho ? 170 : 220, Math.floor(caja.clientHeight) - (arriba + sep + altoF + abajo));
  const Ht = arriba + altoP + sep + altoF + abajo;
  const ts = puntos.map((p) => p.t);
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const X = (t) => izq + (t - t0) / Math.max(1, t1 - t0) * (W - izq - der);

  const comparar = modo === "comparar" && puntos.some((p) => f.valido(p.btc));
  let series;
  if (comparar) {
    const v0 = puntos[0].v;
    const b0 = (puntos.find((p) => f.valido(p.btc)) || {}).btc;
    series = [
      { nombre: "Tu patrimonio", clase: "principal", color: "var(--serie-1)",
        vals: puntos.map((p) => (p.v / v0 - 1) * 100) },
      { nombre: "Bitcoin", clase: "contexto", color: "var(--tinta-3)",
        vals: puntos.map((p) => (f.valido(p.btc) ? (p.btc / b0 - 1) * 100 : null)) },
    ];
  } else {
    series = [{ nombre: "Patrimonio", clase: "principal", color: "var(--serie-1)", area: true,
                vals: puntos.map((p) => p.v) }];
  }
  const todos = series.flatMap((s) => s.vals.filter(f.valido));
  let yMin = Math.min(...todos), yMax = Math.max(...todos);
  if (comparar) { yMin = Math.min(yMin, 0); yMax = Math.max(yMax, 0); }
  // Un tramo mínimo (0,1 % del patrimonio, o medio punto al comparar) para no agrandar movimientos de céntimos.
  const minimo = comparar ? 0.5 : Math.abs(yMax) * 0.001;
  if (yMax - yMin < minimo) { const c = (yMax + yMin) / 2; yMin = c - minimo / 2; yMax = c + minimo / 2; }
  const holgura = (yMax - yMin) * 0.1;
  yMin -= holgura; yMax += holgura;
  const Y = (v) => arriba + (yMax - v) / (yMax - yMin) * altoP;
  const yF0 = arriba + altoP + sep;
  const netos = puntos.map((p) => Math.max(0, p.neto || 0));
  const netoTope = Math.max(0.1, Math.ceil(Math.max(...netos) * 10) / 10);
  const YF = (n) => yF0 + altoF - (n / netoTope) * altoF;

  const ultimo = puntos[puntos.length - 1];
  const etiqueta = comparar
    ? `Tu patrimonio ${f.pct(series[0].vals.at(-1), 2, true)} y Bitcoin ${f.pct(series[1].vals.at(-1), 1, true)} en el periodo.`
    : `Patrimonio de ${f.dinero(puntos[0].v)} a ${f.dinero(ultimo.v)}.`;
  const svg = nodo("svg", { viewBox: `0 0 ${W} ${Ht}`, width: W, height: Ht, role: "img", tabindex: "0",
                            class: "svg-curva", "aria-label": etiqueta + " Flechas para recorrerla." });

  // Rejilla y eje de la franja principal
  const marcas = marcasLimpias(yMin, yMax, estrecho ? 3 : 4);
  const dec = decimalesDe(marcas);
  const yUltimo = Y(series[0].vals.at(-1));
  for (const v of marcas) {
    const y = Y(v);
    if (y < arriba - 1 || y > arriba + altoP + 1) continue;
    nodo("line", { class: v === 0 && comparar ? "base" : "rejilla", x1: izq, x2: W - der, y1: r1(y), y2: r1(y) }, svg);
    if (Math.abs(y - yUltimo) > 17) {
      texto(svg, W - der + 8, y + 4, comparar ? f.pct(v, dec, true) : f.cifra(v, dec), "marca");
    }
  }

  const g = nodo("g", { class: movimientoReducido() ? "" : "aparece" }, svg);
  for (const s of series.slice().reverse()) {
    const d = trazo(ts, s.vals, X, Y);
    if (s.area) {
      nodo("path", { class: "area", d: `${d} L${r1(X(t1))} ${arriba + altoP} L${r1(X(t0))} ${arriba + altoP} Z` }, g);
    }
    nodo("path", { class: "linea " + s.clase, d }, g);
  }
  // Punto final y etiqueta de precio en el eje, como en las plataformas de mercado.
  nodo("circle", { class: "punto-final", cx: r1(X(t1)), cy: r1(yUltimo), r: 4 }, svg);
  const valorFinal = comparar ? f.pct(series[0].vals.at(-1), 1, true)
    : f.cifra(ultimo.v, estrecho && Math.abs(ultimo.v) >= 1000 ? 0 : Math.max(dec, 2));
  nodo("rect", { class: "etiqueta-valor", x: W - der + 3, y: r1(yUltimo - 10), width: der - 3, height: 20, rx: 5 }, svg);
  texto(svg, W - der / 2 + 1.5, yUltimo + 4, valorFinal, "etiqueta-valor-texto", "middle");

  // Franja de exposición
  texto(svg, izq, yF0 - 10, "Exposición al mercado", "titulo-franja");
  nodo("line", { class: "rejilla", x1: izq, x2: W - der, y1: yF0, y2: yF0 }, svg);
  nodo("line", { class: "base", x1: izq, x2: W - der, y1: yF0 + altoF, y2: yF0 + altoF }, svg);
  const dN = trazo(ts, netos, X, YF);
  nodo("path", { class: "area-franja", d: `${dN} L${r1(X(t1))} ${yF0 + altoF} L${r1(X(t0))} ${yF0 + altoF} Z` }, svg);
  nodo("path", { class: "linea-franja", d: dN }, svg);
  texto(svg, W - der + 8, yF0 + 4, f.pctFraccion(netoTope), "marca");
  texto(svg, W - der + 8, yF0 + altoF + 4, "0 %", "marca");

  // Eje del tiempo
  const { marcas: mt, formato } = marcasTiempo(t0, t1, W - izq - der);
  for (const t of mt) {
    const x = X(t);
    if (x < izq + 20 || x > W - der - 20) continue;
    texto(svg, x, Ht - 7, formato(t), "marca", "middle");
  }

  // Lectura
  const mira = nodo("line", { class: "mira", y1: arriba, y2: yF0 + altoF, visibility: "hidden" }, svg);
  const focos = series.map((s) => nodo("circle", { class: "foco " + s.clase, r: 4.5, visibility: "hidden" }, svg));
  const focoF = nodo("circle", { class: "foco franja", r: 3.5, visibility: "hidden" }, svg);
  nodo("rect", { class: "captura", x: 0, y: 0, width: W, height: Ht }, svg);
  caja.appendChild(svg);
  const globo = new Globo(caja);

  const mostrar = (i) => {
    const x = X(ts[i]);
    mira.setAttribute("x1", r1(x)); mira.setAttribute("x2", r1(x)); mira.setAttribute("visibility", "visible");
    series.forEach((s, k) => {
      const ok = f.valido(s.vals[i]);
      focos[k].setAttribute("visibility", ok ? "visible" : "hidden");
      if (ok) { focos[k].setAttribute("cx", r1(x)); focos[k].setAttribute("cy", r1(Y(s.vals[i]))); }
    });
    focoF.setAttribute("cx", r1(x)); focoF.setAttribute("cy", r1(YF(netos[i]))); focoF.setAttribute("visibility", "visible");
    const filas = comparar
      ? [{ valor: f.pct(series[0].vals[i], 2, true), etiqueta: "Tu patrimonio", color: series[0].color },
         { valor: f.valido(series[1].vals[i]) ? f.pct(series[1].vals[i], 1, true) : "—", etiqueta: "Bitcoin", color: series[1].color }]
      : [{ valor: f.dinero(puntos[i].v), etiqueta: "Patrimonio", color: series[0].color }];
    filas.push({ valor: f.pctFraccion(netos[i], 1), etiqueta: "expuesto al mercado", suave: true });
    const escala = svg.getBoundingClientRect().width / W || 1;
    globo.mostrar(x * escala, Y(series[0].vals[i]) * escala, f.diaSemanaCorto(ts[i]) + ", " + f.hora(ts[i]), filas);
  };
  const ocultar = () => {
    mira.setAttribute("visibility", "hidden");
    focos.forEach((c) => c.setAttribute("visibility", "hidden"));
    focoF.setAttribute("visibility", "hidden");
    globo.ocultar();
  };
  lectura(svg, { n: ts.length, mostrar, ocultar,
                 indiceDesdeX: (x) => buscarCercano(ts, t0 + (x - izq) / (W - izq - der) * (t1 - t0)) });
}

// ── barras con signo (ganancia por día o por mes) ────────────────────────────

function barraRedondeada(x, w, y0, y1) {
  // Esquinas de 4 px en el extremo del dato; cuadrada en la base.
  const alto = Math.abs(y1 - y0);
  const r = Math.min(4, w / 2, alto);
  const izq = r1(x - w / 2), der = r1(x + w / 2);
  if (y1 < y0) {   // hacia arriba
    return `M${izq} ${r1(y0)} V${r1(y1 + r)} Q${izq} ${r1(y1)} ${r1(izq + r)} ${r1(y1)} H${r1(der - r)} Q${der} ${r1(y1)} ${der} ${r1(y1 + r)} V${r1(y0)} Z`;
  }
  return `M${izq} ${r1(y0)} V${r1(y1 - r)} Q${izq} ${r1(y1)} ${r1(izq + r)} ${r1(y1)} H${r1(der - r)} Q${der} ${r1(y1)} ${der} ${r1(y1 - r)} V${r1(y0)} Z`;
}

/**
 * items: [{clave, fecha, valor (null = sin datos), parcial, titulo, filas}]
 * Verde arriba, rojo abajo; la posición respecto al cero ya dice el signo, y el globo y la
 * tabla lo dicen con cifras. `referencia` dibuja la línea de lo medido.
 */
export function barras(caja, items, { referencia = null, etiquetaReferencia = "", formatoX = f.dia,
                                      alto = 220, nombre = "Ganancia" } = {}) {
  caja.replaceChildren();
  if (!items.length) { vacio(caja, "Aún no hay días que enseñar."); return; }
  const W = Math.max(280, Math.floor(caja.clientWidth));
  const estrecho = W < 560;
  const izq = 2, der = estrecho ? 50 : 60, arriba = 18, abajo = 26;
  const altoP = estrecho ? Math.round(alto * 0.85) : alto;
  const Ht = arriba + altoP + abajo;
  const vals = items.map((it) => it.valor).filter(f.valido);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (f.valido(referencia)) { lo = Math.min(lo, referencia); hi = Math.max(hi, referencia); }
  if (hi - lo < 1e-9) hi = lo + 1;
  const marcas = marcasLimpias(lo, hi, estrecho ? 3 : 4);
  lo = Math.min(lo, marcas[0]); hi = Math.max(hi, marcas[marcas.length - 1]);
  const Y = (v) => arriba + (hi - v) / (hi - lo) * altoP;
  const ancho = W - izq - der;
  const hueco = ancho / items.length;
  const wBarra = Math.max(1.5, Math.min(24, hueco - Math.max(2, hueco * 0.3)));
  const Xc = (i) => izq + hueco * (i + 0.5);

  const svg = nodo("svg", { viewBox: `0 0 ${W} ${Ht}`, width: W, height: Ht, role: "img", tabindex: "0", class: "svg-barras",
                            "aria-label": `${nombre}: ${items.length} barras. Flechas para recorrerlas; la tabla de abajo trae todas las cifras.` });
  for (const v of marcas) {
    const y = Y(v);
    nodo("line", { class: v === 0 ? "base" : "rejilla", x1: izq, x2: W - der, y1: r1(y), y2: r1(y) }, svg);
    texto(svg, W - der + 8, y + 4, v === 0 ? "0" : f.dineroEje(v), "marca");
  }
  const y0 = Y(0);
  const g = nodo("g", { class: movimientoReducido() ? "" : "crece" }, svg);
  const marcasBarra = items.map((it, i) => {
    if (!f.valido(it.valor) || Math.abs(Y(it.valor) - y0) < 0.5) return null;
    const clase = "barra " + (it.valor >= 0 ? "sube" : "baja") + (it.parcial ? " parcial" : "");
    return nodo("path", { class: clase, d: barraRedondeada(Xc(i), wBarra, y0, Y(it.valor)) }, g);
  });
  if (f.valido(referencia) && referencia !== 0) {
    const yr = Y(referencia);
    nodo("line", { class: "referencia", x1: izq, x2: W - der, y1: r1(yr), y2: r1(yr) }, svg);
    if (etiquetaReferencia) {
      const t = estrecho ? etiquetaReferencia.replace("lo medido", "medido").replace("/día", "") : etiquetaReferencia;
      texto(svg, W - der - 4, referencia >= 0 ? yr - 6 : yr + 14, t, "etiqueta-ref", "end");
    }
  }

  // Etiquetas del eje x: pocas y sin pisarse, contando hacia atrás desde la última.
  const caben = Math.max(2, Math.floor(ancho / (estrecho ? 66 : 84)));
  const cada = Math.max(1, Math.ceil(items.length / caben));
  for (let i = items.length - 1; i >= 0; i -= cada) {
    const x = Xc(i);
    const ancla = x < izq + 30 ? "start" : x > W - der - 30 ? "end" : "middle";
    texto(svg, ancla === "start" ? izq : ancla === "end" ? W - der : x, Ht - 7, formatoX(items[i].fecha), "marca", ancla);
  }

  const resalte = nodo("rect", { class: "resalte", y: arriba, height: altoP, width: r1(hueco), visibility: "hidden" }, svg);
  svg.insertBefore(resalte, g);
  nodo("rect", { class: "captura", x: 0, y: 0, width: W, height: Ht }, svg);
  caja.appendChild(svg);
  const globo = new Globo(caja);
  let activa = null;
  const mostrar = (i) => {
    const it = items[i];
    resalte.setAttribute("x", r1(izq + hueco * i)); resalte.setAttribute("visibility", "visible");
    if (activa) activa.classList.remove("activa");
    activa = marcasBarra[i];
    if (activa) activa.classList.add("activa");
    const escala = svg.getBoundingClientRect().width / W || 1;
    const yv = f.valido(it.valor) ? Math.min(Y(it.valor), y0) : y0;
    globo.mostrar(Xc(i) * escala, yv * escala, it.titulo, it.filas);
  };
  const ocultar = () => {
    resalte.setAttribute("visibility", "hidden");
    if (activa) activa.classList.remove("activa");
    globo.ocultar();
  };
  lectura(svg, { n: items.length, mostrar, ocultar,
                 indiceDesdeX: (x) => Math.max(0, Math.min(items.length - 1, Math.floor((x - izq) / hueco))) });
}

// ── calendario de ganancias ──────────────────────────────────────────────────

const DIAS_SEMANA = ["L", "M", "X", "J", "V", "S", "D"];

/**
 * Un mes en rejilla de semanas (de lunes a domingo). Cada día lleva su cifra escrita: el color
 * (verde gana, rojo pierde, más intenso cuanto más) solo acompaña.
 */
export function calendario(caja, { anio, mes, porDia, hoy, primerDia, alElegir, elegido }) {
  caja.replaceChildren();
  const rejilla = el("div", "cal-rejilla");
  rejilla.setAttribute("role", "grid");
  for (const d of DIAS_SEMANA) rejilla.appendChild(el("span", "cal-cabecera", d));
  const primero = new Date(anio, mes, 1);
  const hueco = (primero.getDay() + 6) % 7;
  for (let i = 0; i < hueco; i++) rejilla.appendChild(el("span", "cal-hueco"));
  const diasMes = new Date(anio, mes + 1, 0).getDate();
  let maximo = 0;
  for (let d = 1; d <= diasMes; d++) {
    const r = porDia.get(f.claveDia(new Date(anio, mes, d)));
    if (r) maximo = Math.max(maximo, Math.abs(r.ganancia));
  }
  // En una pantalla estrecha la cifra va con un decimal menos para que quepa entera.
  const estrecho = caja.clientWidth > 0 && caja.clientWidth < 460;
  const decimales = (v) => (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? (estrecho ? 0 : 1) : estrecho ? 1 : 2);
  const botones = [];
  for (let d = 1; d <= diasMes; d++) {
    const fecha = new Date(anio, mes, d);
    const clave = f.claveDia(fecha);
    const r = porDia.get(clave);
    const b = el("button", "cal-dia");
    b.type = "button";
    b.appendChild(el("span", "cal-num", String(d)));
    if (r) {
      const s = f.signoDe(r.ganancia);
      b.classList.add(s || "plano");
      b.appendChild(el("span", "cal-cifra", f.cifra(r.ganancia, decimales(r.ganancia), true)));
      const intensidad = maximo > 0 ? 14 + 34 * Math.sqrt(Math.abs(r.ganancia) / maximo) : 14;
      b.style.setProperty("--intensidad", intensidad.toFixed(0) + "%");
      b.setAttribute("aria-label", `${f.diaSemana(fecha)}: ${f.dinero(r.ganancia, { signo: true })}`);
    } else {
      b.classList.add(clave > hoy ? "futuro" : "sin-datos");
      b.setAttribute("aria-label", `${f.diaSemana(fecha)}: ${clave > hoy ? "aún no ha llegado" : clave < primerDia ? "antes de empezar" : "sin datos"}`);
      if (clave > hoy || clave < primerDia) b.disabled = true;
    }
    if (clave === hoy) b.classList.add("hoy");
    if (clave === elegido) b.setAttribute("aria-pressed", "true");
    b.addEventListener("click", () => alElegir(clave));
    botones.push(b);
    rejilla.appendChild(b);
  }
  caja.appendChild(rejilla);
}

// ── piezas pequeñas ───────────────────────────────────────────────────────────

/** Barra de partes de un todo: cada parte con su cuota escrita dentro si cabe. */
export function segmentos(caja, partes) {
  caja.replaceChildren();
  const total = partes.reduce((s, p) => s + Math.max(0, p.valor), 0);
  if (!(total > 0)) return;
  const barra = el("div", "segmentos-barra");
  const nombre = partes.map((p) => `${p.nombre} ${f.pctFraccion(p.valor / total)}`).join(", ");
  barra.setAttribute("role", "img");
  barra.setAttribute("aria-label", nombre);
  for (const p of partes) {
    if (!(p.valor > 0)) continue;
    const parte = el("div", "segmento");
    parte.style.flexGrow = String(p.valor / total);
    parte.style.background = p.color;
    parte.title = `${p.nombre}: ${f.pctFraccion(p.valor / total)}`;
    const t = el("span", "segmento-texto" + (p.textoOscuro ? " oscuro" : ""), f.pctFraccion(p.valor / total));
    parte.appendChild(t);
    barra.appendChild(parte);
  }
  caja.appendChild(barra);
  requestAnimationFrame(() => {
    for (const parte of barra.children) {
      const t = parte.firstChild;
      if (t && t.offsetWidth + 14 > parte.clientWidth) t.hidden = true;
    }
  });
}

/** Línea pequeña de la última semana; el punto final lleva el color de cómo va. */
export function minilinea(valores, { ancho = 112, alto = 32, signo = "" } = {}) {
  const svg = nodo("svg", { viewBox: `0 0 ${ancho} ${alto}`, width: ancho, height: alto, class: "minilinea", "aria-hidden": "true" });
  const vs = valores.filter(f.valido);
  if (vs.length < 2) return svg;
  const lo = Math.min(...vs), hi = Math.max(...vs);
  const X = (i) => 2 + i / (valores.length - 1) * (ancho - 8);
  const Y = (v) => 3 + (hi - v) / Math.max(1e-12, hi - lo) * (alto - 6);
  nodo("path", { class: "minilinea-trazo", d: trazo(valores.map((_, i) => i), valores, X, Y) }, svg);
  nodo("circle", { class: "minilinea-fin " + signo, cx: r1(X(valores.length - 1)), cy: r1(Y(valores.at(-1))), r: 3 }, svg);
  return svg;
}

/** Medidor de tendencia de −1 a +1 desde el centro. */
export function medidor(valor) {
  const caja = el("div", "medidor");
  const pista = el("div", "medidor-pista");
  if (f.valido(valor)) {
    const barra = el("div", "medidor-barra " + (valor >= 0 ? "pos" : "neg"));
    barra.style.width = (Math.min(1, Math.abs(valor)) * 50).toFixed(1) + "%";
    pista.appendChild(barra);
  }
  caja.append(pista, el("span", "medidor-numero", f.valido(valor) ? f.cifra(valor, 2, true) : "—"));
  return caja;
}

/** Los diez relojes: seis cruces de medias y cuatro canales. Lleno = a favor; hueco = sin señal. */
export function relojes(r) {
  const caja = el("div", "relojes");
  if (!r) return caja;
  const grupo = (lista, nombre) => {
    const g = el("span", "relojes-grupo");
    g.title = nombre;
    for (const v of lista) g.appendChild(el("span", "reloj " + (v > 0 ? "pos" : v < 0 ? "neg" : "cero")));
    return g;
  };
  const a = r.cruces.filter((v) => v > 0).length + r.rupturas.filter((v) => v > 0).length;
  const total = r.cruces.length + r.rupturas.length;
  caja.setAttribute("aria-label", `${a} de ${total} relojes a favor`);
  caja.setAttribute("role", "img");
  caja.append(grupo(r.cruces, "Cruces de medias (de 2/8 a 16/64 días)"),
              grupo(r.rupturas, "Rupturas de canal (5, 10, 20 y 40 días)"));
  return caja;
}
