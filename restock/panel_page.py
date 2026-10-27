"""The control panel page. Plain HTML/CSS/JS, no outside requests (no CDNs, no fonts)."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Restock Control</title>
<style>
/* Glass Aurora: deep violet ground, frosted panels, cyan = in stock, violet = actions,
   amber = blocked or waiting, rose = error. Fonts (Sora, Inter, JetBrains Mono) are served by this program
   itself from /fonts, so the page makes no outside requests; system fonts are the fallback. */
@font-face { font-family: "Sora"; src: url(/fonts/sora.woff2) format("woff2"); font-weight: 100 800; font-display: swap; }
@font-face { font-family: "Inter"; src: url(/fonts/inter.woff2) format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "JetBrains Mono"; src: url(/fonts/mono.woff2) format("woff2"); font-weight: 100 800; font-display: swap; }
:root {
  color-scheme: dark;
  --bg: #0b0820; --panel: rgba(255,255,255,.07); --raised: rgba(255,255,255,.09); --line: rgba(255,255,255,.17); --line-soft: rgba(255,255,255,.09);
  --ink: #ece8ff; --muted: #b9b0ec; --faint: #9a91d0;
  --act: #a78bfa; --act-ink: #0b0820; --act-soft: rgba(167,139,250,.24);
  --ok: #67e8f9; --ok-bg: rgba(103,232,249,.12); --ok-strong: #22d3ee;
  --warn: #fcd34d; --warn-bg: rgba(251,191,36,.13); --bad: #fda4af; --bad-bg: rgba(251,113,133,.15);
  --r-s: 12px; --r-m: 22px;
  --grad: linear-gradient(90deg, #a78bfa, #22d3ee);
  --font: "Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
  --font-display: "Sora", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", Consolas, "Cascadia Mono", monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--ink); font: 14px/1.5 var(--font); font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
::selection { background: var(--act-soft); }
* { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.22) transparent; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
a { color: var(--act); }
button, input, select, textarea { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--act); outline-offset: 2px; }

/* ---- frame ---- */
.frame { display: grid; grid-template-columns: 200px minmax(0, 1fr); min-height: 100vh; }
nav.rail { background: var(--panel); border-right: 1px solid var(--line); padding: 18px 10px; position: sticky; top: 0; height: 100vh; }
.brand { font: 600 15px/1.2 var(--font-display); padding: 0 10px 18px; }
.brand small { display: block; font: 400 12px var(--font); color: var(--muted); margin-top: 3px; }
nav.rail button { display: flex; width: 100%; justify-content: space-between; align-items: center; border: 0; background: none; text-align: left; padding: 8px 10px; border-radius: var(--r-s); cursor: pointer; color: var(--muted); }
nav.rail button:hover { background: var(--line-soft); color: var(--ink); }
nav.rail button[aria-current="page"] { background: var(--raised); color: var(--ink); box-shadow: inset 3px 0 0 var(--act); font-weight: 600; }
nav.rail .count { font-size: 12px; color: var(--faint); font-weight: 400; }
nav.rail .navlabel { font-size: 12px; color: var(--faint); padding: 14px 10px 4px; }
.speed-row { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(120px, 220px) auto; gap: 14px; align-items: center; padding: 10px 16px; background: var(--raised); border-bottom: 1px solid var(--line-soft); }
.speed-row.off { opacity: .55; }
.speed-row .t b { display: block; font-weight: 600; }
.speed-row .t span { font-size: 12.5px; color: var(--muted); }
.speed-row input[type=range] { width: 100%; }
main { padding: 0 28px 120px; max-width: 1180px; width: 100%; min-width: 0; }
body { overflow-x: hidden; }

/* ---- annunciator strip: the one loud element ---- */
.strip { display: flex; align-items: stretch; gap: 12px; padding: 16px 0; position: sticky; top: 0; background: var(--bg); z-index: 5; flex-wrap: wrap; }
.lamp { flex: 1 1 260px; display: flex; align-items: center; gap: 14px; padding: 10px 16px; border: 1px solid var(--line); border-radius: var(--r-m); background: var(--panel); min-height: 64px; }
.lamp .big { font: 600 30px/1 var(--font-display); min-width: 1.6ch; letter-spacing: -.02em; }
.lamp > div:last-child { min-width: 0; }
.lamp .what { color: var(--muted); overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.lamp.lit { background: var(--ok-bg); border-color: var(--ok-strong); }
.lamp.lit .big { color: var(--ok); }
.lamp.lit .what { color: var(--ok); }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.state { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border-radius: 999px; background: var(--panel); border: 1px solid var(--line); font-size: 13px; }
.state i { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); }
.state.run i { background: var(--ok-strong); }
.state.pause { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.state.pause i { background: var(--warn); }

.btn { border: 1px solid var(--line); background: var(--raised); padding: 7px 14px; border-radius: var(--r-s); cursor: pointer; white-space: nowrap; font-weight: 500; transition: background .15s, border-color .15s, transform .08s, box-shadow .15s; }
.btn:hover { border-color: var(--muted); background: rgba(255,255,255,.13); }
.btn:active { transform: translateY(1px); }
.btn.primary { background: var(--act); border-color: var(--act); color: var(--act-ink); font-weight: 600; box-shadow: 0 4px 16px -6px var(--act); }
.btn.primary:hover { background: #b9a1ff; }
.btn.quiet { background: none; border-color: transparent; color: var(--muted); padding: 5px 8px; }
.btn.quiet:hover { color: var(--ink); background: var(--line-soft); }
.btn.danger:hover { color: var(--bad); border-color: var(--bad); }
.btn[disabled] { opacity: .5; cursor: default; }

/* ---- sections ---- */
h1 { font: 600 22px/1.25 var(--font-display); margin: 8px 0 4px; }
h2 { font: 600 16px/1.3 var(--font-display); margin: 28px 0 10px; letter-spacing: -.005em; }
h2.sec { margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--line-soft); }
h1 { letter-spacing: -.01em; }
h1 b { background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; font-weight: 700; }
code, .mono { font-family: var(--mono); font-size: .92em; }
.lede { color: var(--muted); margin: 0 0 18px; max-width: 68ch; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-m); backdrop-filter: blur(8px); box-shadow: 0 10px 30px -18px rgba(0,0,0,.6); }
.pad { padding: 16px; }
.hint { color: var(--muted); font-size: 13px; }
.empty { padding: 28px 16px; color: var(--muted); text-align: center; }

/* retailer tiles: grey unless abnormal */
/* Section tabs (pages that share a menu item) */
.subtabs { display: flex; gap: 4px; flex-wrap: wrap; margin: 4px 0 14px; padding: 4px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); width: fit-content; max-width: 100%; }
.subtabs button { border: 0; background: none; color: var(--muted); padding: 6px 12px; border-radius: 9px; cursor: pointer; font-weight: 500; white-space: nowrap; }
.subtabs button:hover { color: var(--ink); background: var(--line-soft); }
.subtabs button.on { background: var(--raised); color: var(--ink); box-shadow: inset 0 -2px 0 var(--act); }
nav.rail .count.warn { color: var(--warn); font-weight: 600; }
/* Home: setup steps */
.steps { padding: 14px 16px; margin: 0 0 18px; }
.steps h2 { margin: 0 0 8px; }
.steps ol { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.steps li { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.steps li .mark { width: 22px; height: 22px; border-radius: 50%; display: inline-grid; place-items: center; font-size: 12px; font-weight: 700; border: 1px solid var(--line); flex: none; }
.steps li.done .mark { background: var(--ok-bg); border-color: var(--ok-strong); color: var(--ok); }
.steps li.done .what { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--faint); }
.steps li .what { flex: 1 1 220px; }
/* Home: what is in stock now */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.scard { padding: 12px 14px; border: 1px solid var(--ok-strong); background: var(--ok-bg); border-radius: var(--r-s); display: grid; gap: 4px; min-width: 0; }
.scard .store { font-size: 12px; color: var(--ok); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.scard a { font-weight: 600; overflow-wrap: anywhere; }
.scard .price { font-variant-numeric: tabular-nums; }
.scard .where { font-size: 13px; color: var(--muted); }
.calm { padding: 16px; display: flex; gap: 12px; align-items: center; }
.calm .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--faint); flex: none; }
/* Home: store health */
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.schip { display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); font-size: 13px; max-width: 100%; }
.schip i { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); flex: none; }
.schip.ok i { background: var(--ok-strong); }
.schip.warn { border-color: var(--warn); } .schip.warn i { background: var(--warn); }
.schip.bad { border-color: var(--bad); } .schip.bad i { background: var(--bad); }
.schip.setup i { background: none; border: 1px dashed var(--muted); }
.schip .btn { padding: 0 4px; font-size: 12px; line-height: 1.2; border: 0; min-height: 0; }
.schip small { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
details.more { margin-top: 10px; }
details.more > summary { cursor: pointer; color: var(--muted); font-size: 13px; padding: 4px 0; width: fit-content; }
details.more > summary:hover { color: var(--ink); }
.summary-line { margin: 0 0 10px; color: var(--muted); }
.summary-line b { color: var(--ink); }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
.tile { padding: 9px 12px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); transition: border-color .15s, transform .15s; }
.tile:hover { border-color: var(--muted); transform: translateY(-1px); }
.tile b { display: block; font-weight: 600; }
.tile span { font-size: 12px; color: var(--muted); }
.tile.warn { background: var(--warn-bg); border-color: var(--warn); }
.tile.warn span { color: var(--warn); }
.tile.bad { background: var(--bad-bg); border-color: var(--bad); }
.tile.bad span { color: var(--bad); }

/* stock table */
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
.toolbar input[type=search] { flex: 1 1 220px; width: auto; }
.toolbar select { width: auto; flex: 0 0 auto; }
table.stock { width: 100%; border-collapse: collapse; }
table.stock tbody tr:hover td { background: rgba(255,255,255,.05); }
table.stock th { text-align: left; font-weight: 600; font-size: 11.5px; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); padding: 8px 10px; border-bottom: 1px solid var(--line); background: var(--panel); }
table.stock td { padding: 8px 10px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }
table.stock tr.in td { background: var(--ok-bg); }
table.stock tr.in td:first-child { box-shadow: inset 4px 0 0 var(--ok-strong); }
table.stock tr.dim td { color: var(--faint); }
td.price { white-space: nowrap; text-align: right; font-family: var(--mono); font-size: 13px; }
td .sub { display: block; font-size: 12px; color: var(--muted); }
tr.in td .sub { color: var(--ok); }
td.act { white-space: nowrap; text-align: right; }
.table-wrap { background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-m); overflow-x: auto; overflow-y: hidden; -webkit-overflow-scrolling: touch; }
.table-wrap table { min-width: 100%; }
table.matrix td, table.matrix th { overflow-wrap: anywhere; }
table.matrix th:first-child, table.matrix td:first-child { min-width: 90px; }

.two { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.feed { list-style: none; margin: 0; padding: 0; }
.feed li { padding: 10px 14px; border-bottom: 1px solid var(--line-soft); }
.feed li:last-child { border-bottom: 0; }
.feed time { font-size: 12px; color: var(--muted); }
.feed .ok { color: var(--ok); font-weight: 600; }
.log { max-height: 280px; overflow: auto; font-size: 12.5px; }
.log li { padding: 5px 14px; }

/* ---- forms ---- */
.card { background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-m); margin-bottom: 12px; }
.card.off { opacity: .62; }
.card-head { display: flex; gap: 10px; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--line-soft); }
.card-head input.title { flex: 1; font-weight: 600; border-color: transparent; background: transparent; padding-left: 4px; }
.card-head input.title:hover, .card-head input.title:focus { border-color: var(--line); background: var(--raised); }
.card-body { padding: 14px; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px 16px; }
.card-body .wide { grid-column: 1 / -1; }
label.f { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
label.f > span.l { color: var(--ink); font-weight: 600; font-size: 13px; }
input[type=text], input[type=number], input[type=password], input[type=search], textarea, select {
  width: 100%; padding: 7px 9px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--raised);
}
textarea { min-height: 84px; resize: vertical; line-height: 1.4; }
input:focus, textarea:focus, select:focus { border-color: var(--act); outline: none; box-shadow: 0 0 0 3px var(--act-soft); }
.checks { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; cursor: pointer; font-size: 13px; color: var(--ink); background: var(--raised); user-select: none; }
.chip input { margin: 0; accent-color: var(--act); }
.chip:has(input:checked) { background: var(--act-soft); border-color: var(--act); }
.switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; color: var(--ink); font-size: 13px; }
.switch input { appearance: none; width: 34px; height: 20px; border-radius: 999px; background: var(--line); position: relative; margin: 0; cursor: pointer; transition: background .15s; flex: none; }
.switch input::after { content: ""; position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: #fff; transition: transform .15s; }
.switch input:checked { background: var(--act); }
.switch input:checked::after { transform: translateX(14px); }
.settings-list { display: grid; gap: 2px; }
.setting { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 12px 16px; background: var(--raised); }
.setting:first-child { border-radius: var(--r-m) var(--r-m) 0 0; }
.setting:last-child { border-radius: 0 0 var(--r-m) var(--r-m); }
.setting .t b { display: block; font-weight: 600; }
.setting .t span { display: block; margin-top: 2px; font-size: 13px; color: var(--muted); }
.mc-row { display: grid; grid-template-columns: minmax(0,1.6fr) repeat(3, minmax(70px,.5fr)) auto; gap: 12px; align-items: center; padding: 12px 16px; background: var(--raised); }
.mc-row + .mc-row { margin-top: 2px; }
.mc-group { padding: 10px 16px 6px; font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
.mc-row .n { font-weight: 600; font-variant-numeric: tabular-nums; }
.mc-row .k { display: block; font-size: 12px; color: var(--muted); }
.mc-row .nm b { display: block; }
.mc-row .nm span { display: block; font-size: 13px; color: var(--muted); }
.mc-row .nm b .badge { display: inline-block; font-size: 12px; font-weight: 500; margin-left: 6px; }
.mc-row.off { opacity: .8; }
.spark { display: flex; align-items: flex-end; gap: 1px; height: 28px; min-width: 150px; }
.spark i { display: block; flex: 1; min-width: 3px; background: var(--ok-strong); border-radius: 1px; opacity: .85; }
.spark i.none { background: var(--line); height: 2px !important; opacity: .6; }
.spark i.warn { background: var(--warn); }
.spark i.bad { background: var(--bad); }
.mc-bar { height: 6px; border-radius: 99px; background: var(--line-soft); overflow: hidden; margin-top: 4px; }
.mc-bar i { display: block; height: 100%; background: var(--ok-strong); }
.mc-bar i.warn { background: var(--warn); }
.mc-bar i.bad { background: var(--bad); }
.mc-tools { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 10px; }
@media (max-width: 1100px) {
  .mc-row { grid-template-columns: repeat(3, minmax(0, 1fr)) auto; }
  .mc-row .nm { grid-column: 1 / -1; }
  .mc-row > .btn { grid-column: 4; grid-row: 2; }
}
@media (max-width: 760px) { .mc-row { grid-template-columns: 1fr 1fr; } .mc-row > .btn { grid-column: 1 / -1; grid-row: auto; justify-self: start; } }
.setting .t, .mc-row .nm, .feed li, .mrow .sub2, .lede, .hint { overflow-wrap: anywhere; }
.setting { flex-wrap: wrap; }
.setting .t { flex: 1 1 260px; min-width: 0; }
.setting input[type=number] { width: 110px; }
.rules td { padding: 6px 8px; border-bottom: 1px solid var(--line-soft); }
.rules { width: 100%; border-collapse: collapse; background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-m); }
.rules th { text-align: left; font-size: 12px; color: var(--muted); font-weight: 600; padding: 8px; border-bottom: 1px solid var(--line); }
.verdict { margin-top: 12px; padding: 12px 14px; border-radius: var(--r-s); border: 1px solid var(--line); background: var(--raised); }
.verdict.yes { background: var(--ok-bg); border-color: var(--ok-strong); color: var(--ok); }
.verdict.no { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.secret { display: flex; gap: 6px; }

/* human-check banner: amber, because it needs the person */
.banner { display: none; margin: 0 0 16px; padding: 12px 16px; border: 1px solid var(--warn); background: var(--warn-bg); color: var(--warn); border-radius: var(--r-m); align-items: center; gap: 12px; flex-wrap: wrap; }
.banner.show { display: flex; }
.banner.offline { border-color: var(--bad); background: var(--bad-bg); color: var(--bad); }
.banner span { flex: 1 1 280px; }
.tile .meta { display: block; font-size: 12px; color: var(--faint); margin-top: 2px; }
.tile.warn .meta { color: var(--warn); }

/* restock-time heatmap */
.heat-wrap { overflow-x: auto; padding: 16px; }
.heat { display: grid; grid-template-columns: 40px repeat(24, minmax(18px, 1fr)); gap: 3px; min-width: 600px; }
.heat .c { aspect-ratio: 1; border-radius: 3px; background: var(--line-soft); }
.heat .hl { font-size: 11px; color: var(--muted); text-align: left; white-space: nowrap; overflow: visible; }
.heat .dl { font-size: 12px; color: var(--muted); align-self: center; }
.best { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.best li { padding: 10px 14px; background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-s); display: flex; justify-content: space-between; gap: 12px; }
.best li b { font-weight: 600; }
.win-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 10px 16px; background: var(--raised); border-bottom: 1px solid var(--line-soft); }
/* Areas: every row on the same columns, whatever the city name's length */
.area-row { display: grid; grid-template-columns: minmax(90px, 140px) 84px minmax(110px, 170px) auto minmax(120px, 1fr) 52px minmax(200px, 1.3fr) auto; gap: 10px; flex-wrap: nowrap; }
.area-row > * { min-width: 0; }
.area-row input[type=text], .area-row input[type=range] { width: 100%; }
.area-row .place { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.area-row .radius-val { text-align: right; white-space: nowrap; }
@media (max-width: 1000px) {
  .area-row { grid-template-columns: minmax(90px, 1fr) 84px minmax(100px, 1fr); }
  .area-row > :nth-child(4) { display: none; }
  .area-row > :nth-child(5) { grid-column: 1 / 3; }
  .area-row > :nth-child(7) { grid-column: 1 / -1; }
}
.win-row input[type=time] { width: 120px; padding: 6px 8px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--raised); }

/* ZIP + radius filter */
.zipbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 10px 12px; margin-bottom: 8px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-m); }
.zipbar input[type=text] { width: 96px; }
.zipbar .where { font-size: 13px; color: var(--muted); min-width: 120px; }
.zipbar.on { border-color: var(--act); box-shadow: inset 3px 0 0 var(--act); }
input[type=range] { accent-color: var(--act); width: 160px; }
.radius-val { font-weight: 600; min-width: 52px; }

/* stores near you */
.radar-wrap { padding: 12px; }
.radar, .mapsvg { width: 100%; max-width: 760px; display: block; margin: 0 auto; border-radius: var(--r-s); background: radial-gradient(120% 100% at 50% 40%, rgba(255,255,255,.05), rgba(255,255,255,.015)); }
.area-map { margin: 14px 0 6px; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; color: var(--muted); padding: 0 16px 14px; justify-content: center; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }
.badge { display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.badge.live { color: var(--ok); border-color: var(--ok-strong); background: var(--ok-bg); }
.badge.online { color: var(--act); border-color: var(--act); background: var(--act-soft); }
.place-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 12px; align-items: center; padding: 10px 16px; background: var(--raised); border-bottom: 1px solid var(--line-soft); }
.place-row.off { opacity: .55; }
.place-row .t b { display: block; font-weight: 600; }
.place-row .t span { font-size: 13px; color: var(--muted); }
.chain-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin: 22px 0 8px; }
.chain-head h2 { margin: 0; }

/* found products */
.group { background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-m); margin-bottom: 10px; overflow: hidden; }
.group-head { padding: 10px 14px; display: flex; gap: 10px; align-items: baseline; justify-content: space-between; flex-wrap: wrap; border-bottom: 1px solid var(--line-soft); }
.group-head b { font-weight: 600; }
.listing { display: grid; grid-template-columns: 130px minmax(0, 1fr) minmax(170px, auto) auto; gap: 12px; align-items: center; padding: 8px 14px; border-bottom: 1px solid var(--line-soft); font-size: 13.5px; }
.listing .pricing { display: grid; grid-template-columns: auto auto; gap: 0 10px; justify-content: end; text-align: right; font-variant-numeric: tabular-nums; }
.listing .pricing span { color: var(--muted); font-size: 12px; }
.listing .pricing b { font-weight: 600; }
.listing .diff { grid-column: 1 / -1; font-size: 12px; font-weight: 600; }
.listing .diff.fair { color: var(--ok); } .listing .diff.high { color: var(--warn); } .listing .diff.gouge { color: var(--bad); }
.listing .sched { display: block; font-size: 12px; color: var(--muted); margin-top: 2px; }
@media (max-width: 760px) { .listing { grid-template-columns: 1fr auto; } .listing .pricing { justify-content: start; text-align: left; } }
.listing:last-child { border-bottom: 0; }
.listing.off { opacity: .5; }
.listing.in { background: var(--ok-bg); }
@media (max-width: 900px) { .listing { grid-template-columns: 1fr auto; } .listing .hide-s { display: none; } .place-row { grid-template-columns: 1fr auto; } .place-row .hide-s { display: none; } }

/* ---- stock by store ---- */
.stockbar .stockrow { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; }
.stockbar select { width: auto; max-width: 100%; min-width: 150px; }
.stockbar input[type=search] { min-width: 0; max-width: 100%; width: auto; }
.stockbar .card-body { display: block; }
.stockbar .stockrow + .stockrow { margin-top: 10px; }
.stockbar input[type=search] { flex: 1 1 200px; }
.stockbar input[type=range] { flex: 1 1 160px; max-width: 320px; }
.stocksum { margin: 10px 0; }
.sstores { display: grid; gap: 8px; margin-bottom: 20px; }
.sstore { border: 1px solid var(--line); border-radius: var(--r-m); background: var(--raised); overflow: hidden; }
.sstore.sel { border-color: var(--ok-strong); box-shadow: 0 0 0 1px var(--ok-strong); }
.sstore-head { display: flex; width: 100%; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 14px; border: 0; background: none; text-align: left; cursor: pointer; color: inherit; flex-wrap: wrap; }
.sstore-head:hover { background: rgba(255,255,255,.05); }
.sname { display: flex; flex-direction: column; min-width: 0; flex: 1 1 220px; overflow-wrap: anywhere; }
.sbadges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.chev { font-size: 12.5px; color: var(--act); font-weight: 600; }
.sstore-peek { padding: 0 14px 12px; overflow-wrap: anywhere; }
.sstore-body { border-top: 1px solid var(--line-soft); }
.sprod { display: flex; justify-content: space-between; gap: 14px; padding: 10px 14px; border-bottom: 1px solid var(--line-soft); align-items: baseline; }
.sprod:last-child { border-bottom: 0; }
.sprod .t { min-width: 0; overflow-wrap: anywhere; }
.sprod .t .hint { display: block; }
.sprice { white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 600; }
.sprice.over { color: var(--warn); }
.stockdot:focus-visible circle { stroke: var(--ink); stroke-width: 3; }

/* save bar */
.savebar { position: fixed; left: 200px; right: 0; bottom: 0; display: none; justify-content: flex-end; align-items: center; gap: 10px; padding: 12px 28px; background: var(--raised); border-top: 2px solid var(--act); z-index: 10; }
.savebar.show { display: flex; }
.savebar .msg { margin-right: auto; font-weight: 600; }
.toast { position: fixed; right: 20px; bottom: 74px; background: var(--ink); color: var(--bg); padding: 10px 14px; border-radius: var(--r-s); opacity: 0; transform: translateY(6px); transition: opacity .2s, transform .2s; pointer-events: none; z-index: 20; max-width: 360px; }
.toast.show { opacity: 1; transform: none; }
.toast.err { background: var(--bad); color: #fff; }

dialog { border: 1px solid var(--line); border-radius: var(--r-m); background: var(--raised); color: var(--ink); padding: 22px; max-width: 340px; }
dialog::backdrop { background: rgba(20, 24, 28, .45); }

@media (max-width: 1100px) and (min-width: 901px) {
  .frame { grid-template-columns: 168px minmax(0, 1fr); }
  main { padding: 0 20px 120px; }
  nav.rail { padding: 14px 8px; overflow-y: auto; }
  nav.rail button { padding: 7px 8px; font-size: 13.5px; }
  .two { grid-template-columns: minmax(0, 1fr); }
  .strip .controls { margin-left: auto; }
  .savebar { left: 168px; padding: 12px 20px; }
}
@media (max-width: 900px) {
  .frame { grid-template-columns: minmax(0, 1fr); }
  nav.rail { position: sticky; top: 0; height: auto; display: flex; gap: 4px; overflow-x: auto; padding: 8px; z-index: 8; border-right: 0; border-bottom: 1px solid var(--line); }
  .brand { display: none; }
  nav.rail button { width: auto; white-space: nowrap; }
  nav.rail button[aria-current="page"] { box-shadow: inset 0 -3px 0 var(--act); }
  nav.rail .count { margin-left: 6px; }
  nav.rail .navlabel { display: none; }
  .speed-row { grid-template-columns: auto 1fr; }
  main { padding: 0 16px 120px; }
  .strip { position: static; }
  .two { grid-template-columns: 1fr; }
  .savebar { left: 0; padding: 12px 16px; }
  table.stock .hide-s { display: none; }
}
/* ---- Glass Aurora surfaces ---- */
body { background: radial-gradient(900px 600px at 12% -5%, #3b1d7a 0%, transparent 60%), radial-gradient(800px 600px at 100% 25%, #0f5b6b 0%, transparent 60%), #0b0820; background-attachment: fixed; }
nav.rail { background: rgba(255,255,255,.05); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 600; }
.brand::before { content: ""; width: 30px; height: 30px; border-radius: 10px; background: var(--grad); flex: none; }
.brand small { display: block; }
.brand > * { min-width: 0; }
nav.rail button { border-radius: 999px; }
nav.rail button[aria-current="page"] { background: var(--act-soft); box-shadow: inset 0 0 0 1px rgba(167,139,250,.5); color: #fff; }
.panel, .card, .table-wrap, .group, .tile, .rules, .zipbar, .best li, .verdict, .lamp { backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
.lamp { border-radius: 26px; min-height: 76px; padding: 12px 22px; }
.lamp .big { font-weight: 300; font-size: 40px; }
.lamp.lit { background: linear-gradient(135deg, rgba(167,139,250,.2), rgba(34,211,238,.2)); border-color: rgba(103,232,249,.6); }
.strip { background: rgba(11,8,32,.78); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); margin: 0 -28px; padding-left: 28px; padding-right: 28px; }
@media (max-width: 1100px) { .strip { margin: 0 -20px; padding-left: 20px; padding-right: 20px; } }
@media (max-width: 900px) { .strip { margin: 0 -16px; padding-left: 16px; padding-right: 16px; } }
.btn { border-radius: 999px; padding: 8px 18px; min-height: 40px; background: rgba(255,255,255,.07); }
.btn.primary { background: var(--grad); border: 0; color: var(--act-ink); }
.btn.quiet { background: none; }
.state { background: rgba(255,255,255,.07); }
h1 { font-weight: 300; font-size: 32px; }
h1 b, .grad { font-weight: 700; background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.switch input:checked { background: var(--grad); }
.card-head, .group-head { border-bottom-color: var(--line-soft); }
.table-wrap, .group, .card, .rules, .panel { box-shadow: 0 8px 30px rgba(5,3,20,.25); }
.savebar { background: rgba(20,16,46,.92); backdrop-filter: blur(16px); border-top: 1px solid rgba(167,139,250,.6); }
dialog { background: #17123a; }
select option { background: #17123a; color: var(--ink); }
input[type=text], input[type=number], input[type=password], input[type=search], textarea, select, input[type=time] { background: rgba(255,255,255,.07); border-radius: 12px; }
.toast { background: #ece8ff; color: #0b0820; }
.toast.err { background: #fda4af; color: #3b0a14; }
table.stock th { background: rgba(255,255,255,.05); }
.setting, .speed-row, .place-row, .win-row, .listing { background: rgba(255,255,255,.04); }
.settings-list { border-radius: var(--r-m); overflow: hidden; border: 1px solid var(--line); }
.setting:first-child, .setting:last-child { border-radius: 0; }
/* Methods lab */
.hero { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; }
.hero .big { flex: 2 1 340px; padding: 24px 28px; border-radius: 26px; background: linear-gradient(135deg, rgba(167,139,250,.18), rgba(34,211,238,.14)); border: 1px solid var(--line); }
.hero .big .k { color: var(--muted); font-size: 13px; }
.hero .big .v { font-size: 30px; font-weight: 300; margin: 6px 0 4px; line-height: 1.2; }
.hero .stat { flex: 1 1 120px; padding: 18px 20px; border-radius: 22px; background: var(--panel); border: 1px solid var(--line); }
.hero .stat .n { font-size: 30px; font-weight: 600; }
.hero .stat .k { color: var(--muted); font-size: 12px; }
.hero .stat.warn { background: var(--warn-bg); border-color: rgba(251,191,36,.4); }
.hero .stat.warn .n { color: var(--warn); }
.mrow { padding: 14px 18px; border-bottom: 1px solid var(--line-soft); }
.mrow:last-child { border-bottom: 0; }
.mrow .top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.mrow .top b { font-weight: 600; }
.mrow .top span { color: var(--muted); font-size: 13px; }
.bar { height: 12px; border-radius: 6px; background: rgba(255,255,255,.1); margin-top: 8px; overflow: hidden; }
.bar i { display: block; height: 12px; border-radius: 6px; background: var(--grad); }
.bar i.warn { background: var(--warn); }
.mrow .sub2 { color: var(--muted); font-size: 12.5px; margin-top: 6px; }
table.matrix { width: 100%; border-collapse: collapse; }
table.matrix th { text-align: left; font-size: 12px; color: var(--muted); font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--line); }
table.matrix td { padding: 10px 14px; border-bottom: 1px solid var(--line-soft); }
table.matrix td.best { background: var(--ok-bg); color: var(--ok); font-weight: 600; }
table.matrix td.bad { background: var(--warn-bg); color: var(--warn); }
table.matrix td.none { color: var(--faint); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="frame">
  <nav class="rail" aria-label="Sections">
    <div class="brand"><span>Searchemon<small id="hostline">Running on this PC</small><small id="verline"></small></span></div>
    <button data-group="home" aria-current="page">Home <span class="count" id="c-home"></span></button>
    <button data-group="near">Stock near me <span class="count" id="c-near"></span></button>
    <button data-group="products">Products <span class="count" id="c-products"></span></button>
    <button data-group="alerts">Discord alerts</button>
    <button data-group="areas">My areas</button>
    <button data-group="stores">Stores <span class="count" id="c-stores"></span></button>
    <button data-group="advanced">Advanced</button>
  </nav>
  <main>
    <div class="strip">
      <div class="lamp" id="lamp"><div class="big" id="lamp-n">0</div><div><div id="lamp-t" style="font-weight:600">Nothing in stock</div><div class="what" id="lamp-s">Waiting for the first check</div></div></div>
      <div class="controls">
        <span class="state" id="state"><i></i><span>Connecting</span></span>
        <button class="btn" id="b-check">Check now</button>
        <button class="btn" id="b-pause">Pause alerts</button>
        <button class="btn" id="b-run">Stop checking</button>
      </div>
    </div>
    <div class="banner offline" id="offline" role="alert"><span>Lost contact with the app. It may have been closed or restarted. Open it again and this page reconnects by itself.</span></div>
    <div class="banner" id="banner" role="alert"><span id="banner-t"></span><button class="btn" id="b-showbrowser">Show browser window</button></div>
    <section id="view"></section>
  </main>
</div>
<div class="savebar" id="savebar"><span class="msg">Unsaved changes</span><button class="btn" id="b-discard">Discard</button><button class="btn primary" id="b-save">Save changes</button></div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<dialog id="pin"><form method="dialog" id="pin-form"><h2 style="margin-top:0">Enter PIN</h2><p class="hint">Set in Stores &amp; keys, under Phone access.</p><input type="password" id="pin-in" autocomplete="current-password" inputmode="numeric"><p><button class="btn primary" style="width:100%">Unlock</button></p></form></dialog>

<script>
"use strict";
const RETAILERS = { target: "Target", bestbuy: "Best Buy", kroger: "Kroger family", walmart: "Walmart", pokemoncenter: "Pokemon Center",
  gamestop: "GameStop", costco: "Costco", samsclub: "Sam's Club", barnesandnoble: "Barnes & Noble", booksamillion: "Books-A-Million",
  amazon: "Amazon", dicks: "Dick's Sporting Goods", safeway: "Safeway", raleys: "Raley's", walgreens: "Walgreens", cvs: "CVS", macys: "Macy's", kohls: "Kohl's", web: "Other sites" };
const SEARCHABLE = ["target", "bestbuy", "walmart", "kroger", "gamestop", "costco", "samsclub", "barnesandnoble", "booksamillion",
  "dicks", "safeway", "walgreens", "cvs", "macys", "kohls"];
const COVERAGE = { live: "Shelf stock checked", online: "Website checked", listed: "Listed only" };
let TYPES_LIST = [];
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
const nearState = Object.assign({ zip: "", radius: 15, online: true, point: null, place: "" }, store.get("restock-near", {}));
const foundState = Object.assign({ q: "", type: "", retailer: "", showIgnored: false }, store.get("restock-found", {}));
function saveFound() { store.set("restock-found", { type: foundState.type, retailer: foundState.retailer, showIgnored: foundState.showIgnored }); }
let placesData = null, catalogData = null;
function milesBetween(a, b) {
  const r = (x) => x * Math.PI / 180, R = 3958.8;
  const dLat = r(b[0] - a[0]), dLon = r(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
function nearFilterOn() { return !!(nearState.zip && nearState.point); }
function storesInRange(points) {
  if (!nearFilterOn()) return points || [];
  return (points || []).filter((p) => p.point && milesBetween(nearState.point, p.point) <= nearState.radius)
    .map((p) => Object.assign({}, p, { away: milesBetween(nearState.point, p.point) }));
}
function passesNear(it) {
  if (!nearFilterOn()) return true;
  if (storesInRange(it.store_points).length) return true;
  return nearState.online && !!it.online;
}
const UPC_RETAILERS = ["target", "bestbuy", "walmart"];
let token = __TOKEN__ || sessionStorage.getItem("restock-pin") || "";
let cfg = null, savedJSON = "", status = null, tab = "dash", viewSig = "";
const dashState = { q: "", retailer: "", inOnly: false };
const timesState = { retailer: "", place: "" };
const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function fmtSecs(n) { return n < 90 ? n + "s" : Math.round(n / 60) + " min"; }
function hourLabel(hr) { hr = ((hr % 24) + 24) % 24; return ((hr % 12) || 12) + (hr < 12 ? " AM" : " PM"); }

/* ---------- tiny DOM helper (text is always set as text, never HTML) ---------- */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "text") el.textContent = v;
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
}
const $ = (id) => document.getElementById(id);
const money = (n) => (n === null || n === undefined || n === "") ? "" : "$" + Number(n).toFixed(2);
function ago(t) { if (!t || !status) return ""; const s = Math.max(0, Math.round(status.now - t)); return s < 60 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago"; }
function toast(msg, err) { const t = $("toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : ""); clearTimeout(t._t); t._t = setTimeout(() => t.className = "toast", 3200); }
function extLink(url, text) { return h("a", { href: url, target: "_blank", rel: "noreferrer noopener", text }); }

/* ---------- API ---------- */
async function api(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-Token": token, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      referrerPolicy: "no-referrer",
    });
  } catch (e) {
    // The browser could not reach the app at all: it was closed, is restarting, or the PC went to sleep.
    setOffline(true);
    throw new Error("Lost contact with the app. It may have been closed or restarted. Open it again; this page reconnects by itself.");
  }
  setOffline(false);
  if (res.status === 401) { askPin(); throw new Error("PIN required"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
  return data;
}
function setOffline(on) { const el = $("offline"); if (el) el.classList.toggle("show", on); }
function askPin() { const d = $("pin"); if (!d.open) d.showModal(); }
$("pin-form").addEventListener("submit", () => { token = $("pin-in").value.trim(); sessionStorage.setItem("restock-pin", token); boot(); });

/* ---------- config editing ---------- */
const dirty = () => cfg && JSON.stringify(cfg) !== savedJSON;
function touch() { $("savebar").classList.toggle("show", dirty()); counts(); }
function counts() {
  if (!cfg || !status) return;
  const live = status.items.filter((i) => i.in_stock && !i.note).length;
  const set = (id, v, warn) => { const el = $(id); if (el) { el.textContent = v || ""; el.classList.toggle("warn", !!warn && !!v); } };
  set("c-home", live, false);
  set("c-near", "", false);
  set("c-products", status.catalog_total + (cfg.watchlist || []).length, false);
  set("c-stores", (status.retailers || []).filter((r) => storeState(r.status).cls !== "ok" && storeState(r.status).cls !== "").length, true);
}
/* The menu: seven plain sections; pages that belong together share a section and get tabs at the top. */
const GROUPS = [
  { key: "home", tabs: [["dash", "Home"]] },
  { key: "near", tabs: [["places", "Stores with stock"], ["scan", "Scan a ZIP"]] },
  { key: "products", tabs: [["found", "Found for you"], ["watch", "Your own links"], ["search", "Keyword searches"], ["filters", "Prices & filters"]] },
  { key: "alerts", tabs: [["notify", "Discord alerts"]] },
  { key: "areas", tabs: [["areas", "My areas"]] },
  { key: "stores", tabs: [["retail", "Stores & keys"], ["speed", "How often"], ["accounts", "Sign-ins"]] },
  { key: "advanced", tabs: [["times", "Restock patterns"], ["methods", "Connection methods"]] },
];
const lastTab = {};
function groupOf(t) { return GROUPS.find((g) => g.tabs.some(([k]) => k === t)) || GROUPS[0]; }
function subTabs() {
  const g = groupOf(tab);
  if (g.tabs.length < 2) return null;
  return h("div", { class: "subtabs", role: "tablist", "aria-label": "Pages in this section" }, g.tabs.map(([k, label]) =>
    h("button", { type: "button", role: "tab", "aria-selected": String(k === tab), class: k === tab ? "on" : "", text: label, onclick: () => go(k) })));
}
/* A short, plain state for each store, from its full status line. */
function storeState(st) {
  st = st || "";
  let m;
  if (/^OK/.test(st)) return /no Pokemon products found yet/.test(st) ? { label: "No products found yet", cls: "warn" } : { label: "Checking", cls: "ok" };
  if ((m = st.match(/^Blocked, retry in (.+)$/))) return { label: "Paused by the store, back in " + m[1], cls: "warn" };
  if (/^Waiting for you/.test(st)) return { label: "Needs you: finish the check in the browser window", cls: "warn" };
  if (/^Needs a free/.test(st)) return { label: "Needs setup", cls: "setup" };
  if (/^Error/.test(st)) return { label: "Problem, retrying", cls: "bad" };
  if (/^Waiting for first check/.test(st) || !st) return { label: "Starting", cls: "" };
  return { label: st.length > 48 ? st.slice(0, 46) + "..." : st, cls: "" };
}
function text(obj, key, attrs = {}) {
  return h("input", { type: "text", value: obj[key] ?? "", ...attrs, oninput: (e) => { obj[key] = e.target.value; touch(); } });
}
function num(obj, key, attrs = {}) {
  return h("input", { type: "number", step: "any", value: obj[key] ?? "", ...attrs,
    oninput: (e) => { const v = e.target.value; obj[key] = v === "" ? null : Number(v); touch(); } });
}
function secret(obj, key, placeholder) {
  const inp = h("input", { type: "password", value: obj[key] ?? "", placeholder, autocomplete: "off", oninput: (e) => { obj[key] = e.target.value.trim(); touch(); } });
  return h("div", { class: "secret" }, inp, h("button", { class: "btn quiet", type: "button", text: "Show", onclick: (e) => { const s = inp.type === "password"; inp.type = s ? "text" : "password"; e.target.textContent = s ? "Hide" : "Show"; } }));
}
function lines(obj, key, attrs = {}) {
  return h("textarea", { ...attrs, value: (obj[key] || []).join("\n"),
    oninput: (e) => { obj[key] = e.target.value.split(/\n/).map((s) => s.trim()).filter(Boolean); touch(); } });
}
function sw(obj, key, label, invert) {
  return h("label", { class: "switch" }, h("input", { type: "checkbox", checked: invert ? !obj[key] : !!obj[key],
    onchange: (e) => { obj[key] = invert ? !e.target.checked : e.target.checked; touch(); if (key === "enabled") render(); } }), label);
}
function picks(obj, key, options) {
  obj[key] = obj[key] || [];
  return h("div", { class: "checks" }, options.map((r) => h("label", { class: "chip" },
    h("input", { type: "checkbox", checked: obj[key].includes(r), onchange: (e) => {
      obj[key] = e.target.checked ? [...new Set([...obj[key], r])] : obj[key].filter((x) => x !== r); touch(); } }), RETAILERS[r])));
}
const field = (label, input, hint, wide) => h("label", { class: "f" + (wide ? " wide" : "") }, h("span", { class: "l", text: label }), input, hint ? h("span", { text: hint }) : null);
function setting(title, desc, control) { return h("div", { class: "setting" }, h("div", { class: "t" }, h("b", { text: title }), desc ? h("span", { text: desc }) : null), control); }
function move(arr, i, d) { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; touch(); render(); }


async function trialAct(body, okMsg) {
  try {
    const r = await api("/api/action", body);
    toast(r.message || okMsg || "Done", r.ok === false);
    await poll();
  } catch (e) { toast(e.message, true); }
}

function sparkBars(days, ok, fail) {
  const tot = days.map((d) => ok(d) + fail(d)), max = Math.max(1, ...tot);
  return h("div", { class: "spark" }, days.map((d, i) => {
    const n = tot[i], bad = n ? fail(d) / n : 0;
    return h("i", { class: !n ? "none" : bad >= 0.5 ? "bad" : bad >= 0.1 ? "warn" : "", style: n ? "height:" + Math.max(12, Math.round(100 * n / max)) + "%" : "",
      title: (d.day ? d.day.slice(4, 6) + "/" + d.day.slice(6) + ": " : "") + (n ? ok(d) + " loaded, " + fail(d) + " failed" : "no checks") });
  }));
}

function historyPanel(hist, label) {
  const stores = (hist && hist.stores) || [], methods = (hist && hist.methods) || [];
  const sec = (ms) => ms === null || ms === undefined ? "n/a" : (ms / 1000).toFixed(1) + " s";
  return [
    h("h2", { text: "The whole picture" }),
    h("p", { class: "lede", text: "Every store, every day, kept for 180 days in data\\store-history.json, so closing the app loses nothing. Bars show the last 30 days: taller means more checks, amber and red mean failures." }),
    stores.length ? h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
      h("tr", {}, ["Store", "Checks", "Loaded", "Avg check time", "Products found", "Alerts sent", "Last 30 days"].map((x) => h("th", { text: x }))),
      stores.map((s) => {
        const t = s.totals;
        return h("tr", {},
          h("td", { text: s.display }),
          h("td", { text: t.checks ? t.checks + (t.since ? " since " + t.since.slice(4, 6) + "/" + t.since.slice(6) : "") : "none yet" }),
          h("td", { class: t.success === null ? "none" : t.success >= 90 ? "best" : t.success < 60 ? "bad" : "", text: t.success === null ? "n/a" : t.success + "%" }),
          h("td", { text: sec(t.avg_ms) }),
          h("td", { class: s.tracked ? "" : "none", text: s.tracked ? s.tracked + " in the catalog" : (s.search ? "none found yet" : "no store search, add links") }),
          h("td", { text: t.alerts }),
          h("td", {}, sparkBars(s.days, (d) => d.ok, (d) => d.fail)));
      }))) : h("div", { class: "panel empty", text: "No stores are being checked yet." }),
    methods.length ? [
      h("h3", { text: "By method" }),
      h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
        h("tr", {}, ["Method", "Checks (180 days)", "Failed or blocked", "Last 14 days"].map((x) => h("th", { text: x }))),
        methods.map((m) => h("tr", {},
          h("td", { text: label(m.method) }),
          h("td", { text: m.checks }),
          h("td", { class: m.checks && m.fail / m.checks >= 0.5 ? "bad" : "", text: m.checks ? Math.round(100 * m.fail / m.checks) + "%" : "n/a" }),
          h("td", {}, sparkBars(m.days, (d) => d[0], (d) => d[1])))))),
    ] : null,
  ];
}

function methodControl(tri, rows) {
  const arms = (tri.arms || []).filter((a) => !a.control);
  const by = {};
  rows.forEach((r) => { const m = by[r.method] = by[r.method] || { checks: 0, blocks: 0 }; m.checks += r.checks; m.blocks += r.blocks; });
  const stopped = arms.filter((a) => a.stopped);
  const onCount = arms.filter((a) => a.on).length;
  const ruleText = "A method that is on is switched off by itself once it has had more than " + tri.stop_after + " attempts and " + tri.stop_fail_pct + "% or more of them failed or were blocked.";
  const when = (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const kindText = { off: "switched off by you", on: "switched on by you", auto_stop: "stopped automatically", new: "switched on to be tried (new in this version)" };
  return [
    h("h2", { text: "Method control" }),
    h("p", { class: "lede", text: "Turn trial methods on or off here. Changes take effect at once and are remembered, so after a restart everything is as you left it. " + (tri.auto_stop ? ruleText : "Automatic stopping is off.") }),
    stopped.length ? h("div", { class: "banner", style: "display:flex" }, h("span", { text:
      "Stopped automatically: " + stopped.map((a) => a.label + " (" + a.stopped.fails + " of " + a.stopped.attempts + " failed or blocked)").join("; ") + ". Switch one back on to give it a fresh count." })) : null,
    h("div", { class: "mc-tools" },
      h("button", { class: "btn primary", type: "button", text: "Keep only the best 3", onclick: () => trialAct({ action: "trial_bulk", mode: "best" }) }),
      h("button", { class: "btn", type: "button", text: "Turn off all trials", onclick: () => trialAct({ action: "trial_bulk", mode: "off" }) }),
      h("span", { class: "hint", text: onCount + " of " + arms.length + " trial methods on. The best are ranked by how rarely they fail (at least 10 checks)." })),
    h("div", { class: "panel", style: "overflow:hidden" }, arms.map((a, i) => {
      const m = by[a.key] || { checks: 0, blocks: 0 };
      const head = (i === 0 || arms[i - 1].group !== a.group) ? h("div", { class: "mc-group", text: a.group || "Built in" }) : null;
      const pct = m.checks ? Math.round(100 * m.blocks / m.checks) : null;
      const prog = Math.min(100, Math.round(100 * a.attempts / Math.max(1, tri.stop_after + 1)));
      const failPct = a.attempts ? Math.round(100 * a.fails / a.attempts) : 0;
      const state = a.unavailable ? "Cannot run yet" : a.stopped ? "Stopped automatically" : a.on ? "On" : "Off";
      const row = h("div", { class: "mc-row" + (a.on ? "" : " off") },
        h("div", { class: "nm" },
          h("b", {}, a.label, a.best ? h("span", { class: "badge live", style: "display:inline-block;margin-left:8px", text: "Best so far" }) : null),
          h("span", { text: state + (a.on ? " | " + (a.family === "browser" ? "browser stores" : "plain-request stores") : "") }),
          a.unavailable ? h("span", { style: "color:var(--warn)", text: a.unavailable }) : null,
          a.stopped ? h("span", { style: "color:var(--warn)", text: "Stopped " + when(a.stopped.at) + ": " + a.stopped.fails + " of " + a.stopped.attempts + " failed or blocked (" + a.stopped.pct + "%)" }) : null),
        h("div", {}, h("span", { class: "n", text: m.checks }), h("span", { class: "k", text: "checks in all" })),
        h("div", {}, h("span", { class: "n", text: pct === null ? "n/a" : pct + "%" }), h("span", { class: "k", text: "blocked in all" })),
        h("div", {}, h("span", { class: "n", text: a.attempts + " (" + failPct + "% failed)" }),
          h("span", { class: "k", text: "since switched on" }),
          h("div", { class: "mc-bar" }, h("i", { class: failPct >= tri.stop_fail_pct && a.attempts > 5 ? "bad" : failPct >= tri.stop_fail_pct / 2 ? "warn" : "", style: "width:" + prog + "%" }))),
        h("button", { class: "btn" + (a.on ? "" : " primary"), type: "button", text: a.on ? "Turn off" : "Turn on",
          "aria-label": (a.on ? "Turn off " : "Turn on ") + a.label, onclick: () => trialAct({ action: "trial_toggle", key: a.key, on: !a.on }) }));
      return head ? [head, row] : row;
    })),
    h("h3", { text: "How checks are shared out right now" }),
    (tri.balance || []).length ? h("div", { class: "panel" }, h("ul", { class: "feed" }, tri.balance.map((b) =>
      h("li", {}, h("b", { text: (RETAILERS[b.store] || b.store) + ": " }),
        b.settled ? h("span", { class: "badge live", style: "display:inline-block;margin-right:8px;white-space:normal;max-width:100%", text: "Scored: most turns go to " + b.arms[0].label }) : null,
        b.arms.map((a) => a.label + " " + a.share + "%" + (a.rate === null ? " (still learning)" : " (" + a.rate + "% loaded recently)")).join("  |  "))))) :
      h("div", { class: "panel empty", text: tri.auto_balance ? "Still learning. Once a method has had about 6 recent checks at a store, the ones that work get more of that store's checks and the ones that fail get fewer." : "Auto-balance is off, so every method gets equal turns." }),
    h("h3", { text: "What happened" }),
    (tri.events || []).length ? h("div", { class: "panel" }, h("ul", { class: "feed" }, tri.events.slice().reverse().map((e) => {
      const arm = arms.find((a) => a.key === e.arm);
      return h("li", {}, h("b", { text: (arm ? arm.label : e.arm) }), " " + (kindText[e.kind] || e.kind) + " on " + when(e.t) + (e.kind === "auto_stop" && e.detail ? ": " + e.detail : ""));
    }))) : h("div", { class: "panel empty", text: "Nothing has been switched off automatically, and no buttons have been used yet." }),
  ];
}

/* Proxies, User-Agents, VPN and the CAPTCHA service (network.py, captcha.py). */
function networkPanel(net) {
  const n = cfg.network = cfg.network || {}, c = cfg.captcha = cfg.captcha || {};
  const px = (net && net.proxies) || [], vpn = (net && net.vpn) || {}, cap = (net && net.captcha) || {};
  const when = (t) => t ? new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never";
  const capSites = Object.entries(cap.sites || {});
  return [
    h("h2", { text: "Proxies, User-Agents, VPN and CAPTCHA service" }),
    h("p", { class: "lede", text: "Used by the trial methods under \"Other identities and addresses\" and by the checking browsers. Each is scored per store like every other method, so the tables above show whether it pays off. Proxies and the CAPTCHA service see which store pages are checked; your sign-ins never go through them." }),
    h("div", { class: "settings-list" },
      setting("Proxies", "One per line: host:port, host:port:user:pass, http://user:pass@host:port or socks5://host:port. Most VPN apps also offer a SOCKS5 proxy address. Each check uses the next one; one a store blocks sits out there for 2 hours.",
        lines(n, "proxies", { rows: 4, placeholder: "203.0.113.10:8080:user:pass", "aria-label": "Proxies", style: "min-width:260px" })),
      setting("User-Agents", "Browsers the \"different browser each time\" method goes out as. Leave empty for a built-in list of current Chrome, Edge, Firefox and Safari.",
        lines(n, "user_agents", { rows: 3, placeholder: "Leave empty for the built-in list", "aria-label": "User-Agents", style: "min-width:260px" })),
      setting("CAPTCHA service", "Answers CAPTCHAs (reCAPTCHA, hCaptcha, Turnstile, picture codes) in the checking browsers instead of waiting for you. Walmart and Target's Press & hold cannot be answered by these services.",
        h("select", { "aria-label": "CAPTCHA service", onchange: (e) => { c.service = e.target.value; touch(); } },
          [["", "Off"], ["2captcha", "2Captcha"], ["anticaptcha", "Anti-Captcha"], ["capsolver", "CapSolver"]]
            .map(([v, t]) => h("option", { value: v, text: t, selected: (c.service || "") === v })))),
      setting("CAPTCHA service key", "Your API key from that service's account page.", secret(c, "api_key", "API key")),
      setting("Most CAPTCHAs a day", "Never sends more than this many in a day (each costs a fraction of a cent).",
        h("input", { type: "number", min: "1", max: "1000", value: String(c.max_per_day || 30), "aria-label": "Most CAPTCHAs a day",
          oninput: (e) => { c.max_per_day = Math.max(1, Number(e.target.value) || 30); touch(); } })),
      setting("Only on these sites", "For example cvs.com or amazon.com, one per line. Empty = any site.",
        lines(c, "stores", { rows: 2, placeholder: "Empty = any site", "aria-label": "CAPTCHA sites", style: "min-width:260px" }))),
    h("div", { class: "panel", style: "margin-top:10px" }, h("ul", { class: "feed" },
      h("li", {}, h("b", { text: "Proxies: " }), px.length ? px.map((p) => p.proxy + " " + p.checks + " checks, " + p.blocks + " blocked" + (p.resting_at.length ? " (resting at " + p.resting_at.map((x) => RETAILERS[x] || x).join(", ") + ")" : "")).join("  |  ") : "none added"),
      h("li", {}, h("b", { text: "CAPTCHA service: " }), cap.service ? (cap.name + ", " + cap.used_today + " of " + cap.max_per_day + " used today" + (capSites.length ? ". " + capSites.map(([k, v]) => k + " " + v.solved + " of " + v.tried + " got through").join(", ") : "")) : "off"),
      h("li", {}, h("b", { text: "VPN reconnect: " }), vpn.set ? ("runs after " + vpn.after_blocks + " blocks in a row, at most every " + vpn.min_minutes + " min. Ran " + vpn.runs + " times, last " + when(vpn.last) + (vpn.last_result ? " (" + vpn.last_result + ")" : "")) :
        "not set. Add your VPN app's reconnect command to config.yaml under network: vpn_reconnect_command (it runs a program, so it cannot be set from this page). It reconnects the whole PC."))),
  ];
}

function trialPanel(tri) {
  cfg.trials = cfg.trials || {};
  cfg.trials.active = cfg.trials.active || [];
  const t = cfg.trials;
  const where = {};
  Object.entries(tri.current || {}).forEach(([store, arm]) => { (where[arm] = where[arm] || []).push(store); });
  const resting = {};
  (tri.resting || []).forEach((r) => { (resting[r.arm] = resting[r.arm] || []).push(r.store + " (" + r.minutes + " min)"); });
  const rows = (tri.arms || []).map((a) => h("div", { class: "setting" },
    h("div", { class: "t" },
      h("b", { text: a.label + (a.control ? " (normal method, always in the rotation)" : "") }),
      h("span", { text: a.idea }),
      h("span", { text: "Idea from: " + a.source }),
      a.unavailable ? h("span", { style: "color:var(--warn)", text: "Cannot run yet: " + a.unavailable }) : null,
      where[a.key] ? h("span", { text: "In use now at: " + where[a.key].join(", ") }) : null,
      resting[a.key] ? h("span", { style: "color:var(--warn)", text: "Resting after a block at: " + resting[a.key].join(", ") }) : null),
    h("span", { class: "badge" + (a.on ? " live" : ""), text: a.control ? (a.family === "browser" ? "browser stores" : "plain-request stores") : (a.on ? "On" : "Off") })));
  return h("div", {},
    h("div", { class: "settings-list" },
      setting("Run trials", "Off keeps every store on its normal method only.", sw(t, "enabled", "")),
      setting("Checks per turn", "How many checks a method gets before the next one takes over.",
        h("input", { type: "number", min: "5", max: "200", value: String(t.slice_checks || 20), "aria-label": "Checks per turn",
          oninput: (e) => { t.slice_checks = Math.max(5, Number(e.target.value) || 20); touch(); } })),
      setting("Auto-balance checks", "Give methods that are working longer turns at each store and failing ones shorter turns (never below a quarter of a normal turn, so they can recover).", sw(t, "auto_balance", "")),
      setting("Stop failing methods by themselves", "Switch a method off once it has failed or been blocked too often.", sw(t, "auto_stop", "")),
      setting("Stop after more than (attempts)", "A method is only judged after this many attempts since it was switched on.",
        h("input", { type: "number", min: "5", max: "500", value: String(t.stop_after || 25), "aria-label": "Attempts before judging",
          oninput: (e) => { t.stop_after = Math.max(5, Number(e.target.value) || 25); touch(); } })),
      setting("Stop at this failure rate (%)", "Failed or blocked attempts as a share of all attempts.",
        h("input", { type: "number", min: "10", max: "100", value: String(t.stop_fail_pct || 50), "aria-label": "Failure percent",
          oninput: (e) => { t.stop_fail_pct = Math.min(100, Math.max(10, Number(e.target.value) || 50)); touch(); } }))),
    h("div", { class: "settings-list", style: "margin-top:12px" }, rows),
    h("p", { class: "hint", text: "These settings apply after you save. The on and off buttons are in Method control, under the trust table. A full trace of every switch, block and automatic stop is kept in data\\trial-log.jsonl." }));
}


/* ---------- find stock near a ZIP (started by hand) ---------- */
const scanState = Object.assign({ zip: "", radius: 15, online: false, stores: null, everything: true }, store.get("restock-scan", {}));
let scanData = null, scanTimer = null;
function saveScan() { store.set("restock-scan", { zip: scanState.zip, radius: scanState.radius, online: scanState.online, stores: scanState.stores, everything: scanState.everything }); }
async function scanLoad() {
  clearTimeout(scanTimer); scanTimer = null;
  try { scanData = await api("/api/scan"); } catch (e) { return; }
  if (tab === "scan") drawScan();
  if (scanData && scanData.running && tab === "scan") scanTimer = setTimeout(scanLoad, 2000);
}
async function scanStart() {
  try {
    const r = await api("/api/action", { action: "scan_start", zip: scanState.zip, radius: scanState.radius, online: scanState.online, everything: scanState.everything,
      stores: scanState.stores || (scanData && scanData.available) || undefined });
    if (!r.ok) { toast(r.message, true); return; }
    toast("Scanning near " + scanState.zip);
    scanLoad();
  } catch (e) { toast(e.message, true); }
}
async function scanCancel() { try { await api("/api/action", { action: "scan_cancel" }); toast("Stopping the scan"); } catch (e) { toast(e.message, true); } }
function drawScan() {
  const out = $("scan-out"), d = scanData;
  if (!out) return;
  const btn = $("scan-go");
  if (btn) { btn.disabled = !!(d && d.running) || scanState.zip.length !== 5 || !scanState.stores.length; btn.textContent = d && d.running ? "Scanning..." : "Scan now"; }
  const stop = $("scan-stop"); if (stop) stop.style.display = d && d.running ? "" : "none";
  if (!d || !d.state) { out.replaceChildren(h("div", { class: "panel empty", text: "Nothing scanned yet. Enter a ZIP, set a radius and press Scan now." })); return; }
  const stores = Object.entries(d.stores || {});
  const rows = d.rows || [];
  const sites = new Set(rows.filter((r) => !r.online).map((r) => r.retailer + ":" + r.store));
  const dot = { ok: "var(--ok)", bad: "var(--warn)", run: "var(--muted)", wait: "var(--faint)", skip: "var(--faint)", none: "var(--faint)" };
  const head = h("p", { class: "lede", text: (d.running ? "Scanning " : d.state === "cancelled" ? "Stopped. Partial results for " : "Results for ") + d.zip
    + (d.place ? " (" + d.place + ")" : "") + " within " + d.radius + " miles: " + sites.size + " store" + (sites.size === 1 ? "" : "s") + " with stock so far." });
  const prog = h("div", { class: "panel", style: "overflow:hidden" }, stores.map(([k, v]) => h("div", { class: "mrow" },
    h("div", { class: "top" }, h("b", { text: v.name }), h("span", { style: "color:" + (dot[v.state] || "var(--muted)"), text: v.status }))))) ;
  const table = rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "stock" },
    h("tr", {}, ["Distance", "Store", "Product", "Stock", "Price", ""].map((t) => h("th", { text: t }))),
    rows.map((r) => h("tr", {},
      h("td", { text: r.distance === null ? "Online" : r.distance.toFixed(1) + " mi" }),
      h("td", {}, h("b", { text: r.retailer_name }), " ", r.store === "Online" ? "" : r.store, r.address ? h("div", { class: "hint", text: r.address }) : null),
      h("td", { text: r.product }),
      h("td", { text: r.stock + (r.pickup ? ", pickup" : "") }),
      h("td", { text: money(r.price) + (r.over_msrp ? " (over MSRP)" : "") }),
      h("td", {}, r.url ? extLink(r.url, "Open") : null))))) :
    h("div", { class: "panel empty", text: d.running ? "Nothing found yet..." : "No stores in range have these products in stock right now." });
  out.replaceChildren(head, prog, h("h2", { text: "Stores with stock, nearest first" }), table);
}

/* ---------- views ---------- */
const views = {
  dash() {
    const search = h("input", { type: "search", placeholder: "Filter by product name", "aria-label": "Filter by product name", value: dashState.q, oninput: (e) => { dashState.q = e.target.value; drawTable(); } });
    const sel = h("select", { "aria-label": "Retailer", onchange: (e) => { dashState.retailer = e.target.value; drawTable(); } },
      h("option", { value: "", text: "All retailers" }), Object.entries(RETAILERS).map(([k, v]) => h("option", { value: k, text: v, selected: dashState.retailer === k })));
    const only = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: dashState.inOnly, onchange: (e) => { dashState.inOnly = e.target.checked; drawTable(); } }), "In stock only");
    const zipIn = h("input", { type: "text", inputmode: "numeric", maxlength: "5", placeholder: "ZIP", "aria-label": "Filter by ZIP code", value: nearState.zip,
      oninput: (e) => { nearState.zip = e.target.value.replace(/\D/g, "").slice(0, 5); lookupNear(); } });
    const where = h("span", { class: "where", id: "near-where", text: nearWhere() });
    const radVal = h("span", { class: "radius-val", id: "near-rad", text: nearState.radius + " mi" });
    const rad = h("input", { type: "range", min: "1", max: "100", step: "1", value: String(nearState.radius), "aria-label": "Radius in miles",
      oninput: (e) => { nearState.radius = Number(e.target.value); radVal.textContent = nearState.radius + " mi"; store.set("restock-near", { zip: nearState.zip, radius: nearState.radius, online: nearState.online }); drawDash(); } });
    const onl = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: nearState.online, onchange: (e) => { nearState.online = e.target.checked; store.set("restock-near", { zip: nearState.zip, radius: nearState.radius, online: nearState.online }); drawDash(); } }), "Include online stock");
    const zipbar = h("div", { class: "zipbar" + (nearFilterOn() ? " on" : ""), id: "zipbar" }, h("b", { text: "Near" }), zipIn, where, h("span", { text: "within" }), rad, radVal, onl,
      h("button", { class: "btn quiet", type: "button", text: "Clear", onclick: () => { nearState.zip = ""; nearState.point = null; store.set("restock-near", { zip: "", radius: nearState.radius, online: nearState.online }); render(); } }));
    setTimeout(drawDash);
    return [
      h("h1", { text: "Home" }),
      h("p", { class: "lede", text: "What is in stock right now, and whether every store is being checked. Products are found for you, so there is nothing to look up or paste." }),
      h("div", { id: "setup" }),
      h("h2", { text: "In stock now" }), h("div", { id: "instock" }),
      h("h2", { text: "Your stores" }), h("div", { id: "health" }),
      h("div", { class: "two" },
        h("div", {}, h("h2", { text: "Everything being watched" }), h("div", { class: "toolbar" }, search, sel, only),
          h("details", { class: "more", open: nearFilterOn() }, h("summary", { text: "Only show stores near a ZIP" }), zipbar),
          h("div", { class: "table-wrap", id: "stock" })),
        h("div", {}, h("h2", { text: "Recent alerts" }), h("div", { class: "panel" }, h("ul", { class: "feed", id: "alerts" })),
          h("details", { class: "more" }, h("summary", { text: "Technical log (for troubleshooting)" }),
            h("div", { class: "panel" }, h("ul", { class: "feed log", id: "activity" }))))),
    ];
  },

  times() {
    const sel = h("select", { "aria-label": "Store chain", onchange: (e) => { timesState.retailer = e.target.value; timesState.place = ""; loadPatterns(); } },
      h("option", { value: "", text: "All stores" }), Object.entries(RETAILERS).map(([k, v]) => h("option", { value: k, text: v, selected: timesState.retailer === k })));
    const place = h("select", { id: "place-sel", "aria-label": "Location", onchange: (e) => { timesState.place = e.target.value; loadPatterns(); } },
      h("option", { value: "", text: "Every location" }));
    setTimeout(loadPatterns);
    return [
      h("h1", { text: "Restock patterns" }),
      h("p", { class: "lede", text: "Every restock the monitor catches while it runs is logged here by store, day and hour. After a couple of weeks you can see when each store usually gets stock, so you go at the right time instead of driving around." }),
      h("div", { class: "toolbar" }, sel, place),
      h("div", { id: "times-body" }, h("div", { class: "panel empty", text: "Loading restock history" })),
    ];
  },

  places() {
    setTimeout(loadPlaces);
    return [
      h("h1", { text: "Stores with stock" }),
      h("p", { class: "lede", text: "Stores that have Pokemon cards in stock right now, from the latest checks. Pick an area and a radius, then click a store on the map or in the list to see exactly what it has. Tick the last box to also list every store near you." }),
      h("div", { id: "places-body" }, h("div", { class: "panel empty", text: "Loading stores" })),
    ];
  },

  found() {
    const q = h("input", { type: "search", placeholder: "Filter by name", value: foundState.q, "aria-label": "Filter products", oninput: (e) => { foundState.q = e.target.value; drawFound(); } });
    const typeSel = h("select", { id: "found-type", "aria-label": "Product type", onchange: (e) => { foundState.type = e.target.value; saveFound(); drawFound(); } }, h("option", { value: "", text: "All product types" }));
    const rSel = h("select", { "aria-label": "Store", onchange: (e) => { foundState.retailer = e.target.value; saveFound(); drawFound(); } },
      h("option", { value: "", text: "All stores" }), SEARCHABLE.map((k) => h("option", { value: k, text: RETAILERS[k] || k, selected: foundState.retailer === k })));
    const ign = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: foundState.showIgnored, onchange: (e) => { foundState.showIgnored = e.target.checked; saveFound(); drawFound(); } }), "Show ignored");
    setTimeout(loadFound);
    return [
      h("h1", { text: "Found for you" }),
      h("p", { class: "lede", text: "Pokemon products the monitor found by searching store catalogs, grouped across stores. They are checked automatically, the most wanted types first. Ignore any you don't care about." }),
      h("div", { class: "toolbar" }, q, typeSel, rSel, ign, h("button", { class: "btn", type: "button", text: "Search stores now", onclick: async () => {
        try { await api("/api/action", { action: "rediscover" }); toast("Searching store catalogs now"); setTimeout(loadFound, 8000); } catch (e) { toast(e.message, true); } } })),
      h("div", { id: "found-community" }),
      h("div", { id: "found-body" }, h("div", { class: "panel empty", text: "Loading products" })),
    ];
  },

  watch() {
    cfg.watchlist = cfg.watchlist || [];
    const list = cfg.watchlist.map((w, i) => {
      w.ids = w.ids || {}; w.urls = w.urls || []; w.retailers = w.retailers || [];
      if (w.enabled === undefined) w.enabled = true;
      if (w.in_store === undefined) w.in_store = true;
      return h("div", { class: "card" + (w.enabled ? "" : " off") },
        h("div", { class: "card-head" }, sw(w, "enabled", ""), h("input", { class: "title", type: "text", value: w.name || "", placeholder: "Product name", "aria-label": "Product name", oninput: (e) => { w.name = e.target.value; touch(); } }),
          h("button", { class: "btn quiet danger", type: "button", text: "Remove", onclick: () => { if (confirm("Remove " + (w.name || "this product") + "?")) { cfg.watchlist.splice(i, 1); touch(); render(); } } })),
        h("div", { class: "card-body" },
          field("UPC", text(w, "upc", { placeholder: "12 digits from the barcode", inputmode: "numeric" }), "Finds it at Target, Best Buy, Walmart and Kroger for you"),
          field("MSRP", num(w, "msrp", { placeholder: "49.99" }), "Alerts only at or near this price"),
          field("Target item (TCIN)", text(w.ids, "target", { placeholder: "Number after A- in the link" })),
          field("Best Buy SKU", text(w.ids, "bestbuy", { placeholder: "skuId in the link" })),
          field("Walmart item", text(w.ids, "walmart", { placeholder: "Number after /ip/ in the link" })),
          field("Kroger product ID", text(w.ids, "kroger", { placeholder: "13 digits at the end of a Kroger or Fred Meyer link" })),
          field("Product links", lines(w, "urls", { placeholder: "One link per line: Pokemon Center, GameStop, Costco, Amazon, Walgreens, CVS, or any store" }), "Tracking bits are removed from links automatically", true),
          field("Only check at", picks(w, "retailers", Object.keys(RETAILERS)), "Leave all unticked to check everywhere", true),
          h("div", { class: "wide" }, sw(w, "in_store", "Check nearby store shelves too (Target, Best Buy, Kroger)"))));
    });
    return [
      h("h1", { text: "Your own links" }),
      h("p", { class: "lede", text: "Specific items you want, on top of what the monitor finds on its own. You do not need to add products for most stores: every enabled store searches its own site, and also looks up what other stores list by UPC and name. Add one here only for something it has not found." }),
      list.length ? list : h("div", { class: "panel empty", text: "No products yet. Add one with its UPC or a product link." }),
      h("button", { class: "btn primary", type: "button", text: "Add product", onclick: () => { cfg.watchlist.push({ name: "", upc: "", msrp: null, ids: {}, urls: [], retailers: [], in_store: true, enabled: true }); touch(); render(); } }),
    ];
  },

  search() {
    cfg.searches = cfg.searches || [];
    const list = cfg.searches.map((s, i) => {
      s.keywords = s.keywords || {}; s.retailers = s.retailers || [];
      if (s.enabled === undefined) s.enabled = true;
      return h("div", { class: "card" + (s.enabled ? "" : " off") },
        h("div", { class: "card-head" }, sw(s, "enabled", ""), h("input", { class: "title", type: "text", value: s.name || "", placeholder: "Search name", "aria-label": "Search name", oninput: (e) => { s.name = e.target.value; touch(); } }),
          h("button", { class: "btn quiet danger", type: "button", text: "Remove", onclick: () => { if (confirm("Remove this search?")) { cfg.searches.splice(i, 1); touch(); render(); } } })),
        h("div", { class: "card-body" },
          field("Search for", text(s, "query", { placeholder: "pokemon trading card game" }), "What you would type in the store's search box", true),
          field("Search at", picks(s, "retailers", SEARCHABLE), "Stores whose results are built by script are searched in the browser, so they take a little longer", true),
          field("Must include one of", lines(s.keywords, "include_any", { placeholder: "elite trainer box\nbooster bundle" }), "Added to your global keywords"),
          field("Never alert on", lines(s.keywords, "exclude", { placeholder: "sleeves\nbinder" }), "Added to your global excludes"),
          field("Max price", num(s, "max_price", { placeholder: "Optional" }), "Overrides the MSRP rules for this search"),
          h("div", {}, sw(s, "in_store", "Check nearby stores for matches"), h("p", { class: "hint", text: "Uses more requests. Best for one or two searches." }))));
    });
    return [
      h("h1", { text: "Keyword searches" }),
      h("p", { class: "lede", text: "Catch new listings you don't have a UPC for. Results only alert when the title passes your keywords, the price is at MSRP, and it's in stock." }),
      list.length ? list : h("div", { class: "panel empty", text: "No searches yet." }),
      h("button", { class: "btn primary", type: "button", text: "Add search", onclick: () => { cfg.searches.push({ name: "", query: "", retailers: ["target", "walmart"], keywords: { include_any: [], exclude: [] }, max_price: null, in_store: false, enabled: true }); touch(); render(); } }),
    ];
  },

  filters() {
    setTimeout(loadSellers);
    const typesTable = () => {
      cfg.product_types = cfg.product_types || {};
      if (!TYPES_LIST.length) return h("p", { class: "hint", text: "Loading product types" });
      return h("table", { class: "rules" },
        h("thead", {}, h("tr", {}, h("th", { text: "Product type" }), h("th", { text: "MSRP" }), h("th", { style: "text-align:right", text: "Alert" }))),
        h("tbody", {}, TYPES_LIST.map((t) => {
          const o = cfg.product_types[t.key] = cfg.product_types[t.key] || {};
          const on = o.alert !== false;
          return h("tr", {},
            h("td", {}, t.label),
            h("td", { style: "width:140px" }, h("input", { type: "number", step: "any", value: "msrp" in o ? (o.msrp ?? "") : (t.msrp ?? ""), placeholder: "Any price", "aria-label": t.label + " MSRP",
              oninput: (e) => { o.msrp = e.target.value === "" ? null : Number(e.target.value); touch(); } })),
            h("td", { style: "width:90px;text-align:right" }, h("label", { class: "switch" }, h("input", { type: "checkbox", checked: on, "aria-label": "Alert for " + t.label,
              onchange: (e) => { o.alert = e.target.checked; touch(); } }))));
        })));
    };
    const k = cfg.keywords = cfg.keywords || {}, st = cfg.settings;
    cfg.price_rules = cfg.price_rules || [];
    const rules = h("table", { class: "rules" },
      h("thead", {}, h("tr", {}, h("th", { text: "When the title contains" }), h("th", { text: "MSRP" }), h("th", {}))),
      h("tbody", {}, cfg.price_rules.map((r, i) => h("tr", {},
        h("td", {}, text(r, "match", { placeholder: "elite trainer box" })),
        h("td", { style: "width:130px" }, num(r, "max_price")),
        h("td", { class: "act", style: "width:150px;text-align:right" },
          h("button", { class: "btn quiet", type: "button", title: "Move up", "aria-label": "Move up", text: "↑", onclick: () => move(cfg.price_rules, i, -1) }),
          h("button", { class: "btn quiet", type: "button", title: "Move down", "aria-label": "Move down", text: "↓", onclick: () => move(cfg.price_rules, i, 1) }),
          h("button", { class: "btn quiet danger", type: "button", text: "Remove", onclick: () => { cfg.price_rules.splice(i, 1); touch(); render(); } }))))));

    const tTitle = h("input", { type: "text", placeholder: "Paste a product title, e.g. Pokemon TCG Destined Rivals Elite Trainer Box" });
    const tPrice = h("input", { type: "number", step: "any", placeholder: "49.99" });
    const tSearch = h("select", {}, h("option", { value: "", text: "Global filters only" }), (cfg.searches || []).map((s) => h("option", { value: s.name, text: "Search: " + s.name })));
    const tThird = h("label", { class: "switch" }, h("input", { type: "checkbox" }), "Third-party seller");
    const verdict = h("div", { class: "verdict", text: "Try a title to see whether it would alert and why." });
    const runTest = async () => {
      if (dirty()) { verdict.className = "verdict"; verdict.textContent = "Save your changes first; the tester uses saved settings."; return; }
      try {
        const r = await api("/api/test-filter", { title: tTitle.value, price: tPrice.value, search: tSearch.value, third_party: tThird.querySelector("input").checked });
        verdict.className = "verdict " + (r.alert ? "yes" : "no");
        verdict.textContent = (r.alert ? "Would alert when in stock." : "Would not alert: " + r.reason + ".") + (r.msrp ? " MSRP used " + money(r.msrp) + ", highest price allowed " + money(r.price_cap) + "." : " No MSRP rule matched, so any price passes.");
      } catch (e) { toast(e.message, true); }
    };

    const muted = (status && status.muted) || [];
    return [
      h("h1", { text: "Prices & filters" }),
      h("p", { class: "lede", text: "Decide what counts as a restock worth hearing about. Keyword lists ignore capitals and accents, so Pokemon and Pokémon match the same." }),
      h("h2", { text: "Keywords" }),
      h("div", { class: "card" }, h("div", { class: "card-body" },
        field("Must include one of", lines(k, "include_any"), "One per line. Leave empty to allow anything."),
        field("Must include all of", lines(k, "include_all"), "One per line. Every phrase must appear."),
        field("Never alert on", lines(k, "exclude"), "One per line. Short words match whole words only, so 'lot' won't block 'slot'."),
        h("div", { class: "wide" }, sw(k, "apply_to_watchlist", "Apply keywords to my product list too (normally only searches)")))),
      h("h2", { text: "Product types" }),
      h("p", { class: "hint", text: "Every listing is sorted into a product type from its title. Turn off types you don't want alerts for, and set the MSRP used as the price cap. Leave MSRP blank to accept any price for that type." }),
      typesTable(),
      h("h2", { text: "Your own price rules" }),
      h("p", { class: "hint", text: "Optional. These win over the product-type MSRP when a title contains the phrase. The first matching row wins, so keep specific phrases above general ones." }),
      rules,
      h("p", {}, h("button", { class: "btn", type: "button", text: "Add price rule", onclick: () => { cfg.price_rules.push({ match: "", max_price: null }); touch(); render(); } })),
      h("h2", { text: "Accuracy" }),
      h("div", { class: "settings-list" },
        setting("Price wiggle room", "Allow this many percent over MSRP for rounding and small price bumps.", num(st, "msrp_tolerance_pct")),
        setting("Store sellers only", "Skip marketplace and third-party listings, where scalper prices live.", sw(st, "retailer_sold_only", "")),
        setting("Double-check before alerting", "When stock appears, look once more a few seconds later and only alert if it is still there. Cuts false alarms from glitchy pages.", sw(st, "confirm_restocks", "")),
        setting("Smallest store quantity", "Ignore a store showing fewer units than this. 1 alerts on everything; 2 skips single units, which are often already sold or misplaced.", num(st, "min_store_qty")),
        setting("Include non-English products", "Japanese and other-language products, when a US store lists them.", sw(st, "allow_non_english", ""))),
      h("h2", { text: "Marketplace sellers" }),
      h("p", { class: "hint", text: "Other sellers on Walmart, Amazon and similar stores are judged by what they charge. A seller is blocked by itself when at least 80% of its last offers (3 or more, within 30 days) are past your limit and it typically asks 25% or more over MSRP. It is let through again by itself if it starts pricing fairly. Block or allow by hand to decide yourself." }),
      h("div", { id: "sellers" }, h("p", { class: "hint", text: "Loading sellers" })),
      h("h2", { text: "Muted items" }),
      muted.length ? h("div", { class: "settings-list" }, muted.map((key) => setting(key, "", h("button", { class: "btn", type: "button", text: "Unmute", onclick: () => mute(key, false) })))) :
        h("p", { class: "hint", text: "Nothing muted. Use Mute on the dashboard to silence a single listing." }),
      h("h2", { text: "Test a listing" }),
      h("div", { class: "card" }, h("div", { class: "card-body" },
        field("Product title", tTitle, null, true), field("Price", tPrice), field("Using", tSearch),
        h("div", { style: "display:flex;align-items:end;gap:12px;flex-wrap:wrap" }, tThird, h("button", { class: "btn primary", type: "button", text: "Test listing", onclick: runTest })),
        h("div", { class: "wide" }, verdict))),
    ];
  },

  areas() {
    ensureAreas();
    const n = notifyCfg();
    const capVal = h("span", { class: "radius-val", text: n.max_miles ? n.max_miles + " mi" : "Off" });
    setTimeout(drawAreaMap);
    return [
      h("h1", { text: "My areas" }),
      h("p", { class: "lede", text: "Where you shop. Stores inside any of these circles are checked and can alert; stores outside them are ignored. Give an area its own Discord channel to send it only the stores inside that area." }),
      areasEditor(),
      h("div", { id: "area-map", class: "area-map" }),
      h("p", {}, h("button", { class: "btn", type: "button", text: "Add area", onclick: () => { cfg.areas.push({ name: cfg.areas.length ? "Work" : "Home", zip: "", radius_miles: 15 }); touch(); render(); } })),
      h("h2", { text: "Alert distance" }),
      h("div", { class: "settings-list" },
        setting("Only alert for stores within", "A tighter limit for alerts than your areas, for example check 25 miles but only ping for stores within 10. Off uses your areas.",
          h("div", { style: "display:flex;gap:10px;align-items:center" }, h("input", { type: "range", min: "0", max: "50", value: String(n.max_miles || 0), "aria-label": "Alert distance in miles",
            oninput: (e) => { const v = Number(e.target.value); n.max_miles = v || null; capVal.textContent = v ? v + " mi" : "Off"; touch(); drawAreaMap(); } }), capVal)),
        setting("Check store shelves", "Shelf stock at Target, Best Buy and Kroger stores in your areas.", sw(cfg.settings, "in_store", ""))),
      h("p", { class: "hint" }, "Skip single stores you never visit on ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); go("places"); }, text: "Stores with stock" }), "."),
    ];
  },

  scan() {
    setTimeout(scanLoad, 0);
    const avail = (scanData && scanData.available) || ["target", "bestbuy", "kroger", "gamestop", "cvs", "walgreens"];
    const names = (scanData && scanData.names) || { target: "Target", bestbuy: "Best Buy", kroger: "Kroger family", gamestop: "GameStop", cvs: "CVS", walgreens: "Walgreens" };
    const onlineOnly = (scanData && scanData.online_only) || ["walgreens"];
    const isOn = new Set(((status && status.retailers) || []).map((r) => r.name));
    // First visit: start with every store that is switched on. After that, the ticks are yours and are remembered.
    scanState.stores = (scanState.stores || avail.filter((k) => !status || isOn.has(k))).filter((x) => avail.includes(x));
    const zip = h("input", { type: "text", inputmode: "numeric", maxlength: "5", placeholder: "ZIP code", "aria-label": "ZIP code", value: scanState.zip,
      oninput: (e) => { scanState.zip = e.target.value.replace(/\D/g, "").slice(0, 5); e.target.value = scanState.zip; saveScan(); drawScan(); },
      onkeydown: (e) => { if (e.key === "Enter" && scanState.zip.length === 5) scanStart(); } });
    const radVal = h("span", { class: "radius-val", text: scanState.radius + " mi" });
    const rad = h("input", { type: "range", min: "1", max: "100", step: "1", value: String(scanState.radius), "aria-label": "Search radius in miles",
      oninput: (e) => { scanState.radius = Number(e.target.value); radVal.textContent = scanState.radius + " mi"; saveScan(); } });
    const chips = h("div", { class: "checks" }, avail.map((k) => h("label", { class: "chip", title: onlineOnly.includes(k) ? "Publishes no shelf stock: only the online listing is checked" : "" },
      h("input", { type: "checkbox", checked: scanState.stores.includes(k), onchange: (e) => {
        scanState.stores = e.target.checked ? [...new Set([...scanState.stores, k])] : scanState.stores.filter((x) => x !== k); saveScan(); } }),
      (names[k] || k) + (onlineOnly.includes(k) ? " (online only)" : "") + (status && !isOn.has(k) ? " (off in Stores & keys)" : ""))));
    const pickAll = (on) => { scanState.stores = on ? avail.slice() : []; saveScan(); render(); };
    const all = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: scanState.everything, onchange: (e) => { scanState.everything = e.target.checked; saveScan(); drawScan(); } }),
      "Search every product at the stores ticked below");
    const onl = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: scanState.online, onchange: (e) => { scanState.online = e.target.checked; saveScan(); } }), "Also list online stock");
    return [
      h("h1", { text: "Scan a ZIP" }),
      h("p", { class: "lede", text: "Type a ZIP, choose how far to look, and press Scan now. The app asks each store that shares shelf stock which of its stores nearby have your products. It only runs when you press the button, sends no Discord alerts, and does not change your areas." }),
      h("div", { class: "zipbar on" }, h("b", { text: "Near" }), zip, h("span", { text: "within" }), rad, radVal),
      h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "wide" }, all,
        h("p", { style: "margin:8px 0 6px", class: "hint", text: scanState.everything
          ? "On: asks the stores ticked below, and searches each store's own catalog for Pokemon products right now, so you do not need to add links first. Product types you turned alerts off for are skipped."
          : "Off: only your own links plus what was already found for you." }),
        h("div", { style: "display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin:10px 0 6px" },
          h("b", { text: "Stores to scan" }),
          h("button", { class: "btn quiet", type: "button", text: "All", onclick: () => pickAll(true) }),
          h("button", { class: "btn quiet", type: "button", text: "None", onclick: () => pickAll(false) }),
          h("span", { class: "hint", text: scanState.stores.length + " of " + avail.length + " selected" })),
        chips,
        h("div", { style: "margin-top:8px" }, onl)))),
      h("p", {}, h("button", { class: "btn primary", id: "scan-go", type: "button", text: "Scan now", disabled: scanState.zip.length !== 5 || !scanState.stores.length, onclick: scanStart }),
        " ", h("button", { class: "btn quiet", id: "scan-stop", type: "button", text: "Stop", style: "display:none", onclick: scanCancel })),
      h("div", { id: "scan-out" }),
      h("p", { class: "hint", text: "With the switch on, up to 150 products per store are checked (a store with no search uses what discovery already found); with it off, up to 30. Walmart and the other sites do not share shelf stock, so they are not part of this scan." }),
    ];
  },

  accounts() {
    const rows = (status && status.accounts) || [];
    const enabled = new Set(((status && status.retailers) || []).map((r) => r.name));
    const when = (t) => t ? new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    const act = async (body, quiet) => { try { const r = await api("/api/action", body); if (!quiet) toast(r.message || "Done", r.ok === false); await poll(); } catch (e) { toast(e.message, true); } };
    const signed = rows.filter((r) => r.state === "signed_in");
    const card = (r) => {
      const days = r.expires ? Math.max(0, Math.round((r.expires - Date.now() / 1000) / 86400)) : null;
      const badge = r.state === "signed_in"
        ? h("span", { class: "badge live", text: r.working === false ? "Signed in, store not loading well" : "Signed in and saved" })
        : h("span", { class: "badge", text: r.lost ? "Sign-in is gone" : "Not signed in" });
      return h("div", { class: "mc-row", style: "grid-template-columns:minmax(0,1.5fr) minmax(0,2fr) auto" },
        h("div", { class: "nm" }, h("b", {}, r.display, " ", badge),
          h("span", { text: enabled.has(r.site) ? "Being checked" : "Not being checked (switched off in Stores & keys)" })),
        h("div", { class: "nm" },
          r.state === "signed_in" ? [
            h("span", { text: "Saved in the " + r.profiles.join(", ") + " browser" + (r.profiles.length > 1 ? "s" : "") + (r.confirmed ? " (you confirmed it)" : "") + (r.since ? ", since " + when(r.since) : "") + ". It stays when you close the app." }),
            h("span", { style: r.working === false ? "color:var(--warn)" : "color:var(--ok)", text: r.working === null || r.working === undefined
              ? "Working: no checks to judge by yet" : r.working ? "Working: the store loaded " + r.success + "% of recent checks" : "Not working well: the store loaded " + r.success + "% of recent checks" }),
            days !== null ? h("span", { text: days > 0 ? "Sign-in lasts about " + days + " more day" + (days === 1 ? "" : "s") : "The sign-in cookie is about to expire, sign in again soon" }) : null,
          ] : [
            r.lost ? h("span", { style: "color:var(--warn)", text: "It was saved before but is gone now (expired or you signed out), " + when(r.lost) + ". Sign in again." }) : h("span", { text: "Press Sign in, log in to your account in the window that opens, and it saves by itself." }),
            r.last_seen ? h("span", { text: "Last looked " + when(r.last_seen) }) : h("span", { text: "Not looked at yet (the checking browser has to be running)" }),
          ]),
        h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end" },
          h("button", { class: "btn" + (r.state === "signed_in" ? "" : " primary"), type: "button", text: r.state === "signed_in" ? "Open again" : "Sign in", onclick: () => act({ action: "account_open", store: r.site }) }),
          r.state === "signed_in" ? null : h("button", { class: "btn", type: "button", text: "I signed in", title: "Use if you signed in but it still says not signed in", onclick: () => act({ action: "account_confirm", store: r.site }) })));
    };
    const profiles = (status && status.browser && status.browser.profiles) || [];
    const kindName = { app: "App browser", stealth: "Stealth browser", own: "Your own browser" };
    const profileRow = (p) => h("div", { class: "mc-row", style: "grid-template-columns:minmax(0,1.6fr) minmax(0,2fr) auto" },
      h("div", { class: "nm" }, h("b", {}, p.name, " ", h("span", { class: "badge" + (p.running ? " live" : ""), text: p.running ? "Running" : "Not running" })),
        h("span", { text: (kindName[p.kind] || "Browser") + (p.mb != null ? ", " + p.mb + " MB saved" : "") })),
      h("div", { class: "nm" },
        p.resting.length ? h("span", { style: "color:var(--warn)", text: "Blocked and resting: " + p.resting.map((x) => x.site + " (" + x.minutes + " min)").join(", ") }) : h("span", { text: "No store is resting this browser" }),
        p.failed ? h("span", { style: "color:var(--warn)", text: p.failed }) : null),
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end" },
        h("button", { class: "btn", type: "button", text: "Clear bot-check cookies", title: "Deletes the cookies Akamai, PerimeterX and Cloudflare use to remember a bad opinion of this browser. Your sign-ins stay.",
          onclick: () => { if (confirm("Delete the bot-check cookies in '" + p.name + "'? Sign-ins stay.")) act({ action: "profile_clear_bot", profile: p.name }); } }),
        h("button", { class: "btn danger", type: "button", text: p.kind === "own" ? "Clear all cookies" : "Reset profile", title: p.kind === "own" ? "Clears every cookie in your own browser, including sign-ins." : "Deletes this browser's whole saved profile: cookies, sign-ins and cache. It starts fresh.",
          onclick: () => { if (confirm((p.kind === "own" ? "Clear every cookie in '" : "Delete the whole saved profile '") + p.name + "'? You will have to sign in to your stores again.")) act({ action: "profile_reset", profile: p.name }); } })));
    return [
      h("h1", {}, "Account ", h("b", { text: "sign-ins" })),
      h("p", { class: "lede", text: "Stores trust a browser that is signed in to a real account more than an anonymous one. Sign in once and the checking browser keeps it between runs. The app looks at the saved cookies every few minutes (never their contents) and shows here which stores have a sign-in saved and whether the store is still loading well." }),
      h("div", { class: "mc-tools" },
        h("button", { class: "btn", type: "button", text: "Check now", onclick: () => act({ action: "accounts_scan" }) }),
        h("span", { class: "hint", text: signed.length + " of " + rows.length + " stores signed in. The first check happens about a minute after the app starts." })),
      h("div", { class: "panel", style: "overflow:hidden" }, rows.map(card)),
      h("h2", { class: "sec", text: "Browser profiles" }),
      h("p", { class: "lede", text: "If a store such as CVS or Target (Akamai, PerimeterX) starts blocking a browser because its cookies earned a bad reputation, clear the bot-check cookies first: it keeps your sign-ins. If that does not help, Reset profile deletes everything that browser saved and it starts clean." }),
      profiles.length ? h("div", { class: "panel", style: "overflow:hidden" }, profiles.map(profileRow)) : h("div", { class: "panel empty", text: "No checking browser is set up yet." }),
      h("p", { class: "hint", text: "How it knows: a signed-in browser holds cookies that only exist after logging in. Some stores name them in ways the app cannot recognise, so if you signed in and it says not signed in, press I signed in and it will remember that for as long as the cookies stay. Sign-ins live in your browser folders under data\\ (keep that folder private). Walmart: also pick your store in that window." }),
    ];
  },

  methods() {
    const ses = (status && status.sessions) || { rows: [], profiles: [], resting: [] };
    const rows = ses.rows || [];
    const by = {};
    rows.forEach((r) => { const m = by[r.method] = by[r.method] || { method: r.method, checks: 0, blocks: 0, streak: 0, best: 0 };
      m.checks += r.checks; m.blocks += r.blocks; m.streak += r.streak; m.best = Math.max(m.best, r.best); });
    const methods = Object.values(by).map((m) => Object.assign(m, { per: m.blocks ? m.checks / m.blocks : null }))
      .sort((a, b) => (b.per === null ? 1e9 + b.checks : b.per) - (a.per === null ? 1e9 + a.checks : a.per));
    const tri = (status && status.trials) || { arms: [], current: {}, resting: [], enabled: false, slice_checks: 20 };
    const armName = {};
    (tri.arms || []).forEach((a) => { armName[a.key] = a.label; });
    const label = (m) => armName[m] || (m.startsWith("captcha-") ? "CAPTCHA service: " + m.slice(8) : m === "direct" ? "Plain requests" : m === "pool" ? "Browser pool" : m.endsWith("+page") ? "Page fetch: " + m.slice(0, -5) : "Browser: " + m);
    const totalChecks = methods.reduce((t, m) => t + m.checks, 0), totalBlocks = methods.reduce((t, m) => t + m.blocks, 0);
    const top = methods.find((m) => m.checks >= 5) || methods[0];
    const maxPer = Math.max(1, ...methods.map((m) => m.per === null ? m.checks : m.per));
    const sites = [...new Set(rows.map((r) => r.site))].sort();
    const score = (r) => r ? (r.blocks === 0 ? 1e9 + r.checks : (r.avg_before_block === null ? 0 : r.avg_before_block)) : -1;
    const cell = (site, method, bestMethod) => {
      const r = rows.find((x) => x.site === site && x.method === method);
      if (!r) return h("td", { class: "none", text: "no data" });
      const txt = r.blocks === 0 ? "never blocked (" + r.checks + ")" : Math.round(r.avg_before_block || 0) + " avg, " + r.blocks + " blocks";
      return h("td", { class: method === bestMethod ? "best" : (r.blocks > 2 && (r.avg_before_block || 0) < 10 ? "bad" : ""), text: txt });
    };
    const matrix = sites.map((site) => {
      const best = methods.map((m) => m.method).reduce((a, m) => score(rows.find((x) => x.site === site && x.method === m)) > score(rows.find((x) => x.site === site && x.method === a)) ? m : a, methods[0].method);
      return h("tr", {}, h("td", { text: site }), methods.map((m) => cell(site, m.method, best)));
    });
    return [
      h("h1", { text: "Connection methods" }),
      h("p", { class: "lede", text: "Which way of loading pages lasts longest before a store blocks it. Counts are saved between runs, so the picture gets sharper over time." }),
      trustReport((status && status.trust) || { stores: [], feeds: [] }),
      historyPanel(status && status.history, label),
      methodControl(tri, rows),
      methods.length ? [
        h("div", { class: "hero" },
          h("div", { class: "big" }, h("div", { class: "k", text: "Lasting longest so far" }), h("div", { class: "v grad", text: label(top.method) }),
            h("div", { class: "k", text: top.per === null ? "Never blocked in " + top.checks + " checks" : "About " + Math.round(top.per) + " checks per block" })),
          h("div", { class: "stat" }, h("div", { class: "n", text: totalChecks }), h("div", { class: "k", text: "checks recorded" })),
          h("div", { class: totalBlocks ? "stat warn" : "stat" }, h("div", { class: "n", text: totalBlocks }), h("div", { class: "k", text: "blocks" })),
          h("div", { class: "stat" }, h("div", { class: "n", text: (ses.profiles || []).length }), h("div", { class: "k", text: "browser profiles" }))),
        h("h2", { text: "Checks per block, by method" }),
        h("div", { class: "panel", style: "overflow:hidden" }, methods.map((m) => {
          const w = Math.max(3, Math.round(100 * (m.per === null ? m.checks : m.per) / maxPer));
          return h("div", { class: "mrow" },
            h("div", { class: "top" }, h("b", { text: label(m.method) }), h("span", { text: m.per === null ? "never blocked" : "1 block per " + Math.round(m.per) + " checks" })),
            h("div", { class: "bar" }, h("i", { class: m.blocks > m.checks / 10 ? "warn" : "", style: "width:" + w + "%" })),
            h("div", { class: "sub2", text: m.checks + " checks, " + m.blocks + " blocks, longest clean run " + m.best }));
        })),
        h("h2", { text: "Best method for each store" }),
        h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
          h("tr", {}, h("th", { text: "Store" }), methods.map((m) => h("th", { text: label(m.method) }))), matrix)),
        h("p", { class: "hint", text: "Highlighted = lasts longest at that store. Amber = blocked often." }),
      ] : h("div", { class: "panel empty", text: "No checks recorded yet. Numbers appear once the monitor has run for a few minutes." }),
      (ses.resting || []).length ? [h("h2", { text: "Resting right now" }), h("div", { class: "panel" }, h("ul", { class: "feed" },
        ses.resting.map((r) => h("li", {}, h("b", { text: r.profile }), " on " + r.site + ": back in about " + (r.minutes >= 90 ? Math.round(r.minutes / 60) + " h" : r.minutes + " min")))))] : null,
      (ses.compare || []).length ? sideBySide(ses.compare, label) : h("div", { class: "panel empty", text: "Side-by-side test: no runs yet. It loads one page per store through every method at once, every 15 minutes by default (Stores > Stores & keys, Side-by-side test)." }),
      featureTable(ses.features || []),
      h("h2", { text: "Methods to compare" }),
      h("div", { class: "panel", style: "overflow:hidden" }, [
        { id: "direct", name: "Plain requests", pick: (m) => m === "direct", idea: "The baseline",
          text: "Ordinary web requests at a polite pace. Fast and light, but stores with bot protection often refuse them." },
        { id: "profiles", name: "App browser profiles (Edge, Chrome)", pick: (m) => m !== "direct" && m !== "pool" && !m.startsWith("my-") && !m.endsWith("+page"), idea: "Real-browser idea from SeleniumBase, without its stealth modes",
          text: "A real browser with its own cookies, kept off screen. Several profiles share the load and a blocked one rests." },
        { id: "my-chrome", name: "Your own Chrome", pick: (m) => m === "my-chrome", idea: "DevTools control of a real Chrome (SeleniumBase CDP mode idea)",
          text: "The Chrome you start with start-my-chrome.ps1. A normal browser with your own profile, tried first at CVS, Dick's and GameStop." },
        { id: "my-edge", name: "Your own Edge", pick: (m) => m === "my-edge", idea: "Same idea as your own Chrome, a second real browser",
          text: "Start it with start-my-edge.ps1. Some stores accept Edge when they refuse Chrome, or the other way round. This shows which." },
        { id: "page", name: "Page fetch", pick: (m) => m.endsWith("+page"), idea: "Page-context calls (SeleniumBase CDP mode idea)",
          text: "When a plain data request is refused, the same call is made from inside the store's own page in a real browser, the way the store's own scripts do it. CVS store counts use it already." },
      ].map((c) => {
        const mine = methods.filter((m) => c.pick(m.method)), checks = mine.reduce((t, m) => t + m.checks, 0), blocks = mine.reduce((t, m) => t + m.blocks, 0);
        const state = !checks ? "Not tried yet" : checks + " checks, " + (blocks ? blocks + " blocked (1 per " + Math.round(checks / blocks) + ")" : "never blocked");
        return h("div", { class: "mrow" },
          h("div", { class: "top" }, h("b", { text: c.name }), h("span", { text: state })),
          h("div", { class: "sub2", text: c.text }), h("div", { class: "sub2", text: "Idea from: " + c.idea }));
      })),
      networkPanel((status && status.network) || null),
      h("h2", { text: "About the trial methods" }),
      h("p", { class: "lede", text: "Extra ways of loading pages, tried one at a time so each can be traced. For every store only one method runs at once: each gets a slice of " + tri.slice_checks + " checks, the normal method takes its turns too for a fair comparison, and a method a store blocks sits out for a while. Results land in the tables above." }),
      trialPanel(tri),
      h("h2", { text: "Profiles and tests" }),
      h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "wide" },
        h("p", { style: "margin:0 0 8px", text: "Active browser profiles: " + ((ses.profiles || []).join(", ") || "none") + ". Add or change them in config.yaml under browser: profiles, then restart the app. Your own Chrome (start-my-chrome.ps1) and Edge (start-my-edge.ps1) join by themselves while they are running." }),
        h("p", { style: "margin:0 0 6px", class: "hint", text: "For a side-by-side test of every method on the same pages, run this in PowerShell from the app folder:" }),
        h("code", { text: ".\\.venv\\Scripts\\python.exe app.py --abtest" })))),
    ];
  },

  notify() {
    const d = cfg.discord, wh = d.webhooks = d.webhooks || {}, n = notifyCfg(), st = cfg.settings;
    const sk = d.status_kinds = d.status_kinds || {};
    ["blocked", "recovered", "human", "signin", "autostop", "browser"].forEach((k) => { if (sk[k] === undefined) sk[k] = true; });
    const br = cfg.browser = cfg.browser || {}, dsc = cfg.discovery = cfg.discovery || {};
    n.quiet_hours = n.quiet_hours || [];
    const kinds = [["restock", "Restocks"], ["queue", "Pokemon Center queue"], ["new_listing", "New listings"]];
    const pingChips = h("div", { class: "checks" }, kinds.map(([k, label]) => h("label", { class: "chip" },
      h("input", { type: "checkbox", checked: (n.ping_on || []).includes(k), onchange: (e) => {
        n.ping_on = e.target.checked ? [...new Set([...(n.ping_on || []), k])] : (n.ping_on || []).filter((x) => x !== k); touch(); } }), label)));
    const storeChips = h("div", { class: "checks" }, Object.keys(RETAILERS).map((k) => h("label", { class: "chip" },
      h("input", { type: "checkbox", checked: !(n.retailers || []).length || n.retailers.includes(k), onchange: (e) => {
        let cur = (n.retailers || []).length ? n.retailers : Object.keys(RETAILERS);
        cur = e.target.checked ? [...new Set([...cur, k])] : cur.filter((x) => x !== k);
        n.retailers = cur.length === Object.keys(RETAILERS).length ? [] : cur; touch(); } }), RETAILERS[k])));
    return [
      h("h1", { text: "Discord alerts" }),
      h("p", { class: "lede", text: "Connect Discord and decide exactly what gets pushed. Stores keep being checked either way; these settings only control the alerts." }),
      h("h2", { text: "Discord" }),
      h("div", { class: "card" }, h("div", { class: "card-body" },
        field("Restock channel webhook", secret(wh, "default", "https://discord.com/api/webhooks/..."), "In Discord: Server Settings, Integrations, Webhooks, New Webhook, pick your channel, Copy Webhook URL. Keep it private.", true),
        h("div", { style: "display:flex;align-items:end" }, h("button", { class: "btn", type: "button", text: "Send test message", onclick: async () => {
          if (dirty()) return toast("Save your changes first, then send the test.", true);
          try { const r = await api("/api/action", { action: "test_discord" }); toast(r.ok ? "Test message sent" : (r.message || "Discord rejected the message. Check the webhook URL."), !r.ok); } catch (e) { toast(e.message, true); } } })),
        h("details", { class: "more", style: "grid-column:1/-1", open: !!(wh.online || wh.in_store || wh.status || d.mention_role_id || d.mention_user_id) },
          h("summary", { text: "More options: separate channels, pings, bot name" }),
          h("div", { class: "card-body", style: "padding:10px 0 0" },
            field("Online restocks channel (optional)", secret(wh, "online", "Webhook URL"), "Things you can order online. Blank uses the restock channel."),
            field("In-store channel (optional)", secret(wh, "in_store", "Webhook URL"), "Shelf stock near you. Each area can also have its own channel under My areas."),
            field("Status channel (optional)", secret(wh, "status", "Webhook URL"), "Everything that is not stock goes here instead: a sign-in is needed, a store keeps blocking, a check needs you, a method was switched off. Stock alerts never post here. Blank means no status messages.", true),
            field("Ping a role", text(d, "mention_role_id", { placeholder: "Role ID, optional" }), "Developer Mode on, then right-click the role, Copy Role ID"),
            field("Ping me", text(d, "mention_user_id", { placeholder: "Your user ID, optional" })),
            field("Bot name", text(d, "username")))))),
      h("h2", { text: "What gets pushed" }),
      h("div", { class: "settings-list" },
        setting("Online restocks", "An item can be bought online again.", sw(n, "online", "")),
        setting("In-store restocks", "Shelf stock appeared at a store in your areas.", sw(n, "in_store", "")),
        setting("Only when pickup works", "Skip stores where an item can't be ordered for pickup, when other stores offer pickup for it. Items no store offers for pickup (CVS sells its Pokemon in store only) still alert.", sw(n, "pickup_only", "")),
        setting("New listings", "A store listed a Pokemon product for the first time.", sw(n, "new_listings", "")),
        setting("Pokemon Center queue", "The waiting room opened, which usually means a drop within minutes.", sw(n, "queue", "")),
        setting("Sold-out notices", "Post when an item sells out online.", sw(st, "notify_sold_out", "")),
        setting("Verification requests", "Post when a store wants you to finish a check in the browser.", sw(br, "notify_discord", "")),
        setting("Windows pop-ups", "Also show alerts as notifications on this PC.", sw(st, "windows_toast", ""))),
      h("h2", { text: "Status channel messages" }),
      h("p", { class: "hint", text: "These post to the status channel above, never to the restock channels. The same message about the same store is not repeated within the quiet period." }),
      h("div", { class: "settings-list" },
        setting("A store keeps blocking", "After several blocks in a row, with the way to clear them.", sw(sk, "blocked", "")),
        setting("Back to normal", "A store that was blocked loads again.", sw(sk, "recovered", "")),
        setting("Verification needed", "A store wants you to finish a check in the browser window.", sw(sk, "human", "")),
        setting("Sign-in needed", "A saved store sign-in expired or was signed out.", sw(sk, "signin", "")),
        setting("Method switched off", "A trial method was stopped automatically for failing too often.", sw(sk, "autostop", "")),
        setting("Browser problem", "A checking browser could not start.", sw(sk, "browser", "")),
        setting("Ping me on these", "Mention your role or you on verification and sign-in messages, since those need you.", sw(d, "ping_status", "")),
        setting("Blocks in a row before posting", "", num(d, "status_block_after")),
        setting("Repeat the same message after (minutes)", "", num(d, "status_cooldown_minutes"))),
      h("h2", { text: "Which stores can alert" }),
      h("p", { class: "hint", text: "Untick a store to stop its alerts while still checking it. All ticked means every store." }),
      h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "wide" }, storeChips))),
      h("h2", { text: "Pings and timing" }),
      h("div", { class: "settings-list" },
        setting("Ping on", "Which alerts mention your role or you. Others post silently.", pingChips),
        setting("Quiet period (minutes)", "The same item at the same store won't alert again within this time.", num(st, "alert_cooldown_minutes")),
        setting("Alert on open", "When the app starts, alert for things already in stock.", sw(st, "alert_on_startup", "")),
        setting("During quiet hours", "", h("select", { style: "width:220px", onchange: (e) => { n.quiet_mode = e.target.value; touch(); } },
          [["no_ping", "Post without pinging"], ["skip", "Don't post (still logged)"]].map(([v, t]) => h("option", { value: v, text: t, selected: (n.quiet_mode || "no_ping") === v }))))),
      windowEditor(n, "quiet_hours", "Quiet hours", "For example overnight, so pings don't wake anyone."),
      h("h2", { text: "Separate channels by store" }),
      h("p", { class: "hint", text: "Optional. Leave blank to use the restock channel above." }),
      h("div", { class: "card" }, h("div", { class: "card-body" }, Object.entries(RETAILERS).map(([k, v]) => field(v, secret(wh, k, "Webhook URL"))))),
    ];
  },

  speed() {
    const rs = cfg.retailers, sc = cfg.schedule = cfg.schedule || {};
    const health = Object.fromEntries(((status && status.retailers) || []).map((r) => [r.name, r]));
    const rows = Object.keys(RETAILERS).map((k) => {
      const r = rs[k] = rs[k] || {};
      const secs = Number(r.interval_seconds || DEFAULT_INTERVALS[k] || 180);
      const label = h("span", { class: "radius-val", style: "min-width:90px", text: everyText(secs) });
      const hl = health[k];
      return h("div", { class: "speed-row" + (r.enabled ? "" : " off") },
        h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!r.enabled, "aria-label": "Check " + RETAILERS[k], onchange: (e) => { r.enabled = e.target.checked; touch(); render(); } })),
        h("div", { class: "t" }, h("b", { text: RETAILERS[k] }), h("span", { text: hl ? (hl.status || "") + (hl.success !== null && hl.checks >= 3 ? ", " + hl.success + "% OK" : "") : (r.enabled ? "Starts after saving" : "Off") })),
        h("input", { type: "range", min: "0", max: String(STEPS.length - 1), value: String(nearestStep(secs)), "aria-label": RETAILERS[k] + " check interval", disabled: !r.enabled,
          oninput: (e) => { r.interval_seconds = STEPS[Number(e.target.value)]; label.textContent = everyText(r.interval_seconds); touch(); } }), label);
    });
    const preset = (f) => { Object.keys(RETAILERS).forEach((k) => { const r = rs[k] = rs[k] || {}; r.interval_seconds = STEPS[nearestStep(Math.max(30, (DEFAULT_INTERVALS[k] || 180) * f))]; }); touch(); render(); };
    return [
      h("h1", { text: "How often each store is checked" }),
      h("p", { class: "lede", text: "How often each store is checked. Faster finds restocks sooner but gets blocked sooner; the monitor slows itself down automatically when a store pushes back." }),
      h("div", { class: "toolbar" }, h("span", { class: "hint", text: "Presets:" }),
        h("button", { class: "btn", type: "button", text: "Gentle", onclick: () => preset(2) }),
        h("button", { class: "btn", type: "button", text: "Balanced", onclick: () => preset(1) }),
        h("button", { class: "btn", type: "button", text: "Fast", onclick: () => preset(0.5) })),
      h("div", { class: "panel", style: "overflow:hidden" }, rows),
      h("h2", { text: "Smart timing" }),
      h("div", { class: "settings-list" },
        setting("Check faster at usual restock times", "Uses Restock times to check more often in hours a store restocked before.", sw(sc, "learn_from_history", "")),
        setting("Speed-up factor", "0.5 checks twice as often during busy hours.", num(sc, "fast_factor")),
        setting("Slow-down factor", "3 checks a third as often during quiet hours.", num(sc, "slow_factor")),
        setting("Fastest allowed (seconds)", "No store is ever checked more often than this.", num(sc, "min_interval_seconds")),
        setting("Random extra delay (seconds)", "Added to each check so stores are not hit on a fixed beat.", num(cfg, "jitter_seconds")),
        setting("Delay between links (seconds)", "Wait this long, plus up to half again at random, before loading the next page on the same store. 0 turns it off.", num(cfg.settings, "link_delay_seconds"))),
      windowEditor(sc, "fast_windows", "Busy hours (check faster)", "For example weekday mornings when trucks arrive."),
      windowEditor(sc, "slow_windows", "Slow hours (check slower)", "For example overnight, when stores are closed."),
    ];
  },

  retail() {
    const rs = cfg.retailers, cp = cfg.control_panel = cfg.control_panel || {};
    const br = cfg.browser = cfg.browser || {};
    const modeField = (r) => field("Loading pages", h("select", { onchange: (e) => { r.fetch_mode = e.target.value; touch(); } },
      [["auto", "Automatic: plain first, browser if blocked"], ["browser", "Always use the browser"], ["direct", "Plain requests only"]]
        .map(([v, t]) => h("option", { value: v, text: t, selected: (r.fetch_mode || "auto") === v }))));
    const browserStatus = () => {
      const b = status && status.browser;
      if (!b) return null;
      const msg = !b.installed ? "Browser support is not installed. Run setup.ps1 again to add it." :
        b.problem ? b.problem : b.running ? "The browser is running and helping with checks." : "Ready. Not needed so far.";
      return h("div", { class: "verdict " + (!b.installed || b.problem ? "no" : ""), style: "margin:0 0 12px", text: msg });
    };
    const dsc = cfg.discovery = cfg.discovery || {};
    dsc.items_per_cycle = dsc.items_per_cycle || {};
    const block = (key, extra, desc) => {
      const r = rs[key] = rs[key] || {};
      // A store's own settings are tucked away until needed, except a key the store cannot work without.
      const missingKey = (key === "kroger" && !(r.client_id && r.client_secret)) || (key === "bestbuy" && !r.api_key);
      return h("div", { class: "card" + (r.enabled ? "" : " off") },
        h("div", { class: "card-head" }, sw(r, "enabled", ""), h("b", { style: "flex:1", text: RETAILERS[key] }), h("span", { class: "hint", text: desc })),
        r.enabled && extra ? h("details", { class: "more", style: "margin:0 14px 10px", open: missingKey },
          h("summary", { text: missingKey ? "Needs a free key to work" : "Options for this store" }),
          h("div", { class: "card-body", style: "padding:10px 0 4px" }, extra(r))) : null);
    };
    return [
      h("h1", { text: "Stores & keys" }),
      h("p", { class: "lede", text: "Turn stores on or off, add the free keys some need, and choose how website-based stores are loaded. How often each store is checked is on the next tab." }),
      block("target", (r) => field("Only these store numbers", lines(r, "store_ids", { placeholder: "Leave empty for all stores in range" }), "One per line"), "Online and nearby store shelves, with quantities"),
      block("bestbuy", (r) => field("API key", secret(r, "api_key", "Free at developer.bestbuy.com"), "Required. Takes a few minutes to get.", true), "Online and nearby store shelves"),
      block("kroger", (r) => [
        field("Client ID", text(r, "client_id", { placeholder: "From developer.kroger.com" }), "Free developer account, then create an app with the Products scope"),
        field("Client secret", secret(r, "client_secret", "")),
        field("Stores to check", num(r, "max_stores"), "Nearest stores in your areas. 5 fits the free daily limit."),
        field("Only these store IDs", lines(r, "store_ids", { placeholder: "Optional, one per line" }))],
        "Kroger, Fred Meyer, Smith's and other Kroger stores: stock level per store"),
      block("walmart", (r) => [modeField(r),
        field("Walmart.io Consumer ID", text(r, "consumer_id", { placeholder: "From your app on walmart.io" }), "Optional. With the key file below, stock comes from Walmart's own feed instead of its website."),
        field("Private key file", text(r, "private_key_file", { placeholder: "C:\\Users\\you\\walmart\\private.pem" }), "Full path to the .pem private key you made for Walmart.io. It stays on this PC."),
        field("Key version", text(r, "key_version", { placeholder: "1" }), "Shown next to your uploaded public key on walmart.io, usually 1."),
        field("Publisher ID (optional)", text(r, "publisher_id", { placeholder: "Impact publisher ID" }))],
        "Online, plus pickup at the store set in the checking browser. Add Walmart.io details for the official feed"),
      block("pokemoncenter", (r) => [modeField(r), h("div", { class: "wide" }, sw(r, "watch_queue", "Watch the Pokemon Center queue (usually opens minutes before a drop)"))], "Online drops and the waiting-room queue"),
      block("dicks", modeField, "Online, found automatically from its Pokemon section"),
      block("safeway", modeField, "Online, for the store set in the checking browser"),
      block("raleys", modeField, "Online. Finds Pokemon products by itself, or add product links"),
      block("gamestop", modeField, "Online, plus pickup stock at stores in your areas. Finds Pokemon products by itself, newest first"),
      block("costco", modeField, "Online. Finds Pokemon products by itself, or add product links"),
      block("samsclub", modeField, "Online. Finds Pokemon products by itself, or add product links"),
      block("barnesandnoble", modeField, "Online. Finds Pokemon products by itself, or add product links"),
      block("booksamillion", modeField, "Online. Finds Pokemon products by itself, or add product links"),
      block("amazon", modeField, "Online, sold by Amazon only"),
      block("walgreens", (r) => [modeField(r),
        field("API key (optional)", secret(r, "api_key", "From developer.walgreens.com"), "Adds exact Walgreens stores to Stores with stock. Walgreens' API has no stock data, so stock still comes from product pages.")],
        "Online. Finds Pokemon products by itself (through the browser); store locations with a key"),
      block("cvs", modeField, "Online, plus shelf counts at stores around your areas. Finds Pokemon products by itself (your own Chrome)"),
      block("macys", modeField, "Online. Finds Pokemon products by itself (through the browser)"),
      block("kohls", modeField, "Online. Finds Pokemon products by itself (through the browser)"),
      block("web", (r) => [modeField(r),
        field("Page says in stock when it shows", lines(r, "in_stock_text", { placeholder: "add to cart" }), "Only used on pages without built-in stock data"),
        field("Page says sold out when it shows", lines(r, "out_of_stock_text", { placeholder: "out of stock\nsold out" }))], "Any other product link"),
      h("h2", { text: "Finding products and stores on its own" }),
      h("div", { class: "settings-list" },
        setting("Find products automatically", "Track every sealed Pokemon product these stores list, not only the ones you add.", sw(dsc, "enabled", "")),
        setting("Stores to search", "Stores with a searchable catalog.", picks(dsc, "retailers", SEARCHABLE)),
        setting("Search again every (hours)", "New listings are spotted at this pace.", num(dsc, "refresh_hours")),
        setting("Target items per check", "Items seen in stock recently are always checked.", num(dsc.items_per_cycle, "target")),
        setting("Best Buy items per check", "", num(dsc.items_per_cycle, "bestbuy")),
        setting("Kroger items per check", "Up to 50 cost one request per store.", num(dsc.items_per_cycle, "kroger")),
        setting("Dick's items per check", "Each loads a page in the browser, so keep this small.", num(dsc.items_per_cycle, "dicks")),
        setting("Find stores near my areas", "Map the stores around your ZIP codes weekly.", sw(dsc, "places", ""))),
      h("h2", { text: "When a store blocks checks" }),
      browserStatus(),
      h("div", { class: "settings-list" },
        setting("Use a real browser when needed", "Only starts the first time a store blocks plain checks.", sw(br, "enabled", "")),
        setting("Browser", "Edge comes with Windows.", h("select", { style: "width:180px", onchange: (e) => { br.channel = e.target.value; touch(); } },
          [["msedge", "Microsoft Edge"], ["chrome", "Google Chrome"]].map(([v, t]) => h("option", { value: v, text: t, selected: (br.channel || "msedge") === v })))),
        setting("Keep the window out of the way", "It moves on screen only when a store needs you.", sw(br, "show_window", "", true)),
        setting("Ask me to verify", "Bring the window forward when a store wants a person to finish a check.", sw(br, "ask_me_to_verify", "")),
        setting("Slowest pace for browser checks (seconds)", "Browser checks load whole pages, so go easy.", num(br, "min_interval_seconds")),
        setting("Tabs per store", "Pages of one store rotate through this many tabs (1 to 6) instead of reloading a single tab.", num(br, "tabs_per_site", { min: "1", max: "6" })),
        setting("Close my Chrome and Edge with the app", "When the app closes, the Chrome and Edge started by start-my-chrome and start-my-edge close too. Your sign-ins are kept for next time.", sw(br, "close_own_on_exit", "")),
        setting("Feature trial", "Run about half of the checks without learned routing and tab rotation so Connection methods can show whether they help.", sw(br, "feature_trial", "")),
        setting("Side-by-side test (minutes, 0 = off)", "At stores that pushed back in the last day, one page loads through every method at once so Connection methods can compare them. Never more often than hourly, and not while a store is refusing.", num(br, "compare_every_minutes", { min: "0", max: "240" }))),
      h("p", { class: "hint", text: "Browser changes take effect after restarting the app." }),
      h("h2", { text: "Phone access" }),
      h("div", { class: "settings-list" },
        setting("Open this panel from my phone", "Lets devices on your home Wi-Fi reach it. Needs a PIN, then save and restart the app.", sw(cp, "allow_lan", "")),
        setting("PIN", "At least 4 characters.", h("div", { style: "width:180px" }, secret(cp, "pin", ""))),
        setting("Port", "Change only if 8765 is taken. Needs an app restart.", num(cp, "port"))),
      phonePanel((status && status.phone) || null),
      h("h2", { text: "Troubleshooting" }),
      h("div", { class: "settings-list" }, setting("Save raw responses", "Writes what each store sends back to data\\debug, for fixing a broken checker.", sw(cfg.settings, "debug_dump", ""))),
    ];
  },
};

/* ---------- shared settings helpers ---------- */
const DEFAULT_INTERVALS = { target: 90, bestbuy: 60, kroger: 300, walmart: 180, pokemoncenter: 900, gamestop: 240, costco: 300, samsclub: 300,
  barnesandnoble: 300, booksamillion: 300, amazon: 300, dicks: 300, safeway: 300, raleys: 300, walgreens: 240, cvs: 240, web: 180 };
const STEPS = [30, 45, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200, 1800, 3600];
function nearestStep(s) { let best = 0; STEPS.forEach((v, i) => { if (Math.abs(v - s) < Math.abs(STEPS[best] - s)) best = i; }); return best; }
function everyText(s) { s = Number(s); return s < 60 ? "every " + s + "s" : s < 3600 ? "every " + (s % 60 ? (s / 60).toFixed(1) : s / 60) + " min" : "every " + (s / 3600) + " hr"; }
function notifyCfg() { cfg.notify = cfg.notify || {}; const n = cfg.notify;
  for (const [k, v] of Object.entries({ online: true, in_store: true, pickup_only: false, new_listings: true, queue: true, ping_on: ["restock", "queue"], retailers: [], quiet_mode: "no_ping" }))
    if (!(k in n)) n[k] = v;
  return n; }
function sideBySide(rows, label) {
  const stores = [...new Set(rows.map((r) => r.store))].sort();
  const methods = [...new Set(rows.map((r) => r.method))].sort((a, b) => a === "direct" ? -1 : b === "direct" ? 1 : a.localeCompare(b));
  const cell = (store, method) => {
    const r = rows.find((x) => x.store === store && x.method === method);
    if (!r) return h("td", { class: "none", text: "not run" });
    const pct = Math.round(100 * r.ok / r.runs);
    const txt = pct + "% loaded (" + r.ok + " of " + r.runs + ")" + (r.avg_ms ? ", " + (r.avg_ms / 1000).toFixed(1) + " s" : "") + (r.last_ok ? "" : ", last: " + (r.last_kind || "blocked"));
    return h("td", { class: pct >= 90 ? "best" : (pct < 50 ? "bad" : ""), text: txt });
  };
  return [
    h("h2", { text: "Side by side, same page at the same time" }),
    h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
      h("tr", {}, h("th", { text: "Store" }), methods.map((m) => h("th", { text: label(m) }))),
      stores.map((st) => h("tr", {}, h("td", { text: st }), methods.map((m) => cell(st, m)))))),
    h("p", { class: "hint", text: "Each run loads one product page through every method together. Green = loads almost every time, amber = often refused." }),
  ];
}

function trustReport(t) {
  const stores = t.stores || [], feeds = t.feeds || [];
  const cls = (v) => v === "Reliable" ? "best" : (v === "Blocked" || v === "Flaky" ? "bad" : "none");
  return [
    h("h2", { text: "Can I trust each store?" }),
    stores.length ? h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
      h("tr", {}, ["Store", "Rating", "Based on", "Best method", "What to do"].map((x) => h("th", { text: x }))),
      stores.map((r) => h("tr", {},
        h("td", { text: r.display }),
        h("td", { class: cls(r.verdict), text: r.verdict + (r.score === null ? "" : " (" + r.score + "%)") }),
        h("td", { text: r.basis || "nothing yet" }),
        h("td", { text: r.best_method ? r.best_method + (r.best_rate === null ? "" : ", " + r.best_rate + "% side by side") : "none yet" }),
        h("td", { text: r.advice || "Nothing needed." }))))) : h("div", { class: "panel empty", text: "No stores are being checked yet." }),
    h("p", { class: "hint", text: "Reliable = 90% or more of real checks loaded. Flaky = 60 to 89%. Blocked = under 60%. Ratings use only the app's own recent checks, the block counts and the side-by-side test, and need about 10 checks." }),
    feeds.length ? h("div", { class: "panel", style: "margin-bottom:16px" }, h("ul", { class: "feed" }, feeds.map((f) =>
      h("li", {}, h("b", { text: f.label }), " is not switched on. Free key: " + f.where + ". Official feeds do not use bot checks, so they are the most dependable way to cover that store.")))) : null,
  ];
}

function featureTable(rows) {
  const pct = (b, c) => c ? (100 * b / c).toFixed(1) + "% blocked" : "no data";
  return [
    h("h2", { text: "Do the new features help?" }),
    h("div", { class: "table-wrap" }, h("table", { class: "matrix" },
      h("tr", {}, ["Feature", "With it", "Without it", "Verdict"].map((t) => h("th", { text: t }))),
      rows.map((r) => h("tr", {}, h("td", { text: r.label }),
        h("td", { text: r.with_checks + " checks, " + pct(r.with_blocks, r.with_checks) }),
        h("td", { text: r.without_checks + " checks, " + pct(r.without_blocks, r.without_checks) }),
        h("td", { class: r.verdict === "Helping" ? "best" : (r.verdict === "Not helping" ? "bad" : ""), text: r.verdict }))))),
    h("p", { class: "hint", text: "With the feature trial on (Stores & keys), about half of the checks run without each feature. A verdict appears after 30 checks on each side." }),
  ];
}

function go(t) { tab = t; window.scrollTo(0, 0); render(); }
function ensureAreas() {
  const loc = cfg.location || {};
  if (!Array.isArray(cfg.areas) || !cfg.areas.length) {
    cfg.areas = loc.zip ? [{ name: "Home", zip: loc.zip, radius_miles: loc.radius_miles || 25 }] : [];
    if (loc.zip) { const base = JSON.parse(savedJSON); base.areas = cfg.areas; savedJSON = JSON.stringify(base); }
  }
}
function areasEditor() {
  return cfg.areas.length ? h("div", { class: "panel", style: "overflow:hidden" }, cfg.areas.map((a, i) => {
    const placeTag = h("span", { class: "hint place", text: "" });
    const look = async () => {
      if (!/^\d{5}$/.test(a.zip || "")) { placeTag.textContent = a.zip ? "5 digits" : ""; return; }
      try { const g = await api("/api/geo?zip=" + a.zip); geoCache[a.zip] = g; placeTag.textContent = g.lat !== null ? g.place : (g.ready ? "Unknown ZIP" : "ZIP lookup not installed"); drawAreaMap(); } catch (e) {}
    };
    setTimeout(look);
    const radVal = h("span", { class: "radius-val", text: (a.radius_miles || 15) + " mi" });
    return h("div", { class: "win-row area-row" },
      h("input", { type: "text", value: a.name || "", placeholder: "Name", "aria-label": "Area name", oninput: (e) => { a.name = e.target.value; touch(); } }),
      h("input", { type: "text", value: a.zip || "", placeholder: "ZIP", inputmode: "numeric", maxlength: "5", "aria-label": "ZIP code",
        oninput: (e) => { a.zip = e.target.value.replace(/\D/g, "").slice(0, 5); touch(); look(); } }), placeTag,
      h("span", { text: "radius" }),
      h("input", { type: "range", min: "1", max: "100", value: String(a.radius_miles || 15), "aria-label": "Radius in miles",
        oninput: (e) => { a.radius_miles = Number(e.target.value); radVal.textContent = a.radius_miles + " mi"; touch(); drawAreaMap(); } }), radVal,
      secret(a, "webhook", "Own Discord channel (optional)"),
      h("button", { class: "btn quiet danger", type: "button", text: "Remove", onclick: () => { cfg.areas.splice(i, 1); touch(); render(); } }));
  })) : h("div", { class: "panel empty", text: "No area yet. Add your home ZIP so nearby store shelves can be checked." });
}
function dayChips(w) {
  return h("div", { class: "checks" }, DAY_KEYS.map((d, i) => h("label", { class: "chip" },
    h("input", { type: "checkbox", checked: w.days.includes(d), onchange: (e) => {
      w.days = e.target.checked ? DAY_KEYS.filter((x) => x === d || w.days.includes(x)) : w.days.filter((x) => x !== d); touch(); } }), DAY_LABELS[i])));
}
function windowEditor(obj, key, title, hint) {
  obj[key] = obj[key] || [];
  const rows = obj[key].map((w, i) => {
    if (!Array.isArray(w.days)) w.days = (!w.days || w.days === "all") ? [...DAY_KEYS] : [String(w.days).slice(0, 3).toLowerCase()];
    return h("div", { class: "win-row" }, dayChips(w),
      h("input", { type: "time", value: w.start || "22:00", "aria-label": "Start", onchange: (e) => { w.start = e.target.value; touch(); } }), "to",
      h("input", { type: "time", value: w.end || "06:00", "aria-label": "End", onchange: (e) => { w.end = e.target.value; touch(); } }),
      h("button", { class: "btn quiet danger", type: "button", text: "Remove", onclick: () => { obj[key].splice(i, 1); touch(); render(); } }));
  });
  return [h("h2", { text: title }), h("p", { class: "hint", text: hint }),
    rows.length ? h("div", { class: "panel", style: "overflow:hidden" }, rows) : null,
    h("p", {}, h("button", { class: "btn", type: "button", text: "Add hours", onclick: () => { obj[key].push({ days: [...DAY_KEYS], start: key === "fast_windows" ? "06:00" : "22:00", end: key === "fast_windows" ? "10:00" : "06:00" }); touch(); render(); } }))];
}

function drawDash() {
  const s = status || { items: [], alerts: [], activity: [], retailers: [] };
  const health = $("health"); if (!health) return;
  drawSetup(s);
  // In stock now: one card per listing you can buy, with where.
  const live = s.items.filter((i) => i.in_stock && !i.note && passesNear(i));
  $("instock").replaceChildren(live.length ? h("div", { class: "cards" }, live.slice(0, 24).map((it) => {
    const where = [];
    if (it.online) where.push("Online");
    const near = nearFilterOn() ? storesInRange(it.store_points).sort((a, b) => a.away - b.away).map((p) => p.name + " (" + p.away.toFixed(1) + " mi)")
      : (it.store_points || []).map((p) => p.name + (p.distance !== null && p.distance !== undefined ? " (" + p.distance + " mi)" : ""));
    if (near.length) where.push(near.slice(0, 2).join(", ") + (near.length > 2 ? " and " + (near.length - 2) + " more" : ""));
    const vs = it.msrp && it.price ? (Math.abs(it.price - it.msrp) < 0.01 ? "at MSRP" : it.price > it.msrp ? money(it.price - it.msrp) + " over MSRP" : money(it.msrp - it.price) + " under MSRP") : "";
    return h("div", { class: "scard" }, h("span", { class: "store", text: it.retailer_name }), extLink(it.url, it.title),
      h("span", { class: "price", text: money(it.price) + (vs ? ", " + vs : "") }), h("span", { class: "where", text: where.join("; ") || "In stock" }));
  })) : h("div", { class: "panel calm" }, h("span", { class: "dot" }), h("span", {},
    "Nothing in stock right now. ", h("span", { class: "hint", text: "Watching " + s.items.length + " listings at " + s.retailers.length + " stores. You get a Discord alert the moment something comes back." }))));
  // Your stores: a one-line summary, the stores that need attention first, details on request.
  const rows = s.retailers.map((r) => ({ r, st: storeState(r.status) }));
  const n = (c) => rows.filter((x) => x.st.cls === c).length;
  const parts = [[n("ok"), "checking normally"], [n("warn"), "paused or need you"], [n("bad"), "with a problem"], [n("setup"), "need setup"]].filter(([k]) => k);
  rows.sort((a, b) => ["bad", "warn", "setup", "", "ok"].indexOf(a.st.cls) - ["bad", "warn", "setup", "", "ok"].indexOf(b.st.cls));
  health.replaceChildren(...(rows.length ? [
    h("p", { class: "summary-line" }, ...parts.flatMap(([k, t], i) => [i ? ", " : "", h("b", { text: String(k) }), " " + t]), "."),
    h("div", { class: "chips" }, rows.map(({ r, st }) => h("span", { class: "schip " + st.cls, title: r.status || "" }, h("i"), r.display,
      st.cls && st.cls !== "ok" ? h("small", { text: st.label }) : null,
      st.cls === "setup" ? h("button", { class: "btn quiet", type: "button", text: "Fix", onclick: () => go("retail") }) : null))),
    h("details", { class: "more" }, h("summary", { text: "Details for each store" }), h("div", { class: "tiles", style: "margin-top:8px" }, s.retailers.map((r) => {
      const meta = [];
      if (r.using_browser) meta.push("Using the browser");
      if (r.success !== null && r.checks >= 3) meta.push(r.success + "% of recent checks OK");
      if (r.next_in !== null && r.next_in !== undefined) meta.push("next check in " + fmtSecs(r.next_in));
      return h("div", { class: "tile " + (storeState(r.status).cls === "bad" ? "bad" : storeState(r.status).cls === "warn" ? "warn" : ""), title: r.last_block || "" },
        h("b", { text: r.display }), h("span", { text: r.status || "" }), meta.length ? h("span", { class: "meta", text: meta.join(", ") }) : null);
    }))),
  ] : [h("div", { class: "panel calm" }, h("span", { class: "dot" }), h("span", {}, "No stores are switched on. ",
    h("button", { class: "btn", type: "button", text: "Choose stores", onclick: () => go("retail") })))]));
  const alertsShown = s.alerts.filter((a) => !nearFilterOn() || !a.points || storesInRange(a.points).length || (nearState.online && a.online !== false));
  $("alerts").replaceChildren(...(alertsShown.length ? alertsShown.slice(0, 25).map((a) => h("li", {},
    h("time", { text: new Date(a.time * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) }),
    h("div", {}, h("span", { class: "ok", text: a.retailer + " " }), extLink(a.url, a.title)),
    h("div", { class: "hint", text: plainReason(a.reason) + (a.price ? ", " + money(a.price) : "") + (a.sent ? "" : " (not sent to Discord)") }))) :
    [h("li", { class: "hint", text: nearFilterOn() ? "No alerts near this ZIP yet." : "Restock alerts show up here and in your Discord channel." })]));
  $("activity").replaceChildren(...s.activity.slice(0, 80).map((a) => h("li", {}, h("time", { text: new Date(a.time * 1000).toLocaleTimeString() + "  " }), a.msg)));
  drawTable();
}
function plainReason(r) {
  return String(r || "").replace(/^online restock/, "Back in stock online").replace(/in stock at (\d+) new store\(s\)/, (m, k) => "On the shelf at " + k + (k === "1" ? " store" : " stores"))
    .replace(/^new listing/, "New listing");
}
/* Getting started: shown only while something basic is missing. */
function drawSetup(s) {
  const el = $("setup"); if (!el || !cfg) return;
  const hooks = Object.values((cfg.discord || {}).webhooks || {}).some((v) => v) || (cfg.areas || []).some((a) => a && a.webhook);
  const area = (cfg.areas || []).length > 0 || !!((cfg.location || {}).zip);
  const stores = (s.retailers || []).length > 0;
  const needKey = (s.retailers || []).filter((r) => storeState(r.status).cls === "setup").map((r) => r.display);
  const steps = [
    [hooks, "Connect Discord, so alerts reach your phone", "Set up Discord", "notify"],
    [area, "Set your area: a ZIP code and how far you will drive", "Set my area", "areas"],
    [stores, "Choose the stores you shop at", "Choose stores", "retail"],
  ];
  if (needKey.length) steps.push([false, needKey.join(" and ") + (needKey.length > 1 ? " need" : " needs") + " a free key, or switch " + (needKey.length > 1 ? "them" : "it") + " off", "Open Stores", "retail"]);
  if (steps.every(([ok]) => ok)) { el.replaceChildren(); return; }
  el.replaceChildren(h("div", { class: "panel steps" }, h("h2", { text: "Getting started" }),
    h("ol", {}, steps.map(([ok, what, label, to], i) => h("li", { class: ok ? "done" : "" }, h("span", { class: "mark", text: ok ? "\u2713" : String(i + 1) }),
      h("span", { class: "what", text: what }), ok ? null : h("button", { class: "btn primary", type: "button", text: label, onclick: () => go(to) })))),
    h("p", { class: "hint", style: "margin:10px 0 0", text: "Products are found for you at each store. Add your own links only for something it misses." })));
}

let lastHistoryTotal = -1;
async function loadPatterns() {
  try {
    const q = new URLSearchParams({ retailer: timesState.retailer, place: timesState.place });
    drawPatterns(await api("/api/patterns?" + q.toString()));
  } catch (e) { toast(e.message, true); }
}

function drawPatterns(p) {
  const body = $("times-body"); if (!body) return;
  const ps = $("place-sel");
  if (ps) ps.replaceChildren(h("option", { value: "", text: "Every location" }),
    ...p.places.map((pl) => h("option", { value: pl.id, selected: timesState.place === pl.id, text: pl.name + " (" + pl.count + ")" })));
  if (!p.total) {
    body.replaceChildren(h("div", { class: "panel empty", text: "No restocks recorded yet. Leave the monitor running: each restock it sees at your stores is logged, and patterns show up here as they build." }));
    return;
  }
  const max = Math.max(1, ...p.grid.flat());
  const cells = [h("div", {})];
  for (let hr = 0; hr < 24; hr++) cells.push(h("div", { class: "hl", text: hr % 3 === 0 ? hourLabel(hr).replace(" ", "") : "" }));
  p.grid.forEach((row, d) => {
    cells.push(h("div", { class: "dl", text: DAY_LABELS[d] }));
    row.forEach((n, hr) => {
      const pct = n ? Math.round(25 + 75 * n / max) : 0;
      cells.push(h("div", { class: "c", title: DAY_LABELS[d] + " " + hourLabel(hr) + ": " + n + " restock" + (n === 1 ? "" : "s"),
        style: n ? "background: color-mix(in srgb, var(--ok-strong) " + pct + "%, var(--panel))" : null }));
    });
  });
  const best = p.best.length ? h("ul", { class: "best" }, p.best.map((b) => h("li", {}, h("b", { text: b.label }),
    h("span", { class: "hint", text: b.count + " of " + p.total + " restocks" })))) : null;
  const places = h("div", { class: "settings-list" }, p.places.slice(0, 12).map((pl) => setting(pl.name, pl.retailer + ", last restock " + new Date(pl.last * 1000).toLocaleString(),
    h("span", { text: pl.count + (pl.count === 1 ? " restock" : " restocks") }))));
  const recent = h("ul", { class: "feed" }, p.recent.slice(0, 15).map((r) => h("li", {},
    h("time", { text: new Date(r.t * 1000).toLocaleString() }),
    h("div", {}, h("span", { class: "ok", text: r.place + " " }), r.pickup ? h("span", { class: "hint", text: "(pickup)" }) : null),
    h("div", { class: "hint", text: r.items.join("; ") }))));
  body.replaceChildren(
    h("p", { class: "hint", text: p.total + " restock" + (p.total === 1 ? "" : "s") + " recorded. Several items arriving at one store within two hours count as one restock. Times are in your PC's time zone." }),
    best ? h("h2", { text: "Most likely times" }) : null, best,
    h("h2", { text: "By day and hour" }),
    h("div", { class: "panel heat-wrap" }, h("div", { class: "heat", role: "img", "aria-label": "Restocks by weekday and hour" }, cells)),
    timesState.place ? null : h("h2", { text: "Locations" }), timesState.place ? null : places,
    h("h2", { text: "Recent restocks" }), h("div", { class: "panel" }, recent));
}

async function loadPlaces() { try { placesData = await api("/api/places"); drawPlaces(); } catch (e) { toast(e.message, true); } }
async function loadFound() { try { catalogData = await api("/api/catalog"); drawFound(); } catch (e) { toast(e.message, true); } }

const AREA_COLORS = ["#fcd34d", "#fda4af", "#fdba74", "#bef264", "#f0abfc", "#fde68a"];
const SVG_NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, kids = []) { const e = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.forEach((c) => e.append(c)); return e; }
function niceMiles(target) { for (const n of [1, 2, 5, 10, 20, 25, 50, 100, 200]) if (n >= target) return n; return 200; }

/* A drawn map with no outside requests: your areas as circles (to scale), your alert distance, and the stores.
   areas: [{name, zip, lat, lon, radius}], places: [{name, lat, lon, chain, excluded}], chains: [{key, coverage}] */
function mapView(areas, places, chains, opts = {}) {
  areas = (areas || []).filter((a) => a.lat !== null && a.lat !== undefined && a.lon !== null && a.lon !== undefined && a.radius > 0);
  if (!areas.length) return null;
  const lat0 = areas.reduce((t, a) => t + a.lat, 0) / areas.length, lon0 = areas.reduce((t, a) => t + a.lon, 0) / areas.length;
  const kx = 69.17 * Math.cos(lat0 * Math.PI / 180), ky = 69.0;
  const xy = (lat, lon) => [(lon - lon0) * kx, (lat - lat0) * ky];
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  const reach = (a) => Math.max(a.radius, opts.maxMiles || 0);
  areas.forEach((a) => { const [x, y] = xy(a.lat, a.lon), r = reach(a); x0 = Math.min(x0, x - r); x1 = Math.max(x1, x + r); y0 = Math.min(y0, y - r); y1 = Math.max(y1, y + r); });
  const padMi = Math.max(1, 0.08 * Math.max(x1 - x0, y1 - y0)); x0 -= padMi; x1 += padMi; y0 -= padMi; y1 += padMi;
  const W = 720, wMi = x1 - x0, hMi = y1 - y0, H = Math.round(Math.min(560, Math.max(320, W * hMi / wMi)));
  const sc = Math.min(W / wMi, H / hMi), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const P = (lat, lon) => { const [x, y] = xy(lat, lon); return [W / 2 + (x - cx) * sc, H / 2 - (y - cy) * sc]; };
  const svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "mapsvg", role: "img", "aria-label": "Map of your areas and the stores near them" });
  // faint grid so distance is easy to judge
  const step = niceMiles(Math.max(wMi, hMi) / 8), gx0 = Math.ceil(x0 / step) * step, gy0 = Math.ceil(y0 / step) * step;
  for (let x = gx0; x <= x1; x += step) svg.append(svgEl("line", { x1: W / 2 + (x - cx) * sc, y1: 0, x2: W / 2 + (x - cx) * sc, y2: H, stroke: "var(--line-soft)", "stroke-width": "1" }));
  for (let y = gy0; y <= y1; y += step) svg.append(svgEl("line", { x1: 0, y1: H / 2 - (y - cy) * sc, x2: W, y2: H / 2 - (y - cy) * sc, stroke: "var(--line-soft)", "stroke-width": "1" }));
  const centers = areas.map((a) => P(a.lat, a.lon));
  areas.forEach((a, i) => {
    const [px, py] = centers[i], col = AREA_COLORS[i % AREA_COLORS.length];
    svg.append(svgEl("circle", { cx: px, cy: py, r: a.radius * sc, fill: col, "fill-opacity": "0.12", stroke: col, "stroke-width": "1.6" }));
    if (opts.maxMiles && opts.maxMiles < a.radius)
      svg.append(svgEl("circle", { cx: px, cy: py, r: opts.maxMiles * sc, fill: "none", stroke: col, "stroke-width": "1.4", "stroke-dasharray": "5 4" }));
  });
  const inside = (p) => areas.some((a) => { const [ax, ay] = xy(a.lat, a.lon), [sx, sy] = xy(p.lat, p.lon); return Math.hypot(ax - sx, ay - sy) <= a.radius; });
  const color = { live: "var(--ok-strong)", online: "var(--act)", listed: "var(--faint)" };
  const byChain = Object.fromEntries((chains || []).map((c) => [c.key, c]));
  (opts.hidePlaces ? [] : (places || [])).forEach((p) => {
    if (p.lat === null || p.lat === undefined || p.lon === null || p.lon === undefined) return;
    const [x, y] = P(p.lat, p.lon); if (x < -4 || x > W + 4 || y < -4 || y > H + 4) return;
    const cov = (byChain[p.chain] || {}).coverage || "listed", out = !inside(p);
    const dot = svgEl("circle", { cx: x, cy: y, r: cov === "live" ? 5 : 3.8, fill: color[cov], stroke: "var(--bg)", "stroke-width": "1.5", opacity: p.excluded || out ? "0.3" : "1" });
    dot.append(svgEl("title")); dot.firstChild.textContent = p.name + (p.distance !== null && p.distance !== undefined ? ", " + p.distance + " mi" : "") + (p.excluded ? " (skipped)" : out ? " (outside your areas)" : "");
    svg.append(dot);
  });
  (opts.markers || []).forEach((m) => {   // stores with stock: big, clickable, on top of everything but the area centers
    const [x, y] = P(m.lat, m.lon); if (x < -4 || x > W + 4 || y < -4 || y > H + 4) return;
    const g = svgEl("g", { class: "stockdot" + (m.selected ? " sel" : ""), tabindex: "0", role: "button", "aria-label": m.label, style: "cursor:pointer" });
    g.append(svgEl("circle", { cx: x, cy: y, r: m.selected ? 13 : 10, fill: "var(--ok-strong)", stroke: m.selected ? "var(--ink)" : "var(--bg)", "stroke-width": m.selected ? "3" : "2" }));
    const t = svgEl("text", { x, y: y + 4, "text-anchor": "middle", "font-size": "11", "font-weight": "700", fill: "var(--bg)", style: "pointer-events:none" });
    t.textContent = String(m.count); g.append(t);
    const tt = svgEl("title"); tt.textContent = m.label; g.append(tt);
    g.addEventListener("click", () => m.onclick && m.onclick());
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); m.onclick && m.onclick(); } });
    svg.append(g);
  });
  const placed = [];
  areas.forEach((a, i) => {   // centers and labels last so nothing covers them
    const [px, py] = centers[i], col = AREA_COLORS[i % AREA_COLORS.length];
    svg.append(svgEl("circle", { cx: px, cy: py, r: 6.5, fill: col, stroke: "var(--bg)", "stroke-width": "2.5", style: "pointer-events:none" }));
    const label = (a.name || "Area") + (a.zip ? " " + a.zip : "") + " · " + a.radius + " mi";
    const right = px < W * 0.62, tw = label.length * 7.4;
    let ty = Math.max(16, py - 12);
    const clash = (y) => placed.some((q) => Math.abs(q.y - y) < 16 && !(right ? px + 12 > q.x1 : px - 12 - tw > q.x1 || px - 12 < q.x0) && (right ? px + 12 + tw > q.x0 : true) && (right ? px + 12 < q.x1 : true));
    for (let n = 0; n < 6 && clash(ty); n++) ty += 16;        // two areas close together: stack their labels
    placed.push({ y: ty, x0: right ? px + 12 : px - 12 - tw, x1: right ? px + 12 + tw : px - 12 });
    const t = svgEl("text", { x: right ? px + 12 : px - 12, y: ty, "text-anchor": right ? "start" : "end", "font-size": "13", "font-weight": "600", fill: "var(--ink)", stroke: "var(--bg)", "stroke-width": "4", "paint-order": "stroke", "stroke-linejoin": "round", style: "pointer-events:none" });
    t.textContent = label; svg.append(t);
  });
  // scale bar and north arrow
  const bar = niceMiles(wMi * 0.2), bw = bar * sc, bx = 16, by = H - 18;
  svg.append(svgEl("path", { d: "M" + bx + " " + (by - 6) + "v6h" + bw + "v-6", fill: "none", stroke: "var(--ink)", "stroke-width": "2" }));
  const st = svgEl("text", { x: bx + bw / 2, y: by - 10, "text-anchor": "middle", "font-size": "12", fill: "var(--ink)", stroke: "var(--bg)", "stroke-width": "3", "paint-order": "stroke" }); st.textContent = bar + " mi"; svg.append(st);
  svg.append(svgEl("path", { d: "M" + (W - 24) + " 38v-22m0 0l-5 8m5-8l5 8", fill: "none", stroke: "var(--ink)", "stroke-width": "2", "stroke-linecap": "round" }));
  const nt = svgEl("text", { x: W - 24, y: 52, "text-anchor": "middle", "font-size": "12", "font-weight": "600", fill: "var(--ink)" }); nt.textContent = "N"; svg.append(nt);
  const legend = h("div", { class: "legend" },
    areas.map((a, i) => h("span", {}, h("i", { style: "background:" + AREA_COLORS[i % AREA_COLORS.length] }), (a.name || "Area") + " circle")),
    opts.markers ? h("span", {}, h("i", { style: "background:var(--ok-strong)" }), "Store with stock (number = products)") : [
    h("span", {}, h("i", { style: "background:var(--ok-strong)" }), COVERAGE.live), h("span", {}, h("i", { style: "background:var(--act)" }), COVERAGE.online),
    h("span", {}, h("i", { style: "background:var(--faint)" }), COVERAGE.listed)],
    opts.maxMiles ? h("span", {}, "Dashed ring: alert distance " + opts.maxMiles + " mi") : null);
  return h("div", { class: "panel radar-wrap" }, svg, legend);
}

function radar(d) {
  return mapView((d.areas || []).map((a) => ({ name: a.name, zip: a.zip, lat: a.lat, lon: a.lon, radius: a.radius })), d.places, d.chains);
}

/* The map on Areas & radius: follows what you type before you save. */
const geoCache = {};
let areaMapPlaces = null, areaMapBusy = false;
function drawAreaMap() {
  const box = $("area-map"); if (!box) return;
  const want = [...new Set(cfg.areas.map((a) => a.zip).filter((z) => /^\d{5}$/.test(z || "")))];
  const missing = want.filter((z) => !(z in geoCache));
  if (missing.length && !areaMapBusy) {
    areaMapBusy = true;
    Promise.all(missing.map((z) => api("/api/geo?zip=" + z).then((g) => { geoCache[z] = g; }).catch(() => { geoCache[z] = null; }))).then(() => { areaMapBusy = false; drawAreaMap(); });
  }
  if (!areaMapPlaces) { areaMapPlaces = { places: [], chains: [] }; api("/api/places").then((d) => { areaMapPlaces = d; drawAreaMap(); }).catch(() => {}); }
  const areas = cfg.areas.map((a) => { const g = geoCache[a.zip]; return { name: a.name, zip: a.zip, radius: Number(a.radius_miles) || 15, lat: g ? g.lat : null, lon: g ? g.lon : null }; });
  const unknown = cfg.areas.filter((a) => /^\d{5}$/.test(a.zip || "") && geoCache[a.zip] && geoCache[a.zip].lat === null).map((a) => a.zip);
  const view = mapView(areas, areaMapPlaces.places, areaMapPlaces.chains, { maxMiles: notifyCfg().max_miles || 0 });
  const kids = [];
  if (view) kids.push(view);
  else kids.push(h("div", { class: "panel empty", text: !cfg.areas.length ? "Add an area to see it on the map." : missing.length || areaMapBusy ? "Looking up your ZIP codes" : "Type a 5 digit ZIP for an area and it appears here." }));
  if (areaMapPlaces && areaMapPlaces.geocoder === false) kids.push(h("p", { class: "hint", text: "ZIP lookup is not installed, so the map cannot place your areas. Run setup.ps1 again to add it." }));
  if (unknown.length) kids.push(h("p", { class: "hint", text: "These ZIP codes were not found: " + unknown.join(", ") }));
  kids.push(h("p", { class: "hint", text: "Drawn to scale from your ZIP codes, with no outside map service. Stores come from the last store search (Stock near me > Stores with stock > Find stores again, after saving). Faded stores are outside your areas or skipped." }));
  box.replaceChildren(...kids);
}

/* ---------- Stores near you: what is in stock, by store ---------- */
const stockView = Object.assign({ area: "", radius: 0, chain: "", q: "", pickup: false, online: true, showAll: false }, store.get("restock-stockview", {}));
let stockSel = "", stockSig = "";
function saveStockView() { store.set("restock-stockview", { area: stockView.area, radius: stockView.radius, chain: stockView.chain, pickup: stockView.pickup, online: stockView.online, showAll: stockView.showAll }); }

/* Every store with something in stock right now, from the monitor's latest checks, filtered by the chosen area and radius. */
function stockStores() {
  const d = placesData || { areas: [] };
  const areas = d.areas || [];
  const chosen = stockView.area ? areas.filter((a) => a.name === stockView.area) : areas;
  const cap = Number(stockView.radius) || 0;
  const q = stockView.q.trim().toLowerCase();
  const stores = new Map(), online = [];
  ((status && status.items) || []).forEach((it) => {
    if (!it.in_stock || it.note || it.muted) return;
    const pts = it.store_points || [];
    if (!pts.length) { if (it.online && stockView.online && (!stockView.chain || it.retailer === stockView.chain) && (!q || it.title.toLowerCase().includes(q) || it.retailer_name.toLowerCase().includes(q))) online.push(it); return; }
    pts.forEach((sp) => {
      if (stockView.chain && (sp.chain || it.retailer) !== stockView.chain && it.retailer !== stockView.chain) return;
      if (stockView.pickup && !sp.pickup) return;
      // distance from the chosen area's centre (or the nearest area when "All areas")
      let dist = null;
      if (sp.point) chosen.forEach((a) => { if (a.lat === null || a.lat === undefined) return; const m = milesBetween([a.lat, a.lon], sp.point); if (dist === null || m < dist) dist = m; });
      if (dist === null && sp.distance !== null && sp.distance !== undefined && (!stockView.area || sp.area === stockView.area || !sp.area)) dist = sp.distance;
      if (dist === null) { if (stockView.area && sp.area && sp.area !== stockView.area) return; }
      const within = chosen.length ? chosen.some((a) => { const m = sp.point && a.lat !== null && a.lat !== undefined ? milesBetween([a.lat, a.lon], sp.point) : (sp.area === a.name || !sp.area ? sp.distance : null); return m !== null && m !== undefined && m <= (cap || a.radius); }) : true;
      if (!within) return;
      const key = (sp.chain || it.retailer) + ":" + (sp.id || sp.name);
      let s = stores.get(key);
      if (!s) { s = { key, name: sp.name || sp.label, address: sp.address || "", retailer: sp.chain || it.retailer, retailer_name: it.retailer_name, point: sp.point, dist, area: sp.area, pickup: false, products: [] }; stores.set(key, s); }
      s.pickup = s.pickup || !!sp.pickup;
      if (dist !== null && (s.dist === null || dist < s.dist)) s.dist = dist;
      s.products.push({ title: it.title, url: it.url, price: it.price, msrp: it.msrp, qty: sp.qty, low: sp.low, pickup: sp.pickup, stock: sp.stock || "in stock", type: it.type });
    });
  });
  let list = [...stores.values()];
  if (q) list = list.filter((s) => s.name.toLowerCase().includes(q) || s.retailer_name.toLowerCase().includes(q) || s.products.some((p) => p.title.toLowerCase().includes(q)));
  list.sort((a, b) => (a.dist === null) - (b.dist === null) || (a.dist || 0) - (b.dist || 0) || a.name.localeCompare(b.name));
  return { stores: list, online, areas, chosen };
}

function stockSection(d, chains) {
  const r = stockStores(), areas = d.areas || [];
  const maxR = Math.max(5, ...((stockView.area ? areas.filter((a) => a.name === stockView.area) : areas).map((a) => a.radius)), 5);
  const radiusNow = Number(stockView.radius) || 0;
  const rLabel = () => radiusNow ? radiusNow + " mi" : "area radius";
  const redraw = () => { saveStockView(); drawPlaces(); };
  const areaSel = h("select", { "aria-label": "Area", onchange: (e) => { stockView.area = e.target.value; stockView.radius = 0; stockSel = ""; redraw(); } },
    h("option", { value: "", text: areas.length > 1 ? "All areas" : (areas[0] ? areas[0].name : "Area") }),
    areas.length > 1 ? areas.map((a) => h("option", { value: a.name, text: a.name + " (" + a.zip + ", " + a.radius + " mi)", selected: stockView.area === a.name })) : null);
  const radVal = h("span", { class: "radius-val", text: rLabel() });
  const rad = h("input", { type: "range", min: "1", max: String(Math.max(maxR, 100)), step: "1", value: String(radiusNow || maxR), "aria-label": "Radius in miles",
    oninput: (e) => { stockView.radius = Number(e.target.value); radVal.textContent = stockView.radius + " mi"; },
    onchange: () => { stockSel = ""; redraw(); } });
  const reset = h("button", { class: "btn quiet", type: "button", text: "Use area radius", onclick: () => { stockView.radius = 0; redraw(); } });
  const chainKeys = [...new Set([...(r.stores.map((s) => s.retailer)), ...((status && status.items) || []).filter((i) => i.in_stock && !i.note).map((i) => i.retailer)])].sort();
  const chainSel = h("select", { "aria-label": "Store", onchange: (e) => { stockView.chain = e.target.value; redraw(); } },
    h("option", { value: "", text: "All stores" }), chainKeys.map((k) => h("option", { value: k, text: RETAILERS[k] || (chains[k] || {}).name || k, selected: stockView.chain === k })));
  const q = h("input", { type: "search", placeholder: "Find a product or store", value: stockView.q, "aria-label": "Find a product or store",
    oninput: (e) => { stockView.q = e.target.value; clearTimeout(q._t); q._t = setTimeout(() => { drawPlaces(); const el = document.querySelector("#stock-q"); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 250); } });
  q.id = "stock-q";
  const chk = (label, key, extra) => h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!stockView[key], onchange: (e) => { stockView[key] = e.target.checked; stockSel = ""; if (extra) extra(); redraw(); } }), label);
  const bar = h("div", { class: "card stockbar" }, h("div", { class: "card-body" },
    h("div", { class: "wide stockrow" }, h("b", { text: "Area" }), areaSel, h("b", { text: "Within" }), rad, radVal, radiusNow ? reset : null),
    h("div", { class: "wide stockrow" }, chainSel, q, chk("Pickup available", "pickup"), chk("Include online listings", "online"), chk("Also list stores with nothing in stock", "showAll"))));

  const total = r.stores.length, products = new Set(r.stores.flatMap((s) => s.products.map((p) => p.title))).size;
  const summary = h("p", { class: "lede stocksum", text: total ? total + " store" + (total === 1 ? "" : "s") + " with stock right now, " + products + " different product" + (products === 1 ? "" : "s")
    + (r.online.length ? ", plus " + r.online.length + " online" : "") + ". Click a store on the map or in the list to see what it has."
    : (status && status.items && status.items.length ? "Nothing is in stock at a store in range right now. Widen the radius, pick all areas, or tick the box below to see every store." : "No checks have finished yet. Start monitoring and stores with stock appear here by themselves.") });

  // map: the chosen area(s) drawn at the chosen radius, with a dot for each store that has stock
  const mapAreas = r.chosen.filter((a) => a.lat !== null && a.lat !== undefined).map((a) => ({ name: a.name, zip: a.zip, lat: a.lat, lon: a.lon, radius: radiusNow || a.radius }));
  const markers = r.stores.filter((s) => s.point).map((s) => ({ lat: s.point[0], lon: s.point[1], count: s.products.length, selected: stockSel === s.key,
    label: s.name + ": " + s.products.length + " product" + (s.products.length === 1 ? "" : "s") + (s.dist !== null ? ", " + s.dist.toFixed(1) + " mi" : ""),
    onclick: () => { stockSel = stockSel === s.key ? "" : s.key; drawPlaces(); const t = [...document.querySelectorAll(".sstore")].find((x) => x.dataset.skey === s.key); if (t && stockSel) t.scrollIntoView({ block: "nearest", behavior: "smooth" }); } }));
  const map = mapView(mapAreas, d.places, d.chains, { markers, hidePlaces: !stockView.showAll });

  const money2 = (v) => v ? "$" + Number(v).toFixed(2) : "";
  const card = (s) => {
    const open = stockSel === s.key;
    const first = s.products[0];
    const head = h("button", { class: "sstore-head", type: "button", "aria-expanded": String(open), onclick: () => { stockSel = open ? "" : s.key; drawPlaces(); } },
      h("span", { class: "sname" }, h("b", { text: s.name }), h("span", { class: "hint", text: [s.address, s.retailer_name].filter(Boolean).join(" , ").replace(" , ", ", ") })),
      h("span", { class: "sbadges" },
        s.pickup ? h("span", { class: "badge live", text: "Pickup" }) : null,
        h("span", { class: "badge live", text: s.products.length + " in stock" }),
        h("span", { class: "hint", text: s.dist !== null ? s.dist.toFixed(1) + " mi" + (r.chosen.length > 1 && s.area ? " from " + s.area : "") : "" }),
        h("span", { class: "chev", text: open ? "Hide" : "Show" })));
    const body = open ? h("div", { class: "sstore-body" }, s.products.map((p) => h("div", { class: "sprod" },
      h("div", { class: "t" }, extLink(p.url, p.title), h("span", { class: "hint", text: (p.type ? p.type + ", " : "") + p.stock + (p.low ? " (low)" : "") })),
      h("span", { class: "sprice" + (p.msrp && p.price && p.price > p.msrp * 1.05 ? " over" : ""), text: money2(p.price) + (p.msrp && p.price && p.price > p.msrp * 1.05 ? " (over MSRP)" : "") })))) :
      h("div", { class: "sstore-peek hint", text: first.title + (s.products.length > 1 ? "  and " + (s.products.length - 1) + " more" : "") });
    return h("div", { class: "sstore" + (open ? " sel" : ""), "data-skey": s.key }, head, body);
  };
  const online = r.online.length ? [h("h2", { text: "In stock online (" + r.online.length + ")" }), h("div", { class: "panel", style: "overflow:hidden" }, r.online.slice(0, 40).map((it) => h("div", { class: "sprod" },
    h("div", { class: "t" }, extLink(it.url, it.title), h("span", { class: "hint", text: it.retailer_name + ", " + it.status })), h("span", { class: "sprice", text: money2(it.price) }))))] : null;
  return [bar, summary, map || (areas.length ? h("div", { class: "panel empty", text: "The map needs your area's ZIP lookup (it works offline once installed)." }) : null),
    total ? [h("h2", { text: "Stores with stock, nearest first" }), h("div", { class: "sstores" }, r.stores.map(card))] : null, online];
}

function drawPlaces() {
  const body = $("places-body"); if (!body || !placesData) return;
  const d = placesData, chains = Object.fromEntries((d.chains || []).map((c) => [c.key, c]));
  const head = h("div", { class: "toolbar" },
    h("span", { class: "hint", style: "flex:1", text: d.places.length ? d.places.length + " stores" + (d.updated ? ", updated " + new Date(d.updated * 1000).toLocaleString() : "") : "" }),
    h("button", { class: "btn", type: "button", text: "Find stores again", onclick: async () => { try { await api("/api/action", { action: "refresh_places" }); toast("Looking up stores near your areas"); setTimeout(loadPlaces, 9000); } catch (e) { toast(e.message, true); } } }));
  if (!d.areas.length) { body.replaceChildren(h("div", { class: "panel empty", text: "Add an area (a ZIP code and radius) under Areas & radius, then stores near it show up here." })); return; }
  const notes = [];
  if (!d.geocoder) notes.push(h("div", { class: "verdict no", style: "margin-bottom:12px", text: "ZIP lookup is not installed, so the map and OpenStreetMap search are off. Run setup.ps1 again to add it." }));
  if (d.error) notes.push(h("p", { class: "hint", text: "Some sources didn't answer: " + d.error }));
  const noPlaces = !d.places.length;
  const byChain = {};
  d.places.forEach((p) => (byChain[p.chain] = byChain[p.chain] || []).push(p));
  const order = Object.keys(byChain).sort((a, b) => ({ live: 0, online: 1, listed: 2 }[(chains[a] || {}).coverage] - { live: 0, online: 1, listed: 2 }[(chains[b] || {}).coverage]) || (byChain[a][0].distance ?? 999) - (byChain[b][0].distance ?? 999));
  const sections = order.map((key) => {
    const c = chains[key] || { name: key, coverage: "listed", note: "" };
    return [h("div", { class: "chain-head" }, h("h2", { text: c.name + " (" + byChain[key].length + ")" }), h("span", { class: "badge " + c.coverage, text: COVERAGE[c.coverage] })),
      c.note ? h("p", { class: "hint", style: "margin-top:0", text: c.note }) : null,
      h("div", { class: "panel", style: "overflow:hidden" }, byChain[key].map((p) => h("div", { class: "place-row" + (p.excluded ? " off" : "") },
        h("div", { class: "t" }, h("b", { text: p.name }), h("span", { text: [p.address, p.city].filter(Boolean).join(", ") + (p.store_id ? "  (store " + p.store_id + ")" : "") })),
        h("span", { class: "hint hide-s", text: (p.distance !== null ? p.distance + " mi" : "") + (p.area && d.areas.length > 1 ? " from " + p.area : "") }),
        c.coverage === "live" && p.store_id ? h("button", { class: "btn quiet", type: "button", text: p.excluded ? "Check this store" : "Skip this store",
          onclick: async () => { try { await api("/api/action", { action: "exclude_store", key: p.key, excluded: !p.excluded }); loadPlaces(); } catch (e) { toast(e.message, true); } } }) : h("span", {}))))];
  });
  const stockPart = stockSection(d, chains);
  body.replaceChildren(head, ...notes, ...stockPart.flat(Infinity).filter(Boolean),
    ...(stockView.showAll ? [h("h2", { text: "Every store near you" }), noPlaces ? h("div", { class: "panel empty", text: d.updated ? "No stores found in your areas. Try a larger radius." : "Store list not built yet. It builds a minute after the app starts, or press Find stores again." }) : null, ...sections.flat()] : []));
  stockSig = stockSignature();
}
function stockSignature() { return JSON.stringify(((status && status.items) || []).filter((i) => i.in_stock && !i.note).map((i) => [i.key, (i.store_points || []).map((s) => s.id || s.name)])); }

async function loadSellers() {
  const el = $("sellers"); if (!el) return;
  let rows = [];
  try { rows = (await api("/api/sellers")).rows || []; } catch (e) { el.replaceChildren(h("p", { class: "hint", text: e.message })); return; }
  if (!rows.length) { el.replaceChildren(h("div", { class: "panel empty", text: "No marketplace sellers seen yet. They show up here once a check finds an item sold by someone other than the store." })); return; }
  const set = async (key, mode) => { try { const r = await api("/api/action", { action: "seller_mode", key, mode }); toast(r.message || "Saved"); loadSellers(); } catch (e) { toast(e.message, true); } };
  el.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "rules" },
    h("thead", {}, h("tr", {}, ["Seller", "Store", "Status", "Why", ""].map((t) => h("th", { text: t })))),
    h("tbody", {}, rows.map((r) => h("tr", {},
      h("td", { text: r.name }), h("td", { text: RETAILERS[r.retailer] || r.retailer }),
      h("td", {}, h("b", { style: "color:" + (r.blocked ? "var(--bad)" : "var(--ok)"), text: r.blocked ? "Blocked" : "Allowed" }), r.mode !== "auto" ? h("span", { class: "hint", text: " (by you)" }) : null),
      h("td", { class: "hint", text: r.why }),
      h("td", { style: "white-space:nowrap;text-align:right" },
        r.mode !== "block" ? h("button", { class: "btn quiet", type: "button", text: "Block", onclick: () => set(r.key, "block") }) : null,
        r.mode !== "allow" ? h("button", { class: "btn quiet", type: "button", text: "Allow", onclick: () => set(r.key, "allow") }) : null,
        r.mode !== "auto" ? h("button", { class: "btn quiet", type: "button", text: "Decide by prices", onclick: () => set(r.key, "auto") }) : null)))))));
}
/* Store price next to MSRP, and how far apart they are, colored by your price limit for that store. */
function priceVsMsrp(price, msrp, retailer) {
  const cells = [h("span", { text: "Store" }), h("b", { text: price ? money(price) : "-" }), h("span", { text: "MSRP" }), h("b", { text: msrp ? money(msrp) : "-" })];
  if (price && msrp) {
    const pct = (price - msrp) / msrp * 100;
    const allow = storeAllowance(retailer);
    const cls = pct <= allow + 0.05 ? "fair" : pct <= Math.max(allow * 2, 25) ? "high" : "gouge";
    const text = Math.abs(pct) < 0.5 ? "At MSRP" : Math.round(Math.abs(pct)) + "% " + (pct > 0 ? "over" : "under") + " MSRP";
    cells.push(h("span", { class: "diff " + cls, title: "Your limit at this store: " + allow + "% over MSRP", text }));
  }
  return h("div", { class: "pricing" }, cells);
}
function storeAllowance(retailer) {
  const own = ((cfg.retailers || {})[retailer] || {}).msrp_tolerance_pct;
  const v = own !== undefined && own !== null && own !== "" ? Number(own) : Number((cfg.settings || {}).msrp_tolerance_pct || 0);
  return isFinite(v) ? v : 0;
}
/* Community tips (r/PokemonTCGDeals) and the newest set names, folded away above the product list. */
function drawCommunity() {
  const box = $("found-community"); if (!box || !catalogData) return;
  const c = cfg.community = cfg.community || {};
  ["reddit", "new_sets"].forEach((k) => { if (c[k] === undefined) c[k] = true; });
  const cm = catalogData.community || { tips: [], sets: [] };
  const ago = (t) => { const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? m + " min ago" : Math.round(m / 60) + " h ago"; };
  const tips = (cm.tips || []).slice(0, 8);
  const summary = (c.reddit ? (tips.length ? tips.length + " recent community tip" + (tips.length === 1 ? "" : "s") : "Community tips on") : "Community tips off")
    + (c.new_sets && (cm.sets || []).length ? ", searching for " + cm.sets.length + " new sets" : "");
  box.replaceChildren(h("details", { class: "more", style: "margin:0 0 14px", open: foundState.community || false,
    ontoggle: (e) => { foundState.community = e.target.open; saveFound(); } },
    h("summary", { text: summary }),
    h("div", { style: "margin-top:8px" },
      h("div", { class: "settings-list" },
        setting("Community restock tips", "Reads new posts on r/PokemonTCGDeals every 5 minutes (a public page; no account, nothing about you is sent). A post naming one of your stores gets the matching products there checked at once, and a direct product link is added here.", sw(c, "reddit", "")),
        setting("Search for the newest sets by name", "Once a day, adds the sets released in the last few months (from tcgcsv.com) to the store searches, so new products turn up sooner.", sw(c, "new_sets", "")),
        setting("Post tips to my status channel", "Also send each community tip to your Discord status webhook.", sw(c, "discord", ""))),
      cm.feed_problem ? h("p", { class: "hint", style: "color:var(--warn);margin:10px 0 0", text: "Reddit did not answer last time (" + cm.feed_problem + "). It is tried again later by itself." }) : null,
      (cm.sets || []).length ? h("p", { class: "hint", style: "margin:10px 0", text: "Newest sets searched for: " + cm.sets.join(", ") }) : null,
      tips.length ? h("div", { class: "panel" }, h("ul", { class: "feed" }, tips.map((t) => h("li", {},
        h("b", { text: ago(t.t) + ": " }), t.post ? extLink(t.post, t.title) : t.title,
        t.link ? [" ", extLink(t.link, "(store link)")] : null,
        h("span", { class: "hint", text: "  " + ((t.stores || []).map((s) => RETAILERS[s] || s).join(", ") || "no store you monitor")
          + (t.woke ? ", checked " + t.woke + " matching listing" + (t.woke === 1 ? "" : "s") : "") + ((t.added || []).length ? ", added here" : "") }))))) :
        h("p", { class: "hint", style: "margin:10px 0 0", text: c.reddit ? "No restock posts since the monitor started reading the feed. The first read only learns what is already there." : "" }))));
}

function drawFound() {
  drawCommunity();
  const body = $("found-body"); if (!body || !catalogData) return;
  const ts = $("found-type");
  if (ts && ts.options.length <= 1) {
    const labels = [...new Set(catalogData.groups.map((g) => g.type_label).filter(Boolean))].sort();
    labels.forEach((l) => ts.append(h("option", { value: l, text: l, selected: foundState.type === l })));
  }
  if (!catalogData.enabled) { body.replaceChildren(h("div", { class: "panel empty", text: "Automatic product finding is off. Turn it on under Stores & keys." })); return; }
  const q = foundState.q.toLowerCase();
  const groups = catalogData.groups.map((g) => Object.assign({}, g, { listings: g.listings.filter((l) =>
    (!foundState.retailer || l.retailer === foundState.retailer) && (foundState.showIgnored || l.status !== "ignored")) }))
    .filter((g) => g.listings.length && (!foundState.type || g.type_label === foundState.type) && (!q || g.title.toLowerCase().includes(q)));
  if (!groups.length) {
    const ran = Object.keys(catalogData.runs || {}).length;
    body.replaceChildren(h("div", { class: "panel empty", text: ran ? "Nothing matches these filters." : "No searches have run yet. They start a few seconds after monitoring starts, or press Search stores now." }));
    return;
  }
  const ignoredN = catalogData.groups.filter((g) => g.listings.length && g.listings.every((l) => l.status === "ignored")).length;
  body.replaceChildren(h("p", { class: "hint", text: groups.length + " products across " + new Set(groups.flatMap((g) => g.listings.map((l) => l.retailer))).size + " stores"
    + (ignoredN && !foundState.showIgnored ? ". " + ignoredN + " you ignored are hidden (Show ignored to see them); they stay ignored at every store" : "") }),
    ...groups.slice(0, 200).map((g) => h("div", { class: "group" },
      h("div", { class: "group-head" }, h("b", { text: g.title }), h("span", { class: "hint", text: (g.type_label || "") + (g.msrp ? ", MSRP " + money(g.msrp) : "") })),
      g.listings.map((l) => {
        const inNow = Date.now() / 1000 - (l.last_in_stock || 0) < 3600;
        const sched = l.schedule && l.schedule.text;
        return h("div", { class: "listing" + (l.status === "ignored" ? " off" : "") + (inNow ? " in" : "") },
          h("b", { text: RETAILERS[l.retailer] || l.retailer_name }),
          h("span", {}, extLink(l.url, l.status_text || "Not checked yet"), l.type_alert ? null : h("span", { class: "hint", text: "  (alerts off for this type)" }),
            sched ? h("span", { class: "sched", text: sched }) : null),
          priceVsMsrp(l.price, l.msrp || g.msrp, l.retailer),
          h("button", { class: "btn quiet", type: "button", text: l.status === "ignored" ? "Track" : "Ignore", onclick: async () => {
            try { const r = await api("/api/action", { action: "product_status", key: l.key, status: l.status === "ignored" ? "tracking" : "ignored" }); toast(r.message || "Saved"); loadFound(); } catch (e) { toast(e.message, true); } } }));
      }))));
}

function drawTable() {
  const wrap = $("stock"); if (!wrap) return;
  const q = dashState.q.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
  const rows = ((status && status.items) || []).filter((it) =>
    (!dashState.retailer || it.retailer === dashState.retailer) && (!dashState.inOnly || (it.in_stock && !it.note)) &&
    (!q || it.title.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").includes(q)) && passesNear(it));
  wrap.replaceChildren(rows.length ? h("table", { class: "stock" },
    h("thead", {}, h("tr", {}, h("th", { text: "Product" }), h("th", { text: "Stock" }), h("th", { class: "hide-s", text: "Price" }), h("th", {}))),
    h("tbody", {}, rows.map((it) => {
      const live = it.in_stock && !it.note;
      return h("tr", { class: live ? "in" : (it.note || it.muted ? "dim" : "") },
        h("td", {}, extLink(it.url, it.title), h("span", { class: "sub", text: [it.retailer_name, it.source === "auto" ? "found for you" : String(it.source || "").startsWith("search:") ? "keyword search" : "your links", it.type, "checked " + ago(it.checked)].filter(Boolean).join(" \u00b7 ") })),
        h("td", {}, it.note || it.status, storeLine(it)),
        h("td", { class: "price hide-s" }, money(it.price), it.msrp ? h("span", { class: "sub", text: "MSRP " + money(it.msrp) }) : null),
        h("td", { class: "act" }, h("button", { class: "btn quiet", type: "button", text: it.muted ? "Unmute" : "Mute", onclick: () => mute(it.key, !it.muted) })));
    }))) : h("div", { class: "empty", text: status && status.items.length ? "Nothing matches these filters." : "Nothing checked yet. Products are found at each store by themselves; the first results show up within a few minutes of starting." }));
}

function storeLine(it) {
  if (nearFilterOn()) {
    const near = storesInRange(it.store_points).sort((a, b) => a.away - b.away);
    if (!near.length) return it.stores.length ? h("span", { class: "sub", text: "No stores within " + nearState.radius + " mi of " + nearState.zip }) : null;
    return h("span", { class: "sub", text: near.slice(0, 3).map((p) => p.name + ", " + p.away.toFixed(1) + " mi" + (p.pickup ? ", pickup" : "")).join("; ") + (near.length > 3 ? "; +" + (near.length - 3) + " more" : "") });
  }
  const pts = it.store_points || [];
  const one = (p) => p.name + " (" + [p.distance !== null && p.distance !== undefined ? p.distance + " mi" : "", p.qty ? p.qty + " on the shelf" : "", p.pickup ? "pickup" : ""].filter(Boolean).join(", ") + ")";
  return pts.length ? h("span", { class: "sub", text: pts.slice(0, 3).map(one).join("; ") + (pts.length > 3 ? "; and " + (pts.length - 3) + " more" : "") }) : null;
}
function nearWhere() {
  if (!nearState.zip) return "Any location";
  if (nearState.zip.length < 5) return "Type 5 digits";
  if (status && status.geocoder === false) return "ZIP lookup not installed";
  return nearState.point ? (nearState.place || "Found") : "Unknown ZIP";
}
let nearTimer = null;
function lookupNear() {
  clearTimeout(nearTimer);
  nearState.point = null;
  nearTimer = setTimeout(async () => {
    if (nearState.zip.length === 5) {
      try { const g = await api("/api/geo?zip=" + nearState.zip); nearState.point = g.lat !== null ? [g.lat, g.lon] : null; nearState.place = g.place || ""; } catch (e) {}
    }
    store.set("restock-near", { zip: nearState.zip, radius: nearState.radius, online: nearState.online });
    const w = $("near-where"); if (w) w.textContent = nearWhere();
    const zb = $("zipbar"); if (zb) zb.classList.toggle("on", nearFilterOn());
    drawDash();
  }, 250);
}

async function mute(key, on) {
  try { await api("/api/action", { action: "mute", key, muted: on }); toast(on ? "Muted. This listing won't alert." : "Unmuted"); await poll(); if (tab !== "dash") render(); } catch (e) { toast(e.message, true); }
}

function render() {
  if (!cfg) return;
  const y = window.scrollY;
  viewSig = viewSigNow();
  lastTab[groupOf(tab).key] = tab;
  $("view").replaceChildren(...[subTabs(), ...views[tab]()].flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false));
  const g = groupOf(tab).key;
  document.querySelectorAll("nav.rail button").forEach((b) => b.dataset.group === g ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  counts();
  if (tab === "scan") drawScan();
  window.scrollTo(0, y);
}
function drawStrip() {
  if (!status) return;
  const live = status.items.filter((i) => i.in_stock && !i.note);
  $("lamp").classList.toggle("lit", live.length > 0);
  $("lamp-n").textContent = live.length;
  $("lamp-t").textContent = live.length ? (live.length === 1 ? "Item in stock now" : "Items in stock now") : "Nothing in stock";
  $("lamp-s").textContent = live.length ? live.slice(0, 2).map((i) => i.retailer_name + ": " + i.title).join("  \u00b7  ").slice(0, 120)
    : "Watching " + status.items.length + " listings at " + (status.retailers || []).length + " stores";
  const st = $("state");
  st.className = "state" + (status.paused ? " pause" : status.running ? " run" : "");
  st.querySelector("span").textContent = status.paused ? "Alerts paused" : status.running ? "Checking" : "Stopped";
  $("b-run").textContent = status.running ? "Stop checking" : "Start checking";
  $("b-pause").textContent = status.paused ? "Resume alerts" : "Pause alerts";
  $("verline").textContent = status.version_label || "";
  if (status.lan_url) $("hostline").textContent = "Also at " + status.lan_url;
  const hc = status.human_checks || [];
  $("banner").classList.toggle("show", hc.length > 0);
  if (hc.length) {
    const sites = hc.map((c) => c.domain.replace(/^www\./, "")).join(", ");
    $("banner-t").textContent = sites + (hc.length > 1 ? " want" : " wants") + " a quick human check before checking can continue. Finish it in the " + (hc[0].profile ? hc[0].profile + " browser window" : "browser window") + " on your PC; checks pick up again by themselves.";
  }
}

/* Phone access: what state it is in, every address to try, and the one Windows Firewall command that usually fixes "cannot connect". */
function phonePanel(p) {
  if (!p) return null;
  const colors = { on: "var(--ok)", off: "var(--muted)", needs_pin: "var(--warn)", restart: "var(--warn)" };
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast("Copied"); } catch (e) { toast("Select the text and copy it", true); } };
  return h("div", { class: "panel", style: "padding:14px 16px;margin:10px 0" },
    h("p", { style: "margin:0 0 8px;font-weight:600;color:" + (colors[p.state] || "inherit"), text: p.message }),
    p.urls && p.urls.length ? [h("p", { class: "hint", style: "margin:0 0 4px", text: "On your phone (same Wi-Fi), open one of these. The first is usually right:" }),
      h("ul", { class: "feed" }, p.urls.map((u) => h("li", {}, h("b", { text: u }), " ", h("button", { class: "btn quiet", type: "button", text: "Copy", onclick: () => copy(u) }))))] : null,
    p.state === "on" ? h("details", { style: "margin-top:8px" },
      h("summary", { text: "Phone cannot connect? Windows Firewall is the usual cause" }),
      h("p", { class: "hint", text: "Windows blocks other devices from reaching a program until you allow it, and the first-run prompt is easy to dismiss. Open PowerShell as administrator (right-click, Run as administrator) and run this once. It opens the port on private networks only (home Wi-Fi), not public ones:" }),
      h("code", { style: "display:block;white-space:pre-wrap;overflow-wrap:anywhere", text: p.firewall }),
      h("p", { style: "margin:8px 0" }, h("button", { class: "btn", type: "button", text: "Copy the command", onclick: () => copy(p.firewall) })),
      h("p", { class: "hint", text: "Also check that the phone is on the same Wi-Fi (not mobile data or a guest network), and that Windows calls this network Private (Settings > Network & internet > Wi-Fi > your network > Private)." })) : null);
}
function viewSigNow() { return !status ? "" : JSON.stringify(tab === "methods" ? [status.sessions, status.trials, status.trust, status.history] : tab === "accounts" ? [status.accounts, status.retailers, status.browser] : null); }
async function poll() {
  try {
    status = await api("/api/status"); drawStrip();
    if (tab === "dash") drawDash();
    if (tab === "places" && placesData && stockSignature() !== stockSig && !(document.activeElement && document.activeElement.id === "stock-q")) drawPlaces();
    if (tab === "methods" || tab === "accounts") {
      // Rebuild only when this tab's own numbers changed, and never while the person is selecting text or typing,
      // so a refresh does not wipe a selection, a half-typed field or the scroll position.
      const sig = viewSigNow();
      const sel = window.getSelection && String(window.getSelection()).length > 0;
      const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && $("view").contains(document.activeElement);
      if (sig !== viewSig && !sel && !typing) { viewSig = sig; render(); }
    }
    if (tab === "times" && status.history_total !== lastHistoryTotal) { lastHistoryTotal = status.history_total; loadPatterns(); }
    if (tab === "places" && placesData && status.places_total !== placesData.places.length) loadPlaces();
    counts();
  }
  catch (e) { $("state").querySelector("span").textContent = "Not connected"; }
}

document.querySelectorAll("nav.rail button").forEach((b) => b.addEventListener("click", () => {
  const g = GROUPS.find((x) => x.key === b.dataset.group);
  tab = lastTab[g.key] || g.tabs[0][0]; window.scrollTo(0, 0); render();
}));
$("b-save").addEventListener("click", async () => {
  try { await api("/api/config", cfg); savedJSON = JSON.stringify(cfg); touch(); toast("Saved. Checks restart with the new settings."); setTimeout(load, 1500); }
  catch (e) { toast(e.message, true); }
});
$("b-discard").addEventListener("click", () => { cfg = JSON.parse(savedJSON); touch(); render(); toast("Changes discarded"); });
$("b-showbrowser").addEventListener("click", async () => { try { await api("/api/action", { action: "show_browser" }); toast("Browser window brought forward on your PC"); } catch (e) { toast(e.message, true); } });
$("b-check").addEventListener("click", async () => { try { await api("/api/action", { action: "check" }); toast("Checking every store now"); } catch (e) { toast(e.message, true); } });
$("b-pause").addEventListener("click", async () => { try { await api("/api/action", { action: "pause", paused: !status.paused }); await poll(); } catch (e) { toast(e.message, true); } });
$("b-run").addEventListener("click", async () => { try { await api("/api/action", { action: status.running ? "stop" : "start" }); setTimeout(poll, 800); } catch (e) { toast(e.message, true); } });
window.addEventListener("beforeunload", (e) => { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });

async function load() {
  if (dirty()) return;
  cfg = await api("/api/config"); savedJSON = JSON.stringify(cfg); touch(); render();
}
async function boot() {
  try {
    try { TYPES_LIST = await api("/api/types"); } catch (e) {}
    await load(); await poll();
    if (nearState.zip.length === 5) lookupNear();
    render();
  } catch (e) { if (e.message !== "PIN required") toast(e.message, true); }
}
boot();
setInterval(() => { if (!document.hidden) poll(); }, 5000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
</script>
</body>
</html>
"""
