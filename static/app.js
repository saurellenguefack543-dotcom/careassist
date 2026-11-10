/* CareAssist — site public (vanilla JS, aucune étape de build) */
(() => {
  "use strict";
  const API = location.protocol === "file:" ? "http://localhost:8000" : "";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const page = document.body.dataset.page || "";
  const CONTACT_EMAIL = "saurellenguefack543@gmail.com";

  const SPECS = [
    { key: "dentiste", icon: "tooth", fr: "Chirurgien-dentiste", en: "Dentist", practice: "Cabinet Dentaire du Parc",
      desc_fr: "Urgences (douleur, gonflement, dent cassée), détartrage, devis prothèses, 100 % Santé.",
      desc_en: "Emergencies (pain, swelling, broken tooth), cleanings, prosthesis quotes.",
      examples: ["Bonjour, je voudrais un détartrage demain matin", "Vous faites le tiers payant avec la mutuelle ?", "J'ai la joue gonflée et très mal depuis hier soir"],
      roi: { missed_calls: 5, new_share: 20, conversion: 50, value: 450 } },
    { key: "psychologue", icon: "brain", fr: "Psychologue / psychothérapeute", en: "Psychologist / therapist", practice: "Cabinet de Psychologie Les Tilleuls",
      desc_fr: "Ton empathique, jamais de thérapie, 3114 et 15 immédiats si idées suicidaires, Mon soutien psy.",
      desc_en: "Empathetic tone, never does therapy, instant 3114/15 on suicidal ideation.",
      examples: ["Bonjour, je voudrais prendre un premier rendez-vous", "Est-ce que les séances sont remboursées ?", "Je suis en pleine crise d'angoisse, je ne vais pas bien"],
      roi: { missed_calls: 2, new_share: 40, conversion: 50, value: 600 } },
    { key: "ophtalmologue", icon: "eye", fr: "Ophtalmologue", en: "Ophthalmologist", practice: "Centre Ophtalmologique Vision Plus",
      desc_fr: "Perte brutale de vision, éclairs, projection chimique : orientation immédiate. Lunettes, glaucome.",
      desc_en: "Sudden vision loss, flashes, chemical splash: immediate triage. Glasses, glaucoma.",
      examples: ["Je voudrais un rendez-vous pour renouveler mes lunettes", "Je vois des éclairs et des taches noires depuis ce matin", "J'ai reçu de la javel dans l'œil"],
      roi: { missed_calls: 10, new_share: 30, conversion: 60, value: 120 } },
    { key: "generaliste", icon: "stethoscope", fr: "Médecin généraliste", en: "General practitioner", practice: "Cabinet Médical Saint-Michel",
      desc_fr: "Soins du jour, renouvellements, certificats. Douleur thoracique, AVC : 15 immédiatement.",
      desc_en: "Same-day care, renewals, certificates. Chest pain, stroke: call 15 now.",
      examples: ["Je voudrais une consultation aujourd'hui, j'ai de la fièvre", "Vous faites le tiers payant ?", "J'ai une douleur dans la poitrine qui serre"],
      roi: { missed_calls: 20, new_share: 15, conversion: 70, value: 90 } },
    { key: "kinesitherapeute", icon: "activity", fr: "Kinésithérapeute", en: "Physiotherapist", practice: "Kiné Santé Nantes",
      desc_fr: "Bilans, rééducation post-op. Signaux d'alerte (phlébite, cicatrice infectée) : orientation médicale.",
      desc_en: "Assessments, post-op rehab. Red flags (DVT, infected scar): medical referral.",
      examples: ["Je dois commencer la rééducation après mon opération du genou", "Faut-il une ordonnance pour venir ?", "Mon mollet est gonflé et chaud depuis l'opération"],
      roi: { missed_calls: 6, new_share: 30, conversion: 60, value: 300 } },
  ];

  const EN = {
    "nav.home": "Home", "nav.features": "Features", "nav.pros": "Specialties", "nav.directory": "Practices",
    "nav.demo": "Demo", "nav.pricing": "Pricing", "nav.contact": "Contact", "nav.cta": "Free trial", "nav.login": "Sign in",
    "hero.pill": "Dentists · Psychologists · Ophthalmologists · GPs · Physios",
    "hero.title": "Never miss an appointment again.",
    "hero.subtitle": "Your 24/7 AI receptionist for healthcare professionals.",
    "hero.text": "CareAssist answers every call — during consultations, evenings and weekends. It books, moves and cancels appointments in your calendar, answers patients' questions and immediately routes emergencies to your country's emergency services.",
    "hero.cta1": "Try the demo", "hero.p1": "no breaks, no sick days", "hero.p2": "to pick up",
    "hero.p3": "Premium, per month, unlimited calls",
    "home.trial": "14-day Premium trial",
    "home.featTitle": "The essentials, without the missed calls",
    "home.moreFeat": "See all features",
    "home.splitTitle": "Built for France and Africa",
    "home.splitText": "A private space per practice, reminders for the patient and the practitioner, cloud telephony, and a price adapted to the country: Europe, Senegal, Côte d'Ivoire, Cameroon… 14-day Premium trial, no card required.",
    "home.dir": "Practice directory", "home.prices": "See pricing",
    "home.ctaTitle": "Try CareAssist in your practice",
    "home.ctaSub": "14 days of Premium, no card. Then a Free plan for life, or Premium at your country's rate.",
    "pros.title": "Built for every healthcare profession",
    "pros.sub": "Each specialty has its own appointment types, FAQs, reimbursement rules and, above all, its own emergency signals.",
    "feat.title": "Everything a front desk does, without the missed calls",
    "feat.pageSub": "A receptionist available 24/7, automatic reminders, and a private space for each practice.",
    "spec.pageTitle": "An assistant that knows your profession",
    "space.title": "Your practice, your private space",
    "space.f1t": "Private practice space", "space.f1": "Patient database, weekly or list calendar, attended / no-show statuses, owner, practitioner and front-desk accounts.",
    "space.f2t": "Automatic reminders", "space.f2": "Patient and practitioner notified on booking, the day before and 2 h before, by SMS, WhatsApp or email (depending on the plan).",
    "space.f3t": "Cloud telephony", "space.f3": "Twilio, Vonage or Africa's Talking: a dedicated number, call log, transfer to staff (Premium plan).",
    "space.f4t": "Adapted to each country", "space.f4": "Time zone, phone format, currency, preferred channels and local emergency numbers: 15 and 3114 in France, 1515 in Senegal, 185 in Côte d'Ivoire, 119 in Cameroon.",
    "space.f5t": "Your data, portable", "space.f5": "JSON or CSV export, automatic daily backups (Premium), per-patient export and erasure (GDPR).",
    "space.f6t": "Secure by default", "space.f6": "Hashed passwords, secure sessions, CSRF protection, strict isolation between practices. HDS-certified hosting recommended in production.",
    "feat.f1t": "Answers 100% of calls", "feat.f1": "During procedures, lunch, evenings and weekends. No more full voicemail.",
    "feat.f2t": "Manages your calendar", "feat.f2": "Real-time booking, rescheduling and cancellation on your real slots only. Google Calendar ready.",
    "feat.f3t": "Triages emergencies", "feat.f3": "Specialty-specific detection: same-day priority slot, or immediate referral to 15 / 3114.",
    "feat.f4t": "Answers questions", "feat.f4": "Hours, access, Carte Vitale, direct billing, top-up insurance, C2S, documents to bring.",
    "feat.f5t": "GDPR by design", "feat.f5": "Minimal data (name, phone), no bank or social security numbers, auditable log.",
    "feat.f6t": "Hands over", "feat.f6": "Transfers to your staff or schedules a callback whenever needed.",
    "how.title": "Live in 48 hours", "how.s1t": "We configure your practice", "how.s1": "Specialty, hours, practitioners, appointment types, emergency rules.",
    "how.s2t": "You forward your calls", "how.s2": "Forward from your current line (on no-answer or always). Keep your number.",
    "how.s3t": "You get the appointments", "how.s3": "Straight into your calendar, with a dashboard of calls and emergencies.",
    "demo.title": "Talk to CareAssist", "demo.sub": "Pick a specialty and try a real conversation: booking, a reimbursement question or an emergency. (Demo is in French.)",
    "demo.reset": "New conversation", "demo.ph": "Type your message (in French)…", "demo.send": "Send",
    "demo.note": "Demo: practices and slots are fictitious. In a real emergency, call 15 or 112.",
    "dir.title": "Practice directory", "dir.sub": "Publicly listed practices in France and Africa. Filter by profession, country or city.",
    "dir.spec": "Specialty", "dir.country": "Country", "dir.city": "City", "dir.filter": "Filter",
    "dir.empty": "No published practice matches these filters.",
    "dir.book": "Book (demo)", "dir.contact": "Contact the practice", "dir.send": "Send",
    "dir.hours": "Opening hours",
    "roi.title": "How much do missed calls cost you?", "roi.sub": "Adjust the assumptions or start from a specialty preset.",
    "roi.preset": "Specialty (preset)", "roi.missed": "Missed calls per day", "roi.new": "Share of new patients among them",
    "roi.conv": "Conversion rate to appointments", "roi.value": "Average value of a new patient (€)", "roi.days": "Working days per month",
    "roi.k1": "New patients recovered / month", "roi.k2": "Revenue recovered / month", "roi.k3": "Return on investment (vs Premium)",
    "roi.k4": "Subscription paid back in", "roi.note": "Indicative estimate based on your assumptions; presets are orders of magnitude, not statistics.",
    "price.title": "A Free plan and a Premium plan", "price.per": "/month excl. VAT",
    "price.sub": "14-day Premium trial, no card. Then stay on Free or upgrade to Premium, at your country's rate (card, SEPA direct debit or mobile money).",
    "price.freeName": "Free", "price.forever": "/month, for life",
    "price.freeDesc": "Discover CareAssist and handle a small volume of calls.",
    "price.startFree": "Create my practice",
    "price.trialBadge": "14-day Premium trial, free",
    "price.region": "Country / region", "price.subscribe": "Subscribe to Premium", "price.f_name": "Practice name", "price.f_phone": "Phone (optional)",
    "price.pay": "Continue to payment", "price.desc": "Unlimited calls for a solo practice or small group.",
    "price.l1": "24/7 AI receptionist, natural French voice", "price.l2": "Booking, rescheduling and cancellation",
    "price.l3": "SMS, WhatsApp and email, multiple users", "price.l4": "Dedicated VoIP number and automatic backups",
    "price.l5": "Emergency protocols for your specialty", "price.l6": "Priority support, no commitment", "price.cta": "Request a demo first",
    "faq.title": "FAQ", "faq.q1": "Do I keep my number?", "faq.a1": "Yes. You just set call forwarding (on no-answer, busy or always) to your CareAssist line.",
    "faq.q2": "What happens in an emergency?", "faq.a2": "Emergency detection is deterministic and specialty-specific. Life-threatening signs trigger an immediate referral to the local emergency number (15 / 112 and 3114 in France, 1515 in Senegal, 119 in Cameroon…); non-vital emergencies get a same-day priority slot and are flagged to you.",
    "faq.q3": "Does CareAssist give medical advice?", "faq.a3": "No. It never diagnoses and does not replace a professional: it organizes, informs and routes. For psychologists, it never does therapy.",
    "faq.q4": "What about health data?", "faq.a4": "Data collection is minimal (name, phone, short reason). In production, hosting must be HDS-certified; we help with your GDPR register and patient notice.",
    "faq.q5": "Which calendars does it work with?", "faq.a5": "Google Calendar natively; practice software and booking platforms connect through their API when available.",
    "faq.q6": "Do patients know they're talking to an AI?", "faq.a6": "Yes, CareAssist introduces itself as the practice's virtual assistant and always offers a human.",
    "faq.q7": "What is the difference between Free and Premium?", "faq.a7": "The Free plan, for life, includes 30 AI conversations per month, one user, email reminders and the core calendar. Premium lifts every limit: unlimited calls, SMS and WhatsApp, multiple users, a VoIP number, backups and priority support. Every new practice starts with 14 days of Premium, no card required.",
    "faq.q8": "What happens when the trial ends?", "faq.a8": "Without a subscription, the practice automatically switches to the Free plan. You can upgrade to Premium at any time from your space. An email is sent 3 days before the trial ends, then again on the day it ends.",
    "lead.title": "Try CareAssist in your practice", "lead.sub": "Leave your details: we set up a demo in your name within 1 business day. The 14-day Premium trial does not require a card.",
    "lead.name": "Practice name", "lead.spec": "Specialty", "lead.phone": "Phone", "lead.msg": "Message (optional)",
    "lead.consent": "I agree to be contacted about CareAssist. My data is never sold.", "lead.cta": "Request my demo",
    "footer.slogan": "Never miss an appointment again. Your 24/7 AI receptionist for healthcare professionals.",
    "footer.legal": "CareAssist is not a medical device and does not replace emergency services. France: emergency 15 / 112, suicide prevention 3114. Elsewhere: your local emergency numbers.",
  };
  const FR = {};
  let lang = localStorage.getItem("ca-lang") || "fr";
  $$("[data-i18n]").forEach(el => (FR[el.dataset.i18n] = el.textContent));
  $$("[data-i18n-ph]").forEach(el => (FR[el.dataset.i18nPh] = el.placeholder));
  Object.assign(FR, {
    "dir.book": "Réserver (démo)", "dir.contact": "Contacter le cabinet", "dir.send": "Envoyer",
  });
  const t = k => (lang === "en" ? (EN[k] || FR[k]) : (FR[k] || EN[k])) || k;
  function applyLang() {
    document.documentElement.lang = lang;
    $$("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    if ($("#lang-toggle")) $("#lang-toggle").textContent = lang === "fr" ? "EN" : "FR";
    if ($("#pros-grid")) renderPros();
    renderTabs();
    if ($("#roi-preset") || $("#lead-spec") || $("#dir-spec")) fillSelects();
    if ($("#r-missed")) renderROI();
    if ($("#region-select") && $("#region-select").options.length) { renderRegionSelect(); renderPrice(); }
    if ($("#dir-grid") && dirItems) renderDirectory(dirItems);
  }
  const langBtn = $("#lang-toggle");
  if (langBtn) langBtn.addEventListener("click", () => { lang = lang === "fr" ? "en" : "fr"; localStorage.setItem("ca-lang", lang); applyLang(); });
  const label = s => (lang === "en" ? s.en : s.fr);

  // ------------------------------------------------------------ nav
  const toggle = $(".nav-toggle");
  const panel = $("#site-nav");
  if (toggle && panel) {
    const setOpen = open => {
      panel.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? (lang === "en" ? "Close menu" : "Fermer le menu") : (lang === "en" ? "Open menu" : "Ouvrir le menu"));
    };
    toggle.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
    $$("#site-nav a").forEach(a => a.addEventListener("click", () => setOpen(false)));
    document.addEventListener("keydown", e => { if (e.key === "Escape") setOpen(false); });
  }
  $$("[data-nav]").forEach(a => { if (a.dataset.nav === page) a.classList.add("active"); });

  // ------------------------------------------------------------ métiers
  function renderPros() {
    const grid = $("#pros-grid"); if (!grid) return;
    grid.innerHTML = SPECS.map(s => `
      <article class="pro" data-key="${s.key}" tabindex="0">
        <picture class="pro-photo"><source srcset="/img/${s.key}.webp" type="image/webp" /><img src="/img/${s.key}.jpg" width="900" height="675" loading="lazy" alt="${label(s)}" /></picture>
        <div class="pro-body"><div class="icon">${caIcon(s.icon)}</div><h3>${label(s)}</h3><p>${lang === "en" ? s.desc_en : s.desc_fr}</p>
        <a class="pro-link" href="/demo?practice=${s.key}">${lang === "en" ? "Try the demo" : "Tester la démo"} ${caIcon("arrowRight")}</a></div>
      </article>`).join("");
    $$(".pro").forEach(el => el.addEventListener("click", e => {
      if (e.target.closest("a")) return;
      location.href = "/specialites#" + el.dataset.key;
    }));
  }

  // ------------------------------------------------------------ démo / chat / spécialités
  let current = SPECS[0];
  const params = new URLSearchParams(location.search);
  const wanted = params.get("practice") || params.get("s") || (location.hash || "").replace("#", "");
  if (wanted) current = SPECS.find(s => s.key === wanted) || current;
  let sessionId = null;
  let online = false;
  const body = $("#chat-body");

  function renderTabs() {
    for (const id of ["#spec-tabs", "#spec-page-tabs"]) {
      const el = $(id); if (!el) continue;
      el.innerHTML = SPECS.map(s =>
        `<button class="spec-tab" role="tab" aria-selected="${s.key === current.key}" data-key="${s.key}">${caIcon(s.icon)} ${label(s)}</button>`).join("");
      $$(".spec-tab", el).forEach(b => b.addEventListener("click", () => selectSpec(b.dataset.key)));
    }
    if ($("#spec-page")) renderSpecPanel();
  }
  function renderSpecPanel() {
    const panelEl = $("#spec-page"); if (!panelEl) return;
    const s = current;
    panelEl.innerHTML = `<picture><source srcset="/img/${s.key}.webp" type="image/webp" /><img src="/img/${s.key}.jpg" width="900" height="675" alt="${label(s)}" /></picture>
      <div><h2>${label(s)}</h2><p>${lang === "en" ? s.desc_en : s.desc_fr}</p>
      <div class="hero-ctas"><a class="btn btn-primary" href="/demo?practice=${s.key}">${lang === "en" ? "Try the demo" : "Tester la démo"}</a>
      <a class="btn btn-outline" href="/contact">${lang === "en" ? "Request a demo" : "Demander une démo"}</a></div></div>`;
  }
  function selectSpec(key) {
    current = SPECS.find(s => s.key === key) || SPECS[0];
    renderTabs();
    if (body) resetChat();
    const sel = $("#roi-preset"); if (sel) { sel.value = current.key; loadPreset(current.key); }
    if (page === "specialites") history.replaceState(null, "", "#" + current.key);
  }
  function resetChat() {
    if (!body) return;
    sessionId = "web-" + Math.random().toString(36).slice(2, 10);
    body.innerHTML = "";
    if ($("#chat-practice")) $("#chat-practice").textContent = current.practice + " (démo)";
    addMsg("bot", `Bonjour, ${current.practice}, je suis l'assistante virtuelle du cabinet. Comment puis-je vous aider ?`);
    if ($("#chips")) {
      $("#chips").innerHTML = current.examples.map(e => `<button class="chip" type="button">${e}</button>`).join("");
      $$(".chip").forEach(c => c.addEventListener("click", () => send(c.textContent)));
    }
  }
  function addMsg(who, text, level) {
    const d = document.createElement("div");
    d.className = "bubble " + (who === "user" ? "user" : "bot") + (level ? " " + level : "");
    if (level) {
      const tag = document.createElement("span");
      tag.className = "tag " + level;
      tag.innerHTML = caIcon(level === "ok" ? "check" : "alert");
      tag.appendChild(document.createTextNode(level === "vital" ? " Urgence vitale" : level === "urgent" ? " Urgence prioritaire" : " Rendez-vous confirmé"));
      d.appendChild(tag); d.appendChild(document.createElement("br"));
    }
    d.appendChild(document.createTextNode(text));
    body.appendChild(d); body.scrollTop = body.scrollHeight;
    return d;
  }
  async function send(text) {
    text = (text || "").trim(); if (!text || !body) return;
    addMsg("user", text);
    if ($("#chat-text")) $("#chat-text").value = "";
    const typing = document.createElement("div"); typing.className = "typing"; typing.textContent = "CareAssist écrit…";
    body.appendChild(typing); body.scrollTop = body.scrollHeight;
    let res;
    try {
      const r = await fetch(API + "/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId, practice: current.key }) });
      if (!r.ok) throw new Error(r.status);
      res = await r.json(); setStatus(true, res.engine);
    } catch (e) {
      res = offlineReply(text); setStatus(false);
    }
    typing.remove();
    const lvl = res.emergency && res.emergency.level !== "none" ? res.emergency.level : (res.intent === "booked" ? "ok" : null);
    addMsg("bot", res.reply, lvl);
  }
  if ($("#chat-form")) $("#chat-form").addEventListener("submit", e => { e.preventDefault(); send($("#chat-text").value); });
  if ($("#chat-reset")) $("#chat-reset").addEventListener("click", resetChat);
  function setStatus(on, engine) {
    const s = $("#chat-status"); if (!s) return;
    online = on;
    s.className = "status " + (on ? "on" : "off");
    s.textContent = on ? `En ligne — moteur CareAssist (${engine || "rules"})` : "Mode hors ligne — réponses simulées (lancez le backend)";
  }

  const norm = s => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[’`]/g, "'");
  let offlineStep = 0;
  function offlineReply(text) {
    const m = norm(text);
    const vital = [/suicid|en finir|envie de mourir|me tuer/, /poitrine|thoracique|respirer|etouff|avc|bouche de travers|perte de connaissance/,
      /javel|produit chimique|acide|perte brutale|rideau|voile noir/];
    if (vital[0].test(m)) return { reply: "Je suis vraiment désolée que vous traversiez cela. Appelez dès maintenant le 3114 (prévention du suicide, gratuit, 24h/24). En cas de danger immédiat, appelez le 15 ou le 112. Ne restez pas seul(e).", emergency: { level: "vital" } };
    if (vital[1].test(m) || vital[2].test(m)) return { reply: "Ce que vous décrivez peut être une urgence vitale. Appelez immédiatement le 15 (SAMU) ou le 112.", emergency: { level: "vital" } };
    if (/gonfl|enfl|mollet|eclair|tache|fievre|cass|tres mal|angoisse|panique|saign/.test(m))
      return { reply: "Je comprends, c'est prioritaire. Je peux vous proposer le premier créneau d'urgence de demain matin. Cela vous convient ? (réponse simulée hors ligne)", emergency: { level: "urgent" } };
    if (/mutuelle|rembours|tiers payant|vitale|c2s|cmu|ordonnance/.test(m)) return { reply: "Le cabinet accepte la carte Vitale ; la prise en charge dépend de votre régime et de votre mutuelle. Souhaitez-vous un rendez-vous ? (réponse simulée hors ligne)", emergency: { level: "none" } };
    if (/horaire|ouvert|ferme/.test(m)) return { reply: "Le cabinet est ouvert du lundi au vendredi en journée et le samedi matin. Je réponds 24h/24 pour vos rendez-vous. (réponse simulée hors ligne)", emergency: { level: "none" } };
    if (/rendez|rdv|voudrais|consult|seance|bilan|detartr|lunette/.test(m)) { offlineStep = 1; return { reply: "Très bien. Je vous propose demain à 9h, demain à 10h30 ou jeudi à 14h. Lequel vous convient ? (réponse simulée hors ligne)", emergency: { level: "none" } }; }
    if (offlineStep === 1) { offlineStep = 2; return { reply: "Parfait. À quel nom et à quel numéro puis-je vous joindre ?", emergency: { level: "none" } }; }
    if (offlineStep === 2) { offlineStep = 0; return { reply: "C'est noté, votre rendez-vous est confirmé (simulation). Lancez le backend pour une réservation réelle dans l'agenda.", intent: "booked", emergency: { level: "none" } }; }
    return { reply: "Je peux prendre, déplacer ou annuler un rendez-vous et répondre à vos questions pratiques. Que puis-je faire pour vous ? (mode hors ligne)", emergency: { level: "none" } };
  }

  // ------------------------------------------------------------ ROI
  const R = id => $("#r-" + id);
  const eur = n => new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n);
  function fillSelects() {
    const opts = SPECS.map(s => `<option value="${s.key}">${label(s)}</option>`).join("");
    if ($("#roi-preset")) { const pv = $("#roi-preset").value || current.key; $("#roi-preset").innerHTML = opts; $("#roi-preset").value = pv; }
    if ($("#lead-spec")) { const lv = $("#lead-spec").value; $("#lead-spec").innerHTML = opts + `<option value="autre">${lang === "en" ? "Other" : "Autre"}</option>`; if (lv) $("#lead-spec").value = lv; }
    if ($("#dir-spec")) {
      const cur = $("#dir-spec").value;
      $("#dir-spec").innerHTML = `<option value="">${lang === "en" ? "All" : "Toutes"}</option>` + opts;
      if (cur) $("#dir-spec").value = cur;
    }
  }
  function loadPreset(key) {
    if (!R("missed")) return;
    const p = (SPECS.find(s => s.key === key) || SPECS[0]).roi;
    R("missed").value = p.missed_calls; R("new").value = p.new_share; R("conv").value = p.conversion; R("value").value = p.value;
    renderROI();
  }
  function renderROI() {
    if (!R("missed")) return;
    const missed = +R("missed").value, nw = +R("new").value, conv = +R("conv").value, value = +R("value").value, days = +R("days").value;
    $("#o-missed").textContent = missed; $("#o-new").textContent = nw + " %"; $("#o-conv").textContent = conv + " %";
    $("#o-value").textContent = eur(value); $("#o-days").textContent = days;
    const patients = missed * days * (nw / 100) * (conv / 100);
    const revenue = patients * value;
    $("#k-patients").textContent = patients.toFixed(1).replace(".0", "");
    $("#k-revenue").textContent = eur(revenue);
    const subEur = (currentRegion && currentRegion.approx_eur) || 299;
    $("#k-roi").textContent = "×" + (revenue / subEur).toFixed(1);
    const perDay = revenue / days;
    $("#k-payback").textContent = perDay > 0 ? (Math.ceil(subEur / perDay) + (lang === "en" ? " working day(s)" : " jour(s) ouvré(s)")) : "–";
  }
  if ($("#roi-preset")) $("#roi-preset").addEventListener("change", e => loadPreset(e.target.value));
  $$(".roi-inputs input[type=range]").forEach(i => i.addEventListener("input", renderROI));

  // ------------------------------------------------------------ lead
  if ($("#lead-form")) $("#lead-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, msg = $("#lead-msg");
    const data = Object.fromEntries(new FormData(f).entries());
    msg.className = "form-msg full";
    if (!f.checkValidity()) { msg.classList.add("err"); msg.textContent = lang === "en" ? "Please fill in all required fields and accept to be contacted." : "Merci de remplir les champs obligatoires et d'accepter d'être recontacté."; return; }
    delete data.consent;
    try {
      const r = await fetch(API + "/api/leads", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j.detail && j.detail[0] && j.detail[0].msg) || "Erreur");
      msg.classList.add("ok"); msg.textContent = lang === "en" ? "Thank you! We'll get back to you within 1 business day." : j.message; f.reset();
    } catch (err) {
      msg.classList.add("err");
      msg.textContent = (err instanceof TypeError)
        ? (lang === "en" ? "Server unreachable: please email us at " + CONTACT_EMAIL + "." : "Serveur injoignable : écrivez-nous à " + CONTACT_EMAIL + ".")
        : (lang === "en" ? "Please check your details: " : "Vérifiez vos informations : ") + err.message;
    }
  });

  // ------------------------------------------------------------ tarification régionale + paiement
  const FALLBACK_PRICING = { regions: [{ key: "europe", label: "Europe (zone euro)", label_en: "Europe (euro area)", currency: "EUR", amount: 299,
    approx_eur: 299, reference: true, indicative: false, provider: "stripe", methods: ["Carte bancaire", "Prélèvement SEPA"], countries: ["FR"] }],
    timezone_country: {}, reference_region: "europe" };
  let PRICING = FALLBACK_PRICING;
  var currentRegion = FALLBACK_PRICING.regions[0];
  const money = (amount, cur) => new Intl.NumberFormat(lang === "en" ? "en-GB" : "fr-FR",
    { style: "currency", currency: cur, maximumFractionDigits: 0 }).format(amount);
  function guessCountry() {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      if (PRICING.timezone_country[tz]) return PRICING.timezone_country[tz];
      if (tz.startsWith("Europe/") && tz !== "Europe/London") return "EU";
    } catch (e) { /* ignore */ }
    const langs = navigator.languages || [navigator.language || ""];
    for (const l of langs) { const m = /-([A-Za-z]{2})$/.exec(l); if (m) return m[1].toUpperCase(); }
    return null;
  }
  function regionForCountry(c) {
    if (!c || c === "EU") return PRICING.reference_region;
    const r = PRICING.regions.find(r => (r.countries || []).includes(c));
    return r ? r.key : PRICING.reference_region;
  }
  function renderRegionSelect() {
    const sel = $("#region-select"); if (!sel) return;
    sel.innerHTML = PRICING.regions.map(r => `<option value="${r.key}">${lang === "en" ? r.label_en : r.label}</option>`).join("");
    sel.value = currentRegion.key;
  }
  function renderFreeFeatures() {
    const ul = $("#plan-free-features");
    if (!ul || !PRICING.plans || !PRICING.plans.free) return;
    const feats = lang === "en" ? PRICING.plans.free.features_en : PRICING.plans.free.features_fr;
    if (feats && feats.length) ul.innerHTML = feats.map(f => `<li>${f}</li>`).join("");
  }
  function renderPrice() {
    const r = currentRegion;
    if ($("#price-amount")) $("#price-amount").textContent = money(r.amount, r.currency);
    if ($("#hero-price")) $("#hero-price").textContent = money(r.amount, r.currency);
    if ($("#price-per")) $("#price-per").textContent = (lang === "en" ? "/month" : "/mois") + (r.currency === "EUR" && r.reference ? (lang === "en" ? " excl. VAT" : " HT") : "");
    if ($("#price-approx")) $("#price-approx").textContent = r.reference ? (lang === "en" ? "Reference price" : "Tarif de référence")
      : (lang === "en" ? `Regional price, approx. ${r.approx_eur} EUR` : `Tarif régional, soit environ ${r.approx_eur} EUR`);
    if ($("#price-methods")) $("#price-methods").innerHTML = (r.methods || []).map(m => `<span class="method">${caIcon("check")} ${m}</span>`).join("");
    if ($("#price-note")) $("#price-note").textContent = r.methods_note || "";
    renderFreeFeatures();
    renderROI();
  }
  function setRegion(key, manual) {
    currentRegion = PRICING.regions.find(r => r.key === key) || PRICING.regions[0];
    if (manual) localStorage.setItem("ca-region", currentRegion.key);
    renderRegionSelect(); renderPrice();
  }
  if ($("#region-select")) $("#region-select").addEventListener("change", e => setRegion(e.target.value, true));
  async function initPricing() {
    try {
      const r = await fetch(API + "/api/pricing");
      if (!r.ok) throw new Error(r.status);
      PRICING = await r.json();
    } catch (e) { PRICING = FALLBACK_PRICING; }
    const saved = localStorage.getItem("ca-region");
    const country = guessCountry();
    const key = saved && PRICING.regions.some(r => r.key === saved) ? saved : regionForCountry(country);
    if ($("#region-guess")) $("#region-guess").textContent = saved ? "" : (country ? (lang === "en" ? `Detected: ${country === "EU" ? "Europe" : country}` : `Détecté : ${country === "EU" ? "Europe" : country}`) : "");
    setRegion(key, false);
  }
  if ($("#subscribe-open")) $("#subscribe-open").addEventListener("click", () => { $("#checkout-form").hidden = false; $("#subscribe-open").hidden = true; });
  if ($("#checkout-form")) $("#checkout-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, msg = $("#checkout-msg");
    msg.className = "form-msg";
    if (!f.checkValidity()) { msg.classList.add("err"); msg.textContent = lang === "en" ? "Practice name and a valid email are required." : "Nom du cabinet et email valide requis."; return; }
    const data = Object.fromEntries(new FormData(f).entries());
    data.region = currentRegion.key;
    try {
      const r = await fetch(API + "/api/checkout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ? (typeof j.detail === "string" ? j.detail : j.detail[0].msg) : r.status);
      msg.classList.add("ok");
      msg.textContent = j.mode === "mock" ? (lang === "en" ? "Demo mode: redirecting to a simulated payment page…" : "Mode démo : redirection vers une page de paiement simulée…")
        : (lang === "en" ? "Redirecting to secure payment…" : "Redirection vers le paiement sécurisé…");
      setTimeout(() => { location.href = j.checkout_url; }, 600);
    } catch (err) {
      msg.classList.add("err");
      msg.textContent = (err instanceof TypeError) ? (lang === "en" ? "Server unreachable: " + CONTACT_EMAIL : "Serveur injoignable : " + CONTACT_EMAIL) : String(err.message);
    }
  });

  // ------------------------------------------------------------ annuaire
  let dirItems = null;
  function renderDirectory(items) {
    const grid = $("#dir-grid"); if (!grid) return;
    dirItems = items;
    const empty = $("#dir-empty");
    if (!items.length) { grid.innerHTML = ""; if (empty) empty.hidden = false; return; }
    if (empty) empty.hidden = true;
    grid.innerHTML = items.map(p => {
      const img = p.has_logo ? `/api/directory/${p.slug}/logo` : `/img/${p.specialty || "praticien"}.jpg`;
      const loc = [p.city, p.country_name || p.country].filter(Boolean).join(", ");
      const tel = p.phone ? `<a href="tel:${p.phone}">${p.phone}</a>` : "";
      const mail = p.email ? `<a href="mailto:${p.email}">${p.email}</a>` : "";
      const book = p.is_demo
        ? `<a class="btn btn-primary btn-sm" href="/demo?practice=${p.specialty}">${t("dir.book")}</a>`
        : `<button type="button" class="btn btn-outline btn-sm" data-contact="${p.slug}">${t("dir.contact")}</button>`;
      const form = p.is_demo ? "" : `<form class="dir-contact" data-form="${p.slug}" hidden>
            <input name="name" required minlength="2" placeholder="${lang === "en" ? "Your name" : "Votre nom"}" />
            <input name="email" type="email" required placeholder="vous@exemple.fr" />
            <input name="phone" type="tel" placeholder="${lang === "en" ? "Phone (optional)" : "Téléphone (facultatif)"}" />
            <textarea name="message" required minlength="5" rows="3" placeholder="${lang === "en" ? "Your message" : "Votre message"}"></textarea>
            <button class="btn btn-primary btn-sm" type="submit">${t("dir.send")}</button>
            <p class="form-msg" role="status"></p>
          </form>`;
      return `<article class="dir-card">
        <img src="${img}" alt="${p.name}" onerror="this.src='/img/praticien.jpg'" />
        <div class="body">
          <h3>${p.name}</h3>
          <p class="meta">${p.specialty_label || p.specialty} · ${loc}</p>
          <p class="hours">${p.hours || ""}</p>
          <p class="meta">${[tel, mail].filter(Boolean).join(" · ")}</p>
          <div class="actions">${book}</div>
          ${form}
        </div>
      </article>`;
    }).join("");
    $$("[data-contact]").forEach(b => b.addEventListener("click", () => {
      const f = document.querySelector(`[data-form="${b.dataset.contact}"]`);
      if (f) f.hidden = !f.hidden;
    }));
    $$("form.dir-contact").forEach(f => f.addEventListener("submit", async e => {
      e.preventDefault();
      const msg = f.querySelector(".form-msg");
      msg.className = "form-msg";
      const data = Object.fromEntries(new FormData(f).entries());
      try {
        const r = await fetch(API + "/api/directory/" + f.dataset.form + "/contact", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || r.status);
        msg.classList.add("ok"); msg.textContent = j.message || (lang === "en" ? "Message sent." : "Message envoyé.");
        f.reset();
      } catch (err) {
        msg.classList.add("err"); msg.textContent = err.message;
      }
    }));
  }
  async function initDirectory() {
    if (!$("#dir-grid")) return;
    const qs = new URLSearchParams(location.search);
    if ($("#dir-spec") && qs.get("specialty")) $("#dir-spec").value = qs.get("specialty");
    if ($("#dir-country") && qs.get("country")) $("#dir-country").value = qs.get("country");
    if ($("#dir-city") && qs.get("city")) $("#dir-city").value = qs.get("city");
    try {
      const countries = await fetch(API + "/api/countries").then(r => r.json());
      const sel = $("#dir-country");
      if (sel && countries.countries) {
        const cur = sel.value || qs.get("country") || "";
        sel.innerHTML = `<option value="">${lang === "en" ? "All" : "Tous"}</option>` +
          countries.countries.map(c => `<option value="${c.code}">${c.name}</option>`).join("");
        if (cur) sel.value = cur;
      }
    } catch (e) { /* ignore */ }
    const q = new URLSearchParams();
    const spec = $("#dir-spec") && $("#dir-spec").value;
    const country = $("#dir-country") && $("#dir-country").value;
    const city = $("#dir-city") && $("#dir-city").value;
    if (spec) q.set("specialty", spec);
    if (country) q.set("country", country);
    if (city) q.set("city", city);
    try {
      const r = await fetch(API + "/api/directory" + (q.toString() ? "?" + q : ""));
      const j = await r.json();
      renderDirectory(j.practices || []);
    } catch (e) {
      renderDirectory([]);
    }
  }
  if ($("#dir-filters")) $("#dir-filters").addEventListener("submit", e => {
    e.preventDefault();
    const q = new URLSearchParams();
    if ($("#dir-spec").value) q.set("specialty", $("#dir-spec").value);
    if ($("#dir-country").value) q.set("country", $("#dir-country").value);
    if ($("#dir-city").value) q.set("city", $("#dir-city").value);
    history.replaceState(null, "", "/cabinets" + (q.toString() ? "?" + q : ""));
    initDirectory();
  });

  window.addEventListener("hashchange", () => {
    if (page !== "specialites") return;
    const key = (location.hash || "").replace("#", "");
    if (key && key !== current.key) selectSpec(key);
  });

  // ------------------------------------------------------------ init
  fillSelects();
  if ($("#r-missed")) loadPreset(current.key);
  applyLang();
  if (body) resetChat();
  initPricing();
  initDirectory();
  if ($("#chat-status")) fetch(API + "/health").then(r => r.json()).then(j => setStatus(true, j.llm)).catch(() => setStatus(false));
})();
