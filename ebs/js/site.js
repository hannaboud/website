/* EBS site behaviour. Content lives in data/site-data.js — you rarely need to edit this file. */
(function () {
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const cfg = EBS.config;

  /* ---------- Header and footer (same on every page) ---------- */
  const PAGES = [
    ["index.html", "Home"], ["about.html", "Who we are"], ["consultants.html", "Consultants"],
    ["projects.html", "Partners & projects"], ["whitepapers.html", "Whitepapers"],
    ["services.html", "Services"], ["events.html", "Events"],
    ["membership.html", "Membership"], ["contact.html", "Contact"]
  ];
  const here = location.pathname.split("/").pop() || "index.html";

  const header = $("#site-header");
  if (header) {
    header.className = "site-header";
    header.innerHTML = `<div class="wrap">
      <a class="brand" href="index.html">EBS <small>European Business Society at Duke</small></a>
      <button class="nav-toggle" aria-expanded="false" aria-controls="nav">Menu</button>
      <nav class="nav" id="nav" aria-label="Main">
        ${PAGES.map(([href, label]) =>
          `<a href="${href}"${href === here ? ' aria-current="page"' : ""}>${esc(label)}</a>`).join("")}
      </nav></div>`;
    const toggle = header.querySelector(".nav-toggle");
    toggle.addEventListener("click", () => {
      const open = $("#nav").classList.toggle("open");
      toggle.setAttribute("aria-expanded", open);
    });
  }

  const footer = $("#site-footer");
  if (footer) {
    footer.className = "site-footer";
    footer.innerHTML = `<div class="wrap"><div class="cols">
      <div><h4>European Business Society at Duke</h4>
        <p>Pro-bono consulting by Duke University students.</p>
        <a href="mailto:${esc(cfg.email)}">${esc(cfg.email)}</a></div>
      <div><h4>Students</h4>
        <a href="membership.html">Join EBS</a><a href="events.html">Events</a>
        <a href="${esc(cfg.dukeGroups)}">Duke Groups</a></div>
      <div><h4>Companies</h4>
        <a href="services.html">Services</a><a href="projects.html">Past projects</a>
        <a href="contact.html">Work with us</a></div>
      <div><h4>Follow</h4>
        <a href="${esc(cfg.linkedin)}">LinkedIn</a><a href="${esc(cfg.instagram)}">Instagram</a></div>
      </div>
      <div class="legal">© ${new Date().getFullYear()} EBS Duke. All rights reserved.</div></div>`;
  }

  /* ---------- Stats ---------- */
  const stats = $("#stats");
  if (stats) stats.innerHTML = EBS.stats.map((s) =>
    `<div class="stat"><b>${esc(s.number)}</b><span>${esc(s.label)}</span></div>`).join("");

  /* ---------- Team ---------- */
  document.querySelectorAll("[data-team]").forEach((el) => {
    const people = EBS.team[el.dataset.team] || [];
    if (!people.length) {
      el.outerHTML = `<div class="empty"><p>${esc(el.dataset.empty || "Profiles are coming soon.")}</p></div>`;
      return;
    }
    el.innerHTML = people.map((p) => {
      const name = p.linkedin ? `<a href="${esc(p.linkedin)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name);
      return `<div class="person"><h3>${name}</h3><p>${esc(p.role)}</p>${p.classOf ? `<p>Class of ${esc(p.classOf)}</p>` : ""}</div>`;
    }).join("");
  });

  /* ---------- Projects ---------- */
  const projects = $("#projects");
  if (projects) projects.innerHTML = EBS.projects.map((p) =>
    `<article class="card"><p class="meta">${esc(p.client)}, ${esc(p.region)}</p>
      <h3>${esc(p.title)}</h3><p>${esc(p.summary)}</p></article>`).join("");

  /* ---------- Whitepapers ---------- */
  const papers = $("#whitepapers");
  if (papers) {
    papers.innerHTML = EBS.whitepapers.length
      ? `<div class="grid c2">${EBS.whitepapers.map((w) =>
          `<article class="card"><p class="meta">${esc(w.date)}</p><h3>${esc(w.title)}</h3>
            <p>${esc(w.summary)}</p><p><a class="text-link" href="${esc(w.file)}">Read the PDF</a></p></article>`).join("")}</div>`
      : `<div class="empty"><p>The whitepaper library is being moved to the new site. Email
          <a href="mailto:${esc(cfg.email)}">${esc(cfg.email)}</a> if you need a paper in the meantime.</p></div>`;
  }

  /* ---------- FAQ ---------- */
  const faq = $("#faq");
  if (faq) faq.innerHTML = EBS.faq.map((f) =>
    `<details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join("");

  /* ---------- Events ---------- */
  const toDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const events = EBS.events.map((e) => ({ ...e, when: toDate(e.date) })).sort((a, b) => a.when - b.when);
  const upcoming = events.filter((e) => e.when >= today);
  const past = events.filter((e) => e.when < today).reverse();

  const eventRow = (e) => {
    const time = e.start ? (e.end ? `${e.start} to ${e.end}` : e.start) : "";
    return `<article class="event">
      <div class="date"><b>${e.when.getDate()}</b><span>${MONTHS[e.when.getMonth()].slice(0, 3)}</span></div>
      <div><h3>${esc(e.title)}</h3>
        <p class="where">${esc([time, e.location].filter(Boolean).join(", "))}</p>
        ${e.description ? `<p>${esc(e.description)}</p>` : ""}
        <div class="tags"><span class="tag">${esc(e.category)}</span>
          ${e.sample ? '<span class="tag sample">Sample event</span>' : ""}
          ${e.link ? `<a class="text-link" href="${esc(e.link)}">RSVP</a>` : ""}</div></div></article>`;
  };
  const listOrEmpty = (list, msg) => list.length
    ? list.map(eventRow).join("") : `<div class="empty"><p>${msg}</p></div>`;

  const next = $("#next-events");
  if (next) next.innerHTML = listOrEmpty(upcoming.slice(0, 3),
    "Upcoming events will be posted here.");

  const cal = $("#calendar");
  if (cal) {
    const first = upcoming[0] ? upcoming[0].when : today;
    const state = { y: first.getFullYear(), m: first.getMonth(), filter: "All" };
    const match = (e) => state.filter === "All" || e.category === state.filter;

    const drawFilters = () => {
      $("#filters").innerHTML = ["All", ...EBS.eventCategories].map((c) =>
        `<button type="button" aria-pressed="${c === state.filter}" data-cat="${esc(c)}">${esc(c)}</button>`).join("");
    };
    const drawLists = () => {
      $("#event-list").innerHTML = listOrEmpty(upcoming.filter(match), "Upcoming events will be posted here.");
      $("#past-events").innerHTML = listOrEmpty(past.filter(match), "Past events will be listed here.");
    };
    const drawCal = () => {
      $("#cal-title").textContent = `${MONTHS[state.m]} ${state.y}`;
      const start = new Date(state.y, state.m, 1);
      const offset = (start.getDay() + 6) % 7;               // weeks start on Monday
      const days = new Date(state.y, state.m + 1, 0).getDate();
      const cells = Math.ceil((offset + days) / 7) * 7;
      let html = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map((d) => `<div class="dow">${d}</div>`).join("");
      for (let i = 0; i < cells; i++) {
        const d = new Date(state.y, state.m, i - offset + 1);
        const out = d.getMonth() !== state.m;
        const todays = events.filter((e) => match(e) && e.when.getTime() === d.getTime());
        html += `<div class="day${out ? " out" : ""}${d.getTime() === today.getTime() ? " today" : ""}${i % 7 === 0 ? " first" : ""}">
          <span class="n">${d.getDate()}</span>
          ${todays.map((e) => `<button type="button" class="ev" data-i="${events.indexOf(e)}" title="${esc(e.title)}">${esc(e.title)}</button>`).join("")}</div>`;
      }
      cal.innerHTML = html;
      $("#cal-detail").innerHTML = "";
    };

    $("#filters").addEventListener("click", (ev) => {
      const b = ev.target.closest("button"); if (!b) return;
      state.filter = b.dataset.cat; drawFilters(); drawCal(); drawLists();
    });
    cal.addEventListener("click", (ev) => {
      const b = ev.target.closest(".ev"); if (!b) return;
      $("#cal-detail").innerHTML = eventRow(events[+b.dataset.i]);
    });
    const shift = (n) => { const d = new Date(state.y, state.m + n, 1); state.y = d.getFullYear(); state.m = d.getMonth(); drawCal(); };
    $("#cal-prev").addEventListener("click", () => shift(-1));
    $("#cal-next").addEventListener("click", () => shift(1));
    drawFilters(); drawCal(); drawLists();
  }

  /* ---------- Contact form: opens the visitor's email app with the message filled in ---------- */
  const form = $("#contact-form");
  if (form) {
    document.querySelectorAll("[data-email]").forEach((a) => { a.href = "mailto:" + cfg.email; a.textContent = cfg.email; });
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = new FormData(form);
      const subject = `[${f.get("type")}] Message from ${f.get("name")}`;
      const body = `${f.get("message")}\n\n${f.get("name")}\n${f.get("email")}`;
      location.href = `mailto:${cfg.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    });
  }
})();