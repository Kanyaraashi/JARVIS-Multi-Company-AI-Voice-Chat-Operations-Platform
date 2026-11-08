"""The staff dashboard web page (Step 27): GET /dashboard.

The page itself contains no company data and no key. The person types their staff key into the
page; it is kept only in that browser tab's memory (never in the address, never saved on disk)
and is sent only to this same server. Everything shown comes from the Step 26 endpoint.

Design: a front-desk board. "What needs a person" comes first, the day's appointments sit beside
it like an appointment book, and the call chart is drawn as a waveform, because calls are voice.
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
/* Palette: the lamps of an old telephone switchboard on deep green-grey. */
:root{
  --bg:#e8efeb; --panel:#f8faf9; --ink:#0f2b2a; --mute:#566f6b; --line:#c9d8d2; --accent:#0f6f6a;
  --night:#0f2b2a; --night-ink:#e6f2ee; --night-mute:#93b0aa; --night-line:#2b4b48;
  --ok:#1b9a5f; --hand:#2f6fd6; --quit:#c98a12; --bad:#d6453a; --bad-bg:#fbe9e6; --warn-bg:#fdf1d8;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0a1a1a; --panel:#10282a; --ink:#e6f2ee; --mute:#8fb0aa; --line:#25403f; --accent:#5fd0c6;
  --night:#06100f; --night-ink:#e6f2ee; --night-mute:#8fb0aa; --night-line:#25403f;
  --ok:#3ddc97; --hand:#6ea2ff; --quit:#ffbf47; --bad:#ff7a6b; --bad-bg:#3a1b1a; --warn-bg:#3a2c10;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--sans);font-variant-numeric:tabular-nums}
.hidden{display:none!important}
.wrap{max-width:1160px;margin:0 auto;padding:0 16px}

/* top bar */
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;justify-content:space-between;padding:16px 0}
.brand{display:flex;align-items:center;gap:12px}
.mark{display:flex;gap:4px}
.mark i{width:10px;height:10px;border-radius:50%;display:block}
.mark i:nth-child(1){background:var(--ok)}.mark i:nth-child(2){background:var(--quit)}.mark i:nth-child(3){background:var(--bad)}
.wordmark{font:600 22px/1 var(--serif);letter-spacing:.01em}
.who{color:var(--mute);font-size:15px}
.tools[hidden]{display:none}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
select,input,button{font:inherit;color:inherit}
select,input{padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.btn{padding:9px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);cursor:pointer}
.btn:hover{border-color:var(--accent)}
.btn.main{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){.btn.main{color:#06100f}}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

/* sign in */
.signin{max-width:520px;margin:9vh auto 0;padding:0 4px}
.signin h1{font:500 clamp(30px,6vw,44px)/1.08 var(--serif);margin:18px 0 10px}
.signin p{color:var(--mute);margin:0 0 20px;max-width:46ch}
.signin form{display:flex;flex-wrap:wrap;gap:10px}
.signin input{flex:1;min-width:220px}

/* messages */
.note{margin:0 0 14px;padding:11px 14px;border-radius:10px;background:var(--warn-bg);border-left:4px solid var(--quit)}
.note.error{background:var(--bad-bg);border-left-color:var(--bad)}

/* hero: the sentence is the design */
.hero{display:grid;gap:28px;grid-template-columns:minmax(0,7fr) minmax(0,5fr);padding:14px 0 30px;align-items:start}
.hero h1{font:500 clamp(34px,5.2vw,62px)/1.04 var(--serif);margin:0 0 6px;letter-spacing:-.01em;max-width:14ch}
.hero .sub{color:var(--mute);font-size:18px;margin:0 0 22px;max-width:44ch}
.lamps{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px;max-width:560px}
.lamp{width:16px;height:16px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,currentColor 18%,transparent)}
.lamp.ok{background:var(--ok);color:var(--ok)}.lamp.hand{background:var(--hand);color:var(--hand)}
.lamp.quit{background:var(--quit);color:var(--quit)}.lamp.bad{background:var(--bad);color:var(--bad)}
.intro .lamp{animation:lampon .5s ease-out both}
@keyframes lampon{from{opacity:.1;transform:scale(.5)}to{opacity:1;transform:scale(1)}}
.legend{display:flex;flex-wrap:wrap;gap:6px 22px;margin:0;padding:0;list-style:none;font-size:15px}
.legend li{display:flex;align-items:center;gap:8px}
.legend .lamp{width:10px;height:10px;box-shadow:none}
.legend strong{font-weight:650}
.scale{color:var(--mute);font-size:14px;margin:8px 0 0}

/* needs a person */
.needs{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}
.needs h2,.sect h2{font:600 22px/1.2 var(--serif);margin:0 0 4px}
.needs .hint{color:var(--mute);margin:0 0 14px;font-size:15px}
.need{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;align-items:baseline;padding:12px 14px;margin-top:8px;border-radius:10px;background:var(--warn-bg);border-left:4px solid var(--quit)}
.need.bad{background:var(--bad-bg);border-left-color:var(--bad)}
.need b{font:600 30px/1 var(--serif)}
.clear{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:10px;background:color-mix(in srgb,var(--ok) 14%,transparent)}

/* sections */
.cols{display:grid;gap:36px;grid-template-columns:minmax(0,1fr) minmax(0,1fr);padding:6px 0 10px}
.sect{margin-bottom:34px}
.sect .hint{color:var(--mute);margin:0 0 14px;font-size:15px}
.ledger{list-style:none;margin:0;padding:0}
.ledger li{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-top:1px solid var(--line)}
.ledger li:last-child{border-bottom:1px solid var(--line)}
.ledger .num{font:600 20px/1.2 var(--serif)}
.ledger .num.bad{color:var(--bad)}
.money{display:block;text-align:right}

/* appointment timeline */
.line{list-style:none;margin:0;padding:0 0 0 22px;border-left:2px solid var(--line)}
.stop{position:relative;padding:0 0 18px 4px}
.stop::before{content:"";position:absolute;left:-29px;top:6px;width:12px;height:12px;border-radius:50%;background:var(--bg);border:3px solid var(--accent)}
.stop .at{font:600 20px/1.2 var(--serif)}
.stop .what{color:var(--mute);overflow-wrap:anywhere}

/* speed: the one dark panel */
.speed{background:var(--night);color:var(--night-ink);border-radius:18px;padding:24px;margin:6px 0 40px}
.speed h2{font:600 24px/1.2 var(--serif);margin:0 0 4px}
.speed .verdict{color:var(--night-mute);margin:0 0 22px;max-width:60ch}
.bars{display:grid;gap:34px;grid-template-columns:minmax(0,1fr)}
.bar-row .cap{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px}
.bar-row .cap span{color:var(--night-mute)}
.bar-row .cap strong{font:600 20px/1 var(--serif);white-space:nowrap}
.track{position:relative;height:14px;border-radius:7px;background:var(--night-line)}
.fill{position:absolute;left:0;top:0;bottom:0;border-radius:7px;background:var(--ok);min-width:6px}
.fill.slow{background:var(--quit)}.fill.model{background:var(--hand)}
.tick{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--night-ink);opacity:.7}
.tick-label{position:absolute;top:20px;transform:translateX(-50%);font-size:12px;color:var(--night-mute);white-space:nowrap}
.facts{display:flex;flex-wrap:wrap;gap:8px 32px;margin:26px 0 0;padding:16px 0 0;border-top:1px solid var(--night-line);list-style:none}
.facts li{color:var(--night-mute)}.facts strong{color:var(--night-ink);font-weight:650}


/* tickets */
.trow{display:grid;grid-template-columns:48px minmax(0,1.7fr) minmax(0,1fr) 84px 140px 150px;gap:10px;align-items:center;width:100%;padding:13px 6px;border:0;background:transparent;text-align:left;cursor:pointer}
.trow:hover{background:color-mix(in srgb,var(--accent) 7%,transparent)}
.trow .t-subject{font-weight:600;overflow-wrap:anywhere}
.prio-urgent{color:var(--bad);font-weight:650}
.est{font-size:14px}.est.failed{color:var(--bad);font-weight:600}.est.sent{color:var(--ok)}
.tdetail{padding:6px 6px 22px;max-width:760px}
.tdetail .desc{margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.tdetail .meta{color:var(--mute);margin:0 0 14px;font-size:15px;overflow-wrap:anywhere}
.tdetail label{display:block;font-weight:600;margin:0 0 6px}
.tdetail textarea{width:100%;min-height:76px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);font:inherit;color:inherit;resize:vertical}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.btn.warn{border-color:var(--bad);color:var(--bad)}
.btn[disabled]{opacity:.55;cursor:wait}
.tstatus{margin:12px 0 0;padding:9px 12px;border-radius:8px;background:color-mix(in srgb,var(--ok) 14%,transparent)}
.tstatus.bad{background:var(--bad-bg)}
.tstatus.warn{background:var(--warn-bg)}

/* call log */
.filters{display:flex;gap:8px;margin:0 0 12px;flex-wrap:wrap}
.chip{padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:transparent;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.calls{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.calls>li{border-bottom:1px solid var(--line)}
.rowbtn{display:grid;grid-template-columns:150px minmax(0,1.4fr) minmax(0,1fr) 70px 80px;gap:10px;align-items:center;width:100%;padding:13px 6px;border:0;background:transparent;text-align:left;cursor:pointer}
.rowbtn:hover{background:color-mix(in srgb,var(--accent) 7%,transparent)}
.rowbtn .who2{overflow-wrap:anywhere}
.badge{display:inline-flex;align-items:center;gap:8px}
.badge i{width:10px;height:10px;border-radius:50%;display:block}
.mutes{color:var(--mute)}
.transcript{padding:6px 6px 20px}
.transcript .tools-used{color:var(--mute);margin:0 0 10px;font-size:15px}
.say{max-width:min(620px,92%);padding:9px 13px;border-radius:14px;margin:6px 0;overflow-wrap:anywhere}
.say.user{background:var(--panel);border:1px solid var(--line);border-top-left-radius:4px}
.say.assistant{background:var(--accent);color:#fff;margin-left:auto;border-top-right-radius:4px}
@media (prefers-color-scheme:dark){.say.assistant{color:#06100f}}
.say small{display:block;opacity:.75;font-size:12px;margin-bottom:2px}
.empty{color:var(--mute);padding:14px 0}
.foot{color:var(--mute);font-size:14px;padding:6px 0 40px}

@media (max-width:860px){
  .trow{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"subj stat" "cust prio" "mail mail"}
  .trow .t-id{display:none}.trow .t-subject{grid-area:subj}.trow .t-cust{grid-area:cust}
  .trow .t-prio{grid-area:prio;justify-self:end}.trow .t-stat{grid-area:stat;justify-self:end}.trow .t-mail{grid-area:mail}
  .hero,.cols{grid-template-columns:minmax(0,1fr)}
  .cols{gap:6px}
  .rowbtn{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"who badge" "when len"}
  .rowbtn .c-when{grid-area:when}.rowbtn .c-who{grid-area:who}.rowbtn .c-out{grid-area:badge;justify-self:end}
  .rowbtn .c-len{grid-area:len;justify-self:end}.rowbtn .c-wait{display:none}.rowbtn .c-head{display:none}
}
@media (prefers-reduced-motion:reduce){.intro .lamp{animation:none}}
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
      <button class="btn" id="refresh" type="button">Refresh</button>
      <button class="btn" id="signout" type="button">Sign out</button>
    </div>
  </header>

  <section id="login" class="signin">
    <span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>
    <h1>Your phone line, at a glance.</h1>
    <p>Enter your staff key to see today&rsquo;s calls, appointments and anything waiting for a person. The key stays in this tab only and is forgotten when you close it.</p>
    <form id="loginform" autocomplete="off">
      <label for="key" class="hidden">Staff key</label>
      <input id="key" type="password" placeholder="Staff key, starts with stf_" autocomplete="off" spellcheck="false" required>
      <button class="btn main" type="submit">Open dashboard</button>
    </form>
  </section>

  <div id="message" class="note hidden" role="alert"></div>

  <main id="board" class="hidden">
    <section class="hero">
      <div>
        <h1 id="headline"></h1>
        <p class="sub" id="subline"></p>
        <div class="lamps" id="lamps" aria-hidden="true"></div>
        <ul class="legend" id="legend"></ul>
        <p class="scale" id="scale"></p>
      </div>
      <aside class="needs">
        <h2>Needs a person</h2>
        <p class="hint">Things the AI could not finish on its own.</p>
        <div id="attention"></div>
      </aside>
    </section>

    <section class="sect" id="tickets-section">
      <h2>Tickets</h2>
      <p class="hint">Requests and callbacks from your customers. Changing a status emails the customer.</p>
      <div class="filters" role="group" aria-label="Filter tickets">
        <button class="chip" type="button" id="t-open" aria-pressed="true">Waiting</button>
        <button class="chip" type="button" id="t-in_progress" aria-pressed="false">In progress</button>
        <button class="chip" type="button" id="t-resolved" aria-pressed="false">Resolved</button>
        <button class="chip" type="button" id="t-all" aria-pressed="false">All</button>
      </div>
      <p class="tstatus hidden" id="tnote" role="status"></p>
      <ul class="calls" id="tickets"></ul>
    </section>

    <div class="cols">
      <section class="sect">
        <h2>Coming up</h2>
        <p class="hint" id="apphint"></p>
        <ol class="line" id="appointments"></ol>
      </section>
      <section class="sect">
        <h2>Open work</h2>
        <p class="hint">Tickets and unpaid invoices for your company.</p>
        <ul class="ledger" id="work"></ul>
      </section>
    </div>

    <section class="speed">
      <h2>How fast callers get an answer</h2>
      <p class="verdict" id="verdict"></p>
      <div class="bars" id="bars"></div>
      <ul class="facts" id="facts"></ul>
    </section>

    <section class="sect">
      <h2>Recent calls</h2>
      <p class="hint">The 10 newest calls in this period. Select one to read what was said.</p>
      <div class="filters" role="group" aria-label="Filter calls">
        <button class="chip" type="button" id="f-all" aria-pressed="true">All calls</button>
        <button class="chip" type="button" id="f-failed" aria-pressed="false">Broke down</button>
      </div>
      <ul class="calls" id="calls"></ul>
    </section>
    <p class="foot" id="updated"></p>
  </main>
</div>
<script nonce="__NONCE__">
"use strict";
var key = null, timer = null, busy = false, firstDraw = true, callFilter = "", opened = null, ticketFilter = "open", openTicket = null;
var $ = function (id) { return document.getElementById(id); };
var OUTCOME = {
  completed: {label: "Answered smoothly", lamp: "ok", legend: " answered smoothly"},
  handoff: {label: "Passed to a person", lamp: "hand", legend: " passed to a person"},
  abandoned: {label: "Hung up before speaking", lamp: "quit", legend: " hung up before speaking"},
  failed: {label: "Broke down", lamp: "bad", legend: " broke down"}
};
var ORDER = ["completed", "handoff", "abandoned", "failed"];
var NEEDS = {
  urgent_tickets: {bad: false, text: "urgent tickets or callback requests are waiting for you."},
  failed_calls: {bad: true, text: "calls broke down, so the caller may not have been helped. Check the call log below."},
  failed_notifications: {bad: false, text: "notifications could not be sent. Ask your admin to check email and n8n."}
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
    var row = el("div", null, "need" + (spec.bad ? " bad" : ""));
    row.appendChild(el("b", a.count)); row.appendChild(el("span", spec.text));
    box.appendChild(row);
  });
}

function drawAppointments(d) {
  var a = d.appointments;
  $("apphint").textContent = plural(a.today, "appointment", "appointments") + " today, " + a.next_7_days + " in the next 7 days.";
  var list = $("appointments"); clear(list);
  if (!a.upcoming.length) { list.appendChild(el("li", "Nothing booked yet. New bookings made by phone show up here.", "empty")); list.style.borderLeftColor = "transparent"; return; }
  list.style.borderLeftColor = "";
  a.upcoming.forEach(function (x) {
    var li = el("li", null, "stop");
    li.appendChild(el("div", fmt(x.starts_at, {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"}), "at"));
    li.appendChild(el("div", (x.customer_name || "Unknown customer") + (x.reason ? ", " + x.reason : ""), "what"));
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
  var recent = all.filter(function (x) { return new Date(x.started_at).getTime() >= cutoff; }).slice(0, 10);
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
    var li = el("li"), btn = el("button", null, "trow"); btn.type = "button"; btn.setAttribute("aria-expanded", "false");
    btn.appendChild(el("span", "#" + t.id, "t-id mutes"));
    btn.appendChild(el("span", t.subject, "t-subject"));
    btn.appendChild(el("span", t.customer_name || t.customer_phone || "No customer linked", "t-cust"));
    btn.appendChild(el("span", t.priority, "t-prio" + (t.priority === "urgent" ? " prio-urgent" : " mutes")));
    btn.appendChild(el("span", STATUS_WORD[t.status] || t.status, "t-stat"));
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
      drawHero(r[0]); drawNeeds(r[0]); drawAppointments(r[0]); drawWork(r[0]); drawSpeed(r[0]);
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
  if (forget) { key = null; firstDraw = true; show($("board"), false); show($("login"), true); $("signedin").hidden = true; $("company").textContent = ""; }
}
function setFilter(value) {
  callFilter = value;
  $("f-all").setAttribute("aria-pressed", value ? "false" : "true");
  $("f-failed").setAttribute("aria-pressed", value ? "true" : "false");
  busy = false; load();
}
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
$("signout").addEventListener("click", function () { stop(true); message(""); });
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
