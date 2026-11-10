(() => {
  "use strict";
  const API = location.protocol === "file:" ? "http://localhost:8000" : "";
  // Le jeton n'est jamais conservé dans l'URL (journaux, Referer) : il passe en sessionStorage puis en en-tête.
  const qsToken = new URLSearchParams(location.search).get("token");
  if (qsToken) { sessionStorage.setItem("ca_admin_token", qsToken); history.replaceState(null, "", location.pathname); }
  let token = sessionStorage.getItem("ca_admin_token") || "";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = iso => iso ? new Date(iso.length <= 16 ? iso + ":00" : iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
  const SPEC = { dentiste: "Dentiste", psychologue: "Psychologue", ophtalmologue: "Ophtalmologue", generaliste: "Généraliste", kinesitherapeute: "Kiné" };
  let tab = "conversations";
  const headers = () => token ? { "X-Admin-Token": token } : {};
  const get = async path => {
    const r = await fetch(API + path, { headers: headers() });
    if (r.status === 401) {
      const t = prompt("Jeton super-admin (ADMIN_TOKEN) :");
      if (t) { sessionStorage.setItem("ca_admin_token", t); token = t; return get(path); }
      throw new Error("Accès refusé : jeton super-admin requis (variable ADMIN_TOKEN).");
    }
    if (!r.ok) throw new Error("Erreur " + r.status);
    return r.json();
  };
  const post = async path => {
    const r = await fetch(API + path, { method: "POST", headers: headers() });
    if (!r.ok) throw new Error("Erreur " + r.status);
    return r.json();
  };
  const level = l => `<span class="badge b-${esc(l || "none")}">${l === "vital" ? "Vitale" : l === "urgent" ? "Urgente" : "—"}</span>`;
  const practiceFilter = () => $("#f-practice").value;
  const keep = row => !practiceFilter() || row.specialty === practiceFilter();

  async function stats() {
    const s = await get("/api/admin/stats");
    const items = [["Conversations", s.conversations], ["Messages", s.messages], ["RDV confirmés", s.appointments],
      ["Annulés", s.cancelled], ["Urgences", s.emergencies, s.vital ? "red" : ""], ["Leads", s.leads], ["Abonnés actifs", `${s.subscriptions_active} / ${s.subscriptions}`]];
    $("#stats").innerHTML = items.map(([k, v, c]) => `<div class="stat ${c || ""}"><span>${k}</span><strong>${v}</strong></div>`).join("");
  }
  async function conversations() {
    const rows = (await get("/api/admin/conversations")).filter(keep);
    $("#panel").innerHTML = `<div class="layout"><div>${rows.length ? `<table><thead><tr><th>Date</th><th>Cabinet</th><th>Canal</th><th>Premier message</th><th>Msg</th><th>Urgence</th></tr></thead><tbody>${
      rows.map(r => `<tr class="click" data-id="${r.id}"><td>${fmt(r.updated_at)}</td><td>${esc(SPEC[r.specialty] || r.practice)}</td><td>${esc(r.channel)}</td><td>${esc((r.first_message || "").slice(0, 70))}</td><td>${r.n_messages}</td><td>${level(r.emergency_level)}</td></tr>`).join("")
    }</tbody></table>` : '<p class="empty">Aucune conversation pour le moment.</p>'}</div><div class="detail" id="detail"><p class="empty">Sélectionnez une conversation.</p></div></div>`;
    document.querySelectorAll("tr.click").forEach(tr => tr.addEventListener("click", () => detail(tr.dataset.id)));
  }
  async function detail(id) {
    const c = await get("/api/admin/conversations/" + id);
    $("#detail").innerHTML = `<h3 style="margin-top:0">Session ${esc(c.session_id)}</h3>` + c.messages.map(m =>
      `<div class="bubble ${m.role === "user" ? "user" : "bot"}">${esc(m.content)}</div>` +
      (m.role !== "user" ? `<div class="meta">${esc(m.intent || "")} · ${esc(m.engine || "")} · ${fmt(m.created_at)}</div>` : "")).join("");
  }
  async function appointments() {
    const rows = (await get("/api/admin/appointments")).filter(keep);
    $("#panel").innerHTML = rows.length ? `<table><thead><tr><th>Créneau</th><th>Cabinet</th><th>Praticien</th><th>Patient</th><th>Téléphone</th><th>Motif</th><th>Statut</th><th>Agenda</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${fmt(r.start)}</td><td>${esc(SPEC[r.specialty] || r.practice)}</td><td>${esc(r.practitioner)}</td><td>${esc(r.patient_name)}</td><td>${esc(r.phone)}</td><td>${esc(r.reason)} ${r.urgent ? '<span class="badge b-urgent">Urgent</span>' : ""}</td><td>${r.status === "cancelled" ? '<span class="badge b-cancel">Annulé</span>' : `<span class="badge b-ok">${esc({ confirmed: "Confirmé", reminded: "Rappel envoyé", honored: "Honoré", no_show: "Absent" }[r.status] || r.status)}</span>`}</td><td><small>${esc(r.calendar_event_id || "—")}</small></td></tr>`).join("")
    }</tbody></table>` : '<p class="empty">Aucun rendez-vous pris par CareAssist pour le moment.</p>';
  }
  async function emergencies() {
    const rows = (await get("/api/admin/emergencies")).filter(keep);
    $("#panel").innerHTML = rows.length ? `<table><thead><tr><th>Date</th><th>Cabinet</th><th>Niveau</th><th>Catégories</th><th>Message</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${fmt(r.created_at)}</td><td>${esc(SPEC[r.specialty] || r.practice)}</td><td>${level(r.level)}</td><td>${esc(r.categories)}</td><td>${esc(r.message)}</td></tr>`).join("")
    }</tbody></table>` : '<p class="empty">Aucune urgence détectée.</p>';
  }
  async function leads() {
    const rows = await get("/api/admin/leads");
    $("#panel").innerHTML = rows.length ? `<table><thead><tr><th>Date</th><th>Cabinet</th><th>Spécialité</th><th>Email</th><th>Téléphone</th><th>Message</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${fmt(r.created_at)}</td><td>${esc(r.practice_name)}</td><td>${esc(SPEC[r.specialty] || r.specialty || "—")}</td><td><a href="mailto:${esc(r.email)}">${esc(r.email)}</a></td><td>${esc(r.phone)}</td><td>${esc(r.message || "")}</td></tr>`).join("")
    }</tbody></table>` : '<p class="empty">Aucun lead pour le moment.</p>';
  }
  async function subscriptions() {
    const rows = await get("/api/admin/subscriptions");
    const st = x => x === "active" ? '<span class="badge b-ok">Actif</span>' : x === "pending" ? '<span class="badge b-pending">En attente</span>'
      : x === "cancelled" ? '<span class="badge b-cancel">Résilié</span>' : `<span class="badge b-vital">${esc(x)}</span>`;
    const amt = r => Number(r.amount).toLocaleString("fr-FR") + " " + esc(r.currency);
    $("#panel").innerHTML = rows.length ? `<table><thead><tr><th>Date</th><th>Cabinet</th><th>Email</th><th>Région</th><th>Montant / mois</th><th>Prestataire</th><th>Mode</th><th>Statut</th><th>Dernier événement</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${fmt(r.created_at)}</td><td>${esc(r.practice_name)}</td><td>${esc(r.email)}</td><td>${esc(r.region)}</td><td>${amt(r)}</td><td>${esc(r.provider)}</td><td><span class="badge b-${r.mode === "mock" ? "mock" : "live"}">${r.mode === "mock" ? "Démo" : "Réel"}</span></td><td>${st(r.status)}</td><td><small>${esc(r.last_event || "—")}</small></td></tr>`).join("")
    }</tbody></table>` : '<p class="empty">Aucun abonnement pour le moment.</p>';
  }
  async function practices() {
    const rows = await get("/api/admin/practices");
    const st = x => x === "published" ? '<span class="badge b-ok">Publié</span>' : x === "rejected" ? '<span class="badge b-cancel">Refusé</span>'
      : x === "pending" ? '<span class="badge b-pending">En attente</span>' : `<span class="badge">${esc(x || "—")}</span>`;
    const plan = r => r.subscription_status === "active" || r.plan === "premium" ? '<span class="badge b-ok">Premium</span>' : r.subscription_status === "trialing" ? '<span class="badge b-pending">Essai</span>' : '<span class="badge">Gratuit</span>';
    $("#panel").innerHTML = `<table><thead><tr><th>Cabinet</th><th>Spécialité</th><th>Pays</th><th>Annuaire</th><th>Forfait</th><th>Comptes</th><th>Patients</th><th>RDV</th><th>Action</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${esc(r.name)} ${r.is_demo ? '<span class="badge b-mock">Démo</span>' : ""}</td><td>${esc(SPEC[r.specialty] || r.specialty)}</td><td>${esc(r.country)}${r.city ? " · " + esc(r.city) : ""}</td><td>${st(r.listing_status)}${r.directory_visible ? "" : ' <span class="badge">masqué</span>'}</td><td>${plan(r)}</td><td>${r.users}</td><td>${r.patients}</td><td>${r.appointments}</td><td>${
        r.listing_status === "pending" || r.listing_status === "rejected"
          ? `<button class="btn btn-primary btn-sm" data-approve="${r.id}">Publier</button> `
          : ""
      }${r.listing_status !== "rejected" ? `<button class="btn-ghost small" data-reject="${r.id}">Refuser</button>` : ""}</td></tr>`).join("")
    }</tbody></table><p class="note">Vue super-admin : volumes uniquement. Les données patients restent dans l'espace de chaque cabinet. Une fiche en attente est publiée automatiquement au bout de 48 h si personne n'intervient.</p>`;
    document.querySelectorAll("[data-approve]").forEach(b => b.addEventListener("click", async () => { await post("/api/admin/practices/" + b.dataset.approve + "/approve"); refresh(); }));
    document.querySelectorAll("[data-reject]").forEach(b => b.addEventListener("click", async () => { await post("/api/admin/practices/" + b.dataset.reject + "/reject"); refresh(); }));
  }
  const views = { conversations, appointments, emergencies, leads, subscriptions, practices };
  async function refresh() {
    try { await stats(); await views[tab](); }
    catch (e) { $("#panel").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
  }
  document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach(x => x.classList.remove("active"));
    b.classList.add("active"); tab = b.dataset.tab; refresh();
  }));
  $("#refresh").addEventListener("click", refresh);
  $("#f-practice").innerHTML += Object.entries(SPEC).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#f-practice").addEventListener("change", refresh);
  refresh(); setInterval(refresh, 15000);
})();
