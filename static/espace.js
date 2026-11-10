const EMERG_LABELS = { samu: "SAMU", general: "urgences (numéro européen)", police: "police", pompiers: "pompiers",
  suicide: "prévention du suicide", sourds: "sourds et malentendants", violences: "violences faites aux femmes",
  permanence_soins: "médecin de garde" };
/* Espace cabinet CareAssist — SPA sans dépendance. Toutes les données sont échappées avant insertion (anti-XSS). */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ic = n => window.caIcon(n);
  const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  const ST = { confirmed: "Confirmé", reminded: "Rappel envoyé", honored: "Honoré", no_show: "Absent", cancelled: "Annulé",
    scheduled: "Planifiée", sent: "Envoyée", mock_sent: "Envoyée (démo)", failed: "Échec", skipped: "Non envoyée", sending: "Envoi…",
    completed: "Terminé", missed: "Manqué", voicemail: "Messagerie", transferred: "Transféré", "in-progress": "En cours" };
  const KIND = k => k === "confirmation" ? "Confirmation" : k === "cancellation" ? "Annulation" : k === "callback_offer" ? "Proposition de rappel"
    : k === "callback_request" ? "Demande de rappel" : k.startsWith("reminder_") ? "Rappel " + offsetLabel(+k.split("_")[1]) : k;
  const offsetLabel = m => m % 1440 === 0 ? `J-${m / 1440}` : m % 60 === 0 ? `H-${m / 60}` : `${m} min`;
  const badge = s => `<span class="badge s-${esc(s)}">${esc(ST[s] || s)}</span>`;
  let ME = null, TZ = "Europe/Paris", view = "dashboard";

  const csrf = () => (document.cookie.match(/(?:^|; )ca_csrf=([^;]+)/) || [])[1] || "";
  async function api(path, opts = {}) {
    const o = { method: opts.method || "GET", headers: { "Accept": "application/json" }, credentials: "same-origin" };
    if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
    if (o.method !== "GET") o.headers["X-CSRF-Token"] = decodeURIComponent(csrf());
    const r = await fetch(path, o);
    if (r.status === 401 && !path.startsWith("/api/auth/login")) { showLogin(); throw new Error("Session expirée, reconnectez-vous."); }
    const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
    if (!r.ok) {
      const d = data && data.detail;
      throw new Error(Array.isArray(d) ? d.map(x => x.msg.replace("Value error, ", "")).join(" ; ") : (d || "Erreur " + r.status));
    }
    return data;
  }
  const toast = msg => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2600); };
  const fmtLocal = iso => { // "YYYY-MM-DDTHH:MM" (heure locale du cabinet)
    if (!iso) return ""; const d = new Date(iso.slice(0, 16) + ":00");
    return `${JOURS[(d.getDay() + 6) % 7]} ${d.toLocaleDateString("fr-FR")} ${iso.slice(11, 16).replace(":", "h")}`;
  };
  const fmtUtc = iso => iso ? new Date(iso).toLocaleString("fr-FR", { timeZone: TZ, dateStyle: "short", timeStyle: "short" }) : "";
  const fmtTs = iso => iso ? new Date(iso).toLocaleString("fr-FR", { timeZone: TZ, dateStyle: "short", timeStyle: "short" }) : "";
  const pname = p => [p.first_name, p.last_name].filter(Boolean).join(" ");

  // ------------------------------------------------------------ auth
  function showLogin() { $("#app-view").hidden = true; $("#login-view").hidden = false; }
  async function boot() {
    try {
      ME = await api("/api/auth/me");
    } catch (e) { showLogin(); loadSignupOptions(); return; }
    TZ = ME.practice.timezone;
    $("#login-view").hidden = true; $("#app-view").hidden = false;
    $("#p-name").textContent = ME.practice.name;
    $("#p-meta").textContent = `${ME.country.name} · ${ME.practice.timezone} · ${ME.practice.currency}`;
    $("#u-name").textContent = `${ME.user.name} (${{ owner: "titulaire", practitioner: "praticien", secretary: "secrétariat" }[ME.user.role]})`;
    document.querySelectorAll("#side-nav [data-role]").forEach(b => { b.hidden = !b.dataset.role.split(" ").includes(ME.user.role); });
    go(location.hash.slice(1) || "dashboard");
  }
  async function loadSignupOptions() {
    try {
      const [{ specialties }, { countries }] = await Promise.all([fetch("/api/specialties").then(r => r.json()), fetch("/api/countries").then(r => r.json())]);
      $("#s-spec").innerHTML = specialties.map(s => `<option value="${esc(s.key)}">${esc(s.label)}</option>`).join("");
      $("#s-country").innerHTML = countries.map(c => `<option value="${esc(c.code)}">${esc(c.name)}</option>`).join("");
    } catch (e) { /* ignore */ }
  }
  $("#login-form").addEventListener("submit", async e => {
    e.preventDefault(); const f = new FormData(e.target); const m = $("#login-msg"); m.className = "form-msg"; m.textContent = "Connexion…";
    try { await api("/api/auth/login", { method: "POST", body: { email: f.get("email"), password: f.get("password") } }); e.target.reset(); m.textContent = ""; boot(); }
    catch (err) { m.className = "form-msg err"; m.textContent = err.message; }
  });
  $("#signup-form").addEventListener("submit", async e => {
    e.preventDefault(); const m = $("#signup-msg"); m.className = "form-msg"; m.textContent = "Création…";
    try { await api("/api/auth/signup", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); boot(); }
    catch (err) { m.className = "form-msg err"; m.textContent = err.message; }
  });
  $("#logout").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }).catch(() => {}); location.hash = ""; showLogin(); });

  // ------------------------------------------------------------ navigation
  const TITLES = { dashboard: "Tableau de bord", agenda: "Rendez-vous", patients: "Patients", calls: "Appels & messages",
    notifications: "Notifications", team: "Équipe & horaires", settings: "Paramètres du cabinet", backup: "Export & sauvegardes" };
  document.querySelectorAll("#side-nav button").forEach(b => b.addEventListener("click", () => go(b.dataset.view)));
  async function go(v) {
    if (!TITLES[v]) v = "dashboard";
    view = v; location.hash = v;
    document.querySelectorAll("#side-nav button").forEach(b => b.classList.toggle("active", b.dataset.view === v));
    $("#view-title").textContent = TITLES[v]; $("#view-actions").innerHTML = ""; $("#view").innerHTML = '<p class="empty">Chargement…</p>';
    try { await VIEWS[v](); } catch (e) { $("#view").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
    window.caHydrateIcons($("#main")); $("#main").focus({ preventScroll: true });
  }

  // ------------------------------------------------------------ modal
  function modal(title, html, onReady) {
    $("#modal-title").textContent = title; $("#modal-body").innerHTML = html; window.caHydrateIcons($("#modal-body"));
    const d = $("#modal"); if (!d.open) d.showModal(); if (onReady) onReady(d);
  }
  const closeModal = () => $("#modal").close();

  // ------------------------------------------------------------ vues
  const apptRow = a => `<tr class="click" data-appt="${a.id}"><td>${esc(fmtLocal(a.start))}</td><td>${esc(a.patient_name)}</td>
    <td>${esc(a.reason || "")}${a.urgent ? ' <span class="badge s-no_show">urgent</span>' : ""}</td><td>${esc(a.practitioner)}</td><td>${badge(a.status)}${a.patient_confirmed_at ? ' <span class="hint">confirmé par le patient</span>' : ""}</td></tr>`;
  const apptTable = rows => rows.length ? `<table class="t"><thead><tr><th>Date</th><th>Patient</th><th>Motif</th><th>Praticien</th><th>Statut</th></tr></thead><tbody>${rows.map(apptRow).join("")}</tbody></table>` : '<p class="empty">Aucun rendez-vous.</p>';
  const bindAppts = () => document.querySelectorAll("[data-appt]").forEach(el => el.addEventListener("click", () => apptModal(+el.dataset.appt)));

  const VIEWS = {
    async dashboard() {
      const d = await api("/api/espace/dashboard"); const s = d.stats;
      const voip = Object.entries(d.voip).map(([k, v]) => `${esc(k)} : <strong>${v === "live" ? "connecté" : "mode démo"}</strong>`).join(" · ");
      $("#view").innerHTML = `<div class="cards">
        <div class="card"><span>RDV aujourd'hui</span><strong>${s.today}</strong></div>
        <div class="card"><span>RDV à venir</span><strong>${s.upcoming}</strong></div>
        <div class="card"><span>Patients</span><strong>${s.patients}</strong></div>
        <div class="card"><span>Appels manqués (7 j)</span><strong>${s.missed_7d} / ${s.calls_7d}</strong></div>
        <div class="card"><span>Rappels planifiés</span><strong>${s.notif_scheduled}</strong></div>
        <div class="card"><span>Notifications envoyées</span><strong>${s.notif_sent}</strong></div>
        <div class="card"><span>Demandes de rappel</span><strong>${s.callback_requests}</strong></div>
        <div class="card"><span>Pays</span><strong style="font-size:1.1rem">${esc(ME.country.name)}</strong></div></div>
        <div class="panel"><h2>7 prochains jours</h2>${apptTable(d.appointments.filter(a => a.status !== "cancelled"))}</div>
        <div class="panel"><h2>Téléphonie et messages</h2><p class="hint">${voip}</p>
        <p class="hint">Numéros d'urgence utilisés par l'assistante (${esc(ME.country.name)}) : ${Object.entries(ME.country.emergency || {}).map(([k, v]) => `${esc(EMERG_LABELS[k] || k)} ${esc(v)}`).join(", ") || "à compléter (TODO)"}</p></div>`;
      bindAppts();
    },

    async agenda() {
      $("#view-actions").innerHTML = `<button class="btn btn-primary btn-sm" id="new-appt">${ic("plus")}Nouveau rendez-vous</button>`;
      $("#new-appt").addEventListener("click", () => newApptModal());
      const state = VIEWS.agenda.state || (VIEWS.agenda.state = { offset: 0, mode: "week" });
      const today = new Date(); const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7) + state.offset * 7);
      const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const end = new Date(monday); end.setDate(monday.getDate() + 7);
      const rows = await api(`/api/espace/appointments?start=${iso(monday)}&end=${iso(end)}`);
      const days = [...Array(7)].map((_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; });
      const cal = `<div class="week">${days.map(d => `<div class="day ${iso(d) === iso(today) ? "today" : ""}"><h3>${JOURS[(d.getDay() + 6) % 7]} ${d.getDate()}/${d.getMonth() + 1}</h3>${
        rows.filter(a => a.start.slice(0, 10) === iso(d)).map(a => `<button class="ev ${esc(a.status)} ${a.urgent ? "urgent" : ""}" data-appt="${a.id}">${esc(a.start.slice(11, 16))} ${esc(a.patient_name)}<br><span class="hint">${esc(a.reason || "")} · ${esc(ST[a.status] || a.status)}</span></button>`).join("")}</div>`).join("")}</div>`;
      $("#view").innerHTML = `<div class="toolbar"><button class="btn-ghost" id="prev">${ic("arrowLeft")} Semaine précédente</button>
        <button class="btn-ghost" id="now">Cette semaine</button><button class="btn-ghost" id="next">Semaine suivante ${ic("arrowRight")}</button>
        <button class="btn-ghost" id="mode">${state.mode === "week" ? ic("list") + " Vue liste" : ic("calendar") + " Vue calendrier"}</button>
        <span class="hint">Semaine du ${monday.toLocaleDateString("fr-FR")} — heures locales du cabinet (${esc(TZ)})</span></div>
        <div class="panel">${state.mode === "week" ? cal : apptTable(rows)}</div>`;
      $("#prev").onclick = () => { state.offset--; go("agenda"); }; $("#next").onclick = () => { state.offset++; go("agenda"); };
      $("#now").onclick = () => { state.offset = 0; go("agenda"); }; $("#mode").onclick = () => { state.mode = state.mode === "week" ? "list" : "week"; go("agenda"); };
      bindAppts();
    },

    async patients() {
      $("#view-actions").innerHTML = `<button class="btn btn-primary btn-sm" id="new-pat">${ic("plus")}Nouveau patient</button>`;
      $("#new-pat").addEventListener("click", () => patientForm());
      $("#view").innerHTML = `<div class="toolbar"><label class="hint" for="q">${ic("search")}</label><input id="q" type="search" placeholder="Rechercher : nom, téléphone, e-mail" aria-label="Rechercher un patient" /></div><div class="panel" id="pat-list"></div>`;
      const load = async () => {
        const rows = await api("/api/espace/patients?q=" + encodeURIComponent($("#q").value));
        $("#pat-list").innerHTML = rows.length ? `<table class="t"><thead><tr><th>Nom</th><th>Téléphone</th><th>E-mail</th><th>Canal préféré</th><th>Notifications</th></tr></thead><tbody>${rows.map(p =>
          `<tr class="click" data-pat="${p.id}"><td>${esc(pname(p))}</td><td>${esc(p.phone_e164 || "")}</td><td>${esc(p.email || "")}</td><td>${esc(p.preferred_channel)}</td><td>${p.notify_consent ? badge("confirmed").replace("Confirmé", "Accepte") : '<span class="badge">Refus</span>'}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucun patient.</p>';
        document.querySelectorAll("[data-pat]").forEach(tr => tr.addEventListener("click", () => patientDetail(+tr.dataset.pat)));
      };
      let t; $("#q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
      await load();
    },

    async calls() {
      const [calls, msgs] = await Promise.all([api("/api/espace/calls"), api("/api/espace/messages")]);
      $("#view").innerHTML = `<div class="panel"><h2>Journal des appels</h2>${calls.length ? `<table class="t"><thead><tr><th>Date</th><th>Appelant</th><th>Fournisseur</th><th>Statut</th><th>Durée</th><th>Transcription / messagerie</th></tr></thead><tbody>${calls.map(c =>
        `<tr><td>${esc(fmtTs(c.started_at))}</td><td>${esc(c.first_name ? pname(c) : c.from_number || "")}</td><td>${esc(c.provider)}</td><td>${badge(c.status)}${c.callback_sms_sent ? ' <span class="hint">SMS de rappel envoyé</span>' : ""}</td><td>${c.duration_s != null ? esc(c.duration_s) + " s" : ""}</td><td>${c.transcript ? `<pre class="tr">${esc(c.transcript)}</pre>` : ""}${c.voicemail_text ? `<pre class="tr">Message vocal : ${esc(c.voicemail_text)}</pre>` : ""}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucun appel pour le moment.</p>'}</div>
        <div class="panel"><h2>SMS, WhatsApp et e-mails</h2>${msgs.length ? `<table class="t"><thead><tr><th>Date</th><th>Sens</th><th>Canal</th><th>Patient / adresse</th><th>Message</th><th>Statut</th></tr></thead><tbody>${msgs.map(m =>
        `<tr><td>${esc(fmtTs(m.created_at))}</td><td>${m.direction === "inbound" ? "Reçu" : "Envoyé"}</td><td>${esc(m.channel)}</td><td>${esc(m.first_name ? pname(m) : (m.direction === "inbound" ? m.from_addr : m.to_addr) || "")}</td><td>${esc(m.body)}</td><td>${badge(m.status)} <span class="hint">${esc(m.provider)}</span></td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucun message.</p>'}</div>`;
    },

    async notifications() {
      $("#view-actions").innerHTML = ME.user.role !== "practitioner" ? `<button class="btn btn-outline btn-sm" id="run">${ic("refresh")}Envoyer les notifications échues</button>` : "";
      if ($("#run")) $("#run").addEventListener("click", async () => { const r = await api("/api/espace/notifications/run", { method: "POST" }); toast(`${r.due} notification(s) traitée(s)`); go("notifications"); });
      const rows = await api("/api/espace/notifications");
      $("#view").innerHTML = `<p class="hint">Rappels automatiques au patient et au praticien : confirmation à la prise de rendez-vous puis rappels configurés (par défaut J-1 et H-2), envoyés hors heures calmes, sur le canal préféré du patient. Le patient peut répondre OUI, ANNULER ou STOP.</p>
        <div class="panel">${rows.length ? `<table class="t"><thead><tr><th>Prévue (heure cabinet)</th><th>Destinataire</th><th>Type</th><th>Canal</th><th>Statut</th><th>Message</th></tr></thead><tbody>${rows.map(n =>
        `<tr><td>${esc(fmtUtc(n.scheduled_for))}</td><td>${n.recipient_type === "patient" ? "Patient" : "Praticien"}<br><span class="hint">${esc(n.to_addr || "")}</span></td><td>${esc(KIND(n.kind))}</td><td>${esc(n.channel || "—")}</td><td>${badge(n.status)}${n.error ? `<br><span class="hint">${esc(n.error)}</span>` : ""}</td><td class="hint">${esc((n.body || "").slice(0, 160))}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucune notification.</p>'}</div>`;
    },

    async team() {
      const [pracs, hours] = await Promise.all([api("/api/espace/practitioners"), api("/api/espace/hours")]);
      const owner = ME.user.role === "owner";
      const users = owner ? await api("/api/espace/users") : [];
      const byDay = JOURS.map((j, wd) => ({ j, wd, ranges: hours.filter(h => h.weekday === wd) }));
      $("#view").innerHTML = `<div class="panel"><h2>Praticiens</h2><table class="t"><thead><tr><th>Nom</th><th>Spécialité</th><th>E-mail</th><th>Téléphone</th><th>Notifications</th></tr></thead><tbody>${pracs.map(p =>
        `<tr><td>${esc(p.name)}${p.active ? "" : ' <span class="badge">inactif</span>'}</td><td>${esc(p.specialty)}</td><td>${esc(p.email || "")}</td><td>${esc(p.phone_e164 || "")}</td><td>${esc(p.notify_channel || "par défaut")}</td></tr>`).join("")}</tbody></table>
        ${owner ? `<div class="actions"><button class="btn-ghost" id="add-prac">${ic("plus")} Ajouter un praticien</button></div>` : ""}</div>
        <div class="panel"><h2>Horaires d'ouverture</h2><p class="hint">Format HH:MM-HH:MM, plusieurs plages séparées par une virgule (ex. 09:00-12:30, 14:00-18:30). Les créneaux des 14 prochains jours sont générés automatiquement.</p>
        <form id="hours-form" class="form-grid">${byDay.map(d => `<label for="h${d.wd}" style="text-transform:capitalize">${d.j}</label><input id="h${d.wd}" name="${d.wd}" value="${esc(d.ranges.map(r => r.open_time + "-" + r.close_time).join(", "))}" ${owner ? "" : "disabled"} />`).join("")}
        ${owner ? '<div class="full actions"><button class="btn btn-primary btn-sm" type="submit">Enregistrer les horaires</button></div>' : ""}</form></div>
        ${owner ? `<div class="panel"><h2>Comptes d'accès</h2><table class="t"><thead><tr><th>Nom</th><th>E-mail</th><th>Rôle</th><th>Dernière connexion</th></tr></thead><tbody>${users.map(u =>
        `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc({ owner: "Titulaire", practitioner: "Praticien", secretary: "Secrétariat" }[u.role])}</td><td>${esc(u.last_login_at ? u.last_login_at.slice(0, 16).replace("T", " ") : "—")}</td></tr>`).join("")}</tbody></table>
        <div class="actions"><button class="btn-ghost" id="add-user">${ic("plus")} Inviter un membre</button></div></div>` : ""}`;
      if (!owner) return;
      $("#hours-form").addEventListener("submit", async e => {
        e.preventDefault(); const out = [];
        for (const [wd, val] of new FormData(e.target)) for (const r of String(val).split(",").map(x => x.trim()).filter(Boolean)) {
          const m = /^(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})$/.exec(r); if (!m) { toast("Plage invalide : " + r); return; }
          out.push({ weekday: +wd, open_time: m[1], close_time: m[2] });
        }
        try { const r = await api("/api/espace/hours", { method: "PUT", body: { hours: out } }); toast(`Horaires enregistrés (${r.slots_created} créneaux créés)`); } catch (err) { toast(err.message); }
      });
      $("#add-prac").addEventListener("click", () => modal("Ajouter un praticien", `<form id="pf" class="form-grid">
        <div class="full"><label for="pn">Nom</label><input id="pn" name="name" required /></div><div><label for="ps">Spécialité</label><input id="ps" name="specialty" /></div>
        <div><label for="pe">E-mail</label><input id="pe" name="email" type="email" /></div><div><label for="pp">Téléphone</label><input id="pp" name="phone" type="tel" /></div>
        <div><label for="pc">Notifications</label><select id="pc" name="notify_channel"><option value="">par défaut</option><option>email</option><option>sms</option><option>whatsapp</option></select></div>
        <div class="full actions"><button class="btn btn-primary btn-sm">Ajouter</button></div><p id="pf-msg" class="form-msg err full"></p></form>`, () => {
        $("#pf").addEventListener("submit", async e => { e.preventDefault(); const b = Object.fromEntries(new FormData(e.target)); Object.keys(b).forEach(k => { if (b[k] === "") b[k] = null; });
          try { await api("/api/espace/practitioners", { method: "POST", body: b }); closeModal(); go("team"); } catch (err) { $("#pf-msg").textContent = err.message; } });
      }));
      $("#add-user").addEventListener("click", () => modal("Inviter un membre de l'équipe", `<form id="uf" class="form-grid">
        <div><label for="un">Nom</label><input id="un" name="name" required /></div><div><label for="ue">E-mail</label><input id="ue" name="email" type="email" required /></div>
        <div><label for="ur">Rôle</label><select id="ur" name="role"><option value="secretary">Secrétariat</option><option value="practitioner">Praticien</option><option value="owner">Titulaire</option></select></div>
        <div><label for="up">Mot de passe provisoire</label><input id="up" name="password" type="password" minlength="10" required autocomplete="new-password" /></div>
        <div class="full actions"><button class="btn btn-primary btn-sm">Créer l'accès</button></div><p id="uf-msg" class="form-msg err full"></p></form>`, () => {
        $("#uf").addEventListener("submit", async e => { e.preventDefault();
          try { await api("/api/espace/users", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); closeModal(); go("team"); } catch (err) { $("#uf-msg").textContent = err.message; } });
      }));
    },

    async settings() {
      const s = await api("/api/espace/settings"); const prof = s.country_profile;
      const opt = (obj, cur) => Object.entries(obj).map(([k, v]) => `<option value="${esc(k)}" ${k === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
      const chans = s.patient_channels || prof.preferred_channels;
      $("#view").innerHTML = `<form id="sf" class="panel form-grid">
        <h2 class="full">Cabinet</h2>
        <div><label for="f-name">Nom</label><input id="f-name" name="name" value="${esc(s.name)}" /></div>
        <div><label for="f-spec">Spécialité</label><select id="f-spec" name="specialty">${opt(s.specialties, s.specialty)}</select></div>
        <div class="full"><label for="f-addr">Adresse</label><input id="f-addr" name="address" value="${esc(s.address)}" /></div>
        <div><label for="f-phone">Téléphone affiché</label><input id="f-phone" name="phone" value="${esc(s.phone)}" /></div>
        <div><label for="f-email">E-mail du cabinet</label><input id="f-email" name="email" type="email" value="${esc(s.email || "")}" /></div>
        <div class="full"><label for="f-hours">Horaires (texte lu par l'assistante)</label><input id="f-hours" name="hours" value="${esc(s.hours)}" /></div>
        <div class="full"><label for="f-ins">Remboursement / assurances (texte lu par l'assistante)</label><textarea id="f-ins" name="insurance_note" rows="2">${esc(s.insurance_note || "")}</textarea></div>
        <h2 class="full">Pays et langue</h2>
        <div><label for="f-country">Pays</label><select id="f-country" name="country">${opt(s.countries, s.country)}</select></div>
        <div><label for="f-tz">Fuseau horaire</label><input id="f-tz" name="timezone" value="${esc(s.timezone)}" /></div>
        <div><label for="f-cur">Devise</label><input id="f-cur" name="currency" value="${esc(s.currency)}" maxlength="3" /></div>
        <div><label for="f-lang">Langue</label><select id="f-lang" name="language">${opt({ fr: "Français", en: "English" }, s.language)}</select></div>
        <p class="full hint">Urgences utilisées pour ${esc(prof.name)} : ${Object.entries(prof.emergency || {}).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(", ") || "<strong>non vérifiées (TODO)</strong> — l'assistante oriente vers les urgences locales sans citer de numéro"}. ${prof.todo ? esc(prof.todo) : ""}</p>
        <h2 class="full">Notifications</h2>
        <label class="check full"><input type="checkbox" name="notify_on_booking" ${s.notify_on_booking ? "checked" : ""}/> Confirmation à la prise de rendez-vous</label>
        <label class="check full"><input type="checkbox" name="notify_practitioner" ${s.notify_practitioner ? "checked" : ""}/> Prévenir aussi le praticien</label>
        <div><label for="f-po">Rappels patient (minutes avant, ex. 1440, 120)</label><input id="f-po" name="notify_patient_offsets" value="${esc((s.notify_patient_offsets || []).join(", "))}" /></div>
        <div><label for="f-pro">Rappels praticien (minutes avant)</label><input id="f-pro" name="notify_practitioner_offsets" value="${esc((s.notify_practitioner_offsets || []).join(", "))}" /></div>
        <div><label for="f-ch">Canaux patient par ordre de priorité</label><input id="f-ch" name="patient_channels" value="${esc(chans.join(", "))}" /><span class="hint">sms, whatsapp, email (défaut pays : ${esc(prof.preferred_channels.join(", "))})</span></div>
        <div><label for="f-pc">Canal praticien</label><select id="f-pc" name="practitioner_channel">${opt({ email: "E-mail", sms: "SMS", whatsapp: "WhatsApp" }, s.practitioner_channel)}</select></div>
        <div><label for="f-qs">Heures calmes : début</label><input id="f-qs" name="quiet_start" value="${esc(s.quiet_start)}" pattern="\\d{2}:\\d{2}" /></div>
        <div><label for="f-qe">Heures calmes : fin</label><input id="f-qe" name="quiet_end" value="${esc(s.quiet_end)}" pattern="\\d{2}:\\d{2}" /></div>
        <h2 class="full">Téléphonie (VoIP cloud)</h2>
        <div><label for="f-vp">Fournisseur</label><select id="f-vp" name="voip_provider">${opt({ auto: "Automatique (selon le pays)", twilio: "Twilio", vonage: "Vonage", africastalking: "Africa's Talking" }, s.voip_provider)}</select></div>
        <div><label for="f-vn">Numéro du cabinet (appels entrants)</label><input id="f-vn" name="voip_number" value="${esc(s.voip_number || "")}" placeholder="${esc(prof.dial_code)} …" /></div>
        <div><label for="f-tn">Transfert vers un humain</label><input id="f-tn" name="transfer_number" value="${esc(s.transfer_number || "")}" /></div>
        <label class="check"><input type="checkbox" name="missed_call_sms" ${s.missed_call_sms ? "checked" : ""}/> SMS automatique après un appel manqué</label>
        <p class="full hint">État des fournisseurs : ${Object.entries(s.voip_status).map(([k, v]) => `${esc(k)} ${v === "live" ? "connecté" : "mode démo"}`).join(" · ")}</p>
        <div class="full actions"><button class="btn btn-primary btn-sm" type="submit">Enregistrer</button></div><p id="sf-msg" class="form-msg full" role="status"></p></form>`;
      $("#sf").addEventListener("submit", async e => {
        e.preventDefault(); const f = new FormData(e.target); const nums = v => String(v || "").split(",").map(x => parseInt(x, 10)).filter(x => x > 0);
        const b = { name: f.get("name"), specialty: f.get("specialty"), address: f.get("address"), phone: f.get("phone"), email: f.get("email") || null,
          hours: f.get("hours"), insurance_note: f.get("insurance_note") || null, country: f.get("country"), timezone: f.get("timezone"), currency: f.get("currency"),
          language: f.get("language"), notify_on_booking: !!f.get("notify_on_booking"), notify_practitioner: !!f.get("notify_practitioner"),
          notify_patient_offsets: nums(f.get("notify_patient_offsets")), notify_practitioner_offsets: nums(f.get("notify_practitioner_offsets")),
          patient_channels: String(f.get("patient_channels")).split(",").map(x => x.trim()).filter(Boolean), practitioner_channel: f.get("practitioner_channel"),
          quiet_start: f.get("quiet_start"), quiet_end: f.get("quiet_end"), voip_provider: f.get("voip_provider"), voip_number: f.get("voip_number") || null,
          transfer_number: f.get("transfer_number") || null, missed_call_sms: !!f.get("missed_call_sms") };
        if (b.country !== s.country) { delete b.timezone; delete b.currency; }
        const m = $("#sf-msg");
        try { await api("/api/espace/settings", { method: "PUT", body: b }); m.className = "form-msg ok"; m.textContent = "Paramètres enregistrés."; ME = await api("/api/auth/me"); TZ = ME.practice.timezone; }
        catch (err) { m.className = "form-msg err"; m.textContent = err.message; }
      });
    },

    async backup() {
      $("#view").innerHTML = `<div class="panel"><h2>Exporter les données du cabinet</h2>
        <p class="hint">Export complet et portable de VOTRE cabinet uniquement (patients, rendez-vous, appels, notifications). Chaque export est tracé dans le journal d'audit.</p>
        <div class="actions"><a class="btn btn-primary btn-sm" href="/api/espace/export?format=json" download>${ic("download")}Export JSON</a>
        <a class="btn btn-outline btn-sm" href="/api/espace/export?format=csv" download>${ic("download")}Export CSV (zip)</a></div></div>
        <div class="panel"><h2>Sauvegardes automatiques</h2><p class="hint">La base est sauvegardée chaque nuit (copie cohérente SQLite, rotation des N dernières copies). Restauration : <code>python -m app.cli restore &lt;fichier&gt;</code> (voir README). En production santé : hébergement certifié HDS et base PostgreSQL managée recommandés.</p></div>
        ${ME.user.role === "owner" ? '<div class="panel"><h2>Journal d\'audit</h2><div id="audit"></div></div>' : ""}`;
      if (ME.user.role === "owner") {
        const rows = await api("/api/espace/audit");
        $("#audit").innerHTML = rows.length ? `<table class="t"><thead><tr><th>Date</th><th>Utilisateur</th><th>Action</th><th>Objet</th></tr></thead><tbody>${rows.map(r =>
          `<tr><td>${esc(fmtTs(r.created_at))}</td><td>${esc(r.user || "—")}</td><td>${esc(r.action)}</td><td>${esc(r.entity ? r.entity + " #" + r.entity_id : "")}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucune action.</p>';
      }
    },
  };

  // ------------------------------------------------------------ patients
  function patientForm(p) {
    p = p || { preferred_channel: "auto", notify_consent: 1, language: "fr" };
    const ch = ["auto", "sms", "whatsapp", "email", "none"].map(c => `<option value="${c}" ${p.preferred_channel === c ? "selected" : ""}>${{ auto: "Automatique (pays)", sms: "SMS", whatsapp: "WhatsApp", email: "E-mail", none: "Aucun" }[c]}</option>`).join("");
    modal(p.id ? "Modifier le patient" : "Nouveau patient", `<form id="patf" class="form-grid">
      <div><label for="pfn">Prénom</label><input id="pfn" name="first_name" value="${esc(p.first_name || "")}" autocomplete="off" /></div>
      <div><label for="pln">Nom</label><input id="pln" name="last_name" value="${esc(p.last_name || "")}" required autocomplete="off" /></div>
      <div><label for="pph">Téléphone</label><input id="pph" name="phone" type="tel" value="${esc(p.phone_e164 || "")}" placeholder="${esc(ME.country.phone_example)}" /></div>
      <div><label for="pem">E-mail</label><input id="pem" name="email" type="email" value="${esc(p.email || "")}" /></div>
      <div><label for="pbd">Date de naissance</label><input id="pbd" name="birth_date" type="date" value="${esc(p.birth_date || "")}" /></div>
      <div><label for="pch">Canal préféré</label><select id="pch" name="preferred_channel">${ch}</select></div>
      <label class="check full"><input type="checkbox" name="notify_consent" ${p.notify_consent ? "checked" : ""}/> Le patient accepte les rappels et notifications de rendez-vous</label>
      <div class="full"><label for="pno">Notes administratives (pas de données médicales)</label><textarea id="pno" name="notes" rows="2">${esc(p.notes || "")}</textarea></div>
      <div class="full actions"><button class="btn btn-primary btn-sm">Enregistrer</button></div><p id="patf-msg" class="form-msg err full"></p></form>`, () => {
      $("#patf").addEventListener("submit", async e => {
        e.preventDefault(); const f = new FormData(e.target);
        const b = { first_name: f.get("first_name"), last_name: f.get("last_name"), phone: f.get("phone") || null, email: f.get("email") || null,
          birth_date: f.get("birth_date") || null, preferred_channel: f.get("preferred_channel"), notify_consent: !!f.get("notify_consent"), notes: f.get("notes") || null };
        try { const r = await api(p.id ? `/api/espace/patients/${p.id}` : "/api/espace/patients", { method: p.id ? "PUT" : "POST", body: b }); closeModal(); toast("Patient enregistré"); if (view === "patients") go("patients"); patientDetail(r.id); }
        catch (err) { $("#patf-msg").textContent = err.message; }
      });
    });
  }
  async function patientDetail(id) {
    const p = await api(`/api/espace/patients/${id}`);
    modal(pname(p), `<dl class="kv"><dt>Téléphone</dt><dd>${esc(p.phone_e164 || "—")}</dd><dt>E-mail</dt><dd>${esc(p.email || "—")}</dd>
      <dt>Canal préféré</dt><dd>${esc(p.preferred_channel)}</dd><dt>Notifications</dt><dd>${p.notify_consent ? "acceptées" : "refusées"}</dd><dt>Notes</dt><dd>${esc(p.notes || "—")}</dd></dl>
      <h3>Rendez-vous</h3>${p.appointments.length ? `<table class="t"><tbody>${p.appointments.map(a => `<tr class="click" data-appt="${a.id}"><td>${esc(fmtLocal(a.start))}</td><td>${esc(a.reason || "")}</td><td>${esc(a.practitioner)}</td><td>${badge(a.status)}</td></tr>`).join("")}</tbody></table>` : '<p class="hint">Aucun.</p>'}
      <h3>Appels</h3>${p.calls.length ? p.calls.map(c => `<p class="hint">${esc(fmtTs(c.started_at))} — ${badge(c.status)} ${c.duration_s != null ? esc(c.duration_s) + " s" : ""}</p>${c.transcript ? `<pre class="tr">${esc(c.transcript)}</pre>` : ""}`).join("") : '<p class="hint">Aucun.</p>'}
      <h3>Messages</h3>${p.messages.length ? p.messages.map(m => `<p class="hint">${esc(fmtTs(m.created_at))} · ${m.direction === "inbound" ? "reçu" : "envoyé"} · ${esc(m.channel)}</p><pre class="tr">${esc(m.body)}</pre>`).join("") : '<p class="hint">Aucun.</p>'}
      <div class="actions"><button class="btn btn-primary btn-sm" id="pd-book">${ic("calendar")}Prendre rendez-vous</button><button class="btn-ghost" id="pd-edit">Modifier</button>
      <a class="btn-ghost" href="/api/espace/patients/${p.id}/export" download>${ic("download")} Exporter (RGPD)</a>
      ${ME.user.role === "owner" ? '<button class="btn-ghost" id="pd-del">Effacer (RGPD)</button>' : ""}</div>`, () => {
      $("#pd-edit").onclick = () => patientForm(p);
      $("#pd-book").onclick = () => newApptModal(p);
      document.querySelectorAll("#modal [data-appt]").forEach(el => el.addEventListener("click", () => apptModal(+el.dataset.appt)));
      if ($("#pd-del")) $("#pd-del").onclick = async () => {
        if (!confirm("Effacer définitivement ce patient et anonymiser son historique ?")) return;
        await api(`/api/espace/patients/${p.id}`, { method: "DELETE" }); closeModal(); toast("Patient effacé"); go("patients");
      };
    });
  }

  // ------------------------------------------------------------ rendez-vous
  async function newApptModal(patient) {
    const pats = patient ? [patient] : await api("/api/espace/patients");
    if (!pats.length) { toast("Créez d'abord un patient"); return; }
    modal("Nouveau rendez-vous", `<form id="af" class="form-grid">
      <div class="full"><label for="ap">Patient</label><select id="ap" name="patient_id">${pats.map(p => `<option value="${p.id}">${esc(pname(p))} ${esc(p.phone_e164 || "")}</option>`).join("")}</select></div>
      <div><label for="ad">Jour</label><input id="ad" name="day" type="date" /></div>
      <div><label for="as">Créneau libre</label><select id="as" name="slot_id" required></select></div>
      <div class="full"><label for="ar">Motif</label><input id="ar" name="reason" value="Consultation" /></div>
      <div class="full"><label for="an">Notes</label><input id="an" name="notes" /></div>
      <label class="check full"><input type="checkbox" name="urgent" /> Urgence</label>
      <p class="full hint">Le patient et le praticien reçoivent une confirmation puis les rappels configurés.</p>
      <div class="full actions"><button class="btn btn-primary btn-sm">Réserver</button></div><p id="af-msg" class="form-msg err full"></p></form>`, async () => {
      const loadSlots = async () => {
        const d = $("#ad").value; const slots = await api("/api/espace/slots?limit=40" + (d ? "&day=" + d : ""));
        $("#as").innerHTML = slots.length ? slots.map(s => `<option value="${s.id}">${esc(s.label)} — ${esc(s.practitioner)}</option>`).join("") : '<option value="">Aucun créneau libre</option>';
      };
      $("#ad").addEventListener("change", loadSlots); await loadSlots();
      $("#af").addEventListener("submit", async e => {
        e.preventDefault(); const f = new FormData(e.target);
        try {
          const a = await api("/api/espace/appointments", { method: "POST", body: { patient_id: +f.get("patient_id"), slot_id: +f.get("slot_id"), reason: f.get("reason"), notes: f.get("notes") || null, urgent: !!f.get("urgent") } });
          closeModal(); toast(`Rendez-vous réservé : ${a.label} — ${a.notifications.length} notification(s) planifiée(s)`); go(view);
        } catch (err) { $("#af-msg").textContent = err.message; }
      });
    });
  }
  async function apptModal(id) {
    const rows = await api(`/api/espace/appointments`); const a = rows.find(x => x.id === id); if (!a) return;
    const notifs = (await api("/api/espace/notifications")).filter(n => n.appointment_id === id);
    modal("Rendez-vous", `<dl class="kv"><dt>Date</dt><dd>${esc(fmtLocal(a.start))} (${esc(a.duration_min)} min)</dd><dt>Patient</dt><dd>${esc(a.patient_name)} ${esc(a.phone)}</dd>
      <dt>Praticien</dt><dd>${esc(a.practitioner)}</dd><dt>Motif</dt><dd>${esc(a.reason || "")}</dd><dt>Statut</dt><dd>${badge(a.status)}</dd><dt>Origine</dt><dd>${esc(a.source || "")}</dd></dl>
      <div class="form-grid"><div><label for="am-st">Changer le statut</label><select id="am-st">${["confirmed", "reminded", "honored", "no_show", "cancelled"].map(s => `<option value="${s}" ${s === a.status ? "selected" : ""}>${ST[s]}</option>`).join("")}</select></div>
      <div><label for="am-no">Notes</label><input id="am-no" value="${esc(a.notes || "")}" /></div></div>
      <div class="actions"><button class="btn btn-primary btn-sm" id="am-save">Enregistrer</button>${a.status !== "cancelled" ? '<button class="btn-ghost" id="am-cancel">Annuler le rendez-vous</button>' : ""}</div>
      <h3>Notifications</h3>${notifs.length ? `<table class="t"><tbody>${notifs.map(n => `<tr><td>${esc(fmtUtc(n.scheduled_for))}</td><td>${n.recipient_type === "patient" ? "Patient" : "Praticien"}</td><td>${esc(KIND(n.kind))}</td><td>${esc(n.channel || "—")}</td><td>${badge(n.status)}</td></tr>`).join("")}</tbody></table>` : '<p class="hint">Aucune.</p>'}`, () => {
      $("#am-save").onclick = async () => { try { await api(`/api/espace/appointments/${id}`, { method: "PUT", body: { status: $("#am-st").value, notes: $("#am-no").value } }); closeModal(); toast("Rendez-vous mis à jour"); go(view); } catch (e) { toast(e.message); } };
      if ($("#am-cancel")) $("#am-cancel").onclick = async () => { if (!confirm("Annuler ce rendez-vous ? Le patient et le praticien seront prévenus.")) return; await api(`/api/espace/appointments/${id}/cancel`, { method: "POST" }); closeModal(); toast("Rendez-vous annulé"); go(view); };
    });
  }

  window.addEventListener("hashchange", () => { if (ME && location.hash.slice(1) !== view) go(location.hash.slice(1)); });
  boot();
})();
