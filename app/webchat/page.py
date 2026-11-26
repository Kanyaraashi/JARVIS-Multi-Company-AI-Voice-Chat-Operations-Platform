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
.langs{display:flex;flex-wrap:wrap;gap:.5rem;margin:.25rem 0 .5rem}
.lg{min-height:2.75rem;padding:.375rem .875rem;border:1px solid var(--line);border-radius:999px;background:var(--bg)}
.lg[aria-pressed="true"]{border-color:var(--accent);background:var(--soft);font-weight:600}
@media (max-width:23rem){.who span{display:none}.dot{width:1.875rem;height:1.875rem}}
@media (max-height:30rem){.welcome h1{margin-top:.75rem;font-size:1.5rem}.welcome p{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
</head>
<body data-code="__CODE__" data-lang="__LANG__" data-langs="__LANGS__">
<div class="app" id="app">
  <header class="bar">
    <button class="back hidden" id="back" type="button" aria-label="Back to the menu" data-ta="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg></button>
    <div class="who"><div class="dot" id="mark" aria-hidden="true"></div><div><b id="name">Chat with us</b><span id="sub" data-t="sub">Usually replies in seconds</span></div></div>
    <a class="call hidden" id="call" href="#" data-t="call">Call us</a>
  </header>
  <main class="scroll" id="scroll">
    <section class="welcome" id="welcome">
      <div class="langs" id="langs" role="group" aria-label="Language" data-ta="lang_label" hidden></div>
      <h1 data-t="h1">How can we help?</h1>
      <p data-t="intro">Type your request and our assistant will sort it out. Typing keeps your name and number accurate.</p>
      <button class="opt first" type="button" data-say="I would like to book an appointment"><span data-t="opt_book">Book an appointment</span> <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I want to change or cancel my appointment"><span data-t="opt_change">Change or cancel a visit</span> <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I want to check on a request I made"><span data-t="opt_check">Check on a request</span> <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I have a question about my invoice"><span data-t="opt_invoice">Invoice question</span> <i>&rsaquo;</i></button>
      <button class="opt" type="button" data-say="I would like to talk to a person"><span data-t="opt_person">Talk to a person</span> <i>&rsaquo;</i></button>
      <p class="hint" id="callhint" data-t="callhint" hidden>Prefer to speak? Call us any time.</p>
    </section>
    <div class="log" id="log" role="log" aria-live="polite"></div>
  </main>
  <form class="composer" id="form" autocomplete="off">
    <input id="text" type="text" maxlength="500" placeholder="Type a message" data-tp="ph" aria-label="Message" data-ta="aria_msg" enterkeyhint="send">
    <button class="send" id="send" type="submit" aria-label="Send" data-ta="aria_send">&rarr;</button>
  </form>
</div>
<script nonce="__NONCE__">
"use strict";
var code = document.body.getAttribute("data-code"), base = "/c/" + code, token = null, busy = false, country = "+91", lastText = "", inChat = false, callNumber = "";
var $ = function (id) { return document.getElementById(id); };
var log = $("log"), scroller = $("scroll"), typing = null;
function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
var T = {"en":{"back":"Back to the menu","sub":"Usually replies in seconds","call":"Call us","h1":"How can we help?","intro":"Type your request and our assistant will sort it out. Typing keeps your name and number accurate.","opt_book":"Book an appointment","opt_change":"Change or cancel a visit","opt_check":"Check on a request","opt_invoice":"Invoice question","opt_person":"Talk to a person","callhint":"Prefer to speak? Call us any time.","ph":"Type a message","aria_msg":"Message","aria_send":"Send","lang_label":"Language","typing":"Typing…","busy":"Too many people are using this chat right now. Please try again in a few minutes.","inactive":"This chat link is not active. Please ask the business for a new QR code.","connect":"Could not connect. Check your internet and reload this page.","timeout":"This chat timed out. Please start again.","fast":"You are sending messages too fast. Please wait a moment and try again.","failsend":"That did not send. Please try again.","failnet":"That did not send. Check your internet and try again.","retry":"Try again","again":"Start again","phone_label":"Mobile number","go":"Continue","phone_bad1":"Check the number. It should include the country code and digits only.","phone_bad2":"Check the number. Type the digits without the country code.","email_label":"Email address","email_bad":"That does not look like an email address. Check it and try again.","didyou":"Did you mean {x}?","yes_use":"Yes, use it","no_keep":"No, keep mine","title":"Chat with {x}"},"hi":{"back":"मेनू पर वापस जाएँ","sub":"आमतौर पर कुछ ही सेकंड में जवाब","call":"कॉल करें","h1":"हम आपकी कैसे मदद करें?","intro":"अपनी ज़रूरत लिखिए, हमारा असिस्टेंट संभाल लेगा। टाइप करने से आपका नाम और नंबर सही रहता है।","opt_book":"अपॉइंटमेंट बुक करें","opt_change":"विज़िट बदलें या रद्द करें","opt_check":"अपने अनुरोध की स्थिति देखें","opt_invoice":"बिल (इनवॉइस) से जुड़ा सवाल","opt_person":"किसी व्यक्ति से बात करें","callhint":"बोलना पसंद है? हमें कभी भी कॉल करें।","ph":"संदेश लिखें","aria_msg":"संदेश","aria_send":"भेजें","lang_label":"भाषा","typing":"लिख रहा है…","busy":"अभी बहुत से लोग इस चैट का उपयोग कर रहे हैं। कृपया कुछ मिनट बाद फिर कोशिश करें।","inactive":"यह चैट लिंक चालू नहीं है। कृपया व्यवसाय से नया QR कोड माँगें।","connect":"कनेक्ट नहीं हो सका। अपना इंटरनेट जाँचें और यह पेज दोबारा खोलें।","timeout":"यह चैट समय सीमा पार कर गई। कृपया फिर से शुरू करें।","fast":"आप बहुत तेज़ी से संदेश भेज रहे हैं। कृपया थोड़ा रुककर फिर कोशिश करें।","failsend":"संदेश नहीं भेजा जा सका। कृपया फिर कोशिश करें।","failnet":"संदेश नहीं भेजा जा सका। अपना इंटरनेट जाँचें और फिर कोशिश करें।","retry":"फिर कोशिश करें","again":"फिर से शुरू करें","phone_label":"मोबाइल नंबर","go":"आगे बढ़ें","phone_bad1":"नंबर जाँचें। उसमें देश कोड और केवल अंक होने चाहिए।","phone_bad2":"नंबर जाँचें। देश कोड के बिना केवल अंक लिखें।","email_label":"ईमेल पता","email_bad":"यह ईमेल पते जैसा नहीं लग रहा। जाँचकर फिर कोशिश करें।","didyou":"क्या आपका मतलब {x} है?","yes_use":"हाँ, यही इस्तेमाल करें","no_keep":"नहीं, मेरा ही रखें","title":"{x} के साथ चैट"},"te":{"back":"మెనూకి తిరిగి వెళ్ళండి","sub":"సాధారణంగా కొన్ని సెకన్లలో సమాధానం","call":"కాల్ చేయండి","h1":"మేము మీకు ఎలా సహాయం చేయగలం?","intro":"మీ అవసరాన్ని టైప్ చేయండి, మా అసిస్టెంట్ చూసుకుంటుంది. టైప్ చేస్తే మీ పేరు, నంబర్ సరిగ్గా ఉంటాయి.","opt_book":"అపాయింట్‌మెంట్ బుక్ చేయండి","opt_change":"సందర్శనను మార్చండి లేదా రద్దు చేయండి","opt_check":"నా అభ్యర్థన స్థితిని చూడండి","opt_invoice":"ఇన్వాయిస్ గురించి ప్రశ్న","opt_person":"ఒక వ్యక్తితో మాట్లాడండి","callhint":"మాట్లాడటం ఇష్టమా? ఎప్పుడైనా మాకు కాల్ చేయండి.","ph":"సందేశం టైప్ చేయండి","aria_msg":"సందేశం","aria_send":"పంపండి","lang_label":"భాష","typing":"టైప్ చేస్తోంది…","busy":"ప్రస్తుతం చాలా మంది ఈ చాట్‌ను ఉపయోగిస్తున్నారు. దయచేసి కొన్ని నిమిషాల తర్వాత మళ్ళీ ప్రయత్నించండి.","inactive":"ఈ చాట్ లింక్ పనిచేయడం లేదు. దయచేసి వ్యాపారాన్ని కొత్త QR కోడ్ అడగండి.","connect":"కనెక్ట్ కాలేకపోయింది. మీ ఇంటర్నెట్‌ను తనిఖీ చేసి ఈ పేజీని మళ్ళీ తెరవండి.","timeout":"ఈ చాట్ సమయం ముగిసింది. దయచేసి మళ్ళీ ప్రారంభించండి.","fast":"మీరు చాలా వేగంగా సందేశాలు పంపుతున్నారు. దయచేసి కొంచెం ఆగి మళ్ళీ ప్రయత్నించండి.","failsend":"సందేశం పంపబడలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి.","failnet":"సందేశం పంపబడలేదు. మీ ఇంటర్నెట్‌ను తనిఖీ చేసి మళ్ళీ ప్రయత్నించండి.","retry":"మళ్ళీ ప్రయత్నించండి","again":"మళ్ళీ ప్రారంభించండి","phone_label":"మొబైల్ నంబర్","go":"కొనసాగించండి","phone_bad1":"నంబర్‌ను తనిఖీ చేయండి. అందులో దేశ కోడ్, అంకెలు మాత్రమే ఉండాలి.","phone_bad2":"నంబర్‌ను తనిఖీ చేయండి. దేశ కోడ్ లేకుండా అంకెలు మాత్రమే టైప్ చేయండి.","email_label":"ఇమెయిల్ చిరునామా","email_bad":"ఇది ఇమెయిల్ చిరునామాలా లేదు. తనిఖీ చేసి మళ్ళీ ప్రయత్నించండి.","didyou":"మీరు {x} అని అనుకున్నారా?","yes_use":"అవును, దీన్నే వాడండి","no_keep":"కాదు, నాదే ఉంచండి","title":"{x}తో చాట్"},"ta":{"back":"மெனுவுக்குத் திரும்பு","sub":"பொதுவாக சில விநாடிகளில் பதில்","call":"அழைக்கவும்","h1":"நாங்கள் எப்படி உதவலாம்?","intro":"உங்கள் தேவையை தட்டச்சு செய்யுங்கள், எங்கள் உதவியாளர் பார்த்துக்கொள்வார். தட்டச்சு செய்வதால் உங்கள் பெயரும் எண்ணும் சரியாக இருக்கும்.","opt_book":"சந்திப்பை முன்பதிவு செய்யுங்கள்","opt_change":"சந்திப்பை மாற்றவும் அல்லது ரத்து செய்யவும்","opt_check":"என் கோரிக்கையின் நிலையைப் பாருங்கள்","opt_invoice":"இன்வாய்ஸ் தொடர்பான கேள்வி","opt_person":"ஒருவரிடம் பேசுங்கள்","callhint":"பேச விரும்புகிறீர்களா? எப்போது வேண்டுமானாலும் எங்களை அழைக்கவும்.","ph":"செய்தியை தட்டச்சு செய்யுங்கள்","aria_msg":"செய்தி","aria_send":"அனுப்பு","lang_label":"மொழி","typing":"தட்டச்சு செய்கிறது…","busy":"இப்போது நிறைய பேர் இந்த அரட்டையைப் பயன்படுத்துகிறார்கள். சில நிமிடங்கள் கழித்து மீண்டும் முயலுங்கள்.","inactive":"இந்த அரட்டை இணைப்பு செயலில் இல்லை. புதிய QR குறியீட்டை வணிகத்திடம் கேளுங்கள்.","connect":"இணைக்க முடியவில்லை. உங்கள் இணையத்தைச் சரிபார்த்து இந்தப் பக்கத்தை மீண்டும் திறக்கவும்.","timeout":"இந்த அரட்டை நேரம் முடிந்துவிட்டது. தயவுசெய்து மீண்டும் தொடங்குங்கள்.","fast":"நீங்கள் மிக வேகமாக செய்திகளை அனுப்புகிறீர்கள். சற்று காத்திருந்து மீண்டும் முயலுங்கள்.","failsend":"செய்தி அனுப்பப்படவில்லை. மீண்டும் முயலுங்கள்.","failnet":"செய்தி அனுப்பப்படவில்லை. உங்கள் இணையத்தைச் சரிபார்த்து மீண்டும் முயலுங்கள்.","retry":"மீண்டும் முயலுங்கள்","again":"மீண்டும் தொடங்குங்கள்","phone_label":"மொபைல் எண்","go":"தொடரவும்","phone_bad1":"எண்ணைச் சரிபார்க்கவும். அதில் நாட்டுக் குறியீடும் எண்களும் மட்டுமே இருக்க வேண்டும்.","phone_bad2":"எண்ணைச் சரிபார்க்கவும். நாட்டுக் குறியீடு இல்லாமல் எண்களை மட்டும் உள்ளிடவும்.","email_label":"மின்னஞ்சல் முகவரி","email_bad":"இது மின்னஞ்சல் முகவரி போலத் தெரியவில்லை. சரிபார்த்து மீண்டும் முயலுங்கள்.","didyou":"நீங்கள் {x} என்று நினைத்தீர்களா?","yes_use":"ஆம், இதையே பயன்படுத்து","no_keep":"இல்லை, என்னுடையதே இருக்கட்டும்","title":"{x} உடன் அரட்டை"}};
var lang = document.body.getAttribute("data-lang") || "en-IN", offered = [];
try { offered = JSON.parse(document.body.getAttribute("data-langs") || "[]"); } catch (e) { offered = []; }
function t(key, x) { var b = lang.split("-")[0], s = (T[b] && T[b][key]) || T.en[key] || key; return x === undefined ? s : s.replace("{x}", x); }
function applyLang() {
  document.documentElement.lang = lang.split("-")[0];
  Array.prototype.slice.call(document.querySelectorAll("[data-t]")).forEach(function (n) { n.textContent = t(n.getAttribute("data-t")); });
  Array.prototype.slice.call(document.querySelectorAll("[data-tp]")).forEach(function (n) { n.setAttribute("placeholder", t(n.getAttribute("data-tp"))); });
  Array.prototype.slice.call(document.querySelectorAll("[data-ta]")).forEach(function (n) { n.setAttribute("aria-label", t(n.getAttribute("data-ta"))); });
  Array.prototype.slice.call(document.querySelectorAll(".lg")).forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-code") === lang ? "true" : "false"); });
}
function pickLang() {
  var codes = offered.map(function (o) { return o[0]; }), want = (navigator.language || "").toLowerCase().split("-")[0];
  var match = codes.filter(function (c) { return c.toLowerCase().split("-")[0] === want; })[0];
  if (match) lang = match; else if (codes.indexOf(lang) < 0 && codes.length) lang = codes[0];
}
function buildLangs() {
  if (offered.length < 2) return;
  var box = $("langs");
  offered.forEach(function (o) {
    var b = el("button", "lg", o[1]); b.type = "button"; b.setAttribute("data-code", o[0]); b.setAttribute("lang", o[0].split("-")[0]);
    b.addEventListener("click", function () { if (lang === o[0]) return; lang = o[0]; applyLang(); if (!inChat) start(); });
    box.appendChild(b);
  });
  box.hidden = false;
}

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
  post("/session", {lang: lang}).then(function (r) {
    if (r.status !== 200) {
      $("welcome").classList.add("hidden");
      say(r.status === 429 ? t("busy") : t("inactive"), "err");
      return;
    }
    token = r.body.session; country = r.body.country || "+91"; setBusy(false);
    $("name").textContent = r.body.name; document.title = t("title", r.body.name);
    $("mark").textContent = (r.body.name || "?").charAt(0).toUpperCase();
    if (r.body.phone) { callNumber = r.body.phone; $("call").href = "tel:" + callNumber; $("call").classList.remove("hidden"); $("callhint").hidden = false; }
  }).catch(function () { say(t("connect"), "err"); });
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

function showTyping() { typing = add(el("div", "typing", t("typing"))); }
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
    if (r.status === 410) { say(t("timeout"), "err"); expired(); return; }
    if (r.status === 429) { say(t("fast"), "err"); retry(); return; }
    say((r.body && typeof r.body.detail === "string") ? r.body.detail : t("failsend"), "err"); retry();
  }).catch(function () { if (mine !== token) return; hideTyping(); setBusy(false); say(t("failnet"), "err"); retry(); });
}
function retry() {
  var b = el("button", "chip", t("retry")); b.type = "button"; var box = el("div", "chips"); box.appendChild(b); add(box);
  b.addEventListener("click", function () { box.remove(); var all = log.querySelectorAll(".u"); if (all.length) all[all.length - 1].remove(); send(lastText); });
}
function expired() { var b = el("button", "again", t("again")); b.type = "button"; add(b); b.addEventListener("click", function () { window.location.reload(); }); setBusy(true); }

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
  var card = el("div", "card"), label = el("label", null, t("phone_label")), row = el("div", "field"), pre = el("span", null, country), input = el("input");
  input.type = "tel"; input.inputMode = "numeric"; input.autocomplete = "tel-national"; input.id = "phone-in"; input.placeholder = "98765 43210"; input.maxLength = 20; label.htmlFor = "phone-in";
  row.appendChild(pre); row.appendChild(input);
  var go = el("button", "go", t("go")); go.type = "button"; var msg = el("p", "msg hidden");
  function submit() {
    var raw = input.value.trim(), d = digitsOnly(raw), full;
    if (raw.charAt(0) === "+") { full = "+" + d; if (d.length < 8 || d.length > 15) return bad(t("phone_bad1")); }
    else { var cc = digitsOnly(country); if (d.length < 8 || d.length > 12) return bad(t("phone_bad2")); full = "+" + cc + d; }
    send("My mobile number is " + full + ".");
  }
  function bad(t) { msg.textContent = t; msg.classList.remove("hidden"); input.focus(); }
  go.addEventListener("click", submit); input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  card.appendChild(label); card.appendChild(row); card.appendChild(go); card.appendChild(msg); add(card); input.focus({preventScroll: true});
}

var DOMAIN_FIX = {"gmial.com": "gmail.com", "gamil.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com", "gmail.con": "gmail.com", "gnail.com": "gmail.com",
  "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.con": "yahoo.com", "hotnail.com": "hotmail.com", "hotmial.com": "hotmail.com", "outlok.com": "outlook.com", "outlook.con": "outlook.com"};
function emailCard() {
  var card = el("div", "card"), label = el("label", null, t("email_label")), row = el("div", "field"), input = el("input");
  input.type = "email"; input.autocomplete = "email"; input.id = "email-in"; input.placeholder = "name@example.com"; input.maxLength = 120; input.spellcheck = false; label.htmlFor = "email-in";
  input.setAttribute("autocapitalize", "none"); row.appendChild(input);
  var go = el("button", "go", t("go")); go.type = "button"; var msg = el("p", "msg hidden");
  function bad(t) { msg.className = "msg"; msg.textContent = t; input.focus(); }
  function submit() {
    var v = input.value.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v)) return bad(t("email_bad"));
    var domain = v.split("@")[1];
    if (DOMAIN_FIX[domain] && !msg.getAttribute("data-asked")) {
      var fixed = v.split("@")[0] + "@" + DOMAIN_FIX[domain];
      msg.setAttribute("data-asked", "1"); msg.className = "msg fix"; msg.textContent = t("didyou", fixed);
      var yes = el("button", null, t("yes_use")); yes.type = "button"; yes.addEventListener("click", function () { send("My email is " + fixed + "."); });
      var no = el("button", null, t("no_keep")); no.type = "button"; no.addEventListener("click", function () { send("My email is " + v + "."); });
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
pickLang(); buildLangs(); applyLang();
start();
</script>
</body>
</html>
"""
