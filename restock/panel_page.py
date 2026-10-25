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
   amber = blocked or waiting, rose = error. Fonts are system fonts only (no outside requests). */
:root {
  color-scheme: dark;
  --bg: #0b0820; --panel: rgba(255,255,255,.07); --raised: rgba(255,255,255,.09); --line: rgba(255,255,255,.17); --line-soft: rgba(255,255,255,.09);
  --ink: #ece8ff; --muted: #b9b0ec; --faint: #9a91d0;
  --act: #a78bfa; --act-ink: #0b0820; --act-soft: rgba(167,139,250,.24);
  --ok: #67e8f9; --ok-bg: rgba(103,232,249,.12); --ok-strong: #22d3ee;
  --warn: #fcd34d; --warn-bg: rgba(251,191,36,.13); --bad: #fda4af; --bad-bg: rgba(251,113,133,.15);
  --r-s: 12px; --r-m: 22px;
  --grad: linear-gradient(90deg, #a78bfa, #22d3ee);
  --font: "Sora", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
  --font-display: "Sora", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--ink); font: 14px/1.45 var(--font); font-variant-numeric: tabular-nums; }
a { color: var(--act); }
button, input, select, textarea { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--act); outline-offset: 2px; }

/* ---- frame ---- */
.frame { display: grid; grid-template-columns: 200px 1fr; min-height: 100vh; }
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
main { padding: 0 28px 120px; max-width: 1180px; width: 100%; }

/* ---- annunciator strip: the one loud element ---- */
.strip { display: flex; align-items: stretch; gap: 12px; padding: 16px 0; position: sticky; top: 0; background: var(--bg); z-index: 5; flex-wrap: wrap; }
.lamp { flex: 1 1 260px; display: flex; align-items: center; gap: 14px; padding: 10px 16px; border: 1px solid var(--line); border-radius: var(--r-m); background: var(--panel); min-height: 64px; }
.lamp .big { font: 600 30px/1 var(--font-display); min-width: 1.6ch; }
.lamp .what { color: var(--muted); }
.lamp.lit { background: var(--ok-bg); border-color: var(--ok-strong); }
.lamp.lit .big { color: var(--ok); }
.lamp.lit .what { color: var(--ok); }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.state { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border-radius: 999px; background: var(--panel); border: 1px solid var(--line); font-size: 13px; }
.state i { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); }
.state.run i { background: var(--ok-strong); }
.state.pause { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
.state.pause i { background: var(--warn); }

.btn { border: 1px solid var(--line); background: var(--raised); padding: 7px 13px; border-radius: var(--r-s); cursor: pointer; white-space: nowrap; }
.btn:hover { border-color: var(--muted); }
.btn.primary { background: var(--act); border-color: var(--act); color: var(--act-ink); font-weight: 600; }
.btn.quiet { background: none; border-color: transparent; color: var(--muted); padding: 5px 8px; }
.btn.quiet:hover { color: var(--ink); background: var(--line-soft); }
.btn.danger:hover { color: var(--bad); border-color: var(--bad); }
.btn[disabled] { opacity: .5; cursor: default; }

/* ---- sections ---- */
h1 { font: 600 22px/1.25 var(--font-display); margin: 8px 0 4px; }
h2 { font: 600 16px/1.3 var(--font-display); margin: 28px 0 10px; }
.lede { color: var(--muted); margin: 0 0 18px; max-width: 68ch; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-m); }
.pad { padding: 16px; }
.hint { color: var(--muted); font-size: 13px; }
.empty { padding: 28px 16px; color: var(--muted); text-align: center; }

/* retailer tiles: grey unless abnormal */
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
.tile { padding: 9px 12px; border: 1px solid var(--line); border-radius: var(--r-s); background: var(--panel); }
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
table.stock th { text-align: left; font-weight: 600; font-size: 12px; color: var(--muted); padding: 8px 10px; border-bottom: 1px solid var(--line); background: var(--panel); }
table.stock td { padding: 8px 10px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }
table.stock tr.in td { background: var(--ok-bg); }
table.stock tr.in td:first-child { box-shadow: inset 4px 0 0 var(--ok-strong); }
table.stock tr.dim td { color: var(--faint); }
td.price { white-space: nowrap; text-align: right; }
td .sub { display: block; font-size: 12px; color: var(--muted); }
tr.in td .sub { color: var(--ok); }
td.act { white-space: nowrap; text-align: right; }
.table-wrap { background: var(--raised); border: 1px solid var(--line); border-radius: var(--r-m); overflow: hidden; }

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
.setting .t span { font-size: 13px; color: var(--muted); }
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
.radar { width: 100%; max-width: 560px; display: block; margin: 0 auto; }
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
.listing { display: grid; grid-template-columns: 130px minmax(0, 1fr) 90px auto; gap: 12px; align-items: center; padding: 8px 14px; border-bottom: 1px solid var(--line-soft); font-size: 13.5px; }
.listing:last-child { border-bottom: 0; }
.listing.off { opacity: .5; }
.listing.in { background: var(--ok-bg); }
@media (max-width: 900px) { .listing { grid-template-columns: 1fr auto; } .listing .hide-s { display: none; } .place-row { grid-template-columns: 1fr auto; } .place-row .hide-s { display: none; } }

/* save bar */
.savebar { position: fixed; left: 200px; right: 0; bottom: 0; display: none; justify-content: flex-end; align-items: center; gap: 10px; padding: 12px 28px; background: var(--raised); border-top: 2px solid var(--act); z-index: 10; }
.savebar.show { display: flex; }
.savebar .msg { margin-right: auto; font-weight: 600; }
.toast { position: fixed; right: 20px; bottom: 74px; background: var(--ink); color: var(--bg); padding: 10px 14px; border-radius: var(--r-s); opacity: 0; transform: translateY(6px); transition: opacity .2s, transform .2s; pointer-events: none; z-index: 20; max-width: 360px; }
.toast.show { opacity: 1; transform: none; }
.toast.err { background: var(--bad); color: #fff; }

dialog { border: 1px solid var(--line); border-radius: var(--r-m); background: var(--raised); color: var(--ink); padding: 22px; max-width: 340px; }
dialog::backdrop { background: rgba(20, 24, 28, .45); }

@media (max-width: 900px) {
  .frame { grid-template-columns: 1fr; }
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
.strip { background: transparent; backdrop-filter: none; }
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
    <div class="navlabel">Monitor</div>
    <button data-tab="dash" aria-current="page">Dashboard</button>
    <button data-tab="found">Found products <span class="count" id="c-found"></span></button>
    <button data-tab="places">Stores near you <span class="count" id="c-places"></span></button>
    <button data-tab="times">Restock times</button>
    <button data-tab="methods">Methods lab</button>
    <div class="navlabel">Set up</div>
    <button data-tab="notify">Notifications</button>
    <button data-tab="areas">Areas &amp; radius</button>
    <button data-tab="speed">Check speed</button>
    <button data-tab="filters">Product filters</button>
    <button data-tab="watch">My products <span class="count" id="c-watch"></span></button>
    <button data-tab="search">Searches <span class="count" id="c-search"></span></button>
    <button data-tab="retail">Stores &amp; keys</button>
  </nav>
  <main>
    <div class="strip">
      <div class="lamp" id="lamp"><div class="big" id="lamp-n">0</div><div><div id="lamp-t" style="font-weight:600">Nothing in stock</div><div class="what" id="lamp-s">Waiting for the first check</div></div></div>
      <div class="controls">
        <span class="state" id="state"><i></i><span>Connecting</span></span>
        <button class="btn" id="b-check">Check now</button>
        <button class="btn" id="b-pause">Pause alerts</button>
        <button class="btn" id="b-run">Stop</button>
      </div>
    </div>
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
  amazon: "Amazon", dicks: "Dick's Sporting Goods", safeway: "Safeway", raleys: "Raley's", walgreens: "Walgreens", cvs: "CVS", web: "Other sites" };
const SEARCHABLE = ["target", "bestbuy", "walmart", "kroger", "dicks"];
const COVERAGE = { live: "Shelf stock checked", online: "Website checked", listed: "Listed only" };
let TYPES_LIST = [];
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
const nearState = Object.assign({ zip: "", radius: 15, online: true, point: null, place: "" }, store.get("restock-near", {}));
const foundState = { q: "", type: "", retailer: "", showIgnored: false };
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
let cfg = null, savedJSON = "", status = null, tab = "dash";
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
function ago(t) { if (!t || !status) return ""; const s = Math.max(0, Math.round(status.now - t)); return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + "m ago" : Math.round(s / 3600) + "h ago"; }
function toast(msg, err) { const t = $("toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : ""); clearTimeout(t._t); t._t = setTimeout(() => t.className = "toast", 3200); }
function extLink(url, text) { return h("a", { href: url, target: "_blank", rel: "noreferrer noopener", text }); }

/* ---------- API ---------- */
async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    referrerPolicy: "no-referrer",
  });
  if (res.status === 401) { askPin(); throw new Error("PIN required"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
  return data;
}
function askPin() { const d = $("pin"); if (!d.open) d.showModal(); }
$("pin-form").addEventListener("submit", () => { token = $("pin-in").value.trim(); sessionStorage.setItem("restock-pin", token); boot(); });

/* ---------- config editing ---------- */
const dirty = () => cfg && JSON.stringify(cfg) !== savedJSON;
function touch() { $("savebar").classList.toggle("show", dirty()); counts(); }
function counts() {
  if (!cfg) return;
  $("c-watch").textContent = (cfg.watchlist || []).length || "";
  $("c-search").textContent = (cfg.searches || []).length || "";
  if (status) { $("c-found").textContent = status.catalog_total || ""; $("c-places").textContent = status.places_total || ""; }
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
      h("h1", { text: "Dashboard" }),
      h("p", { class: "lede", text: "Everything the monitor checked recently. Rows light up when an item is in stock and passes your filters. Mute a listing to stop its alerts." }),
      h("div", { class: "tiles", id: "tiles" }), h("h2", { text: "Listings" }),
      h("div", { class: "two" },
        h("div", {}, zipbar, h("div", { class: "toolbar" }, search, sel, only), h("div", { class: "table-wrap", id: "stock" })),
        h("div", {}, h("h2", { style: "margin-top:0", text: "Recent alerts" }), h("div", { class: "panel" }, h("ul", { class: "feed", id: "alerts" })),
          h("h2", { text: "Activity" }), h("div", { class: "panel" }, h("ul", { class: "feed log", id: "activity" })))),
    ];
  },

  times() {
    const sel = h("select", { "aria-label": "Store chain", onchange: (e) => { timesState.retailer = e.target.value; timesState.place = ""; loadPatterns(); } },
      h("option", { value: "", text: "All stores" }), Object.entries(RETAILERS).map(([k, v]) => h("option", { value: k, text: v, selected: timesState.retailer === k })));
    const place = h("select", { id: "place-sel", "aria-label": "Location", onchange: (e) => { timesState.place = e.target.value; loadPatterns(); } },
      h("option", { value: "", text: "Every location" }));
    setTimeout(loadPatterns);
    return [
      h("h1", { text: "Restock times" }),
      h("p", { class: "lede", text: "Every restock the monitor catches while it runs is logged here by store, day and hour. After a couple of weeks you can see when each store usually gets stock, so you go at the right time instead of driving around." }),
      h("div", { class: "toolbar" }, sel, place),
      h("div", { id: "times-body" }, h("div", { class: "panel empty", text: "Loading restock history" })),
    ];
  },

  places() {
    setTimeout(loadPlaces);
    return [
      h("h1", { text: "Stores near you" }),
      h("p", { class: "lede", text: "Stores around your areas that sell Pokemon cards, found from each chain's store finder and OpenStreetMap. Green stores get live shelf checks; blue ones are covered through their website; grey ones are listed so you know they exist." }),
      h("div", { id: "places-body" }, h("div", { class: "panel empty", text: "Loading stores" })),
    ];
  },

  found() {
    const q = h("input", { type: "search", placeholder: "Filter by name", value: foundState.q, "aria-label": "Filter products", oninput: (e) => { foundState.q = e.target.value; drawFound(); } });
    const typeSel = h("select", { id: "found-type", "aria-label": "Product type", onchange: (e) => { foundState.type = e.target.value; drawFound(); } }, h("option", { value: "", text: "All product types" }));
    const rSel = h("select", { "aria-label": "Store", onchange: (e) => { foundState.retailer = e.target.value; drawFound(); } },
      h("option", { value: "", text: "All stores" }), SEARCHABLE.map((k) => h("option", { value: k, text: RETAILERS[k], selected: foundState.retailer === k })));
    const ign = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: foundState.showIgnored, onchange: (e) => { foundState.showIgnored = e.target.checked; drawFound(); } }), "Show ignored");
    setTimeout(loadFound);
    return [
      h("h1", { text: "Found products" }),
      h("p", { class: "lede", text: "Pokemon products the monitor found by searching store catalogs, grouped across stores. They are checked automatically, the most wanted types first. Ignore any you don't care about." }),
      h("div", { class: "toolbar" }, q, typeSel, rSel, ign, h("button", { class: "btn", type: "button", text: "Search stores now", onclick: async () => {
        try { await api("/api/action", { action: "rediscover" }); toast("Searching store catalogs now"); setTimeout(loadFound, 8000); } catch (e) { toast(e.message, true); } } })),
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
      h("h1", { text: "Products" }),
      h("p", { class: "lede", text: "Specific items you want, on top of what the monitor finds on its own. A UPC is enough for Target, Best Buy, Walmart and Kroger. For other stores, paste the product link." }),
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
          field("Search at", picks(s, "retailers", SEARCHABLE), "Walgreens and CVS don't support search; add their links under Products", true),
          field("Must include one of", lines(s.keywords, "include_any", { placeholder: "elite trainer box\nbooster bundle" }), "Added to your global keywords"),
          field("Never alert on", lines(s.keywords, "exclude", { placeholder: "sleeves\nbinder" }), "Added to your global excludes"),
          field("Max price", num(s, "max_price", { placeholder: "Optional" }), "Overrides the MSRP rules for this search"),
          h("div", {}, sw(s, "in_store", "Check nearby stores for matches"), h("p", { class: "hint", text: "Uses more requests. Best for one or two searches." }))));
    });
    return [
      h("h1", { text: "Searches" }),
      h("p", { class: "lede", text: "Catch new listings you don't have a UPC for. Results only alert when the title passes your keywords, the price is at MSRP, and it's in stock." }),
      list.length ? list : h("div", { class: "panel empty", text: "No searches yet." }),
      h("button", { class: "btn primary", type: "button", text: "Add search", onclick: () => { cfg.searches.push({ name: "", query: "", retailers: ["target", "walmart"], keywords: { include_any: [], exclude: [] }, max_price: null, in_store: false, enabled: true }); touch(); render(); } }),
    ];
  },

  filters() {
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
      h("h1", { text: "Product filters" }),
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
    return [
      h("h1", { text: "Areas & radius" }),
      h("p", { class: "lede", text: "Where you shop. Stores inside any of these circles are checked and can alert; stores outside them are ignored. Give an area its own Discord channel to send it only the stores inside that area." }),
      areasEditor(),
      h("p", {}, h("button", { class: "btn", type: "button", text: "Add area", onclick: () => { cfg.areas.push({ name: cfg.areas.length ? "Work" : "Home", zip: "", radius_miles: 15 }); touch(); render(); } })),
      h("h2", { text: "Alert distance" }),
      h("div", { class: "settings-list" },
        setting("Only alert for stores within", "A tighter limit for alerts than your areas, for example check 25 miles but only ping for stores within 10. Off uses your areas.",
          h("div", { style: "display:flex;gap:10px;align-items:center" }, h("input", { type: "range", min: "0", max: "50", value: String(n.max_miles || 0), "aria-label": "Alert distance in miles",
            oninput: (e) => { const v = Number(e.target.value); n.max_miles = v || null; capVal.textContent = v ? v + " mi" : "Off"; touch(); } }), capVal)),
        setting("Check store shelves", "Shelf stock at Target, Best Buy and Kroger stores in your areas.", sw(cfg.settings, "in_store", ""))),
      h("p", { class: "hint" }, "Skip single stores you never visit on ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); go("places"); }, text: "Stores near you" }), "."),
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
    const label = (m) => m === "direct" ? "Plain requests" : m === "pool" ? "Browser pool" : "Browser: " + m;
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
      h("h1", {}, "Methods ", h("b", { text: "lab" })),
      h("p", { class: "lede", text: "Which way of loading pages lasts longest before a store blocks it. Counts are saved between runs, so the picture gets sharper over time." }),
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
      h("h2", { text: "Profiles and tests" }),
      h("div", { class: "card" }, h("div", { class: "card-body" }, h("div", { class: "wide" },
        h("p", { style: "margin:0 0 8px", text: "Active browser profiles: " + ((ses.profiles || []).join(", ") || "none") + ". Add or change them in config.yaml under browser: profiles, then restart the app." }),
        h("p", { style: "margin:0 0 6px", class: "hint", text: "For a side-by-side test of every method on the same pages, run this in PowerShell from the app folder:" }),
        h("code", { text: ".\\.venv\\Scripts\\python.exe app.py --abtest" })))),
    ];
  },

  notify() {
    const d = cfg.discord, wh = d.webhooks = d.webhooks || {}, n = notifyCfg(), st = cfg.settings;
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
      h("h1", { text: "Notifications" }),
      h("p", { class: "lede", text: "Connect Discord and decide exactly what gets pushed. Stores keep being checked either way; these settings only control the alerts." }),
      h("h2", { text: "Discord" }),
      h("div", { class: "card" }, h("div", { class: "card-body" },
        field("Restock channel webhook", secret(wh, "default", "https://discord.com/api/webhooks/..."), "In Discord: Server Settings, Integrations, Webhooks, New Webhook, pick your channel, Copy Webhook URL. Keep it private.", true),
        field("Online restocks channel (optional)", secret(wh, "online", "Webhook URL"), "Things you can order online. Blank uses the restock channel."),
        field("In-store channel (optional)", secret(wh, "in_store", "Webhook URL"), "Shelf stock near you. Each area can also have its own channel on Areas & radius."),
        field("Ping a role", text(d, "mention_role_id", { placeholder: "Role ID, optional" }), "Developer Mode on, then right-click the role, Copy Role ID"),
        field("Ping me", text(d, "mention_user_id", { placeholder: "Your user ID, optional" })),
        field("Bot name", text(d, "username")),
        h("div", { style: "display:flex;align-items:end" }, h("button", { class: "btn", type: "button", text: "Send test message", onclick: async () => {
          if (dirty()) return toast("Save your changes first, then send the test.", true);
          try { const r = await api("/api/action", { action: "test_discord" }); toast(r.ok ? "Test message sent" : (r.message || "Discord rejected the message. Check the webhook URL."), !r.ok); } catch (e) { toast(e.message, true); } } })))),
      h("h2", { text: "What gets pushed" }),
      h("div", { class: "settings-list" },
        setting("Online restocks", "An item can be bought online again.", sw(n, "online", "")),
        setting("In-store restocks", "Shelf stock appeared at a store in your areas.", sw(n, "in_store", "")),
        setting("Only when pickup works", "Skip in-store stock you can't order for pickup. Pickup stock is the most reliable.", sw(n, "pickup_only", "")),
        setting("New listings", "A store listed a Pokemon product for the first time.", sw(n, "new_listings", "")),
        setting("Pokemon Center queue", "The waiting room opened, which usually means a drop within minutes.", sw(n, "queue", "")),
        setting("Sold-out notices", "Post when an item sells out online.", sw(st, "notify_sold_out", "")),
        setting("Verification requests", "Post when a store wants you to finish a check in the browser.", sw(br, "notify_discord", "")),
        setting("Windows pop-ups", "Also show alerts as notifications on this PC.", sw(st, "windows_toast", ""))),
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
      h("h1", { text: "Check speed" }),
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
      return h("div", { class: "card" + (r.enabled ? "" : " off") },
        h("div", { class: "card-head" }, sw(r, "enabled", ""), h("b", { style: "flex:1", text: RETAILERS[key] }), h("span", { class: "hint", text: desc })),
        r.enabled && extra ? h("div", { class: "card-body" }, extra(r)) : null);
    };
    return [
      h("h1", { text: "Stores & keys" }),
      h("p", { class: "lede", text: "Turn stores on or off, add the free keys some need, and choose how website-based stores are loaded. Check speed has its own page." }),
      block("target", (r) => field("Only these store numbers", lines(r, "store_ids", { placeholder: "Leave empty for all stores in range" }), "One per line"), "Online and nearby store shelves, with quantities"),
      block("bestbuy", (r) => field("API key", secret(r, "api_key", "Free at developer.bestbuy.com"), "Required. Takes a few minutes to get.", true), "Online and nearby store shelves"),
      block("kroger", (r) => [
        field("Client ID", text(r, "client_id", { placeholder: "From developer.kroger.com" }), "Free developer account, then create an app with the Products scope"),
        field("Client secret", secret(r, "client_secret", "")),
        field("Stores to check", num(r, "max_stores"), "Nearest stores in your areas. 5 fits the free daily limit."),
        field("Only these store IDs", lines(r, "store_ids", { placeholder: "Optional, one per line" }))],
        "Kroger, Fred Meyer, Smith's and other Kroger stores: stock level per store"),
      block("walmart", modeField, "Online, plus pickup at the store set in the checking browser"),
      block("pokemoncenter", (r) => [modeField(r), h("div", { class: "wide" }, sw(r, "watch_queue", "Watch the Pokemon Center queue (usually opens minutes before a drop)"))], "Online drops and the waiting-room queue"),
      block("dicks", modeField, "Online, found automatically from its Pokemon section"),
      block("safeway", modeField, "Online, for the store set in the checking browser"),
      block("raleys", modeField, "Online, from product links"),
      block("gamestop", modeField, "Online, from product links"),
      block("costco", modeField, "Online, from product links"),
      block("samsclub", modeField, "Online, from product links"),
      block("barnesandnoble", modeField, "Online, from product links"),
      block("booksamillion", modeField, "Online, from product links"),
      block("amazon", modeField, "Online, sold by Amazon only"),
      block("walgreens", modeField, "Online listings from your product links"),
      block("cvs", modeField, "Online listings from your product links"),
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
        setting("Tabs per store", "Pages of one store rotate through this many tabs (1 to 6) instead of reloading a single tab.", num(br, "tabs_per_site", { min: "1", max: "6" }))),
      h("p", { class: "hint", text: "Browser changes take effect after restarting the app." }),
      h("h2", { text: "Phone access" }),
      h("div", { class: "settings-list" },
        setting("Open this panel from my phone", "Lets devices on your home Wi-Fi reach it. Needs a PIN and an app restart.", sw(cp, "allow_lan", "")),
        setting("PIN", "At least 4 characters.", h("div", { style: "width:180px" }, secret(cp, "pin", ""))),
        setting("Port", "Change only if 8765 is taken. Needs an app restart.", num(cp, "port"))),
      status && status.lan_url ? h("p", { class: "hint" }, "On your phone, open ", h("b", { text: status.lan_url })) : null,
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
    const placeTag = h("span", { class: "hint", text: "" });
    const look = async () => {
      if (!/^\d{5}$/.test(a.zip || "")) { placeTag.textContent = a.zip ? "5 digits" : ""; return; }
      try { const g = await api("/api/geo?zip=" + a.zip); placeTag.textContent = g.lat !== null ? g.place : (g.ready ? "Unknown ZIP" : "ZIP lookup not installed"); } catch (e) {}
    };
    setTimeout(look);
    const radVal = h("span", { class: "radius-val", text: (a.radius_miles || 15) + " mi" });
    return h("div", { class: "win-row" },
      h("input", { type: "text", value: a.name || "", placeholder: "Name", "aria-label": "Area name", style: "width:120px", oninput: (e) => { a.name = e.target.value; touch(); } }),
      h("input", { type: "text", value: a.zip || "", placeholder: "ZIP", inputmode: "numeric", maxlength: "5", "aria-label": "ZIP code", style: "width:90px",
        oninput: (e) => { a.zip = e.target.value.replace(/\D/g, "").slice(0, 5); touch(); look(); } }), placeTag,
      h("span", { text: "radius" }),
      h("input", { type: "range", min: "1", max: "100", value: String(a.radius_miles || 15), "aria-label": "Radius in miles",
        oninput: (e) => { a.radius_miles = Number(e.target.value); radVal.textContent = a.radius_miles + " mi"; touch(); } }), radVal,
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
  const tiles = $("tiles"); if (!tiles) return;
  tiles.replaceChildren(...(s.retailers.length ? s.retailers.map((r) => {
    const st = r.status || "";
    const cls = /^(Blocked|Waiting for you)/.test(st) ? "warn" : /^Error/.test(st) ? "bad" : "";
    const meta = [];
    if (r.using_browser) meta.push("Using the browser");
    if (r.success !== null && r.checks >= 3) meta.push(r.success + "% of recent checks OK");
    if (r.next_in !== null && r.next_in !== undefined) meta.push("next check in " + fmtSecs(r.next_in));
    return h("div", { class: "tile " + cls, title: r.last_block || "" }, h("b", { text: r.display }), h("span", { text: st }),
      meta.length ? h("span", { class: "meta", text: meta.join(", ") }) : null);
  }) : [h("div", { class: "hint", text: "No stores are turned on. Turn some on under Stores & keys or Check speed." })]));
  const alertsShown = s.alerts.filter((a) => !nearFilterOn() || !a.points || storesInRange(a.points).length || (nearState.online && a.online !== false));
  $("alerts").replaceChildren(...(alertsShown.length ? alertsShown.slice(0, 25).map((a) => h("li", {},
    h("time", { text: new Date(a.time * 1000).toLocaleString() }), h("div", {}, h("span", { class: "ok", text: a.retailer + " " }), extLink(a.url, a.title)),
    h("div", { class: "hint", text: a.reason + (a.price ? ", " + money(a.price) : "") + (a.sent ? "" : " (not sent to Discord)") }))) :
    [h("li", { class: "hint", text: nearFilterOn() ? "No alerts near this ZIP yet." : "Restock alerts show up here and in your Discord channel." })]));
  $("activity").replaceChildren(...s.activity.slice(0, 80).map((a) => h("li", {}, h("time", { text: new Date(a.time * 1000).toLocaleTimeString() + "  " }), a.msg)));
  drawTable();
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

function radar(d) {
  const areas = (d.areas || []).filter((a) => a.lat !== null);
  if (!areas.length) return null;
  const lat0 = areas.reduce((s, a) => s + a.lat, 0) / areas.length, lon0 = areas.reduce((s, a) => s + a.lon, 0) / areas.length;
  const k = Math.cos(lat0 * Math.PI / 180);
  const xy = (lat, lon) => [(lon - lon0) * 69.17 * k, (lat - lat0) * 69.17];
  let extent = 1;
  areas.forEach((a) => { const [x, y] = xy(a.lat, a.lon); extent = Math.max(extent, Math.abs(x) + a.radius, Math.abs(y) + a.radius); });
  const W = 560, C = W / 2, sc = (C - 24) / extent;
  const P = (lat, lon) => { const [x, y] = xy(lat, lon); return [C + x * sc, C - y * sc]; };
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, kids = []) => { const e = document.createElementNS(ns, tag); for (const [a, v] of Object.entries(attrs)) e.setAttribute(a, v); kids.forEach((c) => e.append(c)); return e; };
  const svg = el("svg", { viewBox: "0 0 " + W + " " + W, class: "radar", role: "img", "aria-label": "Map of stores around your areas" });
  areas.forEach((a) => {
    const [cx, cy] = P(a.lat, a.lon);
    svg.append(el("circle", { cx, cy, r: a.radius * sc, fill: "var(--act-soft)", "fill-opacity": "0.35", stroke: "var(--act)", "stroke-width": "1.25", "stroke-dasharray": "4 4" }));
    svg.append(el("path", { d: "M" + (cx - 6) + " " + cy + "h12M" + cx + " " + (cy - 6) + "v12", stroke: "var(--ink)", "stroke-width": "2" }));
    const t = el("text", { x: cx + 9, y: cy - 8, "font-size": "13", "font-weight": "600", fill: "var(--ink)" }); t.textContent = a.name + " (" + a.radius + " mi)"; svg.append(t);
  });
  const color = { live: "var(--ok-strong)", online: "var(--act)", listed: "var(--faint)" };
  const chains = Object.fromEntries((d.chains || []).map((c) => [c.key, c]));
  (d.places || []).forEach((p) => {
    if (p.lat === null || p.lon === null) return;
    const [x, y] = P(p.lat, p.lon), cov = (chains[p.chain] || {}).coverage || "listed";
    const dot = el("circle", { cx: x, cy: y, r: cov === "live" ? 5.5 : 4, fill: color[cov], stroke: "var(--raised)", "stroke-width": "1.5", opacity: p.excluded ? "0.3" : "1" });
    const tt = el("title"); tt.textContent = p.name + (p.distance !== null ? ", " + p.distance + " mi" : ""); dot.append(tt); svg.append(dot);
  });
  return h("div", { class: "panel radar-wrap" }, svg, h("div", { class: "legend" },
    h("span", {}, h("i", { style: "background:var(--ok-strong)" }), COVERAGE.live), h("span", {}, h("i", { style: "background:var(--act)" }), COVERAGE.online),
    h("span", {}, h("i", { style: "background:var(--faint)" }), COVERAGE.listed)));
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
  if (!d.places.length) { body.replaceChildren(head, ...notes, h("div", { class: "panel empty", text: d.updated ? "No stores found in your areas. Try a larger radius." : "Store list not built yet. It builds a minute after the app starts, or press Find stores again." })); return; }
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
  body.replaceChildren(head, ...notes, radar(d) || h("span"), ...sections.flat());
}

function drawFound() {
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
  body.replaceChildren(h("p", { class: "hint", text: groups.length + " products across " + new Set(groups.flatMap((g) => g.listings.map((l) => l.retailer))).size + " stores" }),
    ...groups.slice(0, 200).map((g) => h("div", { class: "group" },
      h("div", { class: "group-head" }, h("b", { text: g.title }), h("span", { class: "hint", text: (g.type_label || "") + (g.msrp ? ", MSRP " + money(g.msrp) : "") })),
      g.listings.map((l) => {
        const inNow = Date.now() / 1000 - (l.last_in_stock || 0) < 3600;
        return h("div", { class: "listing" + (l.status === "ignored" ? " off" : "") + (inNow ? " in" : "") },
          h("b", { text: l.retailer_name }),
          h("span", {}, extLink(l.url, l.status_text || "Not checked yet"), l.type_alert ? null : h("span", { class: "hint", text: "  (alerts off for this type)" })),
          h("span", { class: "hint hide-s", text: money(l.price) }),
          h("button", { class: "btn quiet", type: "button", text: l.status === "ignored" ? "Track" : "Ignore", onclick: async () => {
            try { await api("/api/action", { action: "product_status", key: l.key, status: l.status === "ignored" ? "tracking" : "ignored" }); loadFound(); } catch (e) { toast(e.message, true); } } }));
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
        h("td", {}, extLink(it.url, it.title), h("span", { class: "sub", text: it.retailer_name + ", " + (it.source === "auto" ? "found automatically" : it.source) + (it.type ? ", " + it.type : "") + ", " + ago(it.checked) })),
        h("td", {}, it.note || it.status, storeLine(it)),
        h("td", { class: "price hide-s" }, money(it.price), it.msrp ? h("span", { class: "sub", text: "MSRP " + money(it.msrp) }) : null),
        h("td", { class: "act" }, h("button", { class: "btn quiet", type: "button", text: it.muted ? "Unmute" : "Mute", onclick: () => mute(it.key, !it.muted) })));
    }))) : h("div", { class: "empty", text: status && status.items.length ? "Nothing matches these filters." : "No results yet. Add products or searches, then press Check now." }));
}

function storeLine(it) {
  if (nearFilterOn()) {
    const near = storesInRange(it.store_points).sort((a, b) => a.away - b.away);
    if (!near.length) return it.stores.length ? h("span", { class: "sub", text: "No stores within " + nearState.radius + " mi of " + nearState.zip }) : null;
    return h("span", { class: "sub", text: near.slice(0, 3).map((p) => p.name + ", " + p.away.toFixed(1) + " mi" + (p.pickup ? ", pickup" : "")).join("; ") + (near.length > 3 ? "; +" + (near.length - 3) + " more" : "") });
  }
  return it.stores.length ? h("span", { class: "sub", text: it.stores.slice(0, 3).join("; ") + (it.stores.length > 3 ? "; +" + (it.stores.length - 3) + " more" : "") }) : null;
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
  $("view").replaceChildren(...views[tab]().flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false));
  document.querySelectorAll("nav.rail button").forEach((b) => b.dataset.tab === tab ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  counts();
  window.scrollTo(0, y);
}
function drawStrip() {
  if (!status) return;
  const live = status.items.filter((i) => i.in_stock && !i.note);
  $("lamp").classList.toggle("lit", live.length > 0);
  $("lamp-n").textContent = live.length;
  $("lamp-t").textContent = live.length ? (live.length === 1 ? "Item in stock now" : "Items in stock now") : "Nothing in stock";
  $("lamp-s").textContent = live.length ? live.slice(0, 2).map((i) => i.retailer_name + ": " + i.title).join("  |  ").slice(0, 120) : status.items.length + " listings watched";
  const st = $("state");
  st.className = "state" + (status.paused ? " pause" : status.running ? " run" : "");
  st.querySelector("span").textContent = status.paused ? "Alerts paused" : status.running ? "Checking" : "Stopped";
  $("b-run").textContent = status.running ? "Stop" : "Start";
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

async function poll() {
  try {
    status = await api("/api/status"); drawStrip();
    if (tab === "dash") drawDash();
    if (tab === "methods") render();
    if (tab === "times" && status.history_total !== lastHistoryTotal) { lastHistoryTotal = status.history_total; loadPatterns(); }
    if (tab === "places" && placesData && status.places_total !== placesData.places.length) loadPlaces();
    counts();
  }
  catch (e) { $("state").querySelector("span").textContent = "Not connected"; }
}

document.querySelectorAll("nav.rail button").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; window.scrollTo(0, 0); render(); }));
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
