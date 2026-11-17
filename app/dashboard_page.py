"""The staff dashboard web page (Step 27): GET /dashboard.

The page itself contains no company data and no key. The person types their staff key into the
page; it is kept only in that browser tab's memory (never in the address, never saved on disk)
and is sent only to this same server. Everything shown comes from the Step 26 endpoint.

Design: "Dense Desk", a compact staff desk with a left rail, a stat strip and scannable tables.
"""
import secrets

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>JARVIS Staff Dashboard</title>
<style nonce="__NONCE__">
/* JARVIS staff desk: dense, flat and fast. A left rail of sections, a stat strip, tables you can scan.
   Light and dark tokens are paired so text always has contrast on its own background. System fonts only. */
:root{
  --bg:#f6f7f9; --panel:#ffffff; --panel2:#f0f2f6; --ink:#1b2030; --mute:#586075; --line:#e3e6ec; --field:#8790a3;
  --accent:#1d6fdb; --accent-ink:#ffffff; --sel-bg:#e8f0fd; --sel-ink:#13479b; --on-bad:#ffffff;
  --console:var(--panel); --console-ink:var(--ink); --console-mute:var(--mute); --console-line:var(--line);
  --ok:#14794f; --hand:#1d6fdb; --quit:#c98a0b; --bad:#c42b31;
  --bad-bg:#fde7e8; --warn-bg:#fdf1d6; --shadow:0 1px 2px rgba(27,32,48,.06);
  --glow:0 0 0 transparent;
  --serif:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0e1116; --panel:#161a22; --panel2:#1d222c; --ink:#e7eaf1; --mute:#9ba4b7; --line:#2a303c; --field:#667089;
  --accent:#5b9dff; --accent-ink:#08111f; --sel-bg:#1b2a47; --sel-ink:#b3d1ff; --on-bad:#2a0a0d;
  --console:var(--panel); --console-ink:var(--ink); --console-mute:var(--mute); --console-line:var(--line);
  --ok:#3dd598; --hand:#5b9dff; --quit:#f2b24a; --bad:#ff7a84;
  --bad-bg:#3a1a20; --warn-bg:#33290f; --shadow:0 1px 2px rgba(0,0,0,.35);
  --glow:0 0 0 transparent; color-scheme:dark;
}}
:root[data-theme="dark"]{
  --bg:#0e1116; --panel:#161a22; --panel2:#1d222c; --ink:#e7eaf1; --mute:#9ba4b7; --line:#2a303c; --field:#667089;
  --accent:#5b9dff; --accent-ink:#08111f; --sel-bg:#1b2a47; --sel-ink:#b3d1ff; --on-bad:#2a0a0d;
  --console:var(--panel); --console-ink:var(--ink); --console-mute:var(--mute); --console-line:var(--line);
  --ok:#3dd598; --hand:#5b9dff; --quit:#f2b24a; --bad:#ff7a84;
  --bad-bg:#3a1a20; --warn-bg:#33290f; --shadow:0 1px 2px rgba(0,0,0,.35);
  --glow:0 0 0 transparent; color-scheme:dark;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--sans);font-variant-numeric:tabular-nums}
.hidden{display:none!important}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
select,input,button,textarea{font:inherit;color:inherit}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
select,input{padding:10px 13px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
.btn{padding:10px 15px;border-radius:10px;border:1px solid var(--line);background:var(--panel);cursor:pointer;transition:transform .12s,border-color .12s}
.btn:hover{border-color:var(--accent)}.btn:active{transform:translateY(1px)}
.btn.main{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:600}
.btn.warn{border-color:var(--bad);color:var(--bad)}
.btn[disabled]{opacity:.55;cursor:wait}

/* top bar */
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;justify-content:space-between;padding:18px 0 14px}
.brand{display:flex;align-items:center;gap:12px}
.mark{display:flex;gap:5px}
.mark i{width:11px;height:11px;border-radius:50%;display:block;box-shadow:var(--glow)}
.mark i:nth-child(1){background:var(--ok);color:var(--ok)}.mark i:nth-child(2){background:var(--quit);color:var(--quit)}.mark i:nth-child(3){background:var(--bad);color:var(--bad)}
.mark i:nth-child(1){animation:breathe 3.2s ease-in-out infinite}
@keyframes breathe{50%{opacity:.45}}
.wordmark{font:600 23px/1 var(--serif);letter-spacing:.01em}
.who{color:var(--mute);font-size:15px}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.tools[hidden]{display:none}
.themebtn{min-width:104px}

/* sign in */
.signin{max-width:480px;margin:8vh auto 0;padding:30px 28px;background:var(--panel);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}
.signin h1{font:500 clamp(28px,6vw,40px)/1.1 var(--serif);margin:16px 0 8px}
.signin>p{color:var(--mute);margin:0 0 18px}
.signin .seg{display:flex;gap:4px;padding:4px;background:var(--panel2);border-radius:12px;margin:0 0 16px}
.signin .seg button{flex:1;padding:9px 10px;border:0;border-radius:9px;background:transparent;cursor:pointer;font-weight:600;color:var(--mute)}
.signin .seg button[aria-pressed="true"]{background:var(--panel);color:var(--ink);box-shadow:var(--shadow)}
.signin form{display:grid;gap:10px}
.signin input{width:100%}
.signin .hint{color:var(--mute);font-size:14px;margin:12px 0 0}

/* messages */
.note{margin:0 0 14px;padding:11px 14px;border-radius:12px;background:var(--warn-bg);border-left:4px solid var(--quit)}
.note.error{background:var(--bad-bg);border-left-color:var(--bad)}

/* section tabs with a sliding indicator and a 30 second refresh line */
.tabs{position:sticky;top:0;z-index:5;display:flex;gap:2px;overflow-x:auto;background:var(--bg);margin:0 0 22px;padding:6px 0 0;scrollbar-width:none;border-bottom:1px solid var(--line)}
.tabs::-webkit-scrollbar{display:none}
.tab{position:relative;flex:0 0 auto;display:flex;align-items:center;gap:8px;min-height:48px;padding:0 16px;background:none;border:0;color:var(--mute);font:600 16px/1 var(--sans);cursor:pointer;white-space:nowrap;border-radius:10px 10px 0 0}
.tab:hover{color:var(--ink);background:color-mix(in srgb,var(--accent) 7%,transparent)}
.tab[aria-selected="true"]{color:var(--ink)}
.tab:focus-visible{outline-offset:-3px}
.tab-ink{position:absolute;left:0;bottom:-1px;height:3px;width:var(--w,0);transform:translateX(var(--x,0));background:var(--accent);border-radius:3px 3px 0 0;transition:transform .28s cubic-bezier(.3,.8,.3,1),width .28s cubic-bezier(.3,.8,.3,1);box-shadow:var(--glow) var(--accent)}
.pulse{position:absolute;left:0;bottom:-1px;height:1px;width:100%;background:var(--accent);opacity:.5;transform-origin:left;transform:scaleX(0);pointer-events:none}
.pulse.run{animation:pulse 30s linear forwards}
@keyframes pulse{to{transform:scaleX(1)}}
.cnt{min-width:22px;padding:3px 7px;border-radius:999px;background:var(--line);color:var(--ink);font:700 12px/1 var(--sans);text-align:center}
.cnt.bad{background:var(--bad);color:#fff}
.cnt.good{background:color-mix(in srgb,var(--accent) 20%,var(--panel));color:var(--ink)}

.panel{animation:rise .24s ease-out both}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}

/* lamps */
.lamps{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px;max-width:600px}
.lamp{width:15px;height:15px;border-radius:50%;background:var(--ok);color:var(--ok);box-shadow:var(--glow) currentColor}
.lamp.ok{background:var(--ok);color:var(--ok)}.lamp.hand{background:var(--hand);color:var(--hand)}
.lamp.quit{background:var(--quit);color:var(--quit)}.lamp.bad{background:var(--bad);color:var(--bad)}
.intro .lamp{animation:lampon .5s ease-out both}
@keyframes lampon{from{opacity:.1;transform:scale(.5)}to{opacity:1;transform:scale(1)}}

/* overview: the console card is the one bold thing */
.hero{display:grid;gap:22px;grid-template-columns:minmax(0,7fr) minmax(0,5fr);margin:0 0 22px;align-items:stretch}
.console{background:var(--console);color:var(--console-ink);border-radius:24px;padding:28px;border:1px solid var(--console-line);box-shadow:var(--shadow)}
.greet{margin:0 0 6px;color:var(--console-mute);font-size:15px}
.console h1{font:500 clamp(34px,5vw,58px)/1.04 var(--serif);margin:0 0 8px;letter-spacing:-.01em;max-width:15ch}
.console .sub{color:var(--console-mute);font-size:17px;margin:0 0 22px;max-width:44ch}
.legend{display:flex;flex-wrap:wrap;gap:6px 20px;margin:0;padding:0;list-style:none;font-size:15px}
.legend li{display:flex;align-items:center;gap:8px;color:var(--console-mute)}
.legend strong{color:var(--console-ink);font-weight:650}
.legend .lamp{width:10px;height:10px}
.scale{color:var(--console-mute);font-size:14px;margin:10px 0 0}
.needs{background:var(--panel);border:1px solid var(--line);border-radius:24px;padding:22px;box-shadow:var(--shadow)}
.needs h2,.sect h2{font:600 22px/1.2 var(--serif);margin:0 0 4px}
.hint{color:var(--mute);margin:0 0 14px;font-size:15px}
.need{display:grid;grid-template-columns:auto 1fr auto;gap:4px 14px;align-items:center;width:100%;text-align:left;padding:13px 14px;margin-top:8px;border:0;border-radius:14px;background:var(--warn-bg);border-left:5px solid var(--quit);cursor:pointer;transition:transform .14s}
.need:hover{transform:translateX(3px)}
.need.bad{background:var(--bad-bg);border-left-color:var(--bad)}
.need b{font:600 30px/1 var(--serif)}
.need .go{color:var(--mute);font-size:20px}
.clear{display:flex;align-items:center;gap:12px;padding:14px;border-radius:14px;background:color-mix(in srgb,var(--ok) 14%,transparent)}

/* KPI tiles: each is a doorway to its section */
.kpis{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));margin:0 0 22px}
.kpi{position:relative;display:flex;flex-direction:column;gap:2px;text-align:left;padding:16px 18px 16px 20px;border:1px solid var(--line);border-radius:16px;background:var(--panel);cursor:pointer;box-shadow:var(--shadow);transition:transform .16s,border-color .16s;min-height:132px;overflow:hidden}
.kpi::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:4px;border-radius:0 4px 4px 0;background:var(--k,var(--accent));box-shadow:var(--glow) var(--k,var(--accent))}
.kpi:hover{transform:translateY(-3px);border-color:var(--k,var(--accent))}
.kpi .lbl{color:var(--mute);font-size:14px}
.kpi .val{font:600 40px/1.1 var(--serif);letter-spacing:-.01em}
.kpi .val small{font:600 17px var(--sans);color:var(--mute);margin-left:4px}
.kpi .note2{color:var(--mute);font-size:14px;margin-top:auto}
.kpi svg{position:absolute;right:14px;top:14px;width:84px;height:46px;overflow:visible}
.kpi .ring-bg{stroke:var(--line)}.kpi .ring{stroke:var(--k);transition:stroke-dashoffset .9s cubic-bezier(.3,.8,.3,1)}
.kpi .sp{fill:var(--k);opacity:.85}.kpi .sp.last{opacity:1}

/* trend chart */
.sect{margin-bottom:30px}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px 18px 12px;box-shadow:var(--shadow)}
.chart svg{display:block;width:100%;height:190px;overflow:visible}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .axis{fill:var(--mute);font:12px var(--sans)}
.chart .col{cursor:pointer;outline:none}
.chart .col rect.seg{transition:opacity .15s}
.chart .col:hover rect.seg,.chart .col:focus rect.seg{opacity:.8}
.chart .col .hit{fill:transparent}
.chart .col:hover .hit,.chart .col:focus .hit{fill:color-mix(in srgb,var(--accent) 10%,transparent)}
.chart .tip{min-height:24px;color:var(--ink);font-size:15px;margin:8px 0 0}

/* next appointment */
.nextapp{display:flex;flex-wrap:wrap;align-items:center;gap:6px 22px;padding:18px 20px;border:1px solid var(--line);border-radius:18px;background:var(--panel);box-shadow:var(--shadow);cursor:pointer}
.nextapp:hover{border-color:var(--accent)}
.nextapp .when{font:600 30px/1.1 var(--serif)}
.nextapp .rel{margin-left:auto;padding:6px 14px;border-radius:999px;background:color-mix(in srgb,var(--accent) 16%,transparent);font-weight:650}
.nextapp .who2{color:var(--mute);flex-basis:100%;order:3}

/* appointments timeline, grouped by day */
.dayhead{font:600 15px var(--sans);color:var(--mute);margin:18px 0 8px;letter-spacing:.01em}
.dayhead:first-child{margin-top:0}
.line{list-style:none;margin:0 0 6px;padding:0 0 0 22px;border-left:2px solid var(--line)}
.stop{position:relative;padding:12px 16px;margin:0 0 10px 6px;border:1px solid var(--line);border-radius:14px;background:var(--panel);display:grid;grid-template-columns:auto 1fr auto;gap:2px 16px;align-items:center}
.stop::before{content:"";position:absolute;left:-36px;top:50%;margin-top:-7px;width:14px;height:14px;border-radius:50%;background:var(--bg);border:3px solid var(--accent)}
.stop.soon::before{background:var(--accent);box-shadow:var(--glow) var(--accent)}
.stop .at{font:600 22px/1.2 var(--serif)}
.stop .what{color:var(--mute);overflow-wrap:anywhere}
.stop .rel{font-size:14px;padding:4px 10px;border-radius:999px;background:var(--panel2);color:var(--mute);white-space:nowrap}

/* open work */
.ledger{list-style:none;margin:0;padding:0;display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.ledger li{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 18px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
.ledger .num{font:600 26px/1.2 var(--serif)}.ledger .num.bad{color:var(--bad)}

/* speed: a second console */
.speed{background:var(--console);color:var(--console-ink);border-radius:24px;padding:26px;border:1px solid var(--console-line);box-shadow:var(--shadow);margin:0 0 30px}
.speed h2{font:600 24px/1.2 var(--serif);margin:0 0 4px}
.speed .verdict{color:var(--console-mute);margin:0 0 24px;max-width:60ch}
.bars{display:grid;gap:34px}
.bar-row .cap{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px}
.bar-row .cap span{color:var(--console-mute)}
.bar-row .cap strong{font:600 22px/1 var(--serif);white-space:nowrap}
.track{position:relative;height:14px;border-radius:7px;background:var(--console-line)}
.fill{position:absolute;left:0;top:0;bottom:0;border-radius:7px;background:var(--ok);min-width:6px;box-shadow:var(--glow) var(--ok);transform-origin:left;animation:grow .8s cubic-bezier(.3,.8,.3,1) both}
@keyframes grow{from{transform:scaleX(0)}}
.fill.slow{background:var(--quit);box-shadow:var(--glow) var(--quit)}.fill.model{background:var(--hand);box-shadow:var(--glow) var(--hand)}
.tick{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--console-ink);opacity:.7}
.tick-label{position:absolute;top:20px;transform:translateX(-50%);font-size:12px;color:var(--console-mute);white-space:nowrap}
.facts{display:flex;flex-wrap:wrap;gap:8px 32px;margin:28px 0 0;padding:16px 0 0;border-top:1px solid var(--console-line);list-style:none}
.facts li{color:var(--console-mute)}.facts strong{color:var(--console-ink);font-weight:650}

/* search + filters */
.toolrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}
.toolrow .search{flex:1;min-width:200px;max-width:340px}
.filters{display:flex;gap:8px;flex-wrap:wrap}
.chip{padding:7px 15px;border-radius:999px;border:1px solid var(--line);background:var(--panel);cursor:pointer;transition:background .12s}
.chip:hover{border-color:var(--accent)}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink);font-weight:600}

/* tickets and calls as rows you can open */
.calls{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.calls>li{border:1px solid var(--line);border-radius:14px;background:var(--panel);overflow:hidden;transition:border-color .14s,box-shadow .14s}
.calls>li:hover{border-color:color-mix(in srgb,var(--accent) 50%,var(--line));box-shadow:var(--shadow)}
.calls>li.urgent{border-left:5px solid var(--bad)}
.trow,.rowbtn{display:grid;gap:10px;align-items:center;width:100%;padding:14px 16px;border:0;background:transparent;text-align:left;cursor:pointer}
.trow{grid-template-columns:48px minmax(0,1.7fr) minmax(0,1fr) 84px 130px 150px}
.rowbtn{grid-template-columns:150px minmax(0,1.4fr) minmax(0,1fr) 70px 80px}
.trow .t-subject{font-weight:600;overflow-wrap:anywhere}
.t-stat{justify-self:start;padding:3px 11px;border-radius:999px;background:var(--panel2);font-size:14px;font-weight:600}
.t-stat.s-open{background:color-mix(in srgb,var(--quit) 22%,transparent)}
.t-stat.s-in_progress{background:color-mix(in srgb,var(--hand) 22%,transparent)}
.t-stat.s-resolved{background:color-mix(in srgb,var(--ok) 22%,transparent)}
.prio-urgent{color:var(--bad);font-weight:700}
.est{font-size:14px}.est.failed{color:var(--bad);font-weight:600}.est.sent{color:var(--ok)}
.tdetail{padding:6px 16px 22px;max-width:780px;animation:rise .2s ease-out both}
.tdetail .desc{margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.tdetail .meta{color:var(--mute);margin:0 0 14px;font-size:15px;overflow-wrap:anywhere}
.tdetail label{display:block;font-weight:600;margin:0 0 6px}
.tdetail textarea{width:100%;min-height:80px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);resize:vertical}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.tstatus{margin:12px 0 0;padding:10px 13px;border-radius:10px;background:color-mix(in srgb,var(--ok) 14%,transparent)}
.tstatus.bad{background:var(--bad-bg)}.tstatus.warn{background:var(--warn-bg)}
.badge{display:inline-flex;align-items:center;gap:8px}
.badge i{width:10px;height:10px;border-radius:50%;display:block;box-shadow:var(--glow) currentColor}
.mutes{color:var(--mute)}
.transcript{padding:6px 16px 20px;animation:rise .2s ease-out both}
.transcript .tools-used{color:var(--mute);margin:0 0 10px;font-size:15px}
.say{max-width:min(620px,92%);padding:10px 14px;border-radius:16px;margin:6px 0;overflow-wrap:anywhere}
.say.user{background:var(--panel2);border:1px solid var(--line);border-top-left-radius:4px}
.say.assistant{background:var(--accent);color:var(--accent-ink);margin-left:auto;border-top-right-radius:4px}
.say small{display:block;opacity:.75;font-size:12px;margin-bottom:2px}
.empty{color:var(--mute);padding:18px;text-align:center}
.foot{color:var(--mute);font-size:14px;padding:4px 0 8px}
.keys{color:var(--mute);font-size:13px;padding:0 0 40px}
.keys kbd{padding:1px 7px;border:1px solid var(--line);border-bottom-width:2px;border-radius:6px;background:var(--panel);font:600 12px var(--sans)}

@media (max-width:860px){
  .hero{grid-template-columns:minmax(0,1fr)}
  .trow{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"subj stat" "cust prio" "mail mail"}
  .trow .t-id{display:none}.trow .t-subject{grid-area:subj}.trow .t-cust{grid-area:cust}
  .trow .t-prio{grid-area:prio;justify-self:end}.trow .t-stat{grid-area:stat;justify-self:end}.trow .t-mail{grid-area:mail}
  .rowbtn{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"who badge" "when len"}
  .rowbtn .c-when{grid-area:when}.rowbtn .c-who{grid-area:who}.rowbtn .c-out{grid-area:badge;justify-self:end}
  .rowbtn .c-len{grid-area:len;justify-self:end}.rowbtn .c-wait{display:none}
  .stop{grid-template-columns:auto 1fr}.stop .rel{grid-column:1/-1;justify-self:start}
  .keys{display:none}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .kpi{min-height:118px;padding:14px 12px 14px 16px}.kpi .val{font-size:32px}.kpi svg{width:56px;height:34px;right:10px;top:12px}
  .console{padding:22px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
}
.chart .c-completed{fill:var(--ok)}.chart .c-handoff{fill:var(--hand)}.chart .c-abandoned{fill:var(--quit)}.chart .c-failed{fill:var(--bad)}

/* ---- Dense Desk layer: flat, compact, left rail ---- */
body{font-size:15px}
.wrap{max-width:1380px}
::placeholder{color:var(--mute);opacity:1}
select,input,textarea{border-color:var(--field);border-radius:8px}
.btn{border-radius:8px;border-color:var(--field)}
.btn.main{border-color:var(--accent)}
.top{margin:14px 0;padding:10px 16px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.wordmark{font-size:18px;font-weight:700;letter-spacing:0}
.signin{border-radius:12px;box-shadow:none}
.signin h1{font-weight:700;letter-spacing:-.01em}
.signin .seg{border-radius:8px}.signin .seg button{border-radius:6px}
.signin .seg button[aria-pressed="true"]{box-shadow:0 0 0 1px var(--line)}
.panel{animation:none}

#board{display:grid;grid-template-columns:204px minmax(0,1fr);column-gap:18px;align-items:start}
#board>*{grid-column:2}
#board>.tabs{grid-column:1;grid-row:1 / span 30}
.tabs{position:sticky;top:12px;flex-direction:column;gap:2px;overflow:visible;margin:0;padding:10px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.tab{width:100%;justify-content:space-between;min-height:40px;padding:0 12px;border-radius:8px;font-size:15px;color:var(--ink)}
.tab:hover{background:var(--panel2)}
.tab[aria-selected="true"]{background:var(--sel-bg);color:var(--sel-ink);font-weight:700}
.tab-ink{display:none}
.pulse{left:10px;right:10px;width:auto;bottom:0}
.cnt{border-radius:6px;background:var(--panel2);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
.cnt.bad{background:var(--bad);color:var(--on-bad);box-shadow:none}
.cnt.good{background:var(--sel-bg);color:var(--sel-ink);box-shadow:none}

.hero{gap:16px;margin:0 0 16px;grid-template-columns:minmax(0,3fr) minmax(0,2fr)}
.console,.needs,.chart,.nextapp,.speed,.ledger li,.stop{border-radius:12px;box-shadow:none}
.console{padding:18px 20px;border:1px solid var(--line)}
.console h1{font:700 clamp(22px,2.6vw,30px)/1.15 var(--sans);letter-spacing:-.01em;max-width:none;margin:0 0 6px}
.console .sub{font-size:15px;margin:0 0 14px;max-width:60ch}
.greet{font-size:14px}
.lamp{width:12px;height:12px}
.lamps{gap:5px;margin:0 0 12px}
.needs{padding:16px 18px}
.needs h2,.sect h2{font:700 16px/1.3 var(--sans)}
.need{border-radius:10px;padding:10px 12px;grid-template-columns:auto minmax(0,1fr) auto;overflow-wrap:anywhere}
.need b{font:700 24px/1 var(--sans)}
.clear{border-radius:10px}

.kpis{display:flex;flex-wrap:wrap;gap:0;margin:0 0 16px;background:var(--panel);border-top:1px solid var(--line);border-left:1px solid var(--line);border-radius:12px;overflow:hidden}
.kpi{flex:1 1 170px;min-height:0;border:0;border-radius:0;box-shadow:inset -1px -1px 0 var(--line);padding:14px 18px;background:transparent}
.kpi::before{left:0;right:0;top:0;bottom:auto;width:auto;height:3px;border-radius:0}
.kpi:hover{transform:none;background:var(--panel2)}
.kpi .val{font:700 26px/1.15 var(--sans)}
.kpi .val small{font-size:13px}
.kpi svg{width:56px;height:30px;right:12px;top:14px}

.chart{padding:14px 16px 10px}
.nextapp{border-color:var(--accent);background:var(--sel-bg);color:var(--sel-ink)}
.nextapp .when{font:700 22px/1.2 var(--sans)}
.nextapp .who2{color:var(--ink)}
.nextapp .rel{background:var(--panel);color:var(--sel-ink);box-shadow:inset 0 0 0 1px var(--accent)}
.dayhead{font-weight:700;color:var(--ink)}
.stop{padding:10px 14px}
.stop .at{font:700 18px/1.2 var(--sans)}
.ledger li{padding:12px 16px}.ledger .num{font:700 22px/1.2 var(--sans)}
.speed{padding:20px}.speed h2{font:700 18px/1.2 var(--sans)}.bar-row .cap strong{font:700 18px/1 var(--sans)}

.chip{padding:5px 13px;font-size:14px;border-color:var(--field)}
.chip[aria-pressed="true"]{border-color:var(--ink)}
.calls{gap:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.calls>li{border:0;border-bottom:1px solid var(--line);border-radius:0;background:transparent}
.calls>li:last-child{border-bottom:0}
.calls>li:hover{box-shadow:none;background:var(--panel2);border-color:var(--line)}
.calls>li.urgent{border-left:3px solid var(--bad)}
.trow,.rowbtn{padding:10px 16px;font-size:14px}
.trow .t-subject{font-weight:700}
.t-stat{border-radius:6px;font-size:13px}
.say{border-radius:12px}
.tdetail,.transcript{background:var(--panel2)}
.tdetail{padding:12px 16px 18px;max-width:none}
.tdetail textarea{background:var(--panel)}
.empty{padding:16px}

@media (max-width:860px){
  #board{display:block}
  .tabs{position:sticky;top:0;z-index:5;flex-direction:row;overflow-x:auto;margin:0 0 14px;padding:6px;border-radius:12px;background:var(--panel)}
  .tab{width:auto;flex:0 0 auto;gap:8px}
  .tab-ink{display:none}
  .pulse{left:6px;right:6px}
  .kpi{flex:1 1 44%}
  .hero{grid-template-columns:minmax(0,1fr)}
  .top{padding:10px 12px}
}
.kpi .lbl{padding-right:62px}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="wordmark">JARVIS</span>
      <span class="who" id="company"></span>
    </div>
    <div class="tools" id="signedin" hidden>
      <label class="who" for="days">Show</label>
      <select id="days">
        <option value="1">last 24 hours</option>
        <option value="7" selected>last 7 days</option>
        <option value="30">last 30 days</option>
      </select>
      <button class="btn themebtn" id="theme" type="button" title="Switch between automatic, light and dark (T)">Theme: Auto</button>
      <button class="btn" id="refresh" type="button" title="Refresh now (R)">Refresh</button>
      <button class="btn" id="signout" type="button">Sign out</button>
    </div>
  </header>

  <section id="login" class="signin">
    <span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>
    <h1>Your phone line, at a glance.</h1>
    <p>Sign in to see today&rsquo;s calls, appointments and anything waiting for a person. Your sign-in stays in this tab only and is forgotten when you close it.</p>
    <div class="seg" role="group" aria-label="How to sign in">
      <button type="button" id="mode-user" aria-pressed="true">Sign in</button>
      <button type="button" id="mode-key" aria-pressed="false">Use a staff key</button>
    </div>
    <form id="userform" autocomplete="off">
      <label for="co" class="hidden">Company</label>
      <input id="co" type="text" placeholder="Company, for example smile-dental" autocomplete="off" spellcheck="false" required>
      <label for="email" class="hidden">Email</label>
      <input id="email" type="email" placeholder="Your email" autocomplete="off" required>
      <label for="password" class="hidden">Password</label>
      <input id="password" type="password" placeholder="Your password" autocomplete="off" required>
      <button class="btn main" type="submit">Sign in</button>
    </form>
    <form id="loginform" class="hidden" autocomplete="off">
      <label for="key" class="hidden">Staff key</label>
      <input id="key" type="password" placeholder="Staff key, starts with stf_" autocomplete="off" spellcheck="false" required>
      <button class="btn main" type="submit">Open dashboard</button>
    </form>
  </section>

  <div id="message" class="note hidden" role="alert"></div>

  <main id="board" class="hidden">
    <nav class="tabs" id="tabs" role="tablist" aria-label="Dashboard sections">
      <button class="tab" type="button" role="tab" id="tab-overview" data-tab="overview" aria-selected="true" aria-controls="p-overview">Overview<span class="cnt hidden" id="b-overview"></span></button>
      <button class="tab" type="button" role="tab" id="tab-tickets" data-tab="tickets" aria-selected="false" aria-controls="p-tickets" tabindex="-1">Tickets<span class="cnt hidden" id="b-tickets"></span></button>
      <button class="tab" type="button" role="tab" id="tab-appointments" data-tab="appointments" aria-selected="false" aria-controls="p-appointments" tabindex="-1">Appointments<span class="cnt hidden" id="b-appointments"></span></button>
      <button class="tab" type="button" role="tab" id="tab-work" data-tab="work" aria-selected="false" aria-controls="p-work" tabindex="-1">Open work<span class="cnt hidden" id="b-work"></span></button>
      <button class="tab" type="button" role="tab" id="tab-calls" data-tab="calls" aria-selected="false" aria-controls="p-calls" tabindex="-1">Calls<span class="cnt hidden" id="b-calls"></span></button>
      <button class="tab" type="button" role="tab" id="tab-speed" data-tab="speed" aria-selected="false" aria-controls="p-speed" tabindex="-1">Speed</button>
      <span class="tab-ink" id="ink" aria-hidden="true"></span><span class="pulse" id="pulse" aria-hidden="true"></span>
    </nav>

    <div class="panel" id="p-overview" role="tabpanel" aria-labelledby="tab-overview">
    <section class="hero">
      <div class="console">
        <p class="greet" id="greet"></p>
        <h1 id="headline"></h1>
        <p class="sub" id="subline"></p>
        <div class="lamps" id="lamps" aria-hidden="true"></div>
        <ul class="legend" id="legend"></ul>
        <p class="scale" id="scale"></p>
      </div>
      <aside class="needs">
        <h2>Needs a person</h2>
        <p class="hint">Things the AI could not finish on its own. Select one to open it.</p>
        <div id="attention"></div>
      </aside>
    </section>
    <section class="kpis" id="kpis" aria-label="Key numbers"></section>
    <section class="sect">
      <h2>Calls per day</h2>
      <div class="chart"><div id="trend"></div><p class="tip" id="trendtip" role="status"></p></div>
    </section>
    <section class="sect" id="nextsect">
      <h2>Next appointment</h2>
      <div id="nextapp"></div>
    </section>
    </div>

    <div class="panel hidden" id="p-tickets" role="tabpanel" aria-labelledby="tab-tickets">
    <section class="sect" id="tickets-section">
      <h2>Tickets</h2>
      <p class="hint">Requests and callbacks from your customers. Changing a status emails the customer.</p>
      <div class="toolrow"><input class="search" id="tsearch" type="search" placeholder="Search tickets (press /)" aria-label="Search tickets" autocomplete="off">
      <div class="filters" role="group" aria-label="Filter tickets">
        <button class="chip" type="button" id="t-open" aria-pressed="true">Waiting</button>
        <button class="chip" type="button" id="t-in_progress" aria-pressed="false">In progress</button>
        <button class="chip" type="button" id="t-resolved" aria-pressed="false">Resolved</button>
        <button class="chip" type="button" id="t-all" aria-pressed="false">All</button>
      </div></div>
      <p class="tstatus hidden" id="tnote" role="status"></p>
      <ul class="calls" id="tickets"></ul>
    </section>
    </div>

    <div class="panel hidden" id="p-appointments" role="tabpanel" aria-labelledby="tab-appointments">
      <section class="sect">
        <h2>Coming up</h2>
        <p class="hint" id="apphint"></p>
        <div id="appointments"></div>
      </section>
    </div>

    <div class="panel hidden" id="p-work" role="tabpanel" aria-labelledby="tab-work">
      <section class="sect">
        <h2>Open work</h2>
        <p class="hint">Tickets and unpaid invoices for your company.</p>
        <ul class="ledger" id="work"></ul>
      </section>
    </div>

    <div class="panel hidden" id="p-speed" role="tabpanel" aria-labelledby="tab-speed">
    <section class="speed">
      <h2>How fast callers get an answer</h2>
      <p class="verdict" id="verdict"></p>
      <div class="bars" id="bars"></div>
      <ul class="facts" id="facts"></ul>
    </section>
    </div>

    <div class="panel hidden" id="p-calls" role="tabpanel" aria-labelledby="tab-calls">
    <section class="sect">
      <h2>Recent calls</h2>
      <p class="hint">The 25 newest calls in this period. Select one to read what was said.</p>
      <div class="toolrow"><input class="search" id="csearch" type="search" placeholder="Search calls (press /)" aria-label="Search calls" autocomplete="off">
      <div class="filters" role="group" aria-label="Filter calls">
        <button class="chip" type="button" id="f-all" aria-pressed="true">All calls</button>
        <button class="chip" type="button" id="f-failed" aria-pressed="false">Broke down</button>
      </div></div>
      <ul class="calls" id="calls"></ul>
    </section>
    </div>
    <p class="foot" id="updated"></p>
    <p class="keys">Shortcuts: <kbd>1</kbd>&ndash;<kbd>6</kbd> sections, <kbd>R</kbd> refresh, <kbd>/</kbd> search, <kbd>T</kbd> theme.</p>
  </main>
</div>
<script nonce="__NONCE__">
"use strict";
var key = null, timer = null, busy = false, firstDraw = true, callFilter = "", opened = null, ticketFilter = "open", openTicket = null;
var $ = function (id) { return document.getElementById(id); };
var TABS = ["overview", "tickets", "appointments", "work", "calls", "speed"], tab = "overview";
function selectTab(name, focus) {
  if (TABS.indexOf(name) < 0) name = "overview";
  tab = name;
  TABS.forEach(function (t) {
    var on = t === name, btn = $("tab-" + t);
    btn.setAttribute("aria-selected", on ? "true" : "false"); btn.tabIndex = on ? 0 : -1;
    show($("p-" + t), on);
    if (on && focus) btn.focus();
  });
  moveInk();
  if (name === "overview" && lastData) { drawTrend(lastData); }
  if (name === "calls") { applySearch("calls", "csearch"); }
  if (name === "tickets") { applySearch("tickets", "tsearch"); }
}
function setBadge(name, n, kind) {
  var b = $("b-" + name);
  b.textContent = n; b.className = "cnt" + (kind ? " " + kind : "") + (n ? "" : " hidden");
}
function drawBadges(d) {
  var needs = d.attention.reduce(function (sum, a) { return sum + a.count; }, 0);
  setBadge("overview", needs, "bad");
  setBadge("tickets", d.tickets.open + d.tickets.in_progress, d.tickets.urgent_open > 0 ? "bad" : "");
  setBadge("appointments", d.appointments.next_7_days, "good");
  setBadge("work", d.tickets.urgent_open + d.invoices.unpaid_by_currency.reduce(function (sum, x) { return sum + x.count; }, 0), d.tickets.urgent_open > 0 ? "bad" : "");
  setBadge("calls", d.calls.by_outcome.failed, "bad");
}
TABS.forEach(function (t) {
  $("tab-" + t).addEventListener("click", function () { selectTab(t, false); });
  $("tab-" + t).addEventListener("keydown", function (e) {
    var i = TABS.indexOf(t), next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : null;
    if (next === null) return;
    e.preventDefault(); selectTab(TABS[(next + TABS.length) % TABS.length], true);
  });
});

var SVGNS = "http://www.w3.org/2000/svg", lastData = null, lastKpi = {}, themeMode = 0;
var THEMES = ["auto", "light", "dark"];
var REDUCED = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
function svg(tag, attrs, cls) {
  var n = document.createElementNS(SVGNS, tag);
  Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
  if (cls) n.setAttribute("class", cls);
  return n;
}
function moveInk() {
  var btn = $("tab-" + tab), ink = $("ink");
  if (!btn || !btn.offsetWidth) return;
  ink.style.setProperty("--x", btn.offsetLeft + "px"); ink.style.setProperty("--w", btn.offsetWidth + "px");
  if (btn.scrollIntoView && $("board").offsetParent !== null) { try { btn.scrollIntoView({block: "nearest", inline: "nearest"}); } catch (e) { /* older browsers */ } }
}
window.addEventListener("resize", function () { moveInk(); if (lastData && tab === "overview") drawTrend(lastData); });
function restartPulse() {
  var p = $("pulse"); p.classList.remove("run");
  if (REDUCED) return;
  void p.offsetWidth; p.classList.add("run");
}
function applyTheme() {
  var mode = THEMES[themeMode], root = document.documentElement;
  if (mode === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", mode);
  $("theme").textContent = "Theme: " + mode.charAt(0).toUpperCase() + mode.slice(1);
}
function cycleTheme() { themeMode = (themeMode + 1) % THEMES.length; applyTheme(); }
function countTo(node, to, fmtFn, memo) {
  fmtFn = fmtFn || String;
  var from = memo !== undefined && lastKpi[memo] !== undefined ? lastKpi[memo] : 0;
  if (memo !== undefined) lastKpi[memo] = to;
  if (REDUCED || from === to) { node.textContent = fmtFn(to); return; }
  var start = performance.now(), dur = 700;
  node.textContent = fmtFn(from);
  function step(now) {
    var pr = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - pr, 3);
    node.textContent = fmtFn(Math.round(from + (to - from) * e));
    if (pr < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
function greeting(name) {
  var h = new Date().getHours();
  return (h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening") + ", " + name;
}
function relTime(iso) {
  var m = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (m < -60) return "earlier";
  if (m <= 0) return "now";
  if (m < 60) return "in " + m + " min";
  if (m < 1440) return "in " + Math.round(m / 60) + " h";
  return "in " + Math.round(m / 1440) + (Math.round(m / 1440) === 1 ? " day" : " days");
}
function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function dayName(date) {
  var now = new Date(), tomorrow = new Date(now.getTime() + 86400000);
  if (sameDay(date, now)) return "Today";
  if (sameDay(date, tomorrow)) return "Tomorrow";
  return date.toLocaleDateString([], {weekday: "long", day: "numeric", month: "short"});
}
function go(name) { selectTab(name, false); window.scrollTo(0, 0); }

function kpi(spec) {
  var b = el("button", null, "kpi"); b.type = "button"; b.style.setProperty("--k", spec.color);
  b.setAttribute("aria-label", spec.label + ": " + spec.aria + ". Open " + spec.tab + ".");
  b.appendChild(el("span", spec.label, "lbl"));
  var v = el("span", null, "val"); b.appendChild(v);
  if (spec.value === null) v.textContent = "—"; else countTo(v, spec.value, spec.fmt, spec.key);
  b.appendChild(el("span", spec.sub, "note2"));
  if (spec.visual) b.appendChild(spec.visual);
  b.addEventListener("click", function () { go(spec.tab); if (spec.after) spec.after(); });
  return b;
}
function sparkline(values) {
  var s = svg("svg", {viewBox: "0 0 84 46"}), max = Math.max.apply(null, values.concat([1])), n = values.length, step = 84 / n, w = Math.max(2, step * 0.62);
  values.forEach(function (v, i) {
    var h = Math.max(2, (v / max) * 42);
    s.appendChild(svg("rect", {x: (i * step).toFixed(1), y: (44 - h).toFixed(1), width: w.toFixed(1), height: h.toFixed(1), rx: 1.5}, "sp" + (i === n - 1 ? " last" : "")));
  });
  return s;
}
function ring(pctValue) {
  var s = svg("svg", {viewBox: "0 0 84 46"}), C = 2 * Math.PI * 18;
  s.appendChild(svg("circle", {cx: 62, cy: 23, r: 18, fill: "none", "stroke-width": 5}, "ring-bg"));
  var arc = svg("circle", {cx: 62, cy: 23, r: 18, fill: "none", "stroke-width": 5, "stroke-linecap": "round", transform: "rotate(-90 62 23)", "stroke-dasharray": C.toFixed(1), "stroke-dashoffset": C.toFixed(1)}, "ring");
  s.appendChild(arc);
  requestAnimationFrame(function () { arc.setAttribute("stroke-dashoffset", (C * (1 - Math.min(100, pctValue) / 100)).toFixed(1)); });
  return s;
}
function drawKpis(d) {
  var box = $("kpis"); clear(box);
  var c = d.calls, t = d.tickets, a = d.appointments, sp = c.speed;
  var good = c.answered_without_trouble_pct;
  box.appendChild(kpi({key: "calls", tab: "calls", color: "var(--accent)", label: "Calls", value: c.total, aria: c.total + " calls",
    sub: plural(c.today, "call", "calls") + " today", visual: sparkline(d.trend.map(function (x) { return x.total; }))}));
  box.appendChild(kpi({key: "good", tab: "calls", color: good === null ? "var(--mute)" : good >= 90 ? "var(--ok)" : good >= 70 ? "var(--quit)" : "var(--bad)",
    label: "Answered smoothly", value: good, fmt: function (v) { return v + "%"; }, aria: good === null ? "no calls yet" : good + " percent",
    sub: good === null ? "No calls yet" : "without any trouble", visual: good === null ? null : ring(good)}));
  var waiting = t.open + t.in_progress;
  box.appendChild(kpi({key: "tickets", tab: "tickets", color: t.urgent_open > 0 ? "var(--bad)" : "var(--hand)", label: "Tickets waiting", value: waiting,
    aria: waiting + " tickets", sub: t.urgent_open > 0 ? plural(t.urgent_open, "urgent one", "urgent ones") : "None are urgent"}));
  var nextOne = a.upcoming.length ? a.upcoming[0] : null;
  box.appendChild(kpi({key: "apps", tab: "appointments", color: "var(--ok)", label: "Appointments today", value: a.today, aria: a.today + " appointments today",
    sub: nextOne ? "Next: " + fmt(nextOne.starts_at, {hour: "numeric", minute: "2-digit"}) : "Nothing booked soon"}));
  var avg = sp.avg_ms;
  box.appendChild(kpi({key: "speed", tab: "speed", color: avg === null ? "var(--mute)" : avg <= 2000 ? "var(--ok)" : avg <= 4000 ? "var(--quit)" : "var(--bad)",
    label: "Average wait", value: avg, fmt: function (v) { return (v / 1000).toFixed(1) + " s"; }, aria: avg === null ? "not measured" : secs(avg),
    sub: avg === null ? "No answers measured yet" : avg <= 2000 ? "Feels natural" : avg <= 4000 ? "A pause is noticeable" : "Callers will notice"}));
}

function drawTrend(d) {
  var host = $("trend"); clear(host);
  var data = d.trend, W = Math.max(300, host.clientWidth || 720), H = 190, left = 30, bottom = 24, top = 8, n = data.length;
  var max = Math.max.apply(null, data.map(function (x) { return x.total; }).concat([1]));
  var s = svg("svg", {width: W, height: H, role: "img", "aria-label": "Calls per day for the last " + n + " days"});
  [0, 0.5, 1].forEach(function (f) {
    var y = top + (H - bottom - top) * (1 - f);
    s.appendChild(svg("line", {x1: left, x2: W, y1: y, y2: y}, "grid"));
    var lab = svg("text", {x: left - 6, y: y + 4, "text-anchor": "end"}, "axis"); lab.textContent = Math.round(max * f); s.appendChild(lab);
  });
  var slot = (W - left) / n, bw = Math.min(38, slot * 0.62), tip = $("trendtip");
  function say(x) {
    var parts = ORDER.filter(function (k) { return x[k]; }).map(function (k) { return x[k] + " " + OUTCOME[k].legend.trim(); });
    tip.textContent = fmt(x.date + "T12:00:00", {weekday: "long", day: "numeric", month: "short"}) + ": " + (x.total ? plural(x.total, "call", "calls") + " (" + parts.join(", ") + ")" : "no calls");
  }
  data.forEach(function (x, i) {
    var cx = left + slot * i + slot / 2, g = svg("g", {tabindex: 0, role: "img", "aria-label": x.date + ": " + x.total + " calls"}, "col"), y = H - bottom;
    g.appendChild(svg("rect", {x: cx - slot / 2, y: top, width: slot, height: H - bottom - top}, "hit"));
    ORDER.forEach(function (k) {
      if (!x[k]) return;
      var h = (x[k] / max) * (H - bottom - top); y -= h;
      g.appendChild(svg("rect", {x: (cx - bw / 2).toFixed(1), y: y.toFixed(1), width: bw.toFixed(1), height: Math.max(1, h - 1).toFixed(1), rx: 3}, "seg c-" + k));
    });
    if (n <= 14 || i % 2 === 0) {
      var lab = svg("text", {x: cx, y: H - 6, "text-anchor": "middle"}, "axis");
      lab.textContent = new Date(x.date + "T12:00:00").toLocaleDateString([], n <= 7 ? {weekday: "short"} : {day: "numeric"}); g.appendChild(lab);
    }
    ["mouseenter", "focus", "click"].forEach(function (ev) { g.addEventListener(ev, function () { say(x); }); });
    s.appendChild(g);
  });
  host.appendChild(s);
  say(data[n - 1] || {date: new Date().toISOString().slice(0, 10), total: 0});
}

function drawNext(d) {
  var box = $("nextapp"); clear(box);
  var x = d.appointments.upcoming[0];
  if (!x) { box.appendChild(el("p", "Nothing is booked yet. New bookings made by phone show up here.", "empty")); return; }
  var b = el("button", null, "nextapp"); b.type = "button"; b.style.width = "100%"; b.style.textAlign = "left";
  b.appendChild(el("span", fmt(x.starts_at, {weekday: "long", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"}), "when"));
  b.appendChild(el("span", relTime(x.starts_at), "rel"));
  b.appendChild(el("span", (x.customer_name || "Unknown customer") + (x.reason ? ", " + x.reason : ""), "who2"));
  b.addEventListener("click", function () { go("appointments"); });
  box.appendChild(b);
}

function applySearch(listId, inputId) {
  var q = $(inputId).value.trim().toLowerCase(), list = $(listId), any = false, total = 0;
  Array.prototype.slice.call(list.querySelectorAll(".nomatch")).forEach(function (n) { list.removeChild(n); });
  Array.prototype.slice.call(list.children).forEach(function (li) {
    if (li.classList.contains("empty")) return;
    total++;
    var hit = !q || li.textContent.toLowerCase().indexOf(q) >= 0;
    li.classList.toggle("hidden", !hit); if (hit) any = true;
  });
  if (q && total && !any) list.appendChild(el("li", "Nothing matches “" + $(inputId).value.trim() + "”.", "empty nomatch"));
}

document.addEventListener("keydown", function (e) {
  if (!key || e.ctrlKey || e.metaKey || e.altKey) return;
  var tag = (e.target && e.target.tagName) || "";
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) { if (e.key === "Escape") e.target.blur(); return; }
  var n = Number(e.key);
  if (n >= 1 && n <= TABS.length) { selectTab(TABS[n - 1], false); return; }
  var k = e.key.toLowerCase();
  if (k === "r") { load(false, true); }
  else if (k === "t") { cycleTheme(); }
  else if (e.key === "/") {
    var box = tab === "tickets" ? $("tsearch") : tab === "calls" ? $("csearch") : null;
    if (box) { e.preventDefault(); box.focus(); }
  }
});
$("theme").addEventListener("click", cycleTheme);
$("tsearch").addEventListener("input", function () { applySearch("tickets", "tsearch"); });
$("csearch").addEventListener("input", function () { applySearch("calls", "csearch"); });
function setMode(user) {
  $("mode-user").setAttribute("aria-pressed", user ? "true" : "false"); $("mode-key").setAttribute("aria-pressed", user ? "false" : "true");
  show($("userform"), user); show($("loginform"), !user);
  $(user ? "co" : "key").focus();
}
$("mode-user").addEventListener("click", function () { setMode(true); });
$("mode-key").addEventListener("click", function () { setMode(false); });
var OUTCOME = {
  completed: {label: "Answered smoothly", lamp: "ok", legend: " answered smoothly"},
  handoff: {label: "Passed to a person", lamp: "hand", legend: " passed to a person"},
  abandoned: {label: "Hung up before speaking", lamp: "quit", legend: " hung up before speaking"},
  failed: {label: "Broke down", lamp: "bad", legend: " broke down"}
};
var ORDER = ["completed", "handoff", "abandoned", "failed"];
var NEEDS = {
  urgent_tickets: {bad: false, tab: "tickets", text: "urgent tickets or callback requests are waiting for you."},
  failed_calls: {bad: true, tab: "calls", after: function () { setFilter("failed"); }, text: "calls broke down, so the caller may not have been helped. Open them to see what happened."},
  failed_notifications: {bad: false, tab: "tickets", text: "notifications could not be sent. Ask your admin to check email and n8n."}
};

function el(tag, text, cls) {
  var node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function show(node, on) { node.classList.toggle("hidden", !on); }
function message(text, kind) {
  var box = $("message"); box.textContent = text || "";
  box.className = "note" + (kind === "error" ? " error" : "") + (text ? "" : " hidden");
}
function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
function secs(ms) { return ms === null || ms === undefined ? "none yet" : (ms / 1000).toFixed(1) + " s"; }
function pct(v) { return v === null || v === undefined ? "none yet" : v + "%"; }
function fmt(iso, opts) { try { return new Date(iso).toLocaleString([], opts); } catch (e) { return iso; } }
function money(minor, currency) {
  try { return new Intl.NumberFormat([], {style: "currency", currency: currency}).format(minor / 100); }
  catch (e) { return (minor / 100).toFixed(2) + " " + currency; }
}
function dayWord(n) { return n === 1 ? "the last 24 hours" : "the last " + n + " days"; }

function api(path, method, body) {
  var headers = {"X-API-Key": key};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  var init = {method: method || "GET", headers: headers, cache: "no-store", credentials: "omit"};
  if (body !== undefined) init.body = JSON.stringify(body);
  return fetch(path, init).then(function (r) {
    if (r.status === 404 || r.status === 409) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        throw new Error(typeof j.detail === "string" ? j.detail : "That could not be done.");
      });
    }
    if (r.status === 401) throw new Error("That staff key is not valid. Check it, or ask your admin for a new one.");
    if (r.status === 403) throw new Error("This company is switched off. Ask your admin to turn it back on.");
    if (r.status === 429) throw new Error("Too many requests. Wait a minute, then press Refresh.");
    if (!r.ok) throw new Error("The server answered " + r.status + ". Press Refresh in a moment.");
    return r.json();
  });
}

function drawHero(d) {
  var c = d.calls, total = c.total;
  $("headline").textContent = total === 0 ? "No calls yet." : plural(total, "call", "calls") + " in " + dayWord(c.days) + ".";
  $("subline").textContent = total === 0
    ? "Calls appear here a few seconds after they end."
    : pct(c.answered_without_trouble_pct) + " were answered without trouble. " + plural(c.today, "call", "calls") + " came in today.";

  var lamps = $("lamps"); clear(lamps);
  var per = Math.max(1, Math.ceil(total / 60)), index = 0;
  ORDER.forEach(function (name) {
    var n = c.by_outcome[name];
    var count = n ? Math.max(1, Math.round(n / per)) : 0;
    for (var i = 0; i < count; i++) {
      var lamp = el("span", null, "lamp " + OUTCOME[name].lamp);
      lamp.style.animationDelay = (index++ * 22) + "ms";
      lamps.appendChild(lamp);
    }
  });
  $("scale").textContent = per > 1 ? "Each lamp stands for about " + per + " calls." : "";
  var legend = $("legend"); clear(legend);
  ORDER.forEach(function (name) {
    var li = el("li"); li.appendChild(el("span", null, "lamp " + OUTCOME[name].lamp));
    var b = el("strong", c.by_outcome[name]); li.appendChild(b); li.appendChild(document.createTextNode(OUTCOME[name].legend));
    legend.appendChild(li);
  });
}

function drawNeeds(d) {
  var box = $("attention"); clear(box);
  if (!d.attention.length) {
    var ok = el("div", null, "clear"); ok.appendChild(el("span", null, "lamp ok")); ok.appendChild(el("span", "Nothing needs you right now."));
    box.appendChild(ok); return;
  }
  d.attention.forEach(function (a) {
    var spec = NEEDS[a.kind] || {bad: false, text: a.message};
    var row = el("button", null, "need" + (spec.bad ? " bad" : "")); row.type = "button";
    row.appendChild(el("b", a.count)); row.appendChild(el("span", spec.text)); row.appendChild(el("span", "\u203a", "go"));
    row.addEventListener("click", function () { go(spec.tab); if (spec.after) spec.after(); });
    box.appendChild(row);
  });
}

function drawAppointments(d) {
  var a = d.appointments;
  $("apphint").textContent = plural(a.today, "appointment", "appointments") + " today, " + a.next_7_days + " in the next 7 days.";
  var box = $("appointments"); clear(box);
  if (!a.upcoming.length) { box.appendChild(el("p", "Nothing booked yet. New bookings made by phone show up here.", "empty")); return; }
  var current = null, list = null;
  a.upcoming.forEach(function (x) {
    var when = new Date(x.starts_at), label = dayName(when);
    if (label !== current) { current = label; box.appendChild(el("h3", label, "dayhead")); list = el("ol", null, "line"); box.appendChild(list); }
    var mins = Math.round((when.getTime() - Date.now()) / 60000);
    var li = el("li", null, "stop" + (mins >= -30 && mins <= 60 ? " soon" : ""));
    li.appendChild(el("div", fmt(x.starts_at, {hour: "numeric", minute: "2-digit"}), "at"));
    li.appendChild(el("div", (x.customer_name || "Unknown customer") + (x.reason ? ", " + x.reason : ""), "what"));
    li.appendChild(el("div", relTime(x.starts_at), "rel"));
    list.appendChild(li);
  });
}

function drawWork(d) {
  var t = d.tickets, work = $("work"); clear(work);
  function row(label, value, bad) {
    var li = el("li"); li.appendChild(el("span", label)); li.appendChild(el("span", value, "num" + (bad ? " bad" : ""))); work.appendChild(li);
  }
  row("Open tickets", t.open); row("Tickets being worked on", t.in_progress);
  row("Urgent tickets", t.urgent_open, t.urgent_open > 0); row("Tickets opened today", t.created_today);
  if (!d.invoices.unpaid_by_currency.length) row("Unpaid invoices", "None");
  d.invoices.unpaid_by_currency.forEach(function (x) {
    var li = el("li"); li.appendChild(el("span", plural(x.count, "unpaid invoice", "unpaid invoices") + " in " + x.currency));
    li.appendChild(el("span", money(x.total_minor, x.currency), "num")); work.appendChild(li);
  });
}

function bar(label, ms, max, cls) {
  var wrap = el("div", null, "bar-row"), cap = el("div", null, "cap");
  cap.appendChild(el("span", label)); cap.appendChild(el("strong", secs(ms))); wrap.appendChild(cap);
  var track = el("div", null, "track"), fill = el("div", null, "fill " + cls);
  fill.style.width = Math.min(100, Math.max(2, (ms / max) * 100)) + "%"; track.appendChild(fill);
  var at = (3000 / max) * 100;
  if (at <= 100) {
    var tick = el("div", null, "tick"); tick.style.left = at + "%"; track.appendChild(tick);
    var tl = el("div", "3 s", "tick-label"); tl.style.left = at + "%"; track.appendChild(tl);
  }
  wrap.appendChild(track); return wrap;
}

function drawSpeed(d) {
  var s = d.calls.speed, bars = $("bars"), facts = $("facts"); clear(bars); clear(facts);
  if (s.avg_ms === null) {
    $("verdict").textContent = "No answers measured yet. Make a test call, and the timings appear here.";
    return;
  }
  var avg = s.avg_ms;
  $("verdict").textContent = avg <= 2000 ? "Callers get a reply quickly. This feels natural on the phone."
    : avg <= 4000 ? "Replies are acceptable, but a pause is noticeable. A faster AI model would help."
    : "Replies are slow and callers will notice. Ask your admin to try a faster AI model.";
  var max = Math.max(6000, avg, s.p95_ms || 0, s.avg_llm_real_ms || 0);
  bars.appendChild(bar("Callers waited on average", avg, max, avg > 4000 ? "slow" : ""));
  if (s.p95_ms !== null) bars.appendChild(bar("Callers waited in the slowest 5% of answers", s.p95_ms, max, s.p95_ms > 6000 ? "slow" : ""));
  if (s.avg_llm_real_ms !== null) bars.appendChild(bar("The AI model itself needed", s.avg_llm_real_ms, max, "model"));
  [["Heard “One moment please”", pct(s.filler_pct)], ["Backup model had to answer", pct(s.switched_pct)], ["Answers measured", s.turns]].forEach(function (f) {
    var li = el("li"); li.appendChild(document.createTextNode(f[0] + ": ")); li.appendChild(el("strong", f[1])); facts.appendChild(li);
  });
}

function drawCalls(all, days) {
  var cutoff = Date.now() - days * 86400000;     // keep the log in step with the range chosen above
  var recent = all.filter(function (x) { return new Date(x.started_at).getTime() >= cutoff; }).slice(0, 25);
  var list = $("calls"); clear(list); opened = null;
  if (!recent.length) { list.appendChild(el("li", callFilter ? "No calls broke down in " + dayWord(days) + "." : "No calls in " + dayWord(days) + ". Make a test call and it appears here.", "empty")); return; }
  recent.forEach(function (x) {
    var li = el("li"), spec = OUTCOME[x.outcome] || {label: x.outcome, lamp: "quit"};
    var btn = el("button", null, "rowbtn"); btn.type = "button"; btn.setAttribute("aria-expanded", "false");
    btn.appendChild(el("span", fmt(x.started_at, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}), "c-when"));
    btn.appendChild(el("span", x.customer_name || x.caller_phone || (x.direction === "inbound" ? "Caller" : "Web test"), "c-who who2"));
    var out = el("span", null, "c-out badge"); out.appendChild(el("i")); out.firstChild.style.background = "var(--" + spec.lamp + ")"; out.appendChild(el("span", spec.label)); btn.appendChild(out);
    btn.appendChild(el("span", x.duration_seconds + " s", "c-len mutes"));
    btn.appendChild(el("span", x.latency && x.latency.avg_ms !== null && x.latency.avg_ms !== undefined ? (x.latency.avg_ms / 1000).toFixed(1) + " s wait" : "", "c-wait mutes"));
    var slot = el("div", null, "transcript hidden");
    btn.addEventListener("click", function () { toggleCall(x.id, btn, slot); });
    li.appendChild(btn); li.appendChild(slot); list.appendChild(li);
  });
  applySearch("calls", "csearch");
}

function toggleCall(id, btn, slot) {
  var isOpen = btn.getAttribute("aria-expanded") === "true";
  if (isOpen) { btn.setAttribute("aria-expanded", "false"); show(slot, false); return; }
  api("/staff/calls/" + encodeURIComponent(id)).then(function (c) {
    clear(slot);
    var tools = (c.tools_used || []).map(function (t) { return t.name.replace(/_/g, " ") + (t.ok ? "" : " (failed)"); }).join(", ");
    slot.appendChild(el("p", "Tools used: " + (tools || "none"), "tools-used"));
    (c.transcript || []).forEach(function (l) {
      var bubble = el("div", null, "say " + l.role);
      bubble.appendChild(el("small", l.role === "user" ? "Caller" : "Assistant")); bubble.appendChild(document.createTextNode(l.text));
      slot.appendChild(bubble);
    });
    if (!(c.transcript || []).length) slot.appendChild(el("p", "Nothing was said on this call.", "tools-used"));
    btn.setAttribute("aria-expanded", "true"); show(slot, true);
  }).catch(function (e) { message(e.message, "error"); });
}


var STATUS_WORD = {open: "Waiting", in_progress: "In progress", resolved: "Resolved", closed: "Closed"};
function emailWord(t) {
  if (t.update_email === "sent") return ["Customer emailed", "sent"];
  if (t.update_email === "pending") return ["Sending email\u2026", ""];
  if (t.update_email === "failed") return ["Email failed", "failed"];
  return ["", ""];
}
function ticketNote(text, kind) { var n = $("tnote"); n.textContent = text; n.className = "tstatus" + (kind ? " " + kind : "") + (text ? "" : " hidden"); }
function anyOpen(id) { return !!$(id).querySelector('[aria-expanded="true"]'); }

function drawTickets(list) {
  var box = $("tickets"); clear(box);
  if (!list.length) {
    var word = ticketFilter === "all" ? "" : (STATUS_WORD[ticketFilter] || "").toLowerCase() + " ";
    box.appendChild(el("li", "No " + word + "tickets right now.", "empty")); return;
  }
  list.forEach(function (t) {
    var li = el("li", null, t.priority === "urgent" ? "urgent" : ""), btn = el("button", null, "trow"); btn.type = "button"; btn.setAttribute("aria-expanded", "false");
    btn.appendChild(el("span", "#" + t.id, "t-id mutes"));
    btn.appendChild(el("span", t.subject, "t-subject"));
    btn.appendChild(el("span", t.customer_name || t.customer_phone || "No customer linked", "t-cust"));
    btn.appendChild(el("span", t.priority, "t-prio" + (t.priority === "urgent" ? " prio-urgent" : " mutes")));
    btn.appendChild(el("span", STATUS_WORD[t.status] || t.status, "t-stat s-" + t.status));
    var ew = emailWord(t); btn.appendChild(el("span", ew[0], "t-mail est " + ew[1]));
    var slot = el("div", null, "tdetail hidden");
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      openTicket = open ? null : t.id;
      if (!open) buildTicketDetail(t, slot);
      show(slot, !open);
    });
    li.appendChild(btn); li.appendChild(slot); box.appendChild(li);
    if (openTicket === t.id) { btn.setAttribute("aria-expanded", "true"); buildTicketDetail(t, slot); show(slot, true); }   // a redraw keeps the ticket open
  });
  applySearch("tickets", "tsearch");
}

function buildTicketDetail(t, slot) {
  clear(slot);
  slot.appendChild(el("p", t.description, "desc"));
  var who = (t.customer_name || "No customer linked") + (t.customer_phone ? ", " + t.customer_phone : "") + (t.customer_email ? ", " + t.customer_email : "");
  slot.appendChild(el("p", "Customer: " + who + ". Opened " + fmt(t.created_at, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) + ".", "meta"));
  var status = el("p", null, "tstatus hidden"); status.setAttribute("role", "status");
  function say(text, kind) { status.textContent = text; status.className = "tstatus" + (kind ? " " + kind : "") + (text ? "" : " hidden"); }

  if (t.status === "closed") { slot.appendChild(el("p", "This ticket is closed and cannot be changed.", "meta")); return; }
  if (!t.customer_email) say("This customer has no email address, so a status change cannot be emailed. Phone them instead.", "warn");
  else if (t.update_email === "failed") say("The last status email did not go out. Press \u201cSend the email again\u201d.", "bad");

  var label = el("label", "Note for the customer and the team (optional)"); label.htmlFor = "note-" + t.id;
  var note = el("textarea"); note.id = "note-" + t.id; note.maxLength = 1000;
  slot.appendChild(label); slot.appendChild(note);
  var acts = el("div", null, "acts"), buttons = [];
  function lock(on) { buttons.forEach(function (b) { b.disabled = on; }); }
  function change(newStatus, done) {
    lock(true);
    api("/staff/tickets/" + encodeURIComponent(t.id), "PATCH", {status: newStatus, note: note.value.trim() || null}).then(function (r) {
      var tail = r.ticket.customer_email ? " An email to " + r.ticket.customer_email + " is on its way." : " No email was sent because there is no address on file.";
      var done = "Ticket #" + t.id + " is now " + (STATUS_WORD[r.ticket.status] || r.ticket.status).toLowerCase() + "." + tail;
      say(done, r.ticket.customer_email ? "" : "warn"); ticketNote(done, r.ticket.customer_email ? "" : "warn");
      setTimeout(function () { refreshTickets(); }, 2500);
      busy = false; load(false, true);
    }).catch(function (e) { say(e.message, "bad"); lock(false); });
  }
  function add(text, cls, fn) { var b = el("button", text, "btn " + cls); b.type = "button"; b.addEventListener("click", fn); acts.appendChild(b); buttons.push(b); return b; }
  if (t.status === "open") add("Start work", "", function () { change("in_progress"); });
  if (t.status === "open" || t.status === "in_progress") add("Mark resolved", "main", function () { change("resolved"); });
  if (t.status === "resolved") {
    var closer = add("Close ticket", "warn", function () {
      if (closer.dataset.sure !== "yes") { closer.dataset.sure = "yes"; closer.textContent = "Press again to close for good"; return; }
      change("closed");
    });
  }
  if (t.update_email === "failed") add("Send the email again", "", function () {
    lock(true);
    api("/staff/tickets/" + encodeURIComponent(t.id) + "/resend-email", "POST", {}).then(function () {
      say("Sending the email again\u2026"); ticketNote("Ticket #" + t.id + ": sending the email again.", ""); setTimeout(function () { refreshTickets(); }, 2500);
    }).catch(function (e) { say(e.message, "bad"); lock(false); });
  });
  slot.appendChild(acts); slot.appendChild(status);
}

function ticketsUrl() { return "/staff/tickets" + (ticketFilter === "all" ? "" : "?status=" + ticketFilter); }
function refreshTickets() { if (!key) return; api(ticketsUrl()).then(drawTickets).catch(function (e) { message(e.message, "error"); }); }
function setTicketFilter(value) {
  ticketFilter = value; openTicket = null;
  ["open", "in_progress", "resolved", "all"].forEach(function (v) { $("t-" + v).setAttribute("aria-pressed", v === value ? "true" : "false"); });
  refreshTickets();
}

function load(auto, force) {
  if (!key || busy) return;
  busy = true;
  var days = $("days").value;
  var callsUrl = "/staff/calls?limit=100" + (callFilter ? "&outcome=" + callFilter : "");
  if (firstDraw) message("Loading your dashboard…");
  Promise.all([api("/staff/dashboard?days=" + encodeURIComponent(days)), api(callsUrl), api(ticketsUrl())])
    .then(function (r) {
      message("");
      $("company").textContent = r[0].company.name;
      show($("login"), false); show($("board"), true); $("signedin").hidden = false;
      $("board").classList.toggle("intro", firstDraw);
      lastData = r[0];
      $("greet").textContent = greeting(r[0].company.name);
      drawHero(r[0]); drawNeeds(r[0]); drawKpis(r[0]); drawTrend(r[0]); drawNext(r[0]); drawAppointments(r[0]); drawWork(r[0]); drawSpeed(r[0]); drawBadges(r[0]);
      restartPulse();
      if (firstDraw) selectTab("overview", false);
      // The 30-second refresh must never close a ticket or call someone is reading, or wipe a note being typed.
      if (!auto || !anyOpen("calls")) drawCalls(r[1], Number(days));
      if (!force && (!auto || !anyOpen("tickets"))) drawTickets(r[2]);
      firstDraw = false;
      $("updated").textContent = "Updated " + new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) + ". This page refreshes every 30 seconds.";
    })
    .catch(function (e) { message(e.message, "error"); if (/not valid|switched off|Too many/.test(e.message)) stop(true); })
    .then(function () { busy = false; });
}
function stop(forget) {
  if (timer) { clearInterval(timer); timer = null; }
  if (forget) { key = null; firstDraw = true; show($("board"), false); show($("login"), true); $("signedin").hidden = true; $("company").textContent = ""; selectTab("overview", false); lastData = null; lastKpi = {}; }
}
function setFilter(value) {
  callFilter = value;
  $("f-all").setAttribute("aria-pressed", value ? "false" : "true");
  $("f-failed").setAttribute("aria-pressed", value ? "true" : "false");
  busy = false; load();
}
$("userform").addEventListener("submit", function (e) {
  e.preventDefault();
  var body = JSON.stringify({company: $("co").value.trim(), email: $("email").value.trim(), password: $("password").value});
  $("password").value = "";
  fetch("/staff/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: body})
    .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, status: r.status, data: d}; }); })
    .then(function (res) {
      if (!res.ok) { message(res.status === 429 ? "Too many wrong passwords. Try again in a few minutes." : "Wrong company, email or password.", "error"); return; }
      message(""); key = res.data.token; load();
      if (!timer) timer = setInterval(function () { load(true); }, 30000);
    })
    .catch(function () { message("Could not reach the server. Try again.", "error"); });
});
$("loginform").addEventListener("submit", function (e) {
  e.preventDefault();
  key = $("key").value.trim(); $("key").value = "";
  if (!key) return;
  load();
  if (!timer) timer = setInterval(function () { load(true); }, 30000);
});
$("refresh").addEventListener("click", function () { load(); });
$("days").addEventListener("change", function () { load(); });
["open", "in_progress", "resolved", "all"].forEach(function (v) { $("t-" + v).addEventListener("click", function () { setTicketFilter(v); }); });
$("f-all").addEventListener("click", function () { setFilter(""); });
$("f-failed").addEventListener("click", function () { setFilter("failed"); });
$("signout").addEventListener("click", function () {
  if (key && key.indexOf("stu_") === 0) { fetch("/staff/logout", {method: "POST", headers: {"X-API-Key": key}}).catch(function () {}); }
  stop(true); message("");
});
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page():
    nonce = secrets.token_urlsafe(16)
    headers = {
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        ),
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    return HTMLResponse(PAGE.replace("__NONCE__", nonce), headers=headers)
