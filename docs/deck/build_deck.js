// Builds docs/AIOps_Sentinel_Review.pptx from evaluation/results/summary.json.
//   NODE_PATH=<dir with pptxgenjs> PPTX_SKILL=<pptx skill dir> node docs/deck/build_deck.js
// Every number on a results slide is read from the summary file, never typed by hand.
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

const ROOT = path.resolve(__dirname, "..", "..");
const S = JSON.parse(fs.readFileSync(path.join(ROOT, "evaluation", "results", "summary.json"), "utf8"));
const OUT = path.join(ROOT, "docs", "AIOps_Sentinel_Review.pptx");
// Interpretation text (written by people after reading the numbers) lives beside the deck.
const NARRATIVE = path.join(__dirname, "narrative.json");
if (fs.existsSync(NARRATIVE)) Object.assign(S, JSON.parse(fs.readFileSync(NARRATIVE, "utf8")));
// Confirming tests per fault, rolled up over seeds: { F01: { template: "3/3", llm: "2/3" } }.
S.tests_by_scenario_rollup = {};
for (const [key, gens] of Object.entries(S.tests_by_scenario || {})) {
  const id = key.split("-s")[0];
  const row = (S.tests_by_scenario_rollup[id] ||= {});
  for (const [g, ok] of Object.entries(gens)) {
    const [hit, total] = (row[g] || "0/0").split("/").map(Number);
    row[g] = `${hit + (ok ? 1 : 0)}/${total + 1}`;
  }
}

const HEX = { ink: "1B1E2B", white: "FFFFFF", muted: "5A6072", bg: "F5F6FA", teal: "3D4FA0", amber: "E07A2E", purple: "3C8D5A", mint: "E7EAF6", grey: "8A90A2", red: "B5473A", line: "D9DCE6", purpleDark: "2E6B44" };
const THEME = {
  name: "AIOps Sentinel", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: HEX.ink, lt1: HEX.white, dk2: HEX.muted, lt2: HEX.bg, accent1: HEX.teal, accent2: HEX.amber, accent3: HEX.purple,
    accent4: HEX.mint, accent5: HEX.grey, accent6: HEX.red, hlink: HEX.teal, folHlink: HEX.purpleDark },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "AIOps Sentinel - project review";
pres.author = "Akash, Aryan, Syna";
const C = pres.SchemeColor;
const COL = { ink: C.text1, white: C.background1, muted: C.text2, bg: C.background2, teal: C.accent1, amber: C.accent2, purple: C.accent3, mint: C.accent4, grey: C.accent5, red: C.accent6 };

const OWNERS = {
  team: { label: "Whole team", fill: COL.ink, text: COL.white },
  P1: { label: "P1 | Akash", fill: COL.teal, text: COL.white },
  P2: { label: "P2 | Aryan", fill: COL.amber, text: COL.ink },
  P3: { label: "P3 | Syna", fill: COL.purple, text: COL.white },
};

// ---- layouts ------------------------------------------------------------------------------
pres.defineSlideMaster({ title: "TITLE_DARK", background: { color: HEX.ink } });
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.bg },
  objects: [
    { text: { text: "AIOps Sentinel  |  Project review", options: { x: 0.6, y: 6.95, w: 6, h: 0.3, fontSize: 10, color: COL.muted, fontFace: "Calibri", margin: 0 } } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.66, w: 9.4, h: 0.7, fontFace: "Cambria", fontSize: 30, bold: true, color: COL.ink, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.15, y: 6.95, w: 0.55, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
});

// ---- helpers ------------------------------------------------------------------------------
const pct = (v) => (v === undefined || v === null || Number.isNaN(v) ? "n/a" : `${Math.round(v * 100)}%`);
const num = (v, d = 2) => (v === undefined || v === null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d));
const shadow = () => ({ type: "outer", color: "9AA0B4", opacity: 0.25, blur: 4, offset: 1.5, angle: 90 });

const sections = new Set();
function section(title) {
  if (!sections.has(title)) {
    pres.addSection({ title });
    sections.add(title);
  }
  return title;
}

function content(sectionTitle, kicker, title, owner, notes) {
  const slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: section(sectionTitle) });
  slide.addText(kicker.toUpperCase(), { x: 0.6, y: 0.3, w: 9, h: 0.3, fontSize: 12, bold: true, color: COL.teal, charSpacing: 3, margin: 0, isTextBox: true, objectName: "kicker" });
  slide.addText(title, { placeholder: "title" });
  const o = OWNERS[owner];
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 10.1, y: 0.33, w: 2.6, h: 0.42, rectRadius: 0.21, fill: { color: o.fill }, line: { color: o.fill }, objectName: "owner pill" });
  slide.addText(o.label, { x: 10.1, y: 0.33, w: 2.6, h: 0.42, fontSize: 12, bold: true, color: o.text, align: "center", valign: "middle", margin: 0, isTextBox: true });
  if (notes) slide.addNotes(notes);
  return slide;
}

function card(slide, x, y, w, h, fill = COL.white) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill === COL.white ? HEX.line : fill, width: 0.75 }, shadow: fill === COL.white ? shadow() : undefined, objectName: "card" });
}

function badge(slide, label, x, y, fill = COL.teal, textColor = COL.white, size = 0.5) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: size, h: size, fill: { color: fill }, line: { color: fill }, objectName: "badge" });
  slide.addText(String(label), { x, y, w: size, h: size, fontFace: "Cambria", fontSize: 16, bold: true, color: textColor, align: "center", valign: "middle", margin: 0, isTextBox: true });
}

function text(slide, value, opts) {
  slide.addText(value, { margin: 0, isTextBox: true, fontSize: 15, color: COL.ink, valign: "top", ...opts });
}

function bullets(slide, items, opts) {
  slide.addText(items.map((t, i) => ({ text: t, options: { bullet: { indent: 16 }, breakLine: i < items.length - 1 } })),
    { margin: 0, isTextBox: true, fontSize: 15, color: COL.ink, valign: "top", paraSpaceAfter: 6, ...opts });
}

function stat(slide, x, y, w, big, label, sub, color = COL.teal) {
  const bigW = Math.min(1.9, Math.max(0.9, String(big).length * 0.42)); // number column sized to the number
  card(slide, x, y, w, 1.3);
  text(slide, big, { x: x + 0.25, y: y + 0.18, w: bigW, h: 0.95, fontFace: "Cambria", fontSize: 40, bold: true, color, valign: "middle" });
  text(slide, label, { x: x + bigW + 0.5, y: y + 0.2, w: w - bigW - 0.7, h: 0.55, fontSize: 15 });
  if (sub) text(slide, sub, { x: x + bigW + 0.5, y: y + 0.78, w: w - bigW - 0.7, h: 0.4, fontSize: 11, color: COL.muted });
}

const TABLE_HEAD = { bold: true, color: HEX.white, fill: { color: HEX.ink }, fontSize: 12, fontFace: "Calibri" };
function table(slide, header, rows, opts) {
  const body = rows.map((r, i) => r.map((cell) => (typeof cell === "object" ? cell : { text: String(cell), options: { fill: { color: i % 2 ? HEX.bg : HEX.white } } })));
  slide.addTable([header.map((h) => ({ text: h, options: TABLE_HEAD })), ...body],
    { fontSize: 12, fontFace: "Calibri", color: HEX.ink, border: { type: "solid", color: HEX.line, pt: 0.75 }, margin: [3, 6, 3, 6], valign: "middle", ...opts });
}

function barChart(slide, labels, series, opts) {
  slide.addChart(pres.charts.BAR, series.map((s) => ({ name: s.name, labels, values: s.values })), {
    barDir: "col", barGapWidthPct: 60, chartColors: series.map((s) => s.color),
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%", dataLabelFontSize: 11, dataLabelColor: HEX.ink, dataLabelFontFace: "+mn-lt",
    // Values are labelled on the bars, so the value axis is hidden and given headroom for "100%" labels.
    valAxisMaxVal: 1.12, valAxisMinVal: 0, valAxisHidden: true, valAxisLabelFormatCode: "0%",
    catAxisLabelFontSize: 11, catAxisLabelColor: HEX.ink, catAxisLabelFontFace: "+mn-lt",
    valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: series.length > 1, legendPos: "b", legendFontSize: 11, legendFontFace: "+mn-lt", legendColor: HEX.ink,
    ...opts,
  });
}

// Shapes cannot have negative size: a right-to-left or upward arrow is a flipped box.
function arrow(slide, x1, y1, x2, y2) {
  slide.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1, line: { color: HEX.muted, width: 1.25, endArrowType: "triangle" }, objectName: "arrow",
  });
}

module.exports = { pres, S, HEX, COL, THEME, OUT, pct, num, section, content, card, badge, text, bullets, stat, table, barChart, arrow, applyTheme };

if (require.main === module) {
  require("./slides.js");
}
