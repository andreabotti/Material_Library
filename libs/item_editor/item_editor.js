// Add / Edit Item — browser-side form (Streamlit CCv2).
//
// The whole draft lives here: typing, picking, switching tabs, the status
// pills, tab counters, Summary matrix, d/ρ/m_A sync, EPD-variant derivation and
// the GWP conversion panel are all computed in the browser. Python is only
// reached through the `action` trigger (save / delete / select / probe /
// open_voc). The draft is reloaded from `data.record` only when its `token`
// changes, so reruns caused by other parts of the page never wipe edits.
//
// The rules ported from Python are marked with the function they mirror —
// keep the two in step (libs/lib_revalu_map.py, libs/lib_epd_family.py,
// pages/13_Add_Edit_Item.py).

const INSTANCES = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".ie-root");
  if (!root) return;
  let ed = INSTANCES.get(parentElement);
  if (!ed) {
    ed = new Editor(root);
    INSTANCES.set(parentElement, ed);
  }
  ed.trigger = setTriggerValue;
  ed.update(data || {});
}

// ── small helpers ──────────────────────────────────────────────────────────
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// **bold**, *italic* and `code` only — enough for the messages Python and the banners send.
const md = (s) =>
  esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  }
  return el;
}

const str = (v) => (v === null || v === undefined ? "" : String(v));
const NUM_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
// lib_revalu_map._NUMERIC_EMPTY_TOKENS
const NUM_EMPTY = new Set(["", "-", "–", "—", "nan", "none", "<na>", "n/a", "na", "n/r", "nr"]);
// lib_epd_family._NULL_TOKENS
const EPD_NULL = new Set(["", "nan", "none", "<na>", "-", "n/a", "n/r", "na", "nr", "*"]);

function toNum(v, empties = NUM_EMPTY) {
  if (v === null || v === undefined || typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const s = String(v).trim();
  if (empties.has(s.toLowerCase())) return null;
  const t = s.replaceAll(",", ".");
  if (!NUM_RE.test(t)) return null;
  const f = parseFloat(t);
  return Number.isFinite(f) ? f : null;
}
const epdNum = (v) => toNum(v, EPD_NULL);
const round10 = (x) => Number(x.toPrecision(10));

// Compact number for read-outs (GWP panel: _gwp_panel_fmt).
function fmtG(v, dash = "—") {
  if (v === null || v === undefined) return dash;
  const a = Math.abs(v);
  if (a && (a < 1e-4 || a >= 1e7)) return v.toExponential(3);
  return Number(v.toPrecision(6)).toLocaleString("en-US", { maximumFractionDigits: 10 });
}
// _epd_fmt: 10 significant digits, no float noise.
const fmtEpd = (v) => (v === null || v === undefined ? "" : typeof v === "number" ? String(round10(v)) : String(v));

function externalHref(url) {
  const u = str(url).trim();
  if (!u || ["-", "nan", "None", "<NA>"].includes(u)) return null;
  if (/^https?:\/\//i.test(u)) return u;
  if (!u.includes("://")) return "https://" + u.replace(/^\/+/, "");
  return u;
}
const DOC_PLACEHOLDERS = new Set(["-", "–", "—", "n/a", "na", "n/r", "nr", "nan", "none", "<na>", "*"]);
const usableUrl = (v) => {
  const s = str(v).trim();
  return !!s && !DOC_PLACEHOLDERS.has(s.toLowerCase());
};
// _url_ready_to_probe: skip partial URLs while the user is still typing.
function urlReady(url) {
  const href = externalHref(url);
  if (!href || !usableUrl(href)) return false;
  try {
    const host = new URL(href).host.toLowerCase();
    return !!host && host.includes(".");
  } catch (e) {
    return false;
  }
}

// lib_revalu_map.normalize_optional_pct
function normPct(v) {
  if (v === null || v === undefined) return "";
  const s = String(v).trim();
  if (!s || ["nan", "none", "-", "–", "—", "<na>"].includes(s.toLowerCase())) return "";
  const low = s.toLowerCase().replaceAll(" ", "");
  if (["n/d", "nd", "notdeclared", "not_declared"].includes(low)) return "n/d";
  if (["n/a", "na", "n/r", "nr"].includes(low)) return "n/a";
  const f = toNum(s, new Set());
  if (f === null) return s;
  return f.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

// EPD families (lib_epd_family) ────────────────────────────────────────────
const REG_COL = "E__EPD_RegNumber";
const REF_FLAG_COL = "E__EPD_ConvFactor";
const FACTOR_COL = "E__EPD_MultFactor";
const GWP_MODULE_COLS = [
  "G__GWP_A1A3", "G__GWP_A1", "G__GWP_A2", "G__GWP_A3", "G__GWP_A4", "G__GWP_A5",
  "G__GWP_B1", "G__GWP_B2", "G__GWP_B3", "G__GWP_B4", "G__GWP_B5", "G__GWP_B6", "G__GWP_B7",
  "G__GWP_C1", "G__GWP_C2", "G__GWP_C3", "G__GWP_C4", "G__GWP_D",
];
const GWP_COPY_COLS = ["G__GWP_Metric", "G__GWP_FU"];
const GWP_BASIS_COLS = ["G__GWP_A1A3_kg", "G__GWP_A1A3_m3", "G__GWP_A1A3_m2", "G__GWP_A1A3_m2R1"];
const PHYS_INPUTS = {
  rho: ["P__Mass_kgm3", "E__EPD_Density"],
  d_mm: ["P__Thick_mm", "E__EPD_Thick_mm"],
  lam: ["P__L_WmK", "E__L_WmK"],
  m_a: ["P__Mass_kgm2", ""],
  r: ["E__Rvalue", ""],
};
const FU_ANCHORS = {
  m3: ["G__GWP_A1A3_m3", 1.0], m2: ["G__GWP_A1A3_m2", 1.0], kg: ["G__GWP_A1A3_kg", 1.0],
  ton: ["G__GWP_A1A3_kg", 0.001], tonne: ["G__GWP_A1A3_kg", 0.001], t: ["G__GWP_A1A3_kg", 0.001],
  m2_r1: ["G__GWP_A1A3_m2R1", 1.0],
};

function normReg(v) { // fn620_normalise_reg
  const s = str(v).replace(/\s+/g, "").toUpperCase();
  return EPD_NULL.has(s.toLowerCase()) ? "" : s;
}
function epdFlag(v) {
  const s = str(v).trim().toUpperCase();
  return { YES: "Y", NO: "N", SI: "Y", "SÌ": "Y" }[s] || s;
}
function normFu(v) {
  return str(v).trim().toLowerCase().replaceAll("³", "3").replaceAll("²", "2")
    .replaceAll("m^3", "m3").replaceAll("m^2", "m2").replaceAll(" ", "");
}
function physOf(row, key) {
  const [p, f] = PHYS_INPUTS[key];
  let v = epdNum(row[p]);
  if (v === null && f) v = epdNum(row[f]);
  return v;
}
// fn627_derive_gwp_bases
function deriveBases(decl, fu, { rho = null, d_mm = null, lam = null, m_a = null, r = null }) {
  const out = Object.fromEntries(GWP_BASIS_COLS.map((c) => [c, null]));
  const [anchorCol, anchorFactor] = FU_ANCHORS[normFu(fu)] || ["", 0];
  if (decl === null || !anchorCol) return out;
  const anchor = decl * anchorFactor;
  const d = d_mm === null ? null : d_mm / 1000;
  if (m_a === null && rho !== null && d !== null) m_a = rho * d;
  if (r === null && d !== null && lam) r = d / lam;
  let g3 = null;
  if (anchorCol === "G__GWP_A1A3_m3") g3 = anchor;
  else if (anchorCol === "G__GWP_A1A3_kg" && rho !== null) g3 = anchor * rho;
  else if (anchorCol === "G__GWP_A1A3_m2" && d) g3 = anchor / d;
  else if (anchorCol === "G__GWP_A1A3_m2R1" && lam) g3 = anchor / lam;
  const gKg = g3 !== null && rho ? g3 / rho : anchorCol === "G__GWP_A1A3_kg" ? anchor : null;
  let gM2 = null;
  if (g3 !== null && d !== null) gM2 = g3 * d;
  else if (gKg !== null && m_a !== null) gM2 = gKg * m_a;
  let gM2r1 = null;
  if (g3 !== null && lam !== null) gM2r1 = g3 * lam;
  else if (gM2 !== null && r) gM2r1 = gM2 / r;
  Object.assign(out, { G__GWP_A1A3_kg: gKg, G__GWP_A1A3_m3: g3, G__GWP_A1A3_m2: gM2, G__GWP_A1A3_m2R1: gM2r1 });
  out[anchorCol] = anchor;
  return out;
}
const blankish = (v) => v === null || v === undefined || ["", "nan", "<NA>"].includes(String(v).trim());
// fn628_variant_gwp_values
function variantValues(reference, factor, variant) {
  const out = {};
  for (const c of GWP_COPY_COLS) out[c] = blankish(reference[c]) ? null : reference[c];
  for (const c of GWP_MODULE_COLS) {
    const refV = reference[c];
    const n = epdNum(refV);
    if (n !== null) out[c] = round10(n * factor);
    else if (refV === null || refV === undefined) out[c] = null;
    else out[c] = refV;
  }
  const decl = epdNum(out.G__GWP_A1A3);
  const phys = Object.fromEntries(Object.keys(PHYS_INPUTS).map((k) => [k, physOf(variant, k)]));
  const bases = deriveBases(decl, out.G__GWP_FU, phys);
  const oldDecl = epdNum(variant.G__GWP_A1A3);
  for (const [c, v0] of Object.entries(bases)) {
    let v = v0;
    if (v === null && decl !== null && oldDecl) {
      const oldV = epdNum(variant[c]);
      v = oldV === null ? null : (oldV * decl) / oldDecl;
    }
    out[c] = v === null ? null : round10(v);
  }
  return out;
}
function sameVal(a, b) { // lib_epd_family._same
  const na = epdNum(a), nb = epdNum(b);
  if (na !== null || nb !== null) {
    if (na === null || nb === null) return false;
    return Math.abs(na - nb) <= Math.max(1e-9 * Math.max(Math.abs(na), Math.abs(nb)), 1e-12);
  }
  if (blankish(a) && blankish(b)) return true;
  return str(a).trim() === str(b).trim();
}

const STATUS_TEXT = { filled: "● Filled", missing: "● Missing", not_relevant: "● Not relevant" };
const SIDE_FIELDS = new Set(["U__ProductInfo_URL", "U__TechDetails_URL", "U__Img_URL"]);
const SYNC_COLS = ["P__Thick_mm", "P__Mass_kgm3", "P__Mass_kgm2"];
const VOC_CERT_NR_LOCK = new Set(["VO__VOC_Cert_No", "VO__Exp_Date"]);
const VOC_DATA_RELEVANT_COL = "VO__Data_Relevant";
const GWP_TOL = 0.02;

function vocCertIsNr(v) {
  const s = str(v).trim().toLowerCase().replace(/\\/g, "/");
  if (!s) return false;
  return s === "n/r" || s === "nr" || s.startsWith("n/r ") || s.startsWith("nr ");
}

function vocDataIsNr(v) {
  return str(v).trim().toLowerCase() === "no";
}

// ── the editor ─────────────────────────────────────────────────────────────
class Editor {
  constructor(root) {
    this.root = root;
    this.token = undefined;
    this.schemaSig = undefined;
    this.pickerSig = undefined;
    this.values = {};
    this.initial = {};
    this.pctMode = {};
    this.ctrls = {};
    this.activeTab = "summary";
    this.flashSeen = undefined;
    this.flash = null;
    this.localFlash = null;
    this.probes = {};
    this.requested = new Set();
    this.saving = false;
    this.confirmDelete = false;
    this.derived = {};
    root.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (this.record) this.save();
      }
    });
  }

  send(payload) {
    if (this.trigger) this.trigger("action", { ...payload, nonce: Date.now() + Math.random() });
  }

  // ── data from Python ────────────────────────────────────────────────────
  update(data) {
    this.data = data;
    this.section = data.section || "add";
    this.S = data.schema || {};
    this.F = this.S.fields || {};
    let rebuild = false;
    if (data.schema_sig !== this.schemaSig) {
      this.schemaSig = data.schema_sig;
      this.indexSchema();
      rebuild = true;
    }
    const rec = data.record || null;
    const tok = rec ? rec.token : `none:${this.section}`;
    if (tok !== this.token) {
      this.token = tok;
      this.record = rec;
      this.loadRecord(rec);
      this.confirmDelete = false;
      this.localFlash = null;
      rebuild = true;
    }
    this.probes = data.probes || {};
    if (data.flash && data.flash.nonce !== this.flashSeen) {
      this.flashSeen = data.flash.nonce;
      this.flash = data.flash;
      this.localFlash = null;
    }
    this.saving = false;
    if (rebuild || !this.built) this.build();
    else {
      this.renderPicker();
      this.refresh();
      this.refreshUrlBadges();
    }
  }

  indexSchema() {
    const cats = this.S.categories || [];
    const seen = new Set();
    this.allFields = [];
    for (const c of cats) for (const f of c.fields) if (!seen.has(f)) { seen.add(f); this.allFields.push(f); }
    this.phys = new Set(this.S.phys || []);
    this.vocFields = new Set(this.S.voc_fields || []);
    this.vocNrTypes = new Set(this.S.voc_nr_types || []);
    this.cementTypes = new Set(this.S.cement_types || []);
    this.cementOnly = new Set(this.S.cement_only || []);
    this.conceptCols = new Set(this.S.concept_cols || []);
    const nr = this.S.concept_nr || {};
    this.conceptNr = {};
    this.conceptNrLower = {};
    for (const [pt, cols] of Object.entries(nr)) {
      this.conceptNr[pt] = new Set(cols);
      this.conceptNrLower[pt.toLowerCase()] = this.conceptNr[pt];
    }
    this.numberFields = new Set(Object.entries(this.F).filter(([, m]) => m.kind === "number").map(([c]) => c));
    this.pctFields = new Set(Object.entries(this.F).filter(([, m]) => m.kind === "optpct").map(([c]) => c));
  }

  loadRecord(rec) {
    this.values = { ...((rec && rec.values) || {}) };
    this.applyVocCertNrLock();
    this.applyVocDataNrLock();
    this.initial = { ...this.values };
    this.pctMode = {};
    for (const c of this.pctFields || []) {
      const n = normPct(this.values[c]);
      this.pctMode[c] = n === "n/d" || n === "n/a" ? n : n ? "value" : "";
    }
  }

  // ── rules ported from lib_revalu_map ────────────────────────────────────
  productType() { return str(this.values.D__ProductType_ENG).trim(); }
  vocTypeLocked(pt) { return this.vocNrTypes.has(str(pt).trim()); }
  vocDataNr() { return vocDataIsNr(this.values[VOC_DATA_RELEVANT_COL]); }
  vocLocked(pt) { return this.vocTypeLocked(pt) || this.vocDataNr(); }
  vocCertNr() { return vocCertIsNr(this.values.VO__VOC_Cert); }
  conceptNrFor(pt) {
    const p = str(pt).trim();
    return this.conceptNr[p] || this.conceptNrLower[p.toLowerCase()] || this.conceptNr[""] || new Set();
  }
  relevance(col, pt) { // field_relevance
    if (this.vocFields.has(col) && this.vocLocked(pt)) return "not_relevant";
    if (VOC_CERT_NR_LOCK.has(col) && this.vocCertNr()) return "not_relevant";
    if (col === "U__TechDetails_URL") return "relevant";
    if (!this.conceptCols.has(col)) return "unknown";
    return this.conceptNrFor(pt).has(col) ? "not_relevant" : "relevant";
  }
  typeDisabled(col, pt) { // field_disabled_for_product_type
    if (this.vocFields.has(col) && this.vocLocked(pt)) return true;
    if (VOC_CERT_NR_LOCK.has(col) && this.vocCertNr()) return true;
    if (this.conceptCols.has(col) && this.relevance(col, pt) === "not_relevant") return true;
    if (!this.cementOnly.has(col)) return false;
    const p = str(pt).trim();
    if (this.cementTypes.has(p)) return false;
    const low = p.toLowerCase();
    return !["concrete", "grouting", "cement"].some((t) => low.includes(t));
  }
  status(col, v, pt) { // field_status
    if (this.relevance(col, pt) === "not_relevant") return "not_relevant";
    if (this.pctFields.has(col)) {
      const n = normPct(v);
      if (!n) return "missing";
      if (n === "n/d" || n === "n/a") return "filled";
      return toNum(n) !== null ? "filled" : "missing";
    }
    if (this.numberFields.has(col)) return toNum(v) !== null ? "filled" : "missing";
    const s = str(v).trim();
    return ["", "-", "nan", "None", "<NA>"].includes(s) ? "missing" : "filled";
  }
  effVal(col) {
    if (col in this.derived) return this.derived[col];
    if (col === VOC_DATA_RELEVANT_COL && this.vocTypeLocked(this.productType())) return "No";
    if (this.vocFields.has(col) && this.vocLocked(this.productType())) return this.S.voc_nr_value || "n/r";
    if (VOC_CERT_NR_LOCK.has(col) && this.vocCertNr()) return this.S.voc_nr_value || "n/r";
    return this.values[col];
  }
  applyVocCertNrLock() {
    if (!this.vocCertNr()) return;
    const nr = this.S.voc_nr_value || "n/r";
    for (const col of VOC_CERT_NR_LOCK) this.values[col] = nr;
  }
  applyVocDataNrLock() {
    if (!this.vocLocked(this.productType())) return;
    const nr = this.S.voc_nr_value || "n/r";
    for (const col of this.vocFields) this.values[col] = nr;
    if (this.vocTypeLocked(this.productType())) this.values[VOC_DATA_RELEVANT_COL] = "No";
  }
  counts(fields, pt) {
    const c = { filled: 0, missing: 0, not_relevant: 0 };
    for (const f of fields) c[this.status(f, this.effVal(f), pt)] += 1;
    return c;
  }
  label(col) { return (this.F[col] && this.F[col].label) || col; }

  // ── EPD family context (_epd_context) ───────────────────────────────────
  epdContext() {
    const row = this.values;
    const reg = row[REG_COL];
    const key = normReg(reg);
    const selfId = this.record ? str(this.record.eid) : "";
    const epd = this.S.epd || { refs: {}, variants: {} };
    const others = (list) => (list || []).filter((r) => str(r.id) !== selfId);
    const ctx = { role: null, reg, derived: {} };
    const flag = epdFlag(row[REF_FLAG_COL]);
    if (flag === "Y") {
      ctx.role = "reference";
      if (!key) {
        ctx.note = "Enter the **EPD Registration Number** to link the other products covered by this EPD.";
        return ctx;
      }
      const refs = others(epd.refs[key]);
      if (refs.length) {
        ctx.note = `Another product with EPD \`${reg}\` is also flagged **Y**` +
          (refs.length === 1 ? ` (**${refs[0].name}**)` : "") +
          " — the family has no single reference product, so nothing is propagated on save. Set the other product(s) to N.";
        return ctx;
      }
      ctx.family = others(epd.variants[key]);
      ctx.plan = [];
      for (const v of ctx.family) {
        const factor = epdNum(v[FACTOR_COL]);
        if (factor === null) continue;
        const nv = variantValues(row, factor, v);
        const changed = Object.keys(nv).filter((c) => !sameVal(v[c], nv[c]));
        if (changed.length) ctx.plan.push({ id: v.id, name: v.name, factor, before: v.G__GWP_A1A3, after: nv.G__GWP_A1A3, n: changed.length });
      }
      return ctx;
    }
    if (flag !== "N") return ctx;
    ctx.role = "variant";
    const factor = epdNum(row[FACTOR_COL]);
    const refs = key ? others(epd.refs[key]) : [];
    if (!key) ctx.note = "Enter the **EPD Registration Number** to find this EPD's reference product.";
    else if (!refs.length) ctx.note = `No product with EPD \`${reg}\` is flagged **Y** (reference) yet — GWP data stay editable until the reference product is saved.`;
    else if (refs.length > 1) ctx.note = `More than one product with EPD \`${reg}\` is flagged **Y** — fix the reference flag before GWP data can be derived.`;
    else if (factor === null) ctx.note = "Enter the **EPD Multiplication Factor** (EPD Metadata tab) to derive the GWP data from the reference product.";
    if (ctx.note) return ctx;
    ctx.reference = refs[0];
    ctx.factor = factor;
    ctx.derived = variantValues(refs[0], factor, row);
    return ctx;
  }

  // ── thickness / density / m_A (_sync_thickness_density) ─────────────────
  syncPhys() {
    const v = this.values;
    const num = (k) => toNum(v[k], new Set([""]));
    const cm = (k) => str(v[k + "_CM"]).trim().toUpperCase();
    const [dK, rK, mK] = SYNC_COLS;
    const manual = SYNC_COLS.filter((k) => cm(k) === "M" && num(k) !== null);
    if (manual.length !== 2) return;
    const d = num(dK), rho = num(rK), mA = num(mK);
    let target, result;
    if (!manual.includes(mK)) {
      if (d === null || rho === null) return;
      [target, result] = [mK, (rho * d) / 1000];
    } else if (!manual.includes(rK)) {
      if (!d || mA === null) return;
      [target, result] = [rK, (mA * 1000) / d];
    } else {
      if (!rho || mA === null) return;
      [target, result] = [dK, (mA * 1000) / rho];
    }
    const tcm = cm(target);
    if (tcm === "M") return;
    if (tcm !== "C" && num(target) !== null) return;
    const s = result.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    if (v[target] === s && tcm === "C") return;
    v[target] = s;
    v[target + "_CM"] = "C";
    const c = this.ctrls[target];
    if (c) { c.setDisplay(s); if (c.setCm) c.setCm("C"); }
  }

  // ── build DOM ───────────────────────────────────────────────────────────
  build() {
    this.built = true;
    this.ctrls = {};
    this.root.innerHTML = "";
    this.tipEl = null;
    this.flashEl = h("div", { class: "ie-flash" });
    this.topEl = h("div", { class: "ie-top" });
    this.bodyEl = h("div", { class: "ie-body" });
    this.root.append(this.topEl, this.flashEl, this.bodyEl);
    this.pickerSig = undefined;
    this.renderPicker();
    if (!this.record) {
      this.bodyEl.append(h("div", { class: "ie-msg ie-msg-info", text: "Pick a product above to load and edit its data." }));
      this.renderFlash();
      return;
    }
    // Sticky bar: tabs on the left, save / discard / delete on the right.
    this.tabsEl = h("div", { class: "ie-tabs", role: "tablist" });
    this.actionsEl = h("div", { class: "ie-actions" });
    this.confirmEl = h("div", { class: "ie-confirm" });
    this.bodyEl.append(h("div", { class: "ie-bar" }, this.tabsEl, this.actionsEl), this.confirmEl);
    this.panels = {};
    this.panels.summary = h("div", { class: "ie-panel", "data-tab": "summary" });
    this.bodyEl.append(this.panels.summary);
    this.wireSummaryLinks(this.panels.summary);
    for (const cat of this.S.categories || []) {
      const p = h("div", { class: "ie-panel", "data-tab": cat.key });
      this.buildCategory(cat, p);
      this.panels[cat.key] = p;
      this.bodyEl.append(p);
    }
    this.buildActions();
    this.refresh();
    this.refreshUrlBadges();
  }

  renderPicker() {
    if (this.section !== "edit") {
      if (this.topEl) this.topEl.style.display = "none";
      return;
    }
    const pk = this.data.picker || { items: [] };
    const sig = `${pk.items.length}:${pk.items.length ? pk.items[0][0] + pk.items[pk.items.length - 1][0] : ""}:${this.record ? this.record.eid : ""}:${pk.caption || ""}`;
    if (sig === this.pickerSig) return;
    this.pickerSig = sig;
    this.topEl.innerHTML = "";
    this.topEl.style.display = "";
    const labelById = new Map(pk.items);
    const current = this.record ? labelById.get(str(this.record.eid)) || this.record.title || "" : "";
    const combo = makeCombo({
      value: current,
      placeholder: "Search by manufacturer, product name or ID…",
      items: pk.items.map(([id, lbl]) => ({ value: id, label: lbl })),
      allowNew: false,
      tokens: true,
      onPick: (it) => {
        if (this.record && str(this.record.eid) === str(it.value)) return;
        if (this.dirtyCount() && !window.confirm("Discard unsaved changes to the current item?")) {
          combo.setValue(current);
          return;
        }
        this.send({ type: "select", eid: it.value });
      },
    });
    const row = h("div", { class: "ie-pick-row" },
      h("div", { class: "ie-pick" }, h("label", { class: "ie-lab", text: "Select item to edit" }), combo.el),
      this.record ? h("div", { class: "ie-editing", html: `Editing <code>${esc(this.record.eid)}</code>` }) : null,
    );
    this.topEl.append(row);
    if (pk.caption) this.topEl.append(h("div", { class: "ie-caption", html: md(pk.caption) }));
  }

  buildActions() {
    const isAdd = this.section === "add";
    this.dirtyEl = h("span", { class: "ie-dirty" });
    this.discardBtn = h("button", { class: "ie-btn", type: "button", text: "Discard changes", onclick: () => this.discard() });
    this.saveBtn = h("button", {
      class: "ie-btn ie-btn-primary", type: "button", title: "Ctrl+S",
      text: isAdd ? "Save new item" : "Save changes", onclick: () => this.save(),
    });
    this.actionsEl.append(this.dirtyEl, this.discardBtn);
    if (!isAdd) {
      this.deleteBtn = h("button", {
        class: "ie-btn ie-btn-danger-ghost", type: "button", text: "Delete item",
        onclick: () => { this.confirmDelete = true; this.renderConfirm(); },
      });
      this.actionsEl.append(this.deleteBtn);
    }
    this.actionsEl.append(this.saveBtn);
  }

  renderConfirm() {
    const el = this.confirmEl;
    if (!el) return;
    el.innerHTML = "";
    if (this.deleteBtn) this.deleteBtn.disabled = this.confirmDelete;
    if (!this.confirmDelete || !this.record) return;
    const v = this.initial;
    const name = str(v.A__ProductName).trim() || "this item";
    const manu = str(v.A__Manufacturer).trim();
    const title = manu ? `${manu} — ${name}` : name;
    el.append(h("div", { class: "ie-msg ie-msg-warning" },
      h("div", { html: `⚠️ Delete <b>${esc(title)}</b> (<code>${esc(this.record.eid)}</code>)?<br>It disappears from the Catalogue, Charts, Maps and every export on the next rerun.` }),
      h("div", { class: "ie-caption", html: "Recorded as a <code>delete</code> record in <code>edits_data.parquet</code>, keeping a full snapshot of the row. <code>base_data.parquet</code> is not modified, so the item can be restored by removing that record from the edit log." }),
      h("div", { class: "ie-row-btns" },
        h("button", { class: "ie-btn ie-btn-danger", type: "button", text: "Yes, delete this item", onclick: () => this.send({ type: "delete", eid: this.record.eid }) }),
        h("button", { class: "ie-btn", type: "button", text: "Cancel", onclick: () => { this.confirmDelete = false; this.renderConfirm(); } }),
      ),
    ));
  }

  buildCategory(cat, panel) {
    // Health tab: the VOC groups swap between editable and locked n/r; the
    // health-declaration groups below them stay editable for every product type.
    let vocPanel = null;
    const vocFields = new Set(this.S.voc_fields || []);
    if (cat.key === "vo") {
      this.vocLockEl = h("div", { class: "ie-voc-locked" });
      this.vocEditEl = h("div");
      panel.append(this.vocLockEl, this.vocEditEl);
      this.buildVocLocked(cat, this.vocLockEl);
      vocPanel = this.vocEditEl;
    }
    if (cat.key === "gwp") {
      this.bannerEl = h("div", { class: "ie-banner" });
      panel.append(this.bannerEl);
    }
    const fields = new Set(cat.fields);
    if (cat.field_groups) {
      for (const g of cat.field_groups) {
        const gf = (g.fields || []).filter((f) => fields.has(f));
        const isVoc = vocPanel && gf.length && gf.every((f) => vocFields.has(f));
        if (gf.length) this.buildGroup(g, gf, isVoc ? vocPanel : panel);
      }
    } else {
      const bottom = (cat.bottom_fields || []).filter((f) => fields.has(f));
      const main = cat.fields.filter((f) => !bottom.includes(f));
      if (main.length) this.buildGroup({ columns_per_row: cat.columns_per_row || 3 }, main, panel);
      if (bottom.length) this.buildGroup({ columns_per_row: cat.bottom_columns_per_row || 1 }, bottom, panel);
    }
    if (cat.key === "gwp") {
      this.gwpPanelEl = h("div", { class: "ie-gwp" });
      panel.append(this.gwpPanelEl);
    }
  }

  sectionTitle(title, { divider = false, marginTop = null, page = true } = {}) {
    const el = h("div", { class: "ie-section" + (divider ? " ie-section-div" : "") + (page ? " ie-section-page" : "") , text: title });
    if (marginTop) el.style.marginTop = marginTop;
    return el;
  }

  buildGroup(g, gf, panel) {
    if (g.section_title) {
      panel.append(this.sectionTitle(g.section_title, {
        divider: !!g.section_divider,
        marginTop: g.section_margin_top || null,
        page: str(g.section_title_style).toLowerCase() === "page_title",
      }));
    }
    const labels = g.field_labels || {};
    // Identity side-label rows: one full-width row each.
    let rest = [];
    const flush = () => {
      if (rest.length) this.appendGrid(g, rest, panel, labels);
      rest = [];
    };
    for (const f of gf) {
      if (SIDE_FIELDS.has(f)) {
        flush();
        if (f === "U__ProductInfo_URL") panel.append(this.sectionTitle("Product Info URLs", { divider: true }));
        panel.append(this.makeSideField(f));
      } else rest.push(f);
    }
    flush();
    if (g.rating_alignment) {
      this.alignEl = h("div", { class: "ie-align" });
      panel.append(this.alignEl);
      this.refreshRatingAlignment();
    }
    if (g.derived_checklist) {
      this.checklistEl = h("div", { class: "ie-checklist" });
      panel.append(this.checklistEl);
      this.refreshDerivedChecklist();
    }
  }

  // How the chosen VOC claim reads against LEED v4.1, WELL v2 and CAM 2025.
  // The lookup (label and aliases → statuses) is built in Python from
  // aux_12__voc_rating_alignment.json, so the rule lives in one place.
  refreshRatingAlignment() {
    const el = this.alignEl;
    if (!el) return;
    const MARK = { yes: "✓", partial: "~", no: "—", unknown: "?", na: "·" };
    const cert = str(this.values.VO__VOC_Cert).trim();
    el.textContent = "";
    if (!cert || vocCertIsNr(cert)) return;
    const frameworks = this.S.voc_frameworks || [];
    if (!frameworks.length) return;
    const rows = (this.S.voc_align || {})[cert.toLowerCase()];
    const pills = h("div", { class: "ie-align-pills" },
      h("span", { class: "ie-align-lbl", text: "Alignment" }));
    if (!rows) {
      for (const fw of frameworks) {
        pills.append(h("span", { class: "ie-al ie-al-unknown", text: `${fw.short} ?` }));
      }
      el.append(pills, h("div", { class: "ie-align-note ie-align-miss",
        text: "Not in the VOC catalogue — no reading against the schemes." }));
      return;
    }
    const notes = h("div", { class: "ie-align-note" });
    for (const r of rows) {
      const p = h("span", { class: `ie-al ie-al-${r.status}`, text: `${r.short} ${MARK[r.status] || "—"}` });
      p.title = `${r.label} — ${r.credit}`;
      pills.append(p);
      if (r.note) notes.append(h("div", {}, h("b", { text: r.short }), h("span", { text: ` · ${r.note}` })));
    }
    el.append(pills, notes);
  }

  // The three controls that are read off other fields rather than stored. The
  // rule is lib_revalu_map.voc_checklist_derived — kept in step by hand here
  // because the read-out has to update as the draft changes, without a rerun.
  refreshDerivedChecklist() {
    const el = this.checklistEl;
    if (!el) return;
    const spec = this.S.voc_checklist_derived || [];
    el.textContent = "";
    for (const [label, col] of spec) {
      const raw = str(this.effVal ? this.effVal(col) : this.values[col]).trim();
      const low = raw.toLowerCase();
      let answer;
      if (low === "n/r" || low === "nr") answer = "n/r";
      else if (!low || ["-", "nan", "none", "<na>", "n/a", "na", "*"].includes(low)) {
        answer = col === "VO__LEED_Pathway" ? "Unknown" : "No";
      } else if (col === "VO__LEED_Pathway") {
        answer = low.includes("voc content") ? "Yes" : "No";
      } else answer = "Yes";
      const srcLabel = (this.F[col] || {}).label || col;
      el.append(h("div", { class: "ie-checklist-item" },
        h("b", { class: `ie-chk-${answer.toLowerCase().replace("/", "")}`, text: answer }),
        h("span", { text: label }),
        h("em", { text: `← ${srcLabel}` })));
    }
  }

  appendGrid(g, gf, panel, labels) {
    const grid = h("div", { class: "ie-grid" });
    let cols;
    if (g.cm_under_fields) {
      const n = Math.max(gf.length, Number(g.cm_pad_slots || gf.length));
      cols = `repeat(${n}, minmax(0, 1fr))`;
      grid.classList.add("ie-grid-phys");
    } else if (g.pad_slots !== undefined && g.pad_slots !== null) {
      const n = Math.max(Number(g.pad_slots), gf.length, 1);
      const scale = Math.max(0.05, Number(g.slot_width_scale || 1));
      const w = gf.map(() => `minmax(0, ${scale}fr)`);
      const rem = n - scale * gf.length;
      if (rem > 1e-6) w.push(`minmax(0, ${rem}fr)`);
      cols = w.join(" ");
    } else if (g.column_weights && g.column_weights.length === gf.length) {
      cols = g.column_weights.map((w) => `minmax(0, ${Number(w)}fr)`).join(" ");
    } else {
      const n = Number(g.columns_per_row || gf.length || 1);
      cols = `repeat(${n}, minmax(0, 1fr))`;
    }
    grid.style.gridTemplateColumns = cols;
    for (const f of gf) {
      grid.append(g.cm_under_fields && this.phys.has(f) ? this.makePhysField(f, labels[f]) : this.makeField(f, labels[f]));
    }
    panel.append(grid);
  }

  buildVocLocked(cat, el) {
    el.append(h("div", { class: "ie-msg ie-msg-locked", html: "" }));
    const groups = cat.field_groups || [{ fields: cat.fields, columns_per_row: 3 }];
    const vocFields = new Set(this.S.voc_fields || []);
    for (const g of groups) {
      const gf = (g.fields || []).filter((f) => cat.fields.includes(f) && vocFields.has(f));
      if (!gf.length) continue;
      const grid = h("div", { class: "ie-grid" });
      grid.style.gridTemplateColumns = g.column_weights && g.column_weights.length === gf.length
        ? g.column_weights.map((w) => `minmax(0, ${w}fr)`).join(" ")
        : `repeat(${Math.max(1, Number(g.columns_per_row || gf.length))}, minmax(0, 1fr))`;
      for (const f of gf) {
        grid.append(h("div", { class: "ie-f" },
          h("div", { class: "ie-lab ie-muted", text: this.label(f) }),
          h("div", { class: "ie-locked-val", text: this.S.voc_nr_value || "n/r" })));
      }
      el.append(grid);
    }
  }

  // ── field cells ─────────────────────────────────────────────────────────
  metaHtml(col) {
    const m = this.F[col] || {};
    const violet = this.S.violet || "#8c66e0";
    if (!m.rv) return '<span class="ie-rv-none">EETRA-only</span>';
    const [name, tier] = m.rv;
    return `<span class="ie-rv" style="color:${violet}">${tier === "exact" ? "↔" : "≈"} ` +
      `<span class="ie-rv-badge" style="background:${violet}">R</span> <code style="color:${violet}">${esc(name)}</code></span>`;
  }

  labelEl(col, override) {
    const m = this.F[col] || {};
    const lab = h("label", { class: "ie-lab", text: override || this.label(col) });
    if (m.help) lab.append(h("span", { class: "ie-help", title: m.help, text: "?" }));
    return lab;
  }

  // Registers a controller for *col*; returns the cell.
  makeField(col, labelOverride) {
    const m = this.F[col] || { kind: "text" };
    const cell = h("div", { class: "ie-f", "data-col": col });
    const statusEl = h("span", { class: "ie-pill" });
    const newEl = h("span", { class: "ie-new", text: "new value" });
    const meta = h("div", { class: "ie-meta" }, statusEl, newEl, h("span", { html: this.metaHtml(col) }));
    const ctrl = { col, cell, statusEl, newEl, kind: m.kind };
    const set = (v) => this.onEdit(col, v);
    const cur = str(this.values[col]);

    if (m.kind === "combo") {
      const opts = this.optionsFor(m.opts);
      const headRow = h("div", { class: "ie-lab-row" }, this.labelEl(col, labelOverride));
      if (col === "VO__VOC_Cert") {
        headRow.append(h("button", { class: "ie-info-btn", type: "button", title: "Clarifications for all VOC certifications — highlights the selected value.", text: "ⓘ", onclick: () => this.openVocCatalog() }));
      }
      const combo = makeCombo({
        value: cur, items: opts.map((o) => ({ value: o, label: o })), allowNew: true,
        onInput: set, onPick: (it) => set(it.value),
      });
      ctrl.input = combo.input;
      ctrl.setDisplay = (v) => combo.setValue(str(v));
      ctrl.setDisabled = (b) => combo.setDisabled(b);
      ctrl.optionSet = new Set(opts.map((o) => o.toLowerCase()));
      cell.append(headRow, combo.el);
    } else if (m.kind === "readonly") {
      const inp = h("input", { class: "ie-in", type: "text", disabled: true, value: cur, placeholder: this.section === "add" ? "assigned on save" : "" });
      ctrl.input = inp;
      ctrl.setDisplay = (v) => { inp.value = str(v); };
      ctrl.setDisabled = () => {};
      cell.append(this.labelEl(col, labelOverride), inp);
    } else if (m.kind === "yn" || m.kind === "epdref" || m.kind === "checklist" || m.kind === "voc_relevant") {
      let options = m.kind === "yn" ? ["", "Y", "N"] : ["", "Y", "N", "n/r"];
      if (m.kind === "checklist") options = (this.S.voc_checklist_values || ["", "Yes", "No", "Unknown", "n/r"]).slice();
      if (m.kind === "voc_relevant") options = (this.S.voc_data_relevant_values || ["", "Yes", "No", "Not sure"]).slice();
      const fmt = m.kind === "checklist"
        ? { "": "(not reviewed)" }
        : m.kind === "voc_relevant"
        ? { "": "(blank)", Yes: "Yes — VOC data applies", No: "No — lock VOC fields to n/r", "Not sure": "Not sure — leave editable" }
        : m.kind === "yn"
        ? { "": "(blank)" }
        : { "": "(blank)", Y: "Y — reference product (factor 1)", N: "N — reference × multiplication factor" };
      if (cur && !options.includes(cur)) options = [...options, cur];
      const sel = h("select", { class: "ie-in", onchange: (e) => set(e.target.value) },
        options.map((o) => h("option", { value: o, text: fmt[o] ?? o })));
      sel.value = options.includes(cur) ? cur : "";
      ctrl.input = sel;
      ctrl.setDisplay = (v) => { sel.value = str(v); };
      ctrl.setDisabled = (b) => { sel.disabled = b; };
      cell.append(this.labelEl(col, labelOverride), sel);
    } else if (m.kind === "date") {
      const inp = h("input", { class: "ie-in", type: "date", value: cur, oninput: (e) => set(e.target.value) });
      ctrl.input = inp;
      ctrl.setDisplay = (v) => { inp.value = str(v); };
      ctrl.setDisabled = (b) => { inp.disabled = b; };
      cell.append(this.labelEl(col, labelOverride), inp);
    } else if (m.kind === "optpct") {
      const modeSel = h("select", { class: "ie-in" },
        [["", "(blank)"], ["value", "Enter %…"], ["n/d", "n/d — not declared"], ["n/a", "n/a"]].map(([v, t]) => h("option", { value: v, text: t })));
      const num = h("input", { class: "ie-in ie-num", type: "text", inputmode: "decimal", placeholder: "%" });
      const sync = () => {
        const mode = this.pctMode[col] || "";
        modeSel.value = mode;
        num.style.display = mode === "value" ? "" : "none";
        const n = normPct(this.values[col]);
        if (mode === "value" && document.activeElement !== num && num.getRootNode().activeElement !== num) num.value = n === "n/d" || n === "n/a" ? "" : n;
      };
      modeSel.addEventListener("change", () => {
        const mode = modeSel.value;
        this.pctMode[col] = mode;
        if (mode === "value") { num.value = ""; set(""); num.focus(); }
        else set(mode);
        sync();
      });
      num.addEventListener("input", () => { set(num.value); num.classList.toggle("ie-invalid", !!num.value.trim() && toNum(num.value) === null); });
      ctrl.input = modeSel;
      ctrl.setDisplay = () => sync();
      ctrl.setDisabled = (b) => { modeSel.disabled = b; num.disabled = b; };
      sync();
      cell.append(this.labelEl(col, labelOverride), h("div", { class: "ie-pct" }, modeSel, num));
    } else if (m.kind === "textarea") {
      const ta = h("textarea", { class: "ie-in", oninput: (e) => set(e.target.value) });
      ta.value = cur;
      ta.style.height = `${m.h || 90}px`;
      ctrl.input = ta;
      ctrl.setDisplay = (v) => { if (ta.value !== str(v)) ta.value = str(v); };
      ctrl.setDisabled = (b) => { ta.disabled = b; };
      cell.append(this.labelEl(col, labelOverride), ta);
    } else if (m.kind === "url" || m.kind === "voc_url") {
      const inp = h("input", { class: "ie-in", type: "text", value: cur, oninput: (e) => { set(e.target.value); this.updateUrl(col); }, onchange: () => this.requestProbe(col) });
      ctrl.input = inp;
      ctrl.setDisplay = (v) => { if (inp.value !== str(v)) inp.value = str(v); };
      ctrl.setDisabled = (b) => { inp.disabled = b; };
      ctrl.linkEl = h("span", { class: "ie-link" });
      const row = h("div", { class: "ie-url-row" }, inp, ctrl.linkEl);
      if (m.kind === "voc_url") {
        ctrl.openBtn = h("button", { class: "ie-btn ie-btn-sm", type: "button", text: "Open VOC document", onclick: () => this.send({ type: "open_voc", url: this.values[col] }) });
        row.append(ctrl.openBtn);
      }
      cell.append(this.labelEl(col, labelOverride), row);
    } else {
      // text / number (numbers are typed as text so 12,5 works as well as 12.5)
      const isNum = m.kind === "number";
      const inp = h("input", { class: "ie-in" + (isNum ? " ie-num" : ""), type: "text", inputmode: isNum ? "decimal" : null, value: cur });
      inp.addEventListener("input", () => {
        set(inp.value);
        if (isNum) inp.classList.toggle("ie-invalid", !!inp.value.trim() && toNum(inp.value) === null);
      });
      if (isNum) inp.classList.toggle("ie-invalid", !!cur.trim() && toNum(cur) === null);
      ctrl.input = inp;
      ctrl.setDisplay = (v) => { if (inp.value !== str(v)) inp.value = str(v); };
      ctrl.setDisabled = (b) => { inp.disabled = b; };
      cell.append(this.labelEl(col, labelOverride), inp);
    }
    cell.append(meta);
    this.ctrls[col] = ctrl;
    if (ctrl.linkEl) this.updateUrl(col);
    return cell;
  }

  // Physical property: value | C/M flag, status line below.
  makePhysField(col, labelOverride) {
    const cell = this.makeField(col, labelOverride);
    const ctrl = this.ctrls[col];
    const cmCol = `${col}_CM`;
    const sel = h("select", { class: "ie-in ie-cm", title: this.S.phys_cm_help || "" },
      [["", "—"], ["C", "C"], ["M", "M"]].map(([v, t]) => h("option", { value: v, text: t })));
    sel.value = str(this.values[cmCol]).toUpperCase();
    sel.addEventListener("change", () => this.onEdit(cmCol, sel.value));
    ctrl.cmSel = sel;
    ctrl.setCm = (v) => { sel.value = str(v); };
    // Re-wrap: the value input and the C/M select share one row.
    const inputEl = ctrl.input;
    const pair = h("div", { class: "ie-phys-pair" });
    inputEl.replaceWith(pair);
    pair.append(inputEl, h("div", { class: "ie-cm-wrap" }, h("span", { class: "ie-cm-lab", text: "C/M" }), sel));
    return cell;
  }

  // Identity rows: label + status | input | Test link | image preview.
  makeSideField(col) {
    const m = this.F[col] || {};
    const statusEl = h("span", { class: "ie-pill" });
    const labBlock = h("div", { class: "ie-side-lab" },
      h("div", { class: "ie-side-title", title: m.help || "", text: this.label(col) }),
      h("div", { class: "ie-meta" }, statusEl),
      h("div", { class: "ie-meta", html: this.metaHtml(col) }));
    const cur = str(this.values[col]);
    const ctrl = { col, statusEl, kind: m.kind };
    let input;
    if (col === "U__Img_URL") {
      input = h("input", { class: "ie-in", type: "text", value: cur });
    } else {
      input = h("textarea", { class: "ie-in" });
      input.value = cur;
      input.style.height = `${m.h || 90}px`;
    }
    input.addEventListener("input", () => { this.onEdit(col, input.value); if (ctrl.linkEl) this.updateUrl(col); });
    if (col !== "A__ProductDescription") input.addEventListener("change", () => this.requestProbe(col));
    ctrl.input = input;
    ctrl.setDisplay = (v) => { if (input.value !== str(v)) input.value = str(v); };
    ctrl.setDisabled = (b) => { input.disabled = b; };
    const linkCell = h("div", { class: "ie-side-link" });
    const prevCell = h("div", { class: "ie-side-prev" });
    if (col !== "A__ProductDescription") { ctrl.linkEl = h("span", { class: "ie-link" }); linkCell.append(ctrl.linkEl); }
    if (col === "U__Img_URL") { ctrl.prevEl = prevCell; }
    const cell = h("div", { class: "ie-side", "data-col": col }, labBlock, input, linkCell, prevCell);
    ctrl.cell = cell;
    this.ctrls[col] = ctrl;
    if (ctrl.linkEl) this.updateUrl(col);
    return cell;
  }

  optionsFor(key) {
    const o = (this.S.options || {})[key] || [];
    return o;
  }

  // ── URL test links, probes, image preview ───────────────────────────────
  updateUrl(col) {
    const c = this.ctrls[col];
    if (!c || !c.linkEl) return;
    const v = this.values[col];
    const href = externalHref(v);
    let badge;
    const p = this.probes[str(v).trim()] || this.probes[href || ""];
    if (!urlReady(v)) badge = `<span class="ie-probe ie-muted" title="Auto-check runs when the URL looks complete">${href ? "…" : ""}</span>`;
    else if (!p) badge = `<span class="ie-probe ie-muted" title="Checked when you leave the field">…</span>`;
    else if (p.level === "idle") badge = '<span class="ie-probe ie-muted">—</span>';
    else {
      const [cls, icon] = p.level === "ok" ? ["ok", "✓"] : p.level === "warn" ? ["warn", "⚠"] : ["err", "✗"];
      badge = `<span class="ie-probe ie-probe-${cls}" title="${esc(p.detail || "")}">${icon} ${esc(p.label || "—")}</span>`;
    }
    c.linkEl.innerHTML = href
      ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">Test link</a>${badge}`
      : `<span class="ie-muted">—</span>${badge}`;
    if (c.openBtn) c.openBtn.disabled = !usableUrl(v);
    if (c.prevEl) {
      const key = urlReady(v) ? href : "";
      if (c.prevKey !== key) {
        c.prevKey = key;
        c.prevEl.innerHTML = "";
        const ph = h("div", { class: "ie-img-ph", text: "—" });
        if (key) {
          const img = h("img", { class: "ie-img", src: key, alt: "", referrerpolicy: "no-referrer" });
          img.addEventListener("error", () => img.replaceWith(ph));
          c.prevEl.append(img);
        } else c.prevEl.append(ph);
      }
    }
  }
  refreshUrlBadges() {
    for (const c of Object.values(this.ctrls)) if (c.linkEl) this.updateUrl(c.col);
  }
  requestProbe(col) {
    const v = str(this.values[col]).trim();
    if (!urlReady(v) || this.probes[v] || this.requested.has(v)) return;
    this.requested.add(v);
    this.send({ type: "probe", urls: [{ col, url: v }] });
  }

  // ── editing ─────────────────────────────────────────────────────────────
  onEdit(col, v) {
    this.values[col] = v;
    if (col === "VO__VOC_Cert") this.applyVocCertNrLock();
    if (col === VOC_DATA_RELEVANT_COL || col === "D__ProductType_ENG") this.applyVocDataNrLock();
    if (SYNC_COLS.includes(col) || SYNC_COLS.some((s) => `${s}_CM` === col)) this.syncPhys();
    // A message about the last save / check is stale once editing resumes.
    this.localFlash = null;
    this.flash = null;
    this.refresh();
  }

  dirtyCount() {
    if (!this.record) return 0;
    const keys = new Set([...Object.keys(this.values), ...Object.keys(this.initial)]);
    let n = 0;
    for (const k of keys) if (str(this.values[k]) !== str(this.initial[k])) n += 1;
    return n;
  }

  discard() {
    if (!this.dirtyCount()) return;
    this.loadRecord(this.record);
    this.built = false;
    this.build();
  }

  collect() {
    const out = {};
    for (const col of this.allFields) {
      if ((this.F[col] || {}).kind === "readonly") continue;
      const v = this.effVal(col);
      out[col] = v === undefined ? "" : v;
    }
    for (const p of this.phys) out[`${p}_CM`] = str(this.values[`${p}_CM`]).toUpperCase();
    return out;
  }

  save() {
    if (this.saving) return;
    const v = this.collect();
    const missing = [["Manufacturer", "A__Manufacturer"], ["Product Name", "A__ProductName"], ["Product Type", "D__ProductType_ENG"]]
      .filter(([, c]) => !str(v[c]).trim()).map(([l]) => l);
    if (missing.length) {
      this.localFlash = { kind: "error", text: `Please fill in required fields: ${missing.join(", ")}.` };
      this.activeTab = "identity";
      this.refresh();
      return;
    }
    const bad = [...this.numberFields].filter((c) => str(v[c]).trim() && toNum(v[c]) === null && !(c in this.derived));
    if (bad.length) {
      this.localFlash = { kind: "error", text: `Not a number: ${bad.map((c) => this.label(c)).join(", ")}.` };
      this.refresh();
      return;
    }
    this.saving = true;
    this.localFlash = null;
    this.refresh();
    this.send({ type: "save", eid: this.record ? this.record.eid : null, values: v });
  }

  // ── refresh everything computed ─────────────────────────────────────────
  refresh() {
    if (!this.record) { this.renderFlash(); return; }
    this.refreshDerivedChecklist();
    this.refreshRatingAlignment();
    const pt = this.productType();
    const vocLocked = this.vocLocked(pt);
    const epd = this.epdContext();
    this.epd = epd;
    this.derived = epd.derived || {};
    this.applyVocCertNrLock();
    this.applyVocDataNrLock();

    for (const c of Object.values(this.ctrls)) {
      const col = c.col;
      const isDerived = col in this.derived;
      const certLock = VOC_CERT_NR_LOCK.has(col) && this.vocCertNr();
      const typeLocksData = col === VOC_DATA_RELEVANT_COL && this.vocTypeLocked(pt);
      if (isDerived) {
        c.setDisplay(fmtEpd(this.derived[col]));
        c.setDisabled(true);
        c.wasDerived = true;
      } else {
        if (c.wasDerived) { c.setDisplay(this.values[col]); c.wasDerived = false; }
        // Date inputs cannot show "n/r" — switch to text while cert-locked.
        if (c.kind === "date" && c.input) {
          if (certLock) {
            if (c.input.type === "date") {
              c.input.type = "text";
              c._wasDateInput = true;
            }
            c.setDisplay(this.S.voc_nr_value || "n/r");
          } else if (c._wasDateInput) {
            c.input.type = "date";
            c._wasDateInput = false;
            if (vocCertIsNr(this.values[col])) this.values[col] = "";
            c.setDisplay(this.values[col]);
          }
        } else if (certLock) {
          c.setDisplay(this.S.voc_nr_value || "n/r");
        }
        if (typeLocksData) c.setDisplay("No");
        const tDis = this.typeDisabled(col, pt) || typeLocksData;
        const cmC = this.phys.has(col) && c.cmSel && str(this.values[`${col}_CM`]).toUpperCase() === "C";
        c.setDisabled(tDis || cmC);
        if (c.cmSel) c.cmSel.disabled = tDis;
      }
      if (c.cell) {
        c.cell.classList.toggle("ie-derived", isDerived);
        const changed = str(this.values[col]) !== str(this.initial[col]) ||
          (c.cmSel && str(this.values[`${col}_CM`]) !== str(this.initial[`${col}_CM`]));
        c.cell.classList.toggle("ie-changed", !!changed && !isDerived);
      }
      const st = this.status(col, this.effVal(col), pt);
      c.statusEl.className = `ie-pill ie-s-${st}`;
      c.statusEl.textContent = STATUS_TEXT[st];
      if (c.newEl) {
        const v = str(this.values[col]).trim();
        c.newEl.style.display = c.optionSet && v && !c.optionSet.has(v.toLowerCase()) ? "" : "none";
      }
    }

    if (this.vocLockEl) {
      this.vocLockEl.style.display = vocLocked ? "" : "none";
      this.vocEditEl.style.display = vocLocked ? "none" : "";
      if (vocLocked) {
        this.vocLockEl.firstChild.innerHTML = this.vocTypeLocked(pt)
          ? (`🔒 <b>VOC not relevant</b> for product type “${esc(pt)}” — no product in this category can carry an indoor-air ` +
            "emission certificate, so every VOC field is fixed at <code>n/r</code> and locked. Change the <b>Product Type</b> " +
            "on the <b>Product ID</b> tab to edit these fields. Health declarations below remain editable.")
          : ("🔒 <b>VOC Data Relevant</b> is <b>No</b> — inherently non-emitting / no VOC evidence required, so every VOC " +
            "field is fixed at <code>n/r</code> and locked. Choose <b>Yes</b> or <b>Not sure</b> above to edit these fields. " +
            "Health declarations below remain editable.");
      }
    }

    this.renderTabs(pt, vocLocked);
    if (this.activeTab === "summary") this.renderSummary(pt);
    if (this.activeTab === "gwp") { this.renderBanner(); this.renderGwpPanel(); }

    const n = this.dirtyCount();
    this.dirtyEl.textContent = this.saving ? "Saving…" : n ? `${n} unsaved change${n === 1 ? "" : "s"}` : this.section === "add" ? "" : "No changes";
    this.dirtyEl.classList.toggle("ie-dirty-on", !!n);
    this.discardBtn.style.display = n ? "" : "none";
    this.saveBtn.disabled = this.saving || (this.section === "edit" && !n);
    this.renderConfirm();
    this.renderFlash();
  }

  renderFlash() {
    const f = this.localFlash || this.flash;
    this.flashEl.innerHTML = "";
    if (!f) return;
    const close = h("button", { class: "ie-x", type: "button", title: "Dismiss", text: "×", onclick: () => { this.flash = null; this.localFlash = null; this.renderFlash(); } });
    this.flashEl.append(h("div", { class: `ie-msg ie-msg-${f.kind || "info"}` }, h("div", { html: md(f.text) }), close));
  }

  renderTabs(pt, vocLocked) {
    const tabs = [];
    const all = this.counts(this.allFields, pt);
    tabs.push({ key: "summary", text: `Summary (${all.filled}/${all.filled + all.missing})` });
    for (const cat of this.S.categories || []) {
      const c = this.counts(cat.fields, pt);
      const dirty = cat.fields.some((f) => str(this.values[f]) !== str(this.initial[f]) || (this.phys.has(f) && str(this.values[`${f}_CM`]) !== str(this.initial[`${f}_CM`])));
      tabs.push({ key: cat.key, text: `${cat.label} (${c.filled}/${c.filled + c.missing})`, dirty });
    }
    const sig = JSON.stringify([tabs, this.activeTab]);
    if (sig !== this.tabsSig) {
      this.tabsSig = sig;
      this.tabsEl.innerHTML = "";
      for (const t of tabs) {
        this.tabsEl.append(h("button", {
          class: "ie-tab" + (t.key === this.activeTab ? " ie-tab-on" : "") + (t.muted ? " ie-muted" : ""),
          type: "button", role: "tab", "aria-selected": t.key === this.activeTab ? "true" : "false",
          onclick: () => { this.activeTab = t.key; this.refresh(); },
        }, t.text, t.dirty ? h("span", { class: "ie-tab-dot", title: "Unsaved changes" }) : null));
      }
    }
    for (const [k, p] of Object.entries(this.panels)) p.style.display = k === this.activeTab ? "" : "none";
  }

  // ── Summary tab: hover card + click-to-field ────────────────────────────
  // Delegated once on the panel: renderSummary() rewrites its innerHTML on
  // every refresh, so per-cell listeners would be lost.
  wireSummaryLinks(panel) {
    const targetOf = (e) => e.target.closest?.("[data-col]");
    panel.addEventListener("mouseover", (e) => {
      const t = targetOf(e);
      if (t && t.classList.contains("ie-cell-link")) this.showTip(t);
    });
    panel.addEventListener("mouseout", (e) => {
      const t = targetOf(e);
      if (t && !t.contains(e.relatedTarget)) this.hideTip();
    });
    panel.addEventListener("focusin", (e) => {
      const t = targetOf(e);
      if (t && t.classList.contains("ie-cell-link")) this.showTip(t);
    });
    panel.addEventListener("focusout", () => this.hideTip());
    panel.addEventListener("click", (e) => {
      const t = targetOf(e);
      if (!t) return;
      e.preventDefault();
      this.goToField(t.dataset.col, t.dataset.cat);
    });
    panel.addEventListener("keydown", (e) => {
      const t = targetOf(e);
      if (t && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        this.goToField(t.dataset.col, t.dataset.cat);
      }
    });
  }

  showTip(cell) {
    const col = cell.dataset.col;
    const pt = this.productType();
    const s = this.status(col, this.effVal(col), pt);
    const cat = (this.S.categories || []).find((c) => c.key === cell.dataset.cat);
    const m = this.F[col] || {};
    const raw = str(this.effVal(col)).trim();
    let valueLine;
    if (s === "not_relevant") valueLine = `<span class="ie-muted">Not relevant${pt ? ` for “${esc(pt)}”` : ""}</span>`;
    else if (!raw) valueLine = '<span class="ie-muted">Empty</span>';
    else valueLine = esc(raw.length > 140 ? raw.slice(0, 140) + "…" : raw);
    const notes = [];
    if (col in this.derived) notes.push("Derived from the EPD reference product — locked.");
    if (str(this.values[col]) !== str(this.initial[col])) notes.push("Unsaved change.");
    const help = m.help ? (m.help.length > 220 ? m.help.slice(0, 220) + "…" : m.help) : "";
    if (!this.tipEl) {
      this.tipEl = h("div", { class: "ie-tip", role: "tooltip" });
      this.root.append(this.tipEl);
    }
    this.tipEl.innerHTML =
      `<div class="ie-tip-cat">${esc(cat ? cat.label : "")}</div>` +
      `<div class="ie-tip-title">${esc(this.label(col))}</div>` +
      `<div class="ie-tip-row"><span class="ie-pill ie-s-${s}">${STATUS_TEXT[s]}</span> ${this.metaHtml(col)}</div>` +
      `<div class="ie-tip-val">${valueLine}</div>` +
      (help ? `<div class="ie-tip-help">${esc(help)}</div>` : "") +
      notes.map((n) => `<div class="ie-tip-note">${esc(n)}</div>`).join("") +
      `<div class="ie-tip-foot">Click to go to this field</div>`;
    this.tipEl.style.display = "block";
    // Above the cell, flipped below when there is no room; kept inside the viewport.
    const r = cell.getBoundingClientRect();
    const tw = this.tipEl.offsetWidth, th = this.tipEl.offsetHeight;
    let left = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2), window.innerWidth - tw - 8);
    let top = r.top - th - 8;
    if (top < 8) top = r.bottom + 8;
    this.tipEl.style.left = `${left}px`;
    this.tipEl.style.top = `${top}px`;
  }

  hideTip() {
    if (this.tipEl) this.tipEl.style.display = "none";
  }

  goToField(col, catKey) {
    this.hideTip();
    if (!catKey) return;
    this.activeTab = catKey;
    this.refresh();
    // setTimeout, not requestAnimationFrame: rAF never fires in a hidden tab.
    setTimeout(() => {
      const c = this.ctrls[col];
      // Locked VOC fields are hidden on the Health tab — land on the panel instead.
      const visible = c && c.cell && c.cell.offsetParent !== null;
      const target = visible ? c.cell : this.panels[catKey];
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      if (visible) {
        target.classList.remove("ie-goto");
        void target.offsetWidth; // restart the highlight animation
        target.classList.add("ie-goto");
        setTimeout(() => target.classList.remove("ie-goto"), 1800);
        // Not comboboxes: focusing one opens its option list.
        if (c.input && !c.input.disabled && !c.input.classList.contains("ie-combo-in")) c.input.focus({ preventScroll: true });
      }
    }, 0);
  }

  // ── Summary tab (_render_summary_tab) ───────────────────────────────────
  renderSummary(pt) {
    this.hideTip();
    const p = this.panels.summary;
    const all = this.counts(this.allFields, pt);
    const cats = this.S.categories || [];
    // 40% wider than the classic form's label column, so long labels stay on one line.
    const labW = 1.4 * Math.min(300, Math.max(168, Math.max(...cats.map((c) => c.label.length), 20) * 6.5));
    let rows = "";
    let details = "";
    for (const cat of cats) {
      const c = this.counts(cat.fields, pt);
      // Locked VOC fields are not relevant, so Health still counts what applies.
      const vocNote = cat.key === "vo" && this.vocLocked(pt)
        ? (this.vocTypeLocked(pt)
          ? `VOC does not apply to this product type — ${this.vocFields.size} VOC fields fixed at n/r · `
          : `VOC Data Relevant = No — ${this.vocFields.size} VOC fields fixed at n/r · `)
        : "";
      const cells = cat.fields.map((f) => {
        const s = this.status(f, this.effVal(f), pt);
        return `<span class="ie-cell ie-cell-${s} ie-cell-link" data-col="${esc(f)}" data-cat="${esc(cat.key)}" ` +
          `tabindex="0" role="button" aria-label="${esc(this.label(f))}: ${STATUS_TEXT[s].slice(2)} — go to field"></span>`;
      }).join("");
      rows += `<div class="ie-mrow"><div class="ie-my" style="width:${labW}px">${esc(cat.label)} ` +
        `<span class="ie-mcount">(${c.filled}/${c.filled + c.missing})</span></div><div class="ie-mcells">${cells}</div></div>`;
      const sub = vocNote + `${c.filled} filled · ${c.missing} missing` + (c.not_relevant ? ` · ${c.not_relevant} not relevant (excluded from count)` : "");
      details += `<div class="ie-section" style="margin-top:1rem">${esc(cat.label)} <span class="ie-mcount">(${c.filled}/${c.filled + c.missing})</span></div>` +
        `<div class="ie-caption">${sub}</div>` +
        cat.fields.map((f) => {
          const s = this.status(f, this.effVal(f), pt);
          return `<div class="ie-sfield"><span class="ie-pill ie-s-${s}">${STATUS_TEXT[s]}</span> ` +
            `<a class="ie-sname ie-sfield-link" href="#" data-col="${esc(f)}" data-cat="${esc(cat.key)}">${esc(this.label(f))}</a> ${this.metaHtml(f)}</div>`;
        }).join("");
    }
    const open = p.querySelector("details")?.open ? " open" : "";
    p.innerHTML =
      `<div class="ie-caption">${pt
        ? `Completion uses <b>Product Type</b> “${esc(pt)}” for Missing vs. Not relevant (same rules as the Catalogue extended view).`
        : "Set <b>Product Type</b> on the Product Identity tab to refine Missing vs. Not relevant."}</div>` +
      `<div class="ie-metrics">${[["Filled", all.filled], ["Missing", all.missing], ["Not relevant", all.not_relevant]]
        .map(([l, v]) => `<div class="ie-metric"><div class="ie-metric-l">${l}</div><div class="ie-metric-v">${v}</div></div>`).join("")}</div>` +
      `<div class="ie-matrix"><div class="ie-legend">` +
      ["filled", "missing", "not_relevant"].map((s) => `<span><span class="ie-cell ie-cell-${s}"></span>${STATUS_TEXT[s].slice(2)}</span>`).join("") +
      `</div>${rows}</div>` +
      `<div class="ie-caption">One rectangle per field in each tab. Hover a cell for its details; click it to go to the field.</div>` +
      `<details${open}><summary>Field-by-field details</summary>${details}</details>`;
  }

  // ── GWP tab: EPD family banner (_render_epd_family_banner) ──────────────
  renderBanner() {
    const el = this.bannerEl;
    if (!el) return;
    const ctx = this.epd || {};
    let html = "";
    if (!ctx.role) html = "";
    else if (ctx.note) html = `<div class="ie-msg ie-msg-warning">🔗 ${md(ctx.note)}</div>`;
    else if (ctx.role === "variant") {
      const r = ctx.reference;
      html = `<div class="ie-msg ie-msg-info">🔗 ${md(
        `**Derived from the EPD reference product ${r.name}** (\`${r.id}\`, EPD \`${r.reg}\`) × multiplication factor **${round10(ctx.factor)}**. ` +
        "GWP modules are scaled, Metric and FU copied, and the per kg / m³ / m² / R=1 bases re-derived from this product's own ρ, d and λ. " +
        "To change them, edit the reference product — or set *EPD Reference Product* to blank to enter them by hand.")}</div>`;
    } else {
      const fam = ctx.family || [], plan = ctx.plan || [];
      if (!fam.length) html = `<div class="ie-msg ie-msg-info">🔗 ${md(`**EPD reference product.** No other product with EPD \`${ctx.reg}\` is flagged N yet — products saved later with N and a multiplication factor derive their GWP data from this one.`)}</div>`;
      else if (!plan.length) html = `<div class="ie-msg ie-msg-info">🔗 ${md(`**EPD reference product** for ${fam.length} other product(s) — their GWP data already equal these values × their multiplication factors.`)}</div>`;
      else {
        html = `<div class="ie-msg ie-msg-info">🔗 ${md(`**EPD reference product.** On save, the GWP data of **${plan.length}** of the ${fam.length} other product(s) covered by EPD \`${ctx.reg}\` are recomputed as these values × their multiplication factor.`)}</div>` +
          `<details><summary>Preview — ${plan.length} product(s) updated on save</summary><table class="ie-table"><thead><tr><th>Product</th><th>ID</th><th>Factor</th><th>GWP A1-A3 now</th><th>GWP A1-A3 after save</th><th>Fields changed</th></tr></thead><tbody>` +
          plan.map((p) => `<tr><td>${esc(p.name)}</td><td><code>${esc(p.id)}</code></td><td>${round10(p.factor)}</td><td>${esc(fmtEpd(p.before))}</td><td>${esc(fmtEpd(p.after))}</td><td>${p.n}</td></tr>`).join("") +
          "</tbody></table></details>";
      }
    }
    if (el.dataset.html !== html) {
      const open = el.querySelector("details")?.open;
      el.innerHTML = html;
      el.dataset.html = html;
      if (open && el.querySelector("details")) el.querySelector("details").open = true;
    }
  }

  // ── GWP conversion panel (_render_gwp_conversion_panel) ─────────────────
  gnum(col) {
    const raw = this.effVal(col);
    if (raw === null || raw === undefined) return null;
    return toNum(raw, EPD_NULL);
  }
  renderGwpPanel() {
    const el = this.gwpPanelEl;
    if (!el) return;
    const INPUTS = [
      ["ρ", "Vol. Density", "P__Mass_kgm3", "E__EPD_Density", "kg/m³"],
      ["d", "Thickness", "P__Thick_mm", "E__EPD_Thick_mm", "mm"],
      ["λ", "Conductivity", "P__L_WmK", "E__L_WmK", "W/(m·K)"],
      ["m_A", "Sup. Density", "P__Mass_kgm2", "", "kg/m²"],
      ["R", "Thermal resistance", "E__Rvalue", "", "m²K/W"],
    ];
    const vals = {}, srcs = {};
    for (const [sym, , primary, fallback] of INPUTS) {
      let v = this.gnum(primary), src = v !== null ? primary : "";
      if (v === null && fallback) { v = this.gnum(fallback); src = v !== null ? fallback : ""; }
      vals[sym] = v; srcs[sym] = src;
    }
    const rho = vals["ρ"], dMm = vals.d, lam = vals["λ"];
    const d = dMm === null ? null : dMm / 1000;
    let mA = vals.m_A, rVal = vals.R;
    if (mA === null && rho !== null && d !== null) { mA = rho * d; vals.m_A = mA; srcs.m_A = "derived: ρ · d"; }
    if (rVal === null && d !== null && lam) { rVal = d / lam; vals.R = rVal; srcs.R = "derived: d / λ"; }
    const chips = INPUTS.map(([sym, label, , , unit]) =>
      `<div class="ie-chip"><div class="ie-chip-l">${esc(sym)} · ${esc(label)}</div><div class="ie-chip-v">${esc(fmtG(vals[sym]))} <span>${esc(unit)}</span></div><div class="ie-chip-s">${esc(srcs[sym] || "not entered")}</div></div>`).join("");

    const decl = this.gnum("G__GWP_A1A3");
    const fuRaw = this.effVal("G__GWP_FU");
    const [anchorCol, anchorFactor] = FU_ANCHORS[normFu(fuRaw)] || ["", 0];
    const anchorVal = decl === null || !anchorCol ? null : decl * anchorFactor;
    const step1 = !anchorCol
      ? `Declared unit \`${str(fuRaw) || "—"}\` does not map to a normalised basis (linear and piece declarations need a cross-section or a pieces-per-m² figure), so nothing below can be derived from it.`
      : `Declared unit \`${str(fuRaw)}\` → **${this.label(anchorCol)}** anchored ${anchorFactor === 1 ? "unchanged" : `× ${anchorFactor}`}: **${fmtG(anchorVal)}**. Every other basis below is derived from it.`;

    let g3 = null, pivot = "";
    if (anchorVal !== null) {
      if (anchorCol === "G__GWP_A1A3_m3") [g3, pivot] = [anchorVal, "declared per m³ — already the pivot"];
      else if (anchorCol === "G__GWP_A1A3_kg" && rho !== null) [g3, pivot] = [anchorVal * rho, `per m³ = per kg × ρ = ${fmtG(anchorVal)} × ${fmtG(rho)}`];
      else if (anchorCol === "G__GWP_A1A3_m2" && d) [g3, pivot] = [anchorVal / d, `per m³ = per m² ÷ d = ${fmtG(anchorVal)} ÷ ${fmtG(d)}`];
      else if (anchorCol === "G__GWP_A1A3_m2R1" && lam) [g3, pivot] = [anchorVal / lam, `per m³ = per m²(R=1) ÷ λ = ${fmtG(anchorVal)} ÷ ${fmtG(lam)}`];
    }
    let step2 = "";
    if (anchorCol && g3 === null && anchorVal !== null) {
      const need = { G__GWP_A1A3_kg: "ρ", G__GWP_A1A3_m2: "d", G__GWP_A1A3_m2R1: "λ" }[anchorCol] || "—";
      step2 = `**Step 2 — pivot to per m³.** Not possible: \`${need}\` is missing.`;
    } else if (g3 !== null) step2 = `**Step 2 — pivot to per m³.** ${pivot} = **${fmtG(g3)}**`;

    const F_KG = "GWP/kg = GWP/m³ ÷ ρ", F_M2 = "GWP/m² = GWP/m³ × d   (d in m = mm ÷ 1000)", F_M2R1 = "GWP/m²(R=1) = GWP/m³ × λ   (since R = d/λ ⇒ d at R=1 is λ)";
    let gKg = null, fKg = [F_KG, ""];
    if (g3 !== null && rho) { gKg = g3 / rho; fKg = [F_KG, `= ${fmtG(g3)} ÷ ${fmtG(rho)}`]; }
    else if (anchorCol === "G__GWP_A1A3_kg" && anchorVal !== null) { gKg = anchorVal; fKg = ["GWP/kg = declared value", "anchored directly on the declared unit"]; }
    let gM2 = null, fM2 = [F_M2, ""];
    if (g3 !== null && d !== null) { gM2 = g3 * d; fM2 = [F_M2, `= ${fmtG(g3)} × ${fmtG(d)}`]; }
    else if (gKg !== null && mA !== null) { gM2 = gKg * mA; fM2 = ["GWP/m² = GWP/kg × m_A", `= ${fmtG(gKg)} × ${fmtG(mA)}`]; }
    let gR1 = null, fR1 = [F_M2R1, ""];
    if (g3 !== null && lam !== null) { gR1 = g3 * lam; fR1 = [F_M2R1, `= ${fmtG(g3)} × ${fmtG(lam)}`]; }
    else if (gM2 !== null && rVal) { gR1 = gM2 / rVal; fR1 = ["GWP/m²(R=1) = GWP/m² ÷ R", `= ${fmtG(gM2)} ÷ ${fmtG(rVal)}`]; }

    const card = (title, unit, entered, derived, formula, subst, missing) => {
      let badge, cls;
      if (derived === null) [badge, cls] = ["cannot derive", "muted"];
      else if (entered === null) [badge, cls] = ["not entered — suggested", "suggest"];
      else if (entered === 0 || Math.abs(derived / entered - 1) <= GWP_TOL) [badge, cls] = ["matches entered value", "ok"];
      else [badge, cls] = [`differs from entered by ${((derived / entered - 1) * 100 >= 0 ? "+" : "")}${((derived / entered - 1) * 100).toFixed(1)}%`, "warn"];
      const detail = derived === null
        ? `<div class="ie-card-miss">missing input: ${esc(missing.join(", ") || "declared A1–A3 value")}</div>`
        : `<div class="ie-mono ie-muted">${esc(subst)}</div>`;
      return `<div class="ie-card"><div class="ie-card-t">${esc(title)}</div><div class="ie-card-v">${esc(fmtG(derived))} <span>${esc(unit)}</span></div>` +
        `<div class="ie-card-b ie-card-${cls}">${esc(badge)}<span> · entered: ${esc(fmtG(entered, "blank"))}</span></div><div class="ie-mono">${esc(formula)}</div>${detail}</div>`;
    };
    const miss = (pairs) => pairs.filter(([, v]) => !v).map(([s]) => s);
    const cards = [
      card(`${this.label("G__GWP_A1A3_kg")} — per kg`, "kgCO₂e/kg", this.gnum("G__GWP_A1A3_kg"), gKg, fKg[0], fKg[1], miss([["GWP/m³", g3], ["ρ (density)", rho]])),
      card(`${this.label("G__GWP_A1A3_m3")} — per m³`, "kgCO₂e/m³", this.gnum("G__GWP_A1A3_m3"), g3, "GWP/m³ = pivot basis", pivot || "—", ["declared A1–A3 or its unit"]),
      card(`${this.label("G__GWP_A1A3_m2")} — per m²`, "kgCO₂e/m²", this.gnum("G__GWP_A1A3_m2"), gM2, fM2[0], fM2[1], miss([["GWP/m³", g3], ["d (thickness)", d]])),
      card(`${this.label("G__GWP_A1A3_m2R1")} — per m² at R=1`, "kgCO₂e/m²·(m²K/W)", this.gnum("G__GWP_A1A3_m2R1"), gR1, fR1[0], fR1[1], miss([["GWP/m³", g3], ["λ (conductivity)", lam]])),
    ].join("");

    const open = el.querySelector("details")?.open ? " open" : "";
    el.innerHTML =
      `<div class="ie-section ie-section-page ie-section-div" style="margin-top:22px">GWP A1–A3 conversion factors</div>` +
      `<div class="ie-caption">Derived live from the fields above — read-only, never saved. The stored <code>_kg</code> / <code>_m3</code> / <code>_m2</code> / <code>_m2R1</code> columns come from the source workbook; this panel re-computes them so an inconsistent density, thickness or λ is visible here.</div>` +
      `<div class="ie-sub">Input metrics used</div><div class="ie-chips">${chips}</div>` +
      `<p>${md(`**Step 1 — anchor on the declared unit.** ${step1}`)}</p>` +
      (step2 ? `<p>${md(step2)}</p>` : "") +
      `<div class="ie-sub">Step 3 — the four bases</div><div class="ie-cards">${cards}</div>` +
      `<details${open}><summary>Formulae, input metrics and caveats</summary>${GWP_FORMULAE_HTML}</details>`;
  }

  // ── VOC certification catalogue (_voc_cert_catalog_dialog) ──────────────
  openVocCatalog() {
    const cat = this.S.voc_catalog || { tiers: [] };
    const sel = str(this.values.VO__VOC_Cert).trim().toLowerCase();
    let rows = "";
    let found = false;
    for (const t of cat.tiers || []) {
      for (const e of t.entries || []) {
        const isSel = !!sel && e.label.toLowerCase() === sel;
        found = found || isSel;
        rows += `<tr class="${isSel ? "ie-sel" : ""}"><td class="ie-muted">${esc(t.label)}</td><td><b>${esc(e.label)}</b>${isSel ? " ✓" : ""}</td><td>${esc(e.description)}${e.hint ? " " + esc(e.hint) : ""}</td></tr>`;
      }
    }
    const selText = str(this.values.VO__VOC_Cert).trim();
    const head = (cat.caveat ? `<div class="ie-caption">${esc(cat.caveat)}</div>` : "") +
      (selText ? (found ? `<p><b>Selected:</b> ${esc(selText)}</p>` : `<div class="ie-msg ie-msg-info"><b>${esc(selText)}</b> is not in the curated catalog — showing the full reference list without a highlight.</div>`) : "");
    const overlay = h("div", { class: "ie-modal-bg", onclick: (e) => { if (e.target === overlay) overlay.remove(); } });
    const close = () => overlay.remove();
    overlay.append(h("div", { class: "ie-modal", role: "dialog", "aria-label": "VOC certifications" },
      h("div", { class: "ie-modal-head" }, h("div", { class: "ie-section ie-section-page", text: "VOC certifications & clarifications" }), h("button", { class: "ie-x", type: "button", text: "×", onclick: close })),
      h("div", { html: head }),
      h("div", { class: "ie-modal-scroll", html: rows ? `<table class="ie-table"><thead><tr><th>Tier</th><th>Certification / claim</th><th>Clarification</th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="ie-msg ie-msg-warning">VOC catalog is empty — check <code>aux_11__voc_certifications.json</code>.</div>' }),
    ));
    overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    this.root.append(overlay);
    overlay.querySelector(".ie-x").focus();
    overlay.querySelector(".ie-sel")?.scrollIntoView({ block: "center" });
  }
}

const GWP_FORMULAE_HTML = `
<p><b>Conversion matrix</b> — multiply the row basis by the cell to reach the column basis:</p>
<table class="ie-table"><thead><tr><th>from ↓ / to →</th><th>per kg</th><th>per m³</th><th>per m²</th><th>per m² R=1</th></tr></thead><tbody>
<tr><td><b>per kg</b></td><td>1</td><td>× ρ</td><td>× ρ·d</td><td>× ρ·λ</td></tr>
<tr><td><b>per m³</b></td><td>÷ ρ</td><td>1</td><td>× d</td><td>× λ</td></tr>
<tr><td><b>per m²</b></td><td>÷ (ρ·d)</td><td>÷ d</td><td>1</td><td>× λ/d (= ÷ R)</td></tr>
<tr><td><b>per m² R=1</b></td><td>÷ (ρ·λ)</td><td>÷ λ</td><td>× d/λ (= × R)</td><td>1</td></tr></tbody></table>
<p><b>Input metrics</b></p>
<table class="ie-table"><thead><tr><th>Symbol</th><th>Meaning</th><th>Field used</th><th>Fallback</th><th>Unit</th></tr></thead><tbody>
<tr><td>ρ</td><td>Vol. Density</td><td><code>P__Mass_kgm3</code></td><td><code>E__EPD_Density</code></td><td>kg/m³</td></tr>
<tr><td>d</td><td>Thickness</td><td><code>P__Thick_mm</code></td><td><code>E__EPD_Thick_mm</code></td><td>mm → m (÷ 1000)</td></tr>
<tr><td>λ</td><td>Thermal conductivity</td><td><code>P__L_WmK</code></td><td><code>E__L_WmK</code></td><td>W/(m·K)</td></tr>
<tr><td>m_A</td><td>Sup. Density</td><td><code>P__Mass_kgm2</code></td><td>derived ρ · d</td><td>kg/m²</td></tr>
<tr><td>R</td><td>Thermal resistance</td><td><code>E__Rvalue</code></td><td>derived d / λ</td><td>m²K/W</td></tr></tbody></table>
<p><b>Declared-unit anchors</b> — <code>m3</code>, <code>m2</code>, <code>kg</code> and <code>m2_R1</code> map 1:1 onto their basis; <code>ton</code> is the only unit factor (÷ 1000 → per kg); <code>m</code> and <code>unit</code> cannot be normalised.</p>
<p><b>Why R = 1</b> — comparing insulants per m² compares material, not performance. With R = d/λ, the thickness giving R = 1 m²K/W is numerically λ metres, so GWP/m²(R=1) = GWP/m³ × λ. A lower λ is rewarded automatically.</p>
<p><b>Caveats</b> — per m² is tied to the declared thickness and is not comparable across thicknesses; per m²(R=1) is only meaningful for insulants; per kg ignores geometry and performance. All figures are A1–A3 only. A mismatch flagged above usually means a wrong ρ, d or λ, not a wrong GWP.</p>
<p>Values are flagged as disagreeing beyond ±2%. Full reference: <b>Developer → App Documentation → GWP conversion factors</b>.</p>`;

// ── searchable combobox ────────────────────────────────────────────────────
// Free text is allowed when allowNew (a new manufacturer / type / country);
// `tokens` matches every whitespace-separated word anywhere in the label.
function makeCombo({ value = "", items = [], allowNew = true, tokens = false, placeholder = "", onInput, onPick }) {
  const input = h("input", { class: "ie-in ie-combo-in", type: "text", value, placeholder, autocomplete: "off", role: "combobox", "aria-expanded": "false" });
  const caret = h("button", { class: "ie-combo-caret", type: "button", tabindex: "-1", title: "Show all options", text: "▾" });
  const list = h("div", { class: "ie-combo-list", role: "listbox" });
  const el = h("div", { class: "ie-combo" }, input, caret, list);
  let shown = [], hi = -1, open = false, showAll = false;
  const MAX = 300;

  const matches = () => {
    const q = input.value.trim().toLowerCase();
    if (!q || showAll) return items;
    if (tokens) {
      const parts = q.split(/\s+/);
      return items.filter((it) => { const l = it.label.toLowerCase(); return parts.every((p) => l.includes(p)); });
    }
    return items.filter((it) => it.label.toLowerCase().includes(q));
  };
  const render = () => {
    const m = matches();
    shown = m.slice(0, MAX);
    list.innerHTML = "";
    const q = input.value.trim();
    if (allowNew && q && !items.some((it) => it.label.toLowerCase() === q.toLowerCase())) {
      list.append(h("div", { class: "ie-combo-hint", text: `New value “${q}” — kept as typed` }));
    }
    shown.forEach((it, i) => {
      const opt = h("div", { class: "ie-combo-opt" + (i === hi ? " ie-hi" : ""), role: "option", text: it.label });
      opt.addEventListener("mousedown", (e) => { e.preventDefault(); pick(it); });
      list.append(opt);
    });
    if (m.length > MAX) list.append(h("div", { class: "ie-combo-hint", text: `${m.length - MAX} more — keep typing to narrow down` }));
    if (!m.length && !allowNew) list.append(h("div", { class: "ie-combo-hint", text: "No match" }));
  };
  const setOpen = (b) => {
    open = b;
    list.style.display = b ? "block" : "none";
    input.setAttribute("aria-expanded", b ? "true" : "false");
    if (b) render();
    else { hi = -1; showAll = false; }
  };
  const pick = (it) => {
    input.value = it.label;
    setOpen(false);
    if (onPick) onPick(it);
  };
  // "mapei" typed by hand becomes the existing "Mapei" — no case-variant duplicates.
  const exactMatch = () => {
    const q = input.value.trim().toLowerCase();
    return q ? items.find((it) => it.label.toLowerCase() === q) : undefined;
  };
  input.addEventListener("focus", () => { input.select(); setOpen(true); });
  input.addEventListener("blur", () => setTimeout(() => {
    setOpen(false);
    const m = allowNew && exactMatch();
    if (m && input.value !== m.label) pick(m);
  }, 120));
  input.addEventListener("input", () => { hi = -1; showAll = false; if (!open) setOpen(true); else render(); if (onInput) onInput(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); if (!open) setOpen(true); hi = Math.min(shown.length - 1, hi + 1); render(); scrollHi(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); hi = Math.max(-1, hi - 1); render(); scrollHi(); }
    else if (e.key === "Enter") {
      if (open && hi >= 0 && shown[hi]) { e.preventDefault(); pick(shown[hi]); }
      else if (open && !allowNew && shown.length === 1) { e.preventDefault(); pick(shown[0]); }
      else if (open && exactMatch()) { e.preventDefault(); pick(exactMatch()); }
      else setOpen(false);
    } else if (e.key === "Escape") { if (open) { e.stopPropagation(); setOpen(false); } }
  });
  const scrollHi = () => list.querySelector(".ie-hi")?.scrollIntoView({ block: "nearest" });
  caret.addEventListener("mousedown", (e) => {
    e.preventDefault();
    if (input.disabled) return;
    if (open) { setOpen(false); return; }
    input.focus();
    showAll = true;
    setOpen(true);
  });
  setOpen(false);
  return {
    el, input,
    setValue: (v) => { if (input.value !== v) input.value = v; },
    setDisabled: (b) => { input.disabled = b; caret.disabled = b; },
  };
}
