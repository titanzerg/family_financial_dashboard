"use strict";

const S = { data: null, dashPeriod: null };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NF = new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt = (s) => (s == null ? "" : NF.format(s / 100));
const rawAmt = (s) => (s == null ? "" : (s / 100).toFixed(2));
const signed = (s) => (s == null ? "–" : s > 0 ? "+" + fmt(s) : s < 0 ? "−" + fmt(-s) : "0.00");
const GROUP_VAR = { A: "--gA", B: "--gB", C: "--gC", D: "--gD" };
const gcolor = (code) => `var(${GROUP_VAR[code] || "--accent"})`;

function monthLabel(p, style = "short") {
  if (!p) return "–";
  const [y, m] = p.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("th-TH", { month: style, year: "numeric" });
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), isError ? 5000 : 2200);
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `เกิดข้อผิดพลาด (${res.status})`);
  return data;
}

async function run(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg);
    return r;
  } catch (e) {
    toast(e.message, true);
    throw e;
  }
}

async function load() {
  S.data = await api("GET", "/api/state");
  renderAll();
}

/* ------------------------------------------------------------------ */
/* helpers over state                                                  */
/* ------------------------------------------------------------------ */
function index() {
  const d = S.data;
  const bal = new Map(d.balances.map((b) => [b.account_id + "@" + b.period, b]));
  const sum = new Map(d.summary.map((s) => [s.period, s]));
  const acc = new Map(d.accounts.map((a) => [a.id, a]));
  return { bal, sum, acc };
}

function cellStatus(a, p, entry) {
  if (entry) return entry.is_carried ? "carried" : "entered";
  const m = S.data.account_meta[a.id];
  if (!m.first_period || p < m.first_period) return "not_yet";
  if (a.is_active || p < m.last_period) return "missing";
  return "closed";
}

function carriedFrom(accountId, period, bal) {
  const ps = S.data.periods.filter((p) => p < period).reverse();
  for (const p of ps) {
    const e = bal.get(accountId + "@" + p);
    if (e && !e.is_carried) return p;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Monthly table                                                       */
/* ------------------------------------------------------------------ */
function renderTable() {
  const wrap = $("#table-wrap");
  const d = S.data;
  const { bal, sum } = index();
  const ae = document.activeElement;
  const focusKey = ae?.dataset?.key;
  const pending = focusKey && ae.dataset.dirty === "1" ? ae.value : null; // keep in-progress typing

  if (!d.accounts.length) {
    wrap.innerHTML = `<div class="empty">ยังไม่มีบัญชี — เริ่มจากเพิ่มบัญชีในแท็บ <b>จัดการบัญชี</b></div>`;
    return;
  }
  if (!d.periods.length) {
    wrap.innerHTML = `<div class="empty">ยังไม่มีเดือน — เลือกเดือนแล้วกด <b>+ เพิ่มเดือน</b> ด้านบน</div>`;
    return;
  }
  const showInactive = $("#show-inactive").checked;
  const P = d.periods;
  let h = `<table class="grid"><thead><tr><th class="name">บัญชี</th>`;
  for (const p of P) {
    const s = sum.get(p);
    const del = s.has_data ? "" : `<button class="del" data-del-period="${p}" title="ลบเดือนว่างนี้">✕</button>`;
    h += `<th>${esc(monthLabel(p))}${del}<span class="sub">สิ้นเดือน ${p}</span></th>`;
  }
  h += `</tr></thead><tbody>`;

  for (const g of d.groups) {
    const accs = d.accounts.filter((a) => a.group_code === g.code);
    const visible = accs.filter((a) => a.is_active || showInactive);
    const hidden = accs.length - visible.length;
    h += `<tr class="group-head" style="--gc:${gcolor(g.code)}"><td class="name" title="${esc(g.description)}">${g.code} · ${esc(g.name_th)}${hidden ? ` <span class="muted">(+${hidden} บัญชีที่ซ่อน)</span>` : ""}</td>`;
    for (const p of P) h += `<td>${fmt(sum.get(p).group_totals_satang[g.code])}</td>`;
    h += `</tr>`;
    for (const a of visible) {
      h += `<tr class="${a.is_active ? "" : "inactive"}"><td class="name" title="${esc(a.note || "")}">${esc(a.name)}</td>`;
      for (const p of P) {
        const e = bal.get(a.id + "@" + p);
        const st = cellStatus(a, p, e);
        let title = { missing: "ยังไม่ได้กรอกยอดเดือนนี้", not_yet: "ยังไม่มีบัญชีนี้ในเดือนนี้ (ไม่ใช่ 0)", closed: "บัญชีปิดใช้งานแล้ว", entered: "", carried: "" }[st];
        if (st === "carried") {
          const from = carriedFrom(a.id, p, bal);
          title = `ยอดยกมาจาก ${from ? monthLabel(from) : "เดือนก่อน"} — ยังไม่ได้อัปเดตมูลค่าใหม่ (พิมพ์ยอดเพื่อยืนยัน)`;
        }
        if (e?.note) title += (title ? "\n" : "") + "หมายเหตุ: " + e.note;
        const ph = st === "not_yet" ? "ยังไม่มี" : st === "closed" ? "" : "—";
        h += `<td class="cell ${st}${e?.note ? " has-note" : ""}" title="${esc(title)}"><input inputmode="decimal" data-key="${a.id}@${p}" data-a="${a.id}" data-p="${p}" value="${esc(fmt(e?.amount_satang))}" data-raw="${rawAmt(e?.amount_satang)}" placeholder="${ph}" aria-label="${esc(a.name)} ${p}"></td>`;
      }
      h += `</tr>`;
    }
  }
  h += `</tbody><tfoot><tr class="total"><td class="name">รวมสินทรัพย์ (ยอดที่บันทึก)</td>`;
  for (const p of P) h += `<td>${fmt(sum.get(p).total_satang) || "–"}</td>`;
  h += `</tr><tr class="change"><td class="name">เปลี่ยนแปลงจากเดือนก่อนหน้า</td>`;
  for (const p of P) {
    const s = sum.get(p);
    h += s.prev_period
      ? `<td>${signed(s.change_satang)}<span class="vs">เทียบ ${esc(monthLabel(s.prev_period))}</span></td>`
      : `<td class="muted">${s.has_data ? "เดือนแรก" : "–"}</td>`;
  }
  h += `</tr><tr class="status"><td class="name">สถานะข้อมูล</td>`;
  for (const p of P) {
    const s = sum.get(p);
    const parts = [];
    if (s.missing_accounts.length) parts.push(`<span class="warn">ขาด ${s.missing_accounts.length} บัญชี</span> <button class="ghost" data-carry="${p}" title="เติมช่องว่างด้วยยอดล่าสุด (ทำเครื่องหมายว่ายกมา)">ยกยอด</button>`);
    if (s.carried_count) parts.push(`<span style="color:var(--carried)">↻ ยกมา ${s.carried_count}</span>`);
    if (!parts.length && s.has_data) parts.push(`<span class="muted">ครบ</span>`);
    h += `<td>${parts.join("<br>")}</td>`;
  }
  h += `</tr></tfoot></table>`;
  wrap.innerHTML = h;

  if (focusKey) {
    const el = $(`input[data-key="${CSS.escape(focusKey)}"]`, wrap);
    if (el) {
      el.focus();
      if (pending !== null) { el.value = pending; el.dataset.dirty = "1"; } else el.select();
    }
  }
}

function setupTableEvents() {
  const wrap = $("#table-wrap");
  wrap.addEventListener("focusin", (e) => {
    const i = e.target.closest("td.cell input");
    if (!i) return;
    i.value = i.dataset.raw;
    i.select();
  });
  wrap.addEventListener("focusout", (e) => {
    const i = e.target.closest("td.cell input");
    if (!i) return;
    const v = i.value.trim();
    const norm = v.replace(/[,\s฿]/g, "");
    const dirty = i.dataset.dirty === "1";
    delete i.dataset.dirty;
    // Retyping the same number on a carried cell confirms it as a fresh valuation.
    const isCarried = i.closest("td").classList.contains("carried");
    const same = norm === i.dataset.raw || (norm !== "" && i.dataset.raw !== "" && Number(norm) === Number(i.dataset.raw));
    if (!dirty || (same && !isCarried)) {
      i.value = i.dataset.raw === "" ? "" : NF.format(Number(i.dataset.raw));
      return;
    }
    if (norm === "" && i.dataset.raw !== "" && !confirm("ล้างยอดของช่องนี้ (กลับเป็น “ยังไม่บันทึก”)?")) {
      i.value = NF.format(Number(i.dataset.raw));
      return;
    }
    run(() => api("PUT", "/api/balances", { account_id: i.dataset.a, period: i.dataset.p, amount: v }), "บันทึกแล้ว")
      .then(load)
      .catch(() => { i.value = i.dataset.raw; });
  });
  wrap.addEventListener("input", (e) => {
    const i = e.target.closest("td.cell input");
    if (i) i.dataset.dirty = "1";
  });
  wrap.addEventListener("keydown", (e) => {
    const i = e.target.closest("td.cell input");
    if (!i) return;
    if (e.key === "Enter" || e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const col = $$(`input[data-p="${i.dataset.p}"]`, wrap);
      const next = col[col.indexOf(i) + (e.key === "ArrowUp" ? -1 : 1)];
      if (next) next.focus(); else i.blur();
    } else if (e.key === "Escape") {
      delete i.dataset.dirty;
      i.value = i.dataset.raw;
      i.blur();
    }
  });
  wrap.addEventListener("contextmenu", (e) => {
    const i = e.target.closest("td.cell")?.querySelector("input");
    if (!i) return;
    e.preventDefault();
    const entry = S.data.balances.find((b) => b.account_id === i.dataset.a && b.period === i.dataset.p);
    if (!entry) return toast("กรอกยอดก่อน แล้วจึงใส่หมายเหตุได้", true);
    const note = prompt("หมายเหตุสำหรับยอดนี้ (เว้นว่างเพื่อลบ):", entry.note || "");
    if (note === null) return;
    run(() => api("PUT", "/api/balances", { account_id: i.dataset.a, period: i.dataset.p, note }), "บันทึกหมายเหตุแล้ว").then(load);
  });
  wrap.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del-period]");
    if (del) {
      const p = del.dataset.delPeriod;
      if (confirm(`ลบเดือน ${p} (ยังไม่มียอดบันทึก)?`))
        run(() => api("DELETE", `/api/periods/${p}`), "ลบเดือนแล้ว").then(load);
    }
    const carry = e.target.closest("[data-carry]");
    if (carry) {
      const p = carry.dataset.carry;
      if (confirm(`เติมช่องว่างของเดือน ${p} ด้วยยอดล่าสุดของแต่ละบัญชี?\nยอดเหล่านี้จะถูกทำเครื่องหมาย “ยกมา” จนกว่าคุณจะกรอกยอดจริง`))
        run(() => api("POST", `/api/periods/${p}/carry`, {}), (r) => `ยกยอด ${r.carried} บัญชี`).then(load);
    }
  });
  $("#show-inactive").addEventListener("change", renderTable);

  $("#add-period-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const period = f.period.value;
    run(() => api("POST", "/api/periods", { period, carry_groups: f.carry.checked ? ["C"] : [] }),
      (r) => `เพิ่มเดือน ${monthLabel(r.period)} แล้ว` + (r.carried ? ` (ยกยอด ${r.carried} บัญชี)` : ""))
      .then(load);
  });
}

function suggestNextPeriod() {
  const P = S.data.periods;
  let y, m;
  if (P.length) {
    [y, m] = P[P.length - 1].split("-").map(Number);
    m += 1; if (m > 12) { m = 1; y += 1; }
  } else {
    const now = new Date(); y = now.getFullYear(); m = now.getMonth() + 1;
  }
  $("#add-period-form").period.value = `${y}-${String(m).padStart(2, "0")}`;
}

/* ------------------------------------------------------------------ */
/* Dashboard                                                           */
/* ------------------------------------------------------------------ */
function renderDashboard() {
  const d = S.data;
  const el = $("#dashboard");
  const sel = $("#dash-period");
  const withData = d.summary.filter((s) => s.has_data);
  if (!withData.length) {
    sel.innerHTML = "";
    el.innerHTML = `<div class="card empty">ยังไม่มียอดที่บันทึก — กรอกยอดในแท็บ <b>ตารางรายเดือน</b> ก่อน</div>`;
    return;
  }
  if (!S.dashPeriod || !withData.some((s) => s.period === S.dashPeriod)) S.dashPeriod = d.latest_period;
  sel.innerHTML = withData.slice().reverse().map((s) => `<option value="${s.period}" ${s.period === S.dashPeriod ? "selected" : ""}>${esc(monthLabel(s.period, "long"))}</option>`).join("");

  const { bal, sum, acc } = index();
  const s = sum.get(S.dashPeriod);
  const prev = s.prev_period ? sum.get(s.prev_period) : null;
  const gt = s.group_totals_satang;
  const groupD = d.accounts.filter((a) => a.group_code === "D");

  let h = "";
  const notices = [];
  if (s.missing_accounts.length) notices.push(`เดือนนี้ยังไม่ได้กรอก ${s.missing_accounts.length} บัญชี (${s.missing_accounts.map((id) => esc(acc.get(id).name)).join(", ")}) — ยอดรวมจึงยังไม่ครบ`);
  if (s.carried_count) notices.push(`มี ${s.carried_count} บัญชีที่ใช้ยอดยกมาจากเดือนก่อน (${s.carried_accounts.map((id) => esc(acc.get(id).name)).join(", ")}) — ยังไม่ใช่มูลค่าที่ตรวจสอบใหม่`);
  if (prev && (prev.missing_accounts.length)) notices.push(`เดือนที่ใช้เปรียบเทียบ (${esc(monthLabel(prev.period))}) มีข้อมูลไม่ครบ ${prev.missing_accounts.length} บัญชี`);
  if (notices.length) h += `<div class="notice">${notices.join("<br>")}</div>`;

  h += `<div class="kpis">
    <div class="card kpi"><div class="label">รวมสินทรัพย์ ณ สิ้นเดือน ${esc(monthLabel(s.period, "long"))}</div>
      <div class="value">฿${fmt(s.total_satang)}</div>
      <div class="note">ผลรวมยอดคงเหลือของทุกบัญชีที่บันทึก — รวมเงินที่กันไว้ใช้ตามแผน เงินลงทุน และเงินสำรองโปะบ้าน <b>ไม่ใช่เงินที่ใช้จ่ายได้ทันทีทั้งหมด</b></div></div>
    <div class="card kpi"><div class="label">${prev ? `เปลี่ยนแปลงเทียบกับสิ้นเดือน ${esc(monthLabel(prev.period, "long"))}` : "เปลี่ยนแปลงจากเดือนก่อนหน้า"}</div>
      <div class="value">${prev ? signed(s.change_satang) : "–"}</div>
      <div class="note">${prev ? `฿${fmt(prev.total_satang)} → ฿${fmt(s.total_satang)} · เป็นผลต่างของยอดรวมที่บันทึกเท่านั้น ไม่ได้แสดงรายรับ รายจ่าย หรือเงินออม` : "เป็นเดือนแรกที่มีการบันทึก จึงยังไม่มีเดือนให้เปรียบเทียบ"}</div></div>
    <div class="card kpi" style="border-top:3px solid ${gcolor("D")}"><div class="label">เงินสำรองโปะบ้าน (กลุ่ม D)</div>
      <div class="value">${gt.D == null ? "–" : "฿" + fmt(gt.D)}</div>
      <div class="note">${groupD.map((a) => { const e = bal.get(a.id + "@" + s.period); return `${esc(a.name)}: ${e ? "฿" + fmt(e.amount_satang) : "ไม่มีข้อมูล"}`; }).join(" · ") || "ยังไม่มีบัญชีในกลุ่มนี้"}</div></div>
    <div class="card kpi"><div class="label">ข้อมูลล่าสุดที่บันทึก</div>
      <div class="value" style="font-size:22px">สิ้นเดือน ${esc(monthLabel(d.latest_period, "long"))}</div>
      <div class="note">เดือนที่เลือก: กรอกแล้ว ${s.entered_count} · ยกมา ${s.carried_count} · ยังไม่กรอก ${s.missing_accounts.length} บัญชี</div></div>
  </div>`;

  h += `<div class="dash-grid">`;
  h += `<div class="card"><h3>แนวโน้มสินทรัพย์รวม (ยอดสิ้นเดือน)</h3>${trendChart(withData, s.period)}</div>`;

  // groups
  const maxAbs = Math.max(1, ...d.groups.map((g) => Math.abs(gt[g.code] || 0)));
  h += `<div class="card"><h3>แยกตามวัตถุประสงค์ของเงิน · ${esc(monthLabel(s.period))}</h3><div class="bars">`;
  for (const g of d.groups) {
    const v = gt[g.code];
    const pv = prev ? prev.group_totals_satang[g.code] : null;
    const delta = v != null && pv != null ? ` <span class="muted" style="font-size:12px">(${signed(v - pv)})</span>` : "";
    const pct = s.total_satang ? Math.round(((v || 0) / s.total_satang) * 1000) / 10 : 0;
    h += `<div class="row"><span><b style="color:${gcolor(g.code)}">${g.code}</b> ${esc(g.name_th)}</span>
      <span class="num">${v == null ? "–" : "฿" + fmt(v)}${delta} <span class="muted" style="font-size:12px">${v == null ? "" : pct + "%"}</span></span>
      <div class="track"><div class="fill" style="width:${(Math.abs(v || 0) / maxAbs) * 100}%;background:${gcolor(g.code)}"></div></div>
      <div class="desc">${esc(g.description)}</div></div>`;
  }
  h += `</div>${prev ? `<p class="muted" style="font-size:12px;margin:0">ตัวเลขในวงเล็บ = เปลี่ยนแปลงเทียบกับ ${esc(monthLabel(prev.period))}</p>` : ""}</div>`;

  // per-account detail for selected month
  h += `<div class="card"><h3>ยอดรายบัญชี · สิ้นเดือน ${esc(monthLabel(s.period))}</h3><table class="simple"><thead><tr><th>บัญชี</th><th class="num">ยอด</th><th class="num">${prev ? "เทียบ " + esc(monthLabel(prev.period)) : ""}</th><th>อัปเดตมูลค่าล่าสุด</th></tr></thead><tbody>`;
  for (const g of d.groups) {
    const accs = d.accounts.filter((a) => a.group_code === g.code && (a.is_active || bal.has(a.id + "@" + s.period)));
    if (!accs.length) continue;
    h += `<tr><td colspan="4" style="color:${gcolor(g.code)};font-weight:600">${g.code} · ${esc(g.name_th)}</td></tr>`;
    for (const a of accs) {
      const e = bal.get(a.id + "@" + s.period);
      const pe = prev ? bal.get(a.id + "@" + prev.period) : null;
      const verified = e && !e.is_carried ? s.period : carriedFrom(a.id, s.period, bal);
      h += `<tr><td>${esc(a.name)}</td><td class="num">${e ? fmt(e.amount_satang) + (e.is_carried ? ' <span style="color:var(--carried)" title="ยอดยกมา">↻</span>' : "") : '<span class="muted">ไม่มีข้อมูล</span>'}</td>
        <td class="num muted">${e && pe ? signed(e.amount_satang - pe.amount_satang) : ""}</td>
        <td class="muted">${verified ? esc(monthLabel(verified)) : "–"}</td></tr>`;
    }
  }
  h += `</tbody></table></div>`;
  h += `</div>`;
  el.innerHTML = h;
}

function trendChart(rows, selected) {
  const W = 640, H = 230, L = 70, R = 14, T = 14, B = 34;
  const vals = rows.map((r) => r.total_satang / 100);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const x = (i) => L + (rows.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (rows.length - 1));
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const compact = new Intl.NumberFormat("th-TH", { notation: "compact", maximumFractionDigits: 1 });
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4;
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${compact.format(v)}</text>`;
  }
  const step = Math.ceil(rows.length / 8);
  rows.forEach((r, i) => {
    if (i % step === 0 || i === rows.length - 1) g += `<text x="${x(i)}" y="${H - 12}" text-anchor="middle">${esc(monthLabel(r.period))}</text>`;
  });
  const path = rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(vals[i]).toFixed(1)}`).join("");
  g += `<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>`;
  rows.forEach((r, i) => {
    const sel = r.period === selected;
    g += `<circle cx="${x(i)}" cy="${y(vals[i])}" r="${sel ? 5.5 : 3.5}" fill="${sel ? "var(--accent)" : "var(--surface)"}" stroke="var(--accent)" stroke-width="2"><title>${esc(monthLabel(r.period, "long"))}: ฿${fmt(r.total_satang)}${r.change_satang != null ? " (" + signed(r.change_satang) + ")" : ""}</title></circle>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="แนวโน้มสินทรัพย์รวม">${g}</svg>`;
}

/* ------------------------------------------------------------------ */
/* Accounts                                                            */
/* ------------------------------------------------------------------ */
function renderAccounts() {
  const d = S.data;
  $("#new-account-group").innerHTML = d.groups.map((g) => `<option value="${g.code}">${g.code} · ${esc(g.name_th)}</option>`).join("");
  const opts = (cur) => d.groups.map((g) => `<option value="${g.code}" ${g.code === cur ? "selected" : ""}>${g.code} · ${esc(g.name_th)}</option>`).join("");
  let h = "";
  for (const g of d.groups) {
    const accs = d.accounts.filter((a) => a.group_code === g.code);
    h += `<div class="card acc-group" style="--gc:${gcolor(g.code)}"><h3>${g.code} · ${esc(g.name_th)} <small class="muted">${esc(g.name_en)}</small></h3>`;
    if (!accs.length) h += `<p class="muted">ยังไม่มีบัญชีในกลุ่มนี้</p>`;
    accs.forEach((a, i) => {
      const m = d.account_meta[a.id];
      h += `<div class="acc-row ${a.is_active ? "" : "inactive"}" data-id="${a.id}">
        <span><button class="ghost" data-move="up" ${i === 0 ? "disabled" : ""} title="เลื่อนขึ้น">↑</button><button class="ghost" data-move="down" ${i === accs.length - 1 ? "disabled" : ""} title="เลื่อนลง">↓</button></span>
        <span><input name="name" value="${esc(a.name)}" maxlength="100" style="width:100%"><span class="id">${a.id}${m.first_period ? ` · มีข้อมูล ${m.first_period} ถึง ${m.last_period}` : " · ยังไม่มียอด"}</span></span>
        <select name="group_code">${opts(a.group_code)}</select>
        <input name="note" value="${esc(a.note || "")}" placeholder="หมายเหตุ" maxlength="500">
        <button class="ghost" data-toggle>${a.is_active ? "ปิดใช้งาน" : "เปิดใช้งานอีกครั้ง"}</button>
      </div>`;
    });
    h += `</div>`;
  }
  $("#accounts-list").innerHTML = h;
}

function setupAccountEvents() {
  const list = $("#accounts-list");
  const patch = (id, body, msg) => run(() => api("PATCH", `/api/accounts/${id}`, body), msg).then(load, load);
  list.addEventListener("change", (e) => {
    const row = e.target.closest(".acc-row");
    if (!row) return;
    const id = row.dataset.id;
    const a = S.data.accounts.find((x) => x.id === id);
    const f = e.target.name;
    if (f === "name") {
      if (e.target.value.trim() === a.name) return;
      patch(id, { name: e.target.value }, "เปลี่ยนชื่อแล้ว — ประวัติยอดยังผูกกับบัญชีเดิม");
    } else if (f === "note") {
      patch(id, { note: e.target.value }, "บันทึกหมายเหตุแล้ว");
    } else if (f === "group_code") {
      if (!confirm(`ย้าย “${a.name}” ไปกลุ่ม ${e.target.value}?\nประวัติยอดทั้งหมดจะย้ายไปด้วย (ยอดรวมกลุ่มของเดือนก่อน ๆ จะเปลี่ยนตาม)`)) {
        e.target.value = a.group_code;
        return;
      }
      patch(id, { group_code: e.target.value }, "ย้ายกลุ่มแล้ว");
    }
  });
  list.addEventListener("click", (e) => {
    const row = e.target.closest(".acc-row");
    if (!row) return;
    const id = row.dataset.id;
    const a = S.data.accounts.find((x) => x.id === id);
    const mv = e.target.closest("[data-move]");
    if (mv) run(() => api("POST", `/api/accounts/${id}/move`, { direction: mv.dataset.move })).then(load);
    if (e.target.closest("[data-toggle]")) {
      const msg = a.is_active
        ? `ปิดใช้งาน “${a.name}”?\nประวัติยอดเดิมยังเก็บไว้และนับในยอดรวมของเดือนที่บันทึกไว้ แต่จะไม่ถูกนับว่า “ขาด” ในเดือนถัดไป`
        : `เปิดใช้งาน “${a.name}” อีกครั้ง?`;
      if (confirm(msg)) patch(id, { is_active: !a.is_active }, a.is_active ? "ปิดใช้งานแล้ว" : "เปิดใช้งานแล้ว");
    }
  });
  $("#add-account-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    run(() => api("POST", "/api/accounts", { name: f.name.value, group_code: f.group_code.value, note: f.note.value }), "เพิ่มบัญชีแล้ว")
      .then(() => { f.name.value = ""; f.note.value = ""; return load(); });
  });
}

/* ------------------------------------------------------------------ */
/* Data / backup                                                       */
/* ------------------------------------------------------------------ */
const ACTION_TH = { create: "สร้าง", update: "แก้ไข", clear: "ล้างยอด", carry: "ยกยอด", note: "หมายเหตุ", delete: "ลบ", restore: "กู้คืน" };

async function renderDataTab() {
  const [audit, bk] = await Promise.all([api("GET", "/api/audit"), api("GET", "/api/backups")]);
  const names = new Map(S.data.accounts.map((a) => [a.id, a.name]));
  const label = (r) => {
    if (r.entity === "balance") { const [id, p] = r.entity_id.split("@"); return `${esc(names.get(id) || id)} · ${p}`; }
    if (r.entity === "account") return esc(names.get(r.entity_id) || r.entity_id);
    return esc(r.entity_id);
  };
  const val = (j) => {
    if (!j) return "";
    const o = JSON.parse(j);
    if ("amount_satang" in o) return fmt(o.amount_satang) + (o.from_period ? ` (จาก ${o.from_period})` : "") + (o.note ? ` · ${esc(o.note)}` : "");
    return esc(Object.entries(o).map(([k, v]) => `${k}: ${v}`).join(", "));
  };
  $("#audit").innerHTML = audit.length
    ? `<table class="simple"><thead><tr><th>เวลา</th><th>การกระทำ</th><th>รายการ</th><th>ค่าเดิม</th><th>ค่าใหม่</th></tr></thead><tbody>${audit.map((r) =>
      `<tr><td class="muted">${esc(r.ts.replace("T", " "))}</td><td>${ACTION_TH[r.action] || esc(r.action)}</td><td>${label(r)}</td><td class="muted">${val(r.old_value)}</td><td>${val(r.new_value)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="muted" style="padding:10px">ยังไม่มีประวัติ</p>`;
  $("#backup-list").innerHTML = `<p>โฟลเดอร์: <code>${esc(bk.dir)}</code></p>` + (bk.files.map((f) => `<div>${esc(f)}</div>`).join("") || "ยังไม่มีไฟล์สำรอง");
}

function setupDataEvents() {
  $("#backup-now").addEventListener("click", () =>
    run(() => api("POST", "/api/backup"), "สำรองข้อมูลแล้ว").then((r) => { $("#backup-msg").textContent = r.path; renderDataTab(); }));
  $("#restore-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); } catch { return toast("ไฟล์ JSON ไม่ถูกต้อง", true); }
    const n = (data.balances || []).length;
    if (!confirm(`กู้คืนจาก “${file.name}”?\n(${(data.accounts || []).length} บัญชี, ${n} ยอด, ส่งออกเมื่อ ${data.exported_at || "?"})\n\nข้อมูลปัจจุบันทั้งหมดจะถูกแทนที่ — ระบบจะสำรองไว้ให้ก่อน`)) return;
    run(() => api("POST", "/api/restore", data), "กู้คืนข้อมูลเรียบร้อย").then(load).then(renderDataTab);
  });
}

/* ------------------------------------------------------------------ */
function renderAll() {
  renderTable();
  renderDashboard();
  renderAccounts();
  if (!$("#add-period-form").period.value) suggestNextPeriod();
}

function setupTabs() {
  $$("nav button").forEach((b) =>
    b.addEventListener("click", () => {
      $$("nav button").forEach((x) => x.classList.toggle("active", x === b));
      $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
      try { localStorage.setItem("ffd-tab", b.dataset.tab); } catch {}
      if (b.dataset.tab === "data") renderDataTab().catch((e) => toast(e.message, true));
    }));
  let saved = null;
  try { saved = localStorage.getItem("ffd-tab"); } catch {}
  if (saved) $(`nav button[data-tab="${saved}"]`)?.click();
}

$("#dash-period").addEventListener("change", (e) => { S.dashPeriod = e.target.value; renderDashboard(); });
setupTableEvents();
setupAccountEvents();
setupDataEvents();
load().then(setupTabs).catch((e) => toast(e.message, true));
