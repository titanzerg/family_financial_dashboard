"use strict";

const S = { data: null, dashPeriod: null, dlg: null, collapsed: new Set() };
try { S.collapsed = new Set(JSON.parse(localStorage.getItem("ffd-collapsed") || "[]")); } catch {}
function saveCollapsed() { try { localStorage.setItem("ffd-collapsed", JSON.stringify([...S.collapsed])); } catch {} }
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NF = new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt = (s) => (s == null ? "" : NF.format(s / 100));
const rawAmt = (s) => (s == null ? "" : (s / 100).toFixed(2));
const signed = (s) => (s == null ? "–" : s > 0 ? "+" + fmt(s) : s < 0 ? "−" + fmt(-s) : "0.00");
const GROUP_VAR = { A: "--gA", B: "--gB", C: "--gC", D: "--gD" };
const EXTRA_VARS = ["--gE", "--gF", "--gG"];

function gcolor(code) {
  if (GROUP_VAR[code]) return `var(${GROUP_VAR[code]})`;
  const extra = (S.data?.groups || []).filter((g) => !GROUP_VAR[g.code]).map((g) => g.code);
  const i = Math.max(0, extra.indexOf(code));
  return `var(${EXTRA_VARS[i % EXTRA_VARS.length]})`;
}
const gLabel = (g) => (g.code.length === 1 ? `${g.code} · ` : "") + g.name_th;
const roleLabel = (r) => (r ? S.data.roles[r].label : "");

function monthLabel(p, style = "short") {
  if (!p) return "–";
  const [y, m] = p.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("th-TH", { month: style, year: "numeric" });
}
function prevMonth(p) {
  let [y, m] = p.split("-").map(Number);
  m -= 1; if (m === 0) { m = 12; y -= 1; }
  return `${y}-${String(m).padStart(2, "0")}`;
}
function nextMonth(p) {
  let [y, m] = p.split("-").map(Number);
  m += 1; if (m === 13) { m = 1; y += 1; }
  return `${y}-${String(m).padStart(2, "0")}`;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), isError ? 6000 : 2600);
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
  const bal = new Map(d.balances.map((b) => [bkey(b.account_id, b.period), b]));
  const sum = new Map(d.summary.map((s) => [s.period, s]));
  const acc = new Map(d.accounts.map((a) => [a.id, a]));
  const grp = new Map(d.groups.map((g) => [g.code, g]));
  return { bal, sum, acc, grp };
}
const bkey = (aid, p) => `${aid}@${p}`;

function cellStatus(a, p, entry) {
  if (entry) return entry.source === "carried" ? "carried" : entry.source === "allocated" ? "allocated" : "entered";
  const m = S.data.account_meta[a.id];
  if (!m.first_period || p < m.first_period) return "not_yet";
  if (a.is_active || p < m.last_period) return "missing";
  return "closed";
}

function carriedFrom(accountId, period, bal) {
  const ps = S.data.periods.filter((p) => p < period).reverse();
  for (const p of ps) {
    const e = bal.get(bkey(accountId, p));
    if (e && e.source !== "carried") return p;
  }
  return null;
}

/** Later automatic values that follow this balance (same rule as the server). */
function dependentsLocal(aid, period) {
  const rows = S.data.balances.filter((b) => b.account_id === aid && b.period > period).sort((x, y) => (x.period < y.period ? -1 : 1));
  const out = [];
  for (const b of rows) {
    out.push(b);
    if (b.source === "manual") break;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Monthly table                                                       */
/* ------------------------------------------------------------------ */
function allocCell(s) {
  const al = s.allocation;
  if (!al) return `<button data-alloc="${s.period}" title="ใช้เงินเดือนที่เข้าปลาย ${esc(monthLabel(prevMonth(s.period)))}">จัดสรรเงินเดือน</button>`;
  const t = al.calc.transfers;
  return `<span title="A-2 ${fmt(t.A2)} · A-3 ${fmt(t.A3)} · A-1 ${fmt(t.A1)} · LH ${fmt(t.LH)}">LH ${fmt(t.LH)} ✓</span><br><button class="ghost" data-alloc="${s.period}">เปิด</button>`;
}

/** Small "(โอน x)" line under the LH balance of a month with a confirmed allocation. */
function lhTransferNote(a, s) {
  const c = s.allocation?.calc;
  if (!c || c.accounts.LH !== a.id || c.transfers.LH == null) return "";
  return `<span class="xfer-note" title="ยอดโอนไป LH จากการจัดสรรเงินเดือนของเดือนนี้">(โอน ${fmt(c.transfers.LH)})</span>`;
}

function renderTable() {
  const wrap = $("#table-wrap");
  const d = S.data;
  const { bal, sum } = index();
  const ae = document.activeElement;
  const focusKey = ae?.dataset?.key;
  const pending = focusKey && ae.dataset.dirty === "1" ? ae.value : null; // keep in-progress typing

  const cg = d.groups.find((g) => g.code === "C" && g.is_active);
  $("#carry-label").hidden = !cg;
  if (cg) $("#carry-label span").textContent = `ยกยอดกลุ่ม “${cg.name_th}” จากเดือนก่อน`;

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
    const del = !s.has_data && !s.allocation ? `<button class="del" data-del-period="${p}" title="ลบเดือนว่างนี้">✕</button>` : "";
    h += `<th>${esc(monthLabel(p, "long"))}${del}</th>`;
  }
  h += `</tr></thead><tbody>`;

  for (const g of d.groups) {
    const accs = d.accounts.filter((a) => a.group_code === g.code);
    if (!g.is_active && !showInactive) continue;
    if (!accs.length && !g.is_active) continue;
    const visible = accs.filter((a) => a.is_active || showInactive);
    const hidden = accs.length - visible.length;
    const shut = S.collapsed.has(g.code);
    h += `<tr class="group-head" style="--gc:${gcolor(g.code)}"><td class="name" title="${esc(g.description)}"><button class="fold" data-fold="${g.code}" aria-expanded="${!shut}" title="${shut ? "แสดง" : "ซ่อน"}รายการบัญชีในกลุ่มนี้">${shut ? "▸" : "▾"}</button>${esc(gLabel(g))}${shut ? ` <span class="muted fold-count">(${visible.length} บัญชี)</span>` : ""}${g.is_active ? "" : ' <span class="muted">(ปิดใช้งาน)</span>'}${hidden ? ` <span class="muted">(+${hidden} บัญชีที่ซ่อน)</span>` : ""}</td>`;
    for (const p of P) h += `<td>${fmt(sum.get(p).group_totals_satang[g.code])}</td>`;
    h += `</tr>`;
    for (const a of shut ? [] : visible) {
      const role = a.role ? ` <span class="badge" title="${esc(d.roles[a.role].desc)}">${roleLabel(a.role)}</span>` : "";
      h += `<tr class="acc ${a.is_active ? "" : "inactive"}" style="--gc:${gcolor(g.code)}"><td class="name" title="${esc(a.note || "")}">${esc(a.name)}${role}</td>`;
      for (const p of P) {
        const e = bal.get(bkey(a.id, p));
        const st = cellStatus(a, p, e);
        let title = { missing: "ยังไม่ได้กรอกยอด", not_yet: "ยังไม่มีบัญชีนี้ในเดือนนี้ (ไม่ใช่ 0)", closed: "บัญชีปิดใช้งานแล้ว", entered: "", allocated: "ระบบเติมให้จากการจัดสรรเงินเดือน — เทียบกับแอปธนาคาร แล้วแก้ได้", carried: "" }[st];
        if (st === "carried") {
          const from = carriedFrom(a.id, p, bal);
          title = `ยอดยกมาจาก ${from ? monthLabel(from) : "เดือนก่อน"} — ยังไม่ได้ตรวจยอดใหม่ (พิมพ์ยอดเพื่อยืนยัน)`;
        }
        if (e?.note) title += (title ? "\n" : "") + "หมายเหตุ: " + e.note;
        const ph = st === "not_yet" ? "ยังไม่มี" : st === "closed" ? "" : "—";
        h += `<td class="cell ${st}${e?.note ? " has-note" : ""}${e && e.amount_satang < 0 ? " neg" : ""}" title="${esc(title)}"><input inputmode="decimal" data-key="${bkey(a.id, p)}" data-a="${a.id}" data-p="${p}" value="${esc(fmt(e?.amount_satang))}" data-raw="${rawAmt(e?.amount_satang)}" placeholder="${ph}" aria-label="${esc(a.name)} ${p}">${lhTransferNote(a, sum.get(p))}</td>`;
      }
      h += `</tr>`;
    }
  }
  h += `</tbody><tfoot><tr class="total"><td class="name">รวมสินทรัพย์</td>`;
  for (const p of P) h += `<td>${fmt(sum.get(p).total_satang) || "–"}</td>`;
  h += `</tr><tr class="change"><td class="name">เปลี่ยนแปลงจากเดือนก่อนหน้า</td>`;
  for (const p of P) {
    const s = sum.get(p);
    h += s.prev_period
      ? `<td>${signed(s.change_satang)}<span class="vs">เทียบ ${esc(monthLabel(s.prev_period))}</span></td>`
      : `<td class="muted">${s.has_data ? "เดือนแรก" : "–"}</td>`;
  }
  h += `</tr><tr class="plan"><td class="name">จัดสรรเงินเดือน<span class="vs">เงินเดือนที่เข้าปลายเดือนก่อนหน้า</span></td>`;
  for (const p of P) h += `<td>${allocCell(sum.get(p))}</td>`;
  h += `</tr><tr class="status"><td class="name">สถานะ</td>`;
  for (const p of P) {
    const s = sum.get(p);
    const parts = [];
    if (s.missing_accounts.length) parts.push(`<span class="warn">ขาด ${s.missing_accounts.length} บัญชี</span> <button class="ghost" data-carry="${p}" title="เติมช่องที่ว่างด้วยยอดล่าสุด (ทำเครื่องหมายว่ายกมา)">ยกยอด</button>`);
    if (s.allocated_count) parts.push(`<span style="color:var(--transfer)">⇄ ระบบเติม ${s.allocated_count}</span>`);
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

/** Warnings for dependent values before a balance edit (spec 7 / 9). */
function editWarnings(aid, period) {
  const { sum } = index();
  const out = [];
  for (const b of dependentsLocal(aid, period)) {
    if (b.source === "manual") { out.push(`• ยอด ${monthLabel(b.period)} ของบัญชีนี้กรอกเองไว้ — จะไม่ถูกเปลี่ยน`); break; }
    out.push(`• ยอด ${monthLabel(b.period)} ของบัญชีนี้ ${b.source === "allocated" ? "(ระบบเติมจากการจัดสรร)" : "(ยกมา)"} จะถูกคำนวณใหม่ตามยอดนี้`);
  }
  if (out.length && [...sum.values()].some((x) => x.prev_period === period))
    out.push(`• ยอดรวมและส่วนต่างเทียบเดือนถัดไปจะคำนวณใหม่`);
  return out;
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
    // Retyping the same number on an automatic cell confirms it as checked (becomes manual).
    const td = i.closest("td");
    const isAuto = td.classList.contains("carried") || td.classList.contains("allocated");
    const same = norm === i.dataset.raw || (norm !== "" && i.dataset.raw !== "" && Number(norm) === Number(i.dataset.raw));
    const restore = () => { i.value = i.dataset.raw === "" ? "" : NF.format(Number(i.dataset.raw)); };
    if (!dirty || (same && !isAuto)) return restore();
    if (norm === "" && i.dataset.raw !== "" && !confirm(`ล้างยอดของช่องนี้ (กลับเป็น “ยังไม่บันทึก”)?`)) return restore();
    const w = editWarnings(i.dataset.a, i.dataset.p);
    if (w.length && !confirm(`การแก้ไขนี้มีผลกับค่าอื่น:\n${w.join("\n")}\n\nบันทึกต่อ?`)) return restore();
    run(() => api("PUT", "/api/balances", { account_id: i.dataset.a, period: i.dataset.p, amount: v }),
      (r) => "บันทึกแล้ว" + (r.propagated?.length ? ` · อัปเดตยอดอัตโนมัติ ${r.propagated.map((x) => monthLabel(x.period)).join(", ")} แล้ว` : ""))
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
    const note = prompt(`หมายเหตุสำหรับยอดนี้ (เว้นว่างเพื่อลบ):`, entry.note || "");
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
      if (confirm(`เติมช่องที่ว่างของ ${p} ด้วยยอดล่าสุดของแต่ละบัญชี?\nยอดเหล่านี้จะถูกทำเครื่องหมาย “ยกมา” จนกว่าคุณจะกรอกยอดจริง`))
        run(() => api("POST", `/api/periods/${p}/carry`, {}), (r) => `ยกยอด ${r.carried} บัญชี`).then(load);
    }
    const fold = e.target.closest("[data-fold]");
    if (fold) {
      const c = fold.dataset.fold;
      S.collapsed.has(c) ? S.collapsed.delete(c) : S.collapsed.add(c);
      saveCollapsed();
      return renderTable();
    }
    const al = e.target.closest("[data-alloc]");
    if (al) openAllocDialog(al.dataset.alloc);
  });
  $("#show-inactive").addEventListener("change", renderTable);
  $("#fold-all").addEventListener("click", () => {
    const codes = S.data.groups.map((g) => g.code);
    const allShut = codes.every((c) => S.collapsed.has(c));
    S.collapsed = new Set(allShut ? [] : codes);
    saveCollapsed();
    renderTable();
  });

  $("#add-period-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const period = f.period.value;
    const carry = !$("#carry-label").hidden && f.carry.checked ? ["C"] : [];
    run(() => api("POST", "/api/periods", { period, carry_groups: carry }),
      (r) => `เพิ่มเดือน ${monthLabel(r.period)} แล้ว` + (r.carried ? ` (ยกยอด ${r.carried} บัญชี)` : ""))
      .then(load)
      .then(() => openAllocDialog(period));
  });
}

function suggestNextPeriod() {
  const P = S.data.periods;
  let v;
  if (P.length) v = nextMonth(P[P.length - 1]);
  else { const now = new Date(); v = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`; }
  $("#add-period-form").period.value = v;
}

/* ------------------------------------------------------------------ */
/* Salary allocation — จัดสรรเงินเดือน (spec v0.3 §3)                    */
/* ------------------------------------------------------------------ */
const ALLOC_FIELDS = ["salary", "a2", "a3", "keep"];

function openAllocDialog(period) {
  const dlg = $("#alloc-dialog");
  const al = S.data.summary.find((s) => s.period === period)?.allocation;
  const inputs = { salary: "", a2: "", a3: "", keep: "0" };
  if (al) for (const k of ALLOC_FIELDS) inputs[k] = al.inputs[k] ?? inputs[k];
  S.dlg = { period, inputs, preview: null, seq: 0 };
  renderAllocShell();
  if (!dlg.open) dlg.showModal();
  refreshAlloc();
  $("#alloc-in-salary")?.focus();
}

function renderAllocShell() {
  const { period, inputs } = S.dlg;
  const d = S.data;
  const al = d.summary.find((s) => s.period === period)?.allocation;
  const name = (r) => esc(d.accounts.find((a) => a.role === r)?.name || "ยังไม่ได้กำหนด");
  const field = (k, label, help) => `<label class="alloc-in"><span>${label}<small>${help}</small></span>
    <input id="alloc-in-${k}" data-in="${k}" inputmode="decimal" value="${esc(inputs[k])}" placeholder="0.00"></label>`;
  $("#alloc-body").innerHTML = `<h2 id="alloc-title">จัดสรรเงินเดือน · ยอดเดือน ${esc(monthLabel(period, "long"))}</h2>
    <p class="muted" style="margin:0">ใช้เงินเดือนที่เข้าปลาย ${esc(monthLabel(prevMonth(period), "long"))} · ทำหลังจ่ายบัตรเครดิตจาก A-2/A-3 แล้ว${al ? ` · <b>ยืนยันไว้แล้วเมื่อ ${esc(al.confirmed_at.replace("T", " "))}</b>` : ""}</p>
    <h3><span class="step">1</span>กรอกยอดจากแอปธนาคาร</h3>
    <div class="alloc-inputs">
      ${field("salary", "ยอดบัญชีเงินเดือน หลังเงินเดือนเข้า", name("SAL"))}
      ${field("a2", "ยอด A-2 หลังจ่ายบัตรเครดิต", name("A2"))}
      ${field("a3", "ยอด A-3 หลังจ่ายบัตรเครดิต", name("A3"))}
      ${field("keep", "เงินที่ค้างไว้ในบัญชีเงินเดือน", "ปกติ 0 = โอนที่เหลือไป LH ทั้งหมด")}
    </div>
    <div id="alloc-result"></div>`;
}

let allocTimer = null;
function scheduleAlloc() {
  clearTimeout(allocTimer);
  allocTimer = setTimeout(refreshAlloc, 250);
}

async function refreshAlloc() {
  if (!S.dlg) return;
  const seq = ++S.dlg.seq;
  const { period, inputs } = S.dlg;
  try {
    const pv = await api("POST", `/api/allocations/${period}/preview`, { inputs });
    if (!S.dlg || seq !== S.dlg.seq) return;
    S.dlg.preview = pv;
    renderAllocResult();
  } catch (e) {
    if (S.dlg && seq === S.dlg.seq) $("#alloc-result").innerHTML = `<div class="problems">${esc(e.message)}</div>`;
  }
}

function rowSource(r) {
  const w = r.why;
  if (r.keeps_manual) return `<span class="src manual">กรอกเองไว้ — คงค่าเดิม (ระบบคำนวณได้ ${r.default_satang == null ? "–" : fmt(r.default_satang)})</span>`;
  if (r.default_source === "allocated") {
    if (w.role === "A2" || w.role === "A3") return `<span class="src transfer">⇄ เติมให้ครบ ${fmt(r.default_satang)}</span>`;
    if (w.role === "SAL") return `<span class="src transfer">⇄ เงินที่ค้างไว้ในบัญชีเงินเดือน</span>`;
    if (w.base_satang == null) return `<span class="src manual">ไม่มียอดเดือนก่อน — กรอกเอง (ยอดโอน ${fmt(w.transfer_satang)})</span>`;
    return `<span class="src transfer">⇄ ยอด ${esc(monthLabel(w.base_period))} ${fmt(w.base_satang)} + โอน ${fmt(w.transfer_satang)}</span>`;
  }
  if (w.base_satang == null) return `<span class="src manual">ไม่มียอดก่อนหน้า — กรอกเองได้</span>`;
  return `<span class="src auto">↳ ยกจาก ${esc(monthLabel(w.base_period))}</span>`;
}

function renderAllocResult() {
  const { preview } = S.dlg;
  const d = S.data;
  const c = preview.calc;
  let h = `<h3><span class="step">2</span>รายการโอน (ทำตามลำดับในแอปธนาคาร)</h3>
    <table class="simple"><thead><tr><th>#</th><th>โอนไป</th><th>บัญชี</th><th>สูตร</th><th class="num">ยอดโอน</th></tr></thead><tbody>`;
  c.items.forEach((it, n) => {
    const acc = it.account_id ? esc(it.account_name) : `<span class="warn">ยังไม่ได้กำหนด</span>`;
    h += `<tr class="${it.negative ? "neg" : ""}"><td>${n + 1}</td><td><b>${it.label}</b></td><td>${acc}</td><td class="muted">${esc(it.formula)}</td>
      <td class="num amt">${it.amount_satang == null ? '<span class="muted">–</span>' : (it.negative ? "⚠ " : "") + fmt(it.amount_satang)}</td></tr>`;
  });
  h += `</tbody>`;
  if (c.complete) h += `<tfoot><tr><td colspan="4">รวมโอนออกจากบัญชีเงินเดือน (เหลือ ${fmt(c.inputs_satang.keep)})</td><td class="num"><b>${fmt(c.total_out_satang)}</b></td></tr></tfoot>`;
  h += `</table>`;
  if (c.problems.length) h += `<div class="problems">${c.problems.map(esc).join("<br>")}</div>`;
  if (c.negatives.length) h += `<div class="problems">⚠ ยอดโอนติดลบ: ${c.negatives.join(", ")} — ระบบไม่ปรับเป็น 0 ให้ ตรวจตัวเลขที่กรอกก่อนยืนยัน</div>`;

  h += `<h3><span class="step">3</span>โอนเสร็จแล้ว → ตรวจยอดเดือน ${esc(monthLabel(S.dlg.period))} ทุกบัญชี</h3>
    <p class="muted" style="font-size:12px;margin:0 0 6px">ระบบเติมให้ล่วงหน้า เทียบกับแอปธนาคารแล้วแก้ได้ทุกช่อง · ค่าที่ต่างจากที่ระบบคำนวณจะบันทึกเป็น “กรอกเอง” และจะไม่ถูกเขียนทับอัตโนมัติ · ช่องว่าง = ไม่บันทึกยอด
    <button type="button" class="ghost" data-use-defaults>ใช้ค่าที่ระบบคำนวณทุกช่อง</button></p>
    <table class="simple" id="alloc-rows"><thead><tr><th>บัญชี</th><th>ที่มา</th><th class="num">ยอดที่บันทึกอยู่</th><th class="num">ยอดเดือนนี้</th></tr></thead><tbody>`;
  let lastGroup = null;
  const grp = new Map(d.groups.map((g) => [g.code, g]));
  for (const r of preview.rows) {
    if (r.group_code !== lastGroup) {
      lastGroup = r.group_code;
      const g = grp.get(r.group_code);
      h += `<tr><td colspan="4" style="color:${gcolor(g.code)};font-weight:600">${esc(gLabel(g))}</td></tr>`;
    }
    const ex = r.existing;
    h += `<tr><td>${esc(r.account_name)}${r.role ? ` <span class="badge">${roleLabel(r.role)}</span>` : ""}</td><td>${rowSource(r)}</td>
      <td class="num muted">${ex ? fmt(ex.amount_satang) : "–"}</td>
      <td class="num"><input data-bal-acc="${r.account_id}" inputmode="decimal" value="${esc(rawAmt(r.proposed_satang))}" data-default="${esc(rawAmt(r.default_satang))}" data-orig="${esc(rawAmt(ex ? ex.amount_satang : null))}" placeholder="—"></td></tr>`;
  }
  h += `</tbody></table>
    <div class="actions">
      ${preview.confirmed ? `<button type="button" class="ghost" data-alloc-delete title="ลบการจัดสรรของเดือนนี้ (ยอดเงินยังอยู่ครบ)">ลบการจัดสรร</button>` : ""}
      <button type="button" class="ghost" data-close>ปิด</button>
      <button type="button" id="confirm-alloc" ${c.complete ? "" : "disabled title='ยังคำนวณไม่ครบ'"}>โอนเสร็จแล้ว — บันทึกยอด</button></div>`;
  $("#alloc-result").innerHTML = h;
  markChangedRows();
}

function markChangedRows() {
  $$("#alloc-rows input[data-bal-acc]").forEach((i) => {
    const v = i.value.replace(/[,\s฿]/g, "");
    const o = i.dataset.orig;
    const changed = o !== "" && (v === "" || Number(v) !== Number(o));
    i.closest("tr").classList.toggle("changed", changed);
    i.title = changed ? `จะเปลี่ยนจากยอดที่บันทึกไว้ ${NF.format(Number(o))}` : "";
  });
}

function setupAllocDialog() {
  const dlg = $("#alloc-dialog");
  dlg.addEventListener("close", () => { S.dlg = null; });
  dlg.addEventListener("input", (e) => {
    if (e.target.matches("[data-in]")) { S.dlg.inputs[e.target.dataset.in] = e.target.value; scheduleAlloc(); }
    if (e.target.matches("[data-bal-acc]")) markChangedRows();
  });
  dlg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("[data-in]")) {
      e.preventDefault();
      const ins = $$("[data-in]", dlg);
      const next = ins[ins.indexOf(e.target) + 1];
      if (next) next.focus(); else e.target.blur();
    }
  });
  dlg.addEventListener("click", async (e) => {
    if (e.target.closest("[data-close]")) return dlg.close();
    if (e.target.closest("[data-use-defaults]")) {
      $$("#alloc-rows input[data-bal-acc]").forEach((i) => { i.value = i.dataset.default; });
      return markChangedRows();
    }
    if (e.target.closest("[data-alloc-delete]")) {
      const { period } = S.dlg;
      if (!confirm(`ลบการจัดสรรเงินเดือนของ ${monthLabel(period)}?\nยอดเงินทุกช่องยังอยู่ครบ (ช่องที่ระบบเติมจะกลายเป็น “กรอกเอง”)`)) return;
      await run(() => api("DELETE", `/api/allocations/${period}`), "ลบการจัดสรรแล้ว");
      dlg.close();
      return load();
    }
    if (e.target.closest("#confirm-alloc")) {
      clearTimeout(allocTimer);
      const { period, inputs } = S.dlg;
      await refreshAlloc();
      const c = S.dlg.preview.calc;
      if (!c.complete) return toast("ยังคำนวณไม่ครบ", true);
      if (c.negatives.length && !confirm(`ยอดโอนติดลบ (${c.negatives.join(", ")})\nยืนยันบันทึกตามนี้?`)) return;
      const balances = {};
      $$("#alloc-rows input[data-bal-acc]").forEach((i) => { balances[i.dataset.balAcc] = i.value; });
      const changed = $$("#alloc-rows tr.changed").length;
      if (changed && !confirm(`มี ${changed} บัญชีที่ยอดเดิมจะถูกเปลี่ยน (ไฮไลต์ไว้) — ยืนยัน?`)) return;
      await run(() => api("POST", `/api/allocations/${period}/confirm`, { inputs, balances, accept_negative: c.negatives.length > 0 }),
        (r) => `บันทึกยอด ${monthLabel(period)} แล้ว` + (r.propagated?.length ? ` · อัปเดตยอดอัตโนมัติเดือนถัดไป ${r.propagated.length} ช่อง` : ""));
      dlg.close();
      await load();
    }
  });
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
  const lhAcc = d.accounts.find((a) => a.role === "LH");
  const lhBal = lhAcc ? bal.get(bkey(lhAcc.id, s.period)) : null;
  const [rLo, rHi] = d.lh_reserve_range_satang;

  let h = "";
  const notices = [];
  if (s.missing_accounts.length) notices.push(`เดือนนี้ยังไม่ได้กรอก ${s.missing_accounts.length} บัญชี (${s.missing_accounts.map((id) => esc(acc.get(id).name)).join(", ")}) — ยอดรวมจึงยังไม่ครบ`);
  if (s.carried_count) notices.push(`มี ${s.carried_count} บัญชีที่ใช้ยอดยกมาจากเดือนก่อน (${s.carried_accounts.map((id) => esc(acc.get(id).name)).join(", ")}) — ยังไม่ใช่ยอดที่ตรวจใหม่`);
  if (s.allocated_count) notices.push(`มี ${s.allocated_count} บัญชีที่ระบบเติมให้จากการจัดสรรเงินเดือน — ควรเทียบกับแอปธนาคาร`);
  if (prev && prev.missing_accounts.length) notices.push(`เดือนที่ใช้เปรียบเทียบ (${esc(monthLabel(prev.period))}) มีข้อมูลไม่ครบ ${prev.missing_accounts.length} บัญชี`);
  if (notices.length) h += `<div class="notice">${notices.join("<br>")}</div>`;

  h += `<div class="kpis">
    <div class="card kpi"><div class="label">รวมสินทรัพย์ · ${esc(monthLabel(s.period, "long"))}</div>
      <div class="value">฿${fmt(s.total_satang)}</div>
      <div class="note">ผลรวมยอดทุกบัญชี — รวมเงินที่กันไว้ใช้ตามแผน เงินลงทุน และเงินสำรองใน LH <b>ไม่ใช่เงินที่ใช้จ่ายได้ทันทีทั้งหมด</b></div></div>
    <div class="card kpi"><div class="label">${prev ? `เปลี่ยนแปลงเทียบกับ ${esc(monthLabel(prev.period, "long"))}` : "เปลี่ยนแปลงจากเดือนก่อนหน้า"}</div>
      <div class="value">${prev ? signed(s.change_satang) : "–"}</div>
      <div class="note">${prev ? `฿${fmt(prev.total_satang)} → ฿${fmt(s.total_satang)} · เป็นผลต่างของยอดรวมที่บันทึกเท่านั้น ไม่ได้แสดงรายรับ รายจ่าย หรือเงินออม` : "เป็นเดือนแรกที่มีการบันทึก จึงยังไม่มีเดือนให้เปรียบเทียบ"}</div></div>
    <div class="card kpi" style="border-top:3px solid ${lhAcc ? gcolor(lhAcc.group_code) : "var(--line)"}"><div class="label">LH · ${esc(monthLabel(s.period))}</div>
      <div class="value">${lhBal ? "฿" + fmt(lhBal.amount_satang) : "–"}</div>
      <div class="note">${lhAcc ? `ที่พักเงินค่างวดบ้าน + เงินสำรองฉุกเฉินที่ตั้งใจไว้ ${fmt(rLo).replace(/\.00$/, "")}–${fmt(rHi).replace(/\.00$/, "")}` + (lhBal ? (lhBal.amount_satang < rLo ? " · <b>ต่ำกว่าช่วงที่ตั้งใจไว้</b>" : lhBal.amount_satang > rHi ? " · สูงกว่าช่วงที่ตั้งใจไว้ (รวมเงินค่างวดที่ยังไม่โอนออก)" : " · อยู่ในช่วงที่ตั้งใจไว้") : "") + " (แสดงเป็นข้อมูลเท่านั้น)" : "ยังไม่ได้กำหนดบัญชี LH"}</div></div>
    ${allocKpi(s)}
  </div>`;

  h += `<div class="dash-grid">`;
  h += `<div class="card"><h3>แนวโน้มสินทรัพย์รวม</h3>${trendChart(withData, s.period)}</div>`;

  const activeGroups = d.groups.filter((g) => g.is_active || gt[g.code] != null);
  const maxAbs = Math.max(1, ...activeGroups.map((g) => Math.abs(gt[g.code] || 0)));
  h += `<div class="card"><h3>ยอดคงเหลือแยกตามกลุ่ม · ${esc(monthLabel(s.period))}</h3><div class="bars">`;
  for (const g of activeGroups) {
    const v = gt[g.code];
    const pv = prev ? prev.group_totals_satang[g.code] : null;
    const delta = v != null && pv != null ? ` <span class="muted" style="font-size:12px" title="เทียบ ${esc(monthLabel(prev.period))}">(${signed(v - pv)})</span>` : "";
    const pct = s.total_satang ? Math.round(((v || 0) / s.total_satang) * 1000) / 10 : 0;
    h += `<div class="row"><span><b style="color:${gcolor(g.code)}">${esc(gLabel(g))}</b></span>
      <span class="num">${v == null ? "–" : "฿" + fmt(v)}${delta} <span class="muted" style="font-size:12px">${v == null ? "" : pct + "%"}</span></span>
      <div class="track"><div class="fill" style="width:${(Math.abs(v || 0) / maxAbs) * 100}%;background:${gcolor(g.code)}"></div></div>
      <div class="desc">${esc(g.description)}</div></div>`;
  }
  h += `</div>${prev ? `<p class="muted" style="font-size:12px;margin:0">ตัวเลขในวงเล็บ = เปลี่ยนแปลงเทียบกับ ${esc(monthLabel(prev.period))}</p>` : ""}</div>`;

  h += `<div class="card" style="grid-column:1/-1"><h3>ยอดรายบัญชี · ${esc(monthLabel(s.period, "long"))}</h3><div class="table-wrap" style="border:0"><table class="simple"><thead><tr><th>บัญชี</th><th class="num">ยอด</th><th class="num">${prev ? "เทียบ " + esc(monthLabel(prev.period)) : ""}</th><th>ตรวจยอดล่าสุด</th></tr></thead><tbody>`;
  for (const g of d.groups) {
    const accs = d.accounts.filter((a) => a.group_code === g.code && (a.is_active || bal.has(bkey(a.id, s.period))));
    if (!accs.length) continue;
    h += `<tr><td colspan="4" style="color:${gcolor(g.code)};font-weight:600">${esc(gLabel(g))}</td></tr>`;
    for (const a of accs) {
      const e = bal.get(bkey(a.id, s.period));
      const pe = prev ? bal.get(bkey(a.id, prev.period)) : null;
      const verified = e && e.source !== "carried" ? s.period : carriedFrom(a.id, s.period, bal);
      const mark = e?.source === "carried" ? ' <span style="color:var(--carried)" title="ยอดยกมา">↻</span>' : e?.source === "allocated" ? ' <span style="color:var(--transfer)" title="ระบบเติมจากการจัดสรร">⇄</span>' : "";
      h += `<tr><td>${esc(a.name)}${a.role ? ` <span class="badge">${roleLabel(a.role)}</span>` : ""}</td>
        <td class="num">${e ? fmt(e.amount_satang) + mark : '<span class="muted">ไม่มีข้อมูล</span>'}</td>
        <td class="num muted">${e && pe ? signed(e.amount_satang - pe.amount_satang) : ""}</td>
        <td class="muted">${verified ? esc(monthLabel(verified)) : "–"}</td></tr>`;
    }
  }
  h += `</tbody></table></div></div></div>`;
  el.innerHTML = h;
}

function allocKpi(s) {
  const al = s.allocation;
  if (!al)
    return `<div class="card kpi"><div class="label">จัดสรรเงินเดือน · ${esc(monthLabel(s.period))}</div><div class="value">–</div>
      <div class="note">ยังไม่ได้จัดสรรเงินเดือนของเดือนนี้ <button class="ghost" data-dash-alloc="${s.period}">จัดสรรเงินเดือน</button></div></div>`;
  const c = al.calc;
  const lines = ["A2", "A3", "A1", "LH"].map((r) => `${S.data.roles[r].label} ${(c.transfers[r] < 0 ? "⚠ " : "") + fmt(c.transfers[r])}`).join(" · ");
  return `<div class="card kpi"><div class="label">จัดสรรเงินเดือน · ${esc(monthLabel(s.period))}</div>
    <div class="value">฿${fmt(c.inputs_satang.salary)}</div>
    <div class="note">ยอดบัญชีเงินเดือนหลังเงินเดือนเข้า · โอน ${lines} <button class="ghost" data-dash-alloc="${s.period}">เปิด</button></div></div>`;
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
/* Groups & accounts                                                   */
/* ------------------------------------------------------------------ */
function renderAccounts() {
  const d = S.data;
  const activeGroups = d.groups.filter((g) => g.is_active);
  $("#new-account-group").innerHTML = activeGroups.map((g) => `<option value="${g.code}">${esc(gLabel(g))}</option>`).join("");
  const opts = (cur) => d.groups.filter((g) => g.is_active || g.code === cur)
    .map((g) => `<option value="${g.code}" ${g.code === cur ? "selected" : ""}>${esc(gLabel(g))}</option>`).join("");
  const roleOpts = (cur) => `<option value="">— บทบาท —</option>` + d.role_order
    .map((r) => `<option value="${r}" ${r === cur ? "selected" : ""}>${d.roles[r].label} · ${esc(d.roles[r].desc)}</option>`).join("");

  // role summary
  $("#roles-summary").innerHTML = `<div class="roles">${d.role_order.map((r) => {
    const a = d.accounts.find((x) => x.role === r);
    const ro = d.roles[r];
    const rule = ro.fixed_satang != null ? `โอน ${fmt(ro.fixed_satang)} ทุกเดือน` : ro.target_satang != null ? `เติมให้ครบ ${fmt(ro.target_satang)}` : r === "SAL" ? "ต้นทางของการโอน" : "รับเงินที่เหลือทั้งหมด";
    return `<div class="role ${a ? "" : "unset"}"><b>${ro.label}</b> ${esc(ro.desc)} <span class="muted">(${rule})</span><br>${a ? "→ " + esc(a.name) : "ยังไม่ได้กำหนดบัญชี"}</div>`;
  }).join("")}</div>`;

  let h = "";
  d.groups.forEach((g, gi) => {
    const accs = d.accounts.filter((a) => a.group_code === g.code);
    h += `<div class="card acc-group ${g.is_active ? "" : "inactive"}" style="--gc:${gcolor(g.code)}" data-group="${g.code}">
      <h3 class="group-edit">
        <span><button class="ghost" data-gmove="up" ${gi === 0 ? "disabled" : ""} title="เลื่อนกลุ่มขึ้น">↑</button><button class="ghost" data-gmove="down" ${gi === d.groups.length - 1 ? "disabled" : ""} title="เลื่อนกลุ่มลง">↓</button></span>
        <input name="name_th" value="${esc(g.name_th)}" maxlength="100" aria-label="ชื่อกลุ่ม">
        <input name="description" value="${esc(g.description || "")}" maxlength="500" placeholder="หมายเหตุกลุ่ม" aria-label="หมายเหตุกลุ่ม">
        <button class="ghost" data-gtoggle>${g.is_active ? "ปิดใช้งานกลุ่ม" : "เปิดใช้งานกลุ่ม"}</button>
      </h3><div class="id muted" style="font-size:11px;font-family:ui-monospace,monospace;margin:-4px 0 6px">ID: ${esc(g.code)}${g.is_active ? "" : " · ปิดใช้งาน"}</div>`;
    if (!accs.length) h += `<p class="muted">ยังไม่มีบัญชีในกลุ่มนี้</p>`;
    accs.forEach((a, i) => {
      const m = d.account_meta[a.id];
      h += `<div class="acc-row ${a.is_active ? "" : "inactive"}" data-id="${a.id}">
        <span><button class="ghost" data-move="up" ${i === 0 ? "disabled" : ""} title="เลื่อนขึ้น">↑</button><button class="ghost" data-move="down" ${i === accs.length - 1 ? "disabled" : ""} title="เลื่อนลง">↓</button></span>
        <span><input name="name" value="${esc(a.name)}" maxlength="100" style="width:100%"><span class="id">${a.id}${m.first_period ? ` · มียอด ${m.first_period} ถึง ${m.last_period}` : " · ยังไม่มียอด"}</span></span>
        <select name="group_code" aria-label="กลุ่ม">${opts(a.group_code)}</select>
        <select name="role" aria-label="บทบาท" ${a.is_active ? "" : "disabled"}>${roleOpts(a.role)}</select>
        <input name="note" value="${esc(a.note || "")}" placeholder="หมายเหตุ" maxlength="500">
        <button class="ghost" data-toggle>${a.is_active ? "ปิดใช้งาน" : "เปิดใช้งานอีกครั้ง"}</button>
      </div>`;
    });
    h += `</div>`;
  });
  $("#accounts-list").innerHTML = h;
}

function setupAccountEvents() {
  const list = $("#accounts-list");
  const patch = (id, body, msg) => run(() => api("PATCH", `/api/accounts/${id}`, body), msg).then(load, load);
  const gpatch = (code, body, msg) => run(() => api("PATCH", `/api/groups/${code}`, body), msg).then(load, load);
  list.addEventListener("change", (e) => {
    const grpEl = e.target.closest(".group-edit");
    if (grpEl) {
      const code = e.target.closest("[data-group]").dataset.group;
      const g = S.data.groups.find((x) => x.code === code);
      const f = e.target.name;
      if (f === "name_th" && e.target.value.trim() !== g.name_th) gpatch(code, { name_th: e.target.value }, "เปลี่ยนชื่อกลุ่มแล้ว — ประวัติยังผูกกับกลุ่มเดิม");
      if (f === "description") gpatch(code, { description: e.target.value }, "บันทึกหมายเหตุกลุ่มแล้ว");
      return;
    }
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
      const g = S.data.groups.find((x) => x.code === e.target.value);
      if (!confirm(`ย้าย “${a.name}” ไปกลุ่ม “${g.name_th}”?\nประวัติยอดทั้งหมดจะย้ายไปด้วย (ยอดรวมกลุ่มของเดือนก่อน ๆ จะเปลี่ยนตาม)`)) {
        e.target.value = a.group_code;
        return;
      }
      patch(id, { group_code: e.target.value }, "ย้ายกลุ่มแล้ว");
    } else if (f === "role") {
      const r = e.target.value;
      const holder = r ? S.data.accounts.find((x) => x.role === r && x.id !== id) : null;
      const msg = r
        ? `กำหนด “${a.name}” เป็นบัญชี ${roleLabel(r)} สำหรับการจัดสรรเงินเดือน?` + (holder ? `\n(“${holder.name}” จะไม่เป็น ${roleLabel(r)} อีกต่อไป)` : "")
        : `ยกเลิกบทบาท ${roleLabel(a.role)} ของ “${a.name}”?`;
      if (!confirm(msg + "\n\nการจัดสรรที่ยืนยันไปแล้วยังใช้บัญชีเดิมตามที่บันทึกไว้")) {
        e.target.value = a.role || "";
        return;
      }
      patch(id, { role: r || null }, "บันทึกบทบาทแล้ว");
    }
  });
  list.addEventListener("click", (e) => {
    const gcard = e.target.closest("[data-group]");
    const gmv = e.target.closest("[data-gmove]");
    if (gmv) return run(() => api("POST", `/api/groups/${gcard.dataset.group}/move`, { direction: gmv.dataset.gmove })).then(load);
    if (e.target.closest("[data-gtoggle]")) {
      const g = S.data.groups.find((x) => x.code === gcard.dataset.group);
      const msg = g.is_active
        ? `ปิดใช้งานกลุ่ม “${g.name_th}”?\nประวัติยอดของบัญชีในกลุ่มยังเก็บไว้ครบ (ต้องย้ายหรือปิดใช้งานบัญชีที่ใช้งานอยู่ก่อน)`
        : `เปิดใช้งานกลุ่ม “${g.name_th}” อีกครั้ง?`;
      if (confirm(msg)) gpatch(g.code, { is_active: !g.is_active }, g.is_active ? "ปิดใช้งานกลุ่มแล้ว" : "เปิดใช้งานกลุ่มแล้ว");
      return;
    }
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
  $("#add-group-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    run(() => api("POST", "/api/groups", { name: f.name.value, note: f.note.value }), "เพิ่มกลุ่มแล้ว")
      .then(() => { f.name.value = ""; f.note.value = ""; return load(); });
  });
}

/* ------------------------------------------------------------------ */
/* Data / backup                                                       */
/* ------------------------------------------------------------------ */
const ACTION_TH = { create: "สร้าง", update: "แก้ไข", clear: "ล้างยอด", carry: "ยกยอด", note: "หมายเหตุ", delete: "ลบ", restore: "กู้คืน", confirm: "ยืนยันการจัดสรร" };

async function renderDataTab() {
  const [audit, bk] = await Promise.all([api("GET", "/api/audit"), api("GET", "/api/backups")]);
  const names = new Map(S.data.accounts.map((a) => [a.id, a.name]));
  const gnames = new Map(S.data.groups.map((g) => [g.code, g.name_th]));
  const label = (r) => {
    if (r.entity === "balance") {
      const [id, rest] = r.entity_id.split("@");
      const [p, k] = rest.split(":");
      return `${esc(names.get(id) || id)} · ${p}${k ? (k === "begin" ? " ต้นเดือน (v0.2)" : " ปลายเดือน (v0.2)") : ""}`;
    }
    if (r.entity === "account") return esc(names.get(r.entity_id) || r.entity_id);
    if (r.entity === "group") return "กลุ่ม " + esc(gnames.get(r.entity_id) || r.entity_id);
    if (r.entity === "income") return "รายรับ · " + esc(r.entity_id);
    if (r.entity === "plan") return "ยอดต้นเดือน (v0.2) · " + esc(r.entity_id);
    if (r.entity === "allocation") return "จัดสรรเงินเดือน · " + esc(r.entity_id);
    return esc(r.entity_id);
  };
  const val = (j) => {
    if (!j) return "";
    const o = JSON.parse(j);
    if ("amount_satang" in o) return fmt(o.amount_satang) + (o.from_period ? ` (จาก ${o.from_period})` : "") + (o.source && o.source !== "manual" ? ` [${{ transfer: "เงินโอน", allocated: "จัดสรร", carried: "ยกมา" }[o.source] || o.source}]` : "") + (o.note ? ` · ${esc(o.note)}` : "");
    if ("transfers" in o) return (o.income_satang != null ? `รายรับ ${fmt(o.income_satang)} · ` : o.inputs ? `บัญชีเงินเดือน ${fmt(o.inputs.salary)} · ` : "") + Object.entries(o.transfers).map(([k, v]) => `${k} ${fmt(v)}`).join(", ");
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
  // Deep links: #dashboard, #accounts, #data, #table, or #alloc-YYYY-MM (opens the salary allocation dialog)
  const hash = location.hash.slice(1);
  let saved = null;
  try { saved = localStorage.getItem("ffd-tab"); } catch {}
  if (hash && $(`nav button[data-tab="${CSS.escape(hash)}"]`)) saved = hash;
  if (saved) $(`nav button[data-tab="${saved}"]`)?.click();
  const m = hash.match(/^alloc-(\d{4}-\d{2})$/);
  if (m) openAllocDialog(m[1]);
}

$("#dash-period").addEventListener("change", (e) => { S.dashPeriod = e.target.value; renderDashboard(); });
$("#dashboard").addEventListener("click", (e) => {
  const b = e.target.closest("[data-dash-alloc]");
  if (b) openAllocDialog(b.dataset.dashAlloc);
});
setupTableEvents();
setupAllocDialog();
setupAccountEvents();
setupDataEvents();
load().then(setupTabs).catch((e) => toast(e.message, true));
