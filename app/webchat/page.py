"""The customer chat page (opened from a company's QR code): GET /c/{code}.

Like the staff dashboard it holds no data and no keys, loads nothing from outside, never stores
anything in the browser and never inserts raw HTML. The chat lives only in this tab: closing it ends it.
Design "Quiet": white, one teal accent, plain agent text, a soft grey customer bubble.

Made for phones: it uses the phone's own font and its text-size setting (rem units, iOS Dynamic Type),
keeps clear of notches, rounded corners and the Android/iPhone gesture bar (safe areas), stays above the
on-screen keyboard (visualViewport), keeps 16 px inputs so iPhones do not zoom, and has 44 px touch targets.
The Back arrow and the phone's own back button/swipe both return to the menu instead of leaving the page.
"""
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#101216" media="(prefers-color-scheme: dark)">
<meta name="format-detection" content="telephone=no">
<meta name="robots" content="noindex">
<title>Chat with us</title>
<style nonce="__NONCE__">
:root{
  --bg:#ffffff; --ink:#14171f; --mute:#5f6675; --line:#dde0e6; --field:#8a92a3; --soft:#f3f4f6;
  --accent:#0f766e; --accent-ink:#ffffff; --first:#f0f8f7; --err:#b3261e;
  --sans:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans","Helvetica Neue",Arial,sans-serif; color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#101216; --ink:#eceef2; --mute:#a0a7b5; --line:#2b303a; --field:#6a7386; --soft:#1b1f27;
  --accent:#34d3c0; --accent-ink:#06201d; --first:#14262a; --err:#ff8a80; color-scheme:dark;
}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;font-size:100%}
@supports (-webkit-touch-callout:none){html{font:-apple-system-body}}
html,body{margin:0;height:100%;overflow:hidden;overscroll-behavior:none}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:1rem;line-height:1.5;touch-action:manipulation}
button,input{font:inherit;color:inherit}
button{cursor:pointer;touch-action:manipulation}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.hidden{display:none!important}
.app{display:flex;flex-direction:column;height:100vh;height:100dvh;height:var(--app-h,100dvh);max-width:35rem;margin:0 auto;border-inline:1px solid var(--line);
  padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right)}
.bar{display:flex;align-items:center;gap:.5rem;padding:calc(.5rem + env(safe-area-inset-top)) .75rem .5rem .5rem;border-bottom:1px solid var(--line);min-height:3.5rem}
.back{width:2.75rem;height:2.75rem;flex:none;border:0;border-radius:50%;background:transparent;display:flex;align-items:center;justify-content:center}
.back:hover{background:var(--soft)}
.back svg{width:1.5rem;height:1.5rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.who{display:flex;align-items:center;gap:.75rem;min-width:0;flex:1}
.dot{width:2.125rem;height:2.125rem;border-radius:50%;background:var(--ink);color:var(--bg);display:flex;align-items:center;justify-content:center;font-weight:700;flex:none}
.who>div:last-child{min-width:0}
.who b{display:block;font-size:1rem;line-height:1.2;overflow-wrap:anywhere}
.who span{display:block;font-size:.8125rem;color:var(--mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.call{flex:none;min-height:2.75rem;display:flex;align-items:center;padding:0 .5rem;color:var(--mute);font-size:.875rem;text-decoration:underline}
.scroll{flex:1;overflow-y:auto;overscroll-behavior:contain;padding:.5rem 1.125rem 1.125rem;-webkit-overflow-scrolling:touch}
.welcome h1{font-size:1.875rem;line-height:1.15;letter-spacing:-.02em;margin:2rem 0 .5rem}
.welcome p{color:var(--mute);margin:0 0 1.375rem}
.opt{display:flex;justify-content:space-between;align-items:center;width:100%;min-height:3.25rem;padding:.875rem 1rem;margin:0 0 .625rem;border:1px solid var(--line);border-radius:.875rem;background:var(--bg);font-weight:600;text-align:left}
.opt:hover{border-color:var(--accent)}
.opt.first{border-color:var(--accent);background:var(--first)}
.opt i{font-style:normal;color:var(--mute);font-weight:400}
.welcome .hint{color:var(--mute);font-size:.875rem;text-align:center;margin:1.125rem 0 0}
.log{display:flex;flex-direction:column;gap:.875rem;padding-top:.75rem}
.a{max-width:92%;overflow-wrap:anywhere;white-space:pre-wrap}
.u{align-self:flex-end;max-width:84%;background:var(--soft);border-radius:1.125rem 1.125rem .25rem 1.125rem;padding:.625rem .875rem;overflow-wrap:anywhere;white-space:pre-wrap}
.typing{color:var(--mute);font-size:.9375rem}
.err{color:var(--err);font-size:.9375rem}
.card{border:1px solid var(--line);border-radius:.875rem;padding:.875rem}
.card label{display:block;font-size:.875rem;color:var(--mute);margin-bottom:.375rem}
.field{display:flex;border:1px solid var(--field);border-radius:.625rem;overflow:hidden;background:var(--bg)}
.field span{display:flex;align-items:center;padding:0 .75rem;background:var(--soft);border-right:1px solid var(--line)}
.field input{flex:1;min-width:0;min-height:2.75rem;border:0;padding:.5rem .75rem;background:var(--bg);font-size:max(16px,1rem)}
.field input:focus-visible{outline:none}
.field:focus-within{outline:3px solid var(--accent);outline-offset:2px}
.go,.again{margin-top:.625rem;width:100%;min-height:2.75rem;padding:.75rem;border:0;border-radius:.625rem;background:var(--accent);color:var(--accent-ink);font-weight:600}
.go[disabled]{opacity:.6;cursor:default}
.msg{margin:.5rem 0 0;font-size:.875rem;color:var(--err)}
.msg.fix{color:var(--ink)}
.msg button{margin:.25rem 0 0 .375rem;min-height:2.25rem;padding:.25rem .75rem;border:1px solid var(--field);border-radius:999px;background:var(--bg)}
.chips{display:flex;flex-wrap:wrap;gap:.5rem}
.chip{min-height:2.75rem;padding:.5rem .875rem;border:1px solid var(--line);border-radius:999px;background:var(--bg)}
.chip:hover{border-color:var(--accent)}
.composer{display:flex;gap:.5rem;padding:.625rem .875rem calc(.625rem + env(safe-area-inset-bottom));border-top:1px solid var(--line)}
.composer input{flex:1;min-width:0;min-height:2.875rem;border:1px solid var(--line);border-radius:999px;padding:.5rem 1rem;background:var(--bg);font-size:max(16px,1rem)}
.composer input::placeholder{color:var(--mute);opacity:1}
.send{width:2.875rem;height:2.875rem;border-radius:50%;border:0;background:var(--accent);color:var(--accent-ink);font-size:1.25rem;flex:none}
.send[disabled]{opacity:.6;cursor:default}
@media (max-width:23rem){.who span{display:none}.dot{width:1.875rem;height:1.875rem}}
@media (max-height:30rem){.welcome h1{margin-top:.75rem;font-size:1.5rem}.welcome p{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
</head>
<body data-code="__CODE__">
<div class="app" id="app">
  <header class="bar">
    <button class="back hidden" id="back" type="button" aria-label="Back to the menu"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg></button>
    <div class="who"><div class="dot" id="mark" aria-hidden="true"></div><div><b id="name">Chat with us</b><span id="sub">Usually replies in seconds</span></div></div>
    <a class="call hidden" id="call" href="#">Call us</a>
  </header>
  <main class="scroll" id="scroll">
    <section class="welcome" id="welcome">
      <h1>How can we help?</h1>
      <p>Type your request and our assistant will sort it out. Typing keeps your name and number accurate.</p>
      <button class="opt first" type="button" data-say="I would like to book an appointment">Book an appointment <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I want to change or cancel my appointment">Change or cancel a visit <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I want to check on a request I made">Check on a request <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I have a question about my invoice">Invoice question <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I would like to talk to a person">Talk to a person <i>&rsaquo;</i></button>
      <p class="hint" id="callhint" hidden>Prefer to speak? Call us any time.</p>
    </section>
    <div class="log" id="log" role="log" aria-live="polite"></div>
  </main>
  <form class="composer" id="form" autocomplete="off">
    <input id="text" type="text" maxlength="500" placeholder="Type a message" aria-label="Message" enterkeyhint="send">
    <button class="send" id="send" type="submit" aria-label="Send">&rarr;</button>
  </form>
</div>
<script nonce="__NONCE__">
"use strict";
var code = document.body.getAttribute("data-code"), base = "/c/" + code, token = null, busy = false, country = "+91", lastText = "", inChat = false, callNumber = "";
var $ = function (id) { return document.getElementById(id); };
var log = $("log"), scroller = $("scroll"), typing = null;
function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function down() { scroller.scrollTop = scroller.scrollHeight; }
function add(node) { log.appendChild(node); down(); return node; }
function clearWidgets() { Array.prototype.slice.call(log.querySelectorAll(".card,.chips")).forEach(function (n) { n.remove(); }); }
function say(text, cls) { return add(el("div", cls || "a", text)); }
function setBusy(on) { busy = on; $("send").disabled = on; $("text").disabled = on; }

/* keep the chat above the on-screen keyboard (iPhone does not shrink the page by itself) */
function fit() {
  var vv = window.visualViewport;
  $("app").style.setProperty("--app-h", (vv ? Math.round(vv.height) : window.innerHeight) + "px");
  if (vv) window.scrollTo(0, 0);
  if (inChat) down();
}
if (window.visualViewport) { window.visualViewport.addEventListener("resize", fit); window.visualViewport.addEventListener("scroll", function () { window.scrollTo(0, 0); }); }
window.addEventListener("resize", fit); window.addEventListener("orientationchange", fit); fit();

function post(path, body) {
  return fetch(base + path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
    .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return {status: r.status, body: j}; }); });
}

function start() {
  token = null; setBusy(true);
  post("/session", {}).then(function (r) {
    if (r.status !== 200) {
      $("welcome").classList.add("hidden");
      say(r.status === 429 ? "Too many people are using this chat right now. Please try again in a few minutes." : "This chat link is not active. Please ask the business for a new QR code.", "err");
      return;
    }
    token = r.body.session; country = r.body.country || "+91"; setBusy(false);
    $("name").textContent = r.body.name; document.title = "Chat with " + r.body.name;
    $("mark").textContent = (r.body.name || "?").charAt(0).toUpperCase();
    if (r.body.phone) { callNumber = r.body.phone; $("call").href = "tel:" + callNumber; $("call").classList.remove("hidden"); $("callhint").hidden = false; }
  }).catch(function () { say("Could not connect. Check your internet and reload this page.", "err"); });
}

/* Back: the arrow and the phone's own back button/swipe both return to the menu. */
function enterChat() {
  if (inChat) return;
  inChat = true; $("welcome").classList.add("hidden"); $("back").classList.remove("hidden");
  try { history.pushState({chat: 1}, ""); } catch (e) { /* history not available */ }
}
function toMenu() {
  if (!inChat) return;
  inChat = false; typing = null; log.textContent = ""; $("welcome").classList.remove("hidden"); $("back").classList.add("hidden");
  $("text").value = ""; scroller.scrollTop = 0; start();
}
$("back").addEventListener("click", function () { if (history.state && history.state.chat) history.back(); else toMenu(); });
window.addEventListener("popstate", function () { if (inChat) toMenu(); });

function showTyping() { typing = add(el("div", "typing", "Typing…")); }
function hideTyping() { if (typing) { typing.remove(); typing = null; } }

function send(text) {
  text = (text || "").trim();
  if (!text || busy || !token) return;
  lastText = text; enterChat(); clearWidgets();
  say(text, "u"); setBusy(true); showTyping();
  var mine = token;
  post("/message", {session: token, text: text}).then(function (r) {
    if (mine !== token) return;
    hideTyping(); setBusy(false);
    if (r.status === 200) { reply(r.body); return; }
    if (r.status === 410) { say("This chat timed out. Please start again.", "err"); expired(); return; }
    if (r.status === 429) { say("You are sending messages too fast. Please wait a moment and try again.", "err"); retry(); return; }
    say((r.body && typeof r.body.detail === "string") ? r.body.detail : "That did not send. Please try again.", "err"); retry();
  }).catch(function () { if (mine !== token) return; hideTyping(); setBusy(false); say("That did not send. Check your internet and try again.", "err"); retry(); });
}
function retry() {
  var b = el("button", "chip", "Try again"); b.type = "button"; var box = el("div", "chips"); box.appendChild(b); add(box);
  b.addEventListener("click", function () { box.remove(); var all = log.querySelectorAll(".u"); if (all.length) all[all.length - 1].remove(); send(lastText); });
}
function expired() { var b = el("button", "again", "Start again"); b.type = "button"; add(b); b.addEventListener("click", function () { window.location.reload(); }); setBusy(true); }

function reply(data) {
  say(data.reply || "", "a");
  if (data.ask === "phone") phoneCard(); else if (data.ask === "email") emailCard();
  else if (data.choices && data.choices.length) chips(data.choices);
  if (!data.ask) $("text").focus({preventScroll: true});
}

function chips(list) {
  var box = el("div", "chips");
  list.forEach(function (label) { var b = el("button", "chip", label); b.type = "button"; b.addEventListener("click", function () { send(label); }); box.appendChild(b); });
  add(box);
}

function digitsOnly(s) { return (s || "").replace(/[^0-9]/g, ""); }
function phoneCard() {
  var card = el("div", "card"), label = el("label", null, "Mobile number"), row = el("div", "field"), pre = el("span", null, country), input = el("input");
  input.type = "tel"; input.inputMode = "numeric"; input.autocomplete = "tel-national"; input.id = "phone-in"; input.placeholder = "98765 43210"; input.maxLength = 20; label.htmlFor = "phone-in";
  row.appendChild(pre); row.appendChild(input);
  var go = el("button", "go", "Continue"); go.type = "button"; var msg = el("p", "msg hidden");
  function submit() {
    var raw = input.value.trim(), d = digitsOnly(raw), full;
    if (raw.charAt(0) === "+") { full = "+" + d; if (d.length < 8 || d.length > 15) return bad("Check the number. It should include the country code and digits only."); }
    else { var cc = digitsOnly(country); if (d.length < 8 || d.length > 12) return bad("Check the number. Type the digits without the country code."); full = "+" + cc + d; }
    send("My mobile number is " + full + ".");
  }
  function bad(t) { msg.textContent = t; msg.classList.remove("hidden"); input.focus(); }
  go.addEventListener("click", submit); input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  card.appendChild(label); card.appendChild(row); card.appendChild(go); card.appendChild(msg); add(card); input.focus({preventScroll: true});
}

var DOMAIN_FIX = {"gmial.com": "gmail.com", "gamil.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com", "gmail.con": "gmail.com", "gnail.com": "gmail.com",
  "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.con": "yahoo.com", "hotnail.com": "hotmail.com", "hotmial.com": "hotmail.com", "outlok.com": "outlook.com", "outlook.con": "outlook.com"};
function emailCard() {
  var card = el("div", "card"), label = el("label", null, "Email address"), row = el("div", "field"), input = el("input");
  input.type = "email"; input.autocomplete = "email"; input.id = "email-in"; input.placeholder = "name@example.com"; input.maxLength = 120; input.spellcheck = false; label.htmlFor = "email-in";
  input.setAttribute("autocapitalize", "none"); row.appendChild(input);
  var go = el("button", "go", "Continue"); go.type = "button"; var msg = el("p", "msg hidden");
  function bad(t) { msg.className = "msg"; msg.textContent = t; input.focus(); }
  function submit() {
    var v = input.value.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v)) return bad("That does not look like an email address. Check it and try again.");
    var domain = v.split("@")[1];
    if (DOMAIN_FIX[domain] && !msg.getAttribute("data-asked")) {
      var fixed = v.split("@")[0] + "@" + DOMAIN_FIX[domain];
      msg.setAttribute("data-asked", "1"); msg.className = "msg fix"; msg.textContent = "Did you mean " + fixed + "?";
      var yes = el("button", null, "Yes, use it"); yes.type = "button"; yes.addEventListener("click", function () { send("My email is " + fixed + "."); });
      var no = el("button", null, "No, keep mine"); no.type = "button"; no.addEventListener("click", function () { send("My email is " + v + "."); });
      msg.appendChild(yes); msg.appendChild(no); return;
    }
    send("My email is " + v + ".");
  }
  go.addEventListener("click", submit); input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  card.appendChild(label); card.appendChild(row); card.appendChild(go); card.appendChild(msg); add(card); input.focus({preventScroll: true});
}

Array.prototype.slice.call(document.querySelectorAll(".opt")).forEach(function (b) { b.addEventListener("click", function () { send(b.getAttribute("data-say")); }); });
$("form").addEventListener("submit", function (e) { e.preventDefault(); var t = $("text").value; $("text").value = ""; send(t); });
$("text").addEventListener("focus", function () { setTimeout(function () { if (inChat) down(); }, 250); });
start();
</script>
</body>
</html>
"""
