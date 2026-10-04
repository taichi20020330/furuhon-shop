// 本棚の空間：本が島（カテゴリ）ごとに浮かぶ、ドラッグ・ズーム・裏返し・長押し拡大・ランダム・検索・取り置き申し込み。
// 画面の部品（React）とは独立した「空間エンジン」。mountShelfSpace(root, オプション) で動かし、戻り値の destroy() で片付ける。
// root の中には SPACE_HTML の構造が入っている必要がある。
export const SPACE_HTML = `
<div id="stage" aria-label="本の空間。ドラッグで移動できます"><div id="world"></div></div>
<header class="top">
  <div class="searchrow">
    <label class="search" for="q">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="書名・著者・出版社で探す" autocomplete="off">
    </label>
    <select id="maxPrice" class="select" aria-label="価格の上限">
      <option value="">価格すべて</option><option value="300">〜300円</option><option value="500">〜500円</option><option value="1000">〜1,000円</option>
    </select>
  </div>
  <div class="chips" id="chips" role="toolbar" aria-label="棚へ移動"></div>
  <div class="found" id="found" aria-live="polite"></div>
</header>
<div class="zoom">
  <button id="rnd" aria-label="ランダムに1冊見る" title="ランダムに1冊"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3.5"/><circle cx="9" cy="9" r="1" fill="currentColor"/><circle cx="15" cy="15" r="1" fill="currentColor"/><circle cx="15" cy="9" r="1" fill="currentColor"/><circle cx="9" cy="15" r="1" fill="currentColor"/></svg></button>
  <button id="zin" aria-label="拡大">＋</button>
  <button id="zout" aria-label="縮小">−</button>
</div>
<div class="tray"><div class="tray-inner">
  <div class="thumbs" id="thumbs"></div>
  <div class="tray-empty" id="trayEmpty">＋で選んだ本がここに並びます</div>
  <div class="tray-sum" id="traySum" hidden><b id="trayCount">0</b>冊 ・ <b id="trayTotal">¥0</b></div>
  <button class="btn" id="openOrder" disabled>取り置きを頼む</button>
</div></div>
<div class="zveil" id="zveil" hidden><div class="zcard" role="dialog" aria-modal="true" aria-labelledby="zTitle" id="zcard"></div></div>
<div class="veil" id="veil" hidden><div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheetTitle" id="sheet"></div></div>
`;

export function mountShelfSpace(root, { books, shopName = "本棚", orderEndpoint = "", intro = false }) {
  const BOOKS = books.map(b => ({ ...b }));
  const $ = id => root.querySelector("#" + id);
  const cleanups = [];
  const listen = (target, type, fn, opt) => { target.addEventListener(type, fn, opt); cleanups.push(() => target.removeEventListener(type, fn, opt)); };
  let destroyed = false, rafId = 0;


const FORMAT = { shinsho: { w: 128, ar: 0.6 }, bunko: { w: 120, ar: 0.66 }, tanko: { w: 150, ar: 0.7 } };
const PALETTE = [ // 簡易表紙の色（出版社ごとに固定）
  ["#f6f3ea","#8a3a2e","#2a2522","#7b736a"], ["#eef1f3","#2f4d63","#1f2a33","#64727c"],
  ["#f3efe4","#5b6b3a","#2a2a1f","#76735f"], ["#f4eeee","#6b2f45","#2c2023","#7d6c71"],
  ["#eceae4","#3d3d3d","#202020","#6d6d6d"], ["#f1ede2","#a1752b","#2b261c","#7c7363"],
];
const hash = s => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
const rng = seed => () => ((seed = Math.imul(seed ^ (seed >>> 15), 2246822507) ^ Math.imul(seed ^ (seed >>> 13), 3266489909)) >>> 0) / 4294967296;
const yen = n => "¥" + n.toLocaleString("ja-JP");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));

/* ---------- 配置：カテゴリごとに島をつくる ---------- */
// 島の中はひまわりの種の並び（黄金角のらせん）。冊数が増えても重ならず、島が大きくなるだけ。
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const HOLE = 110, STEP = 92, GAP = 64;           // ラベルの穴・本どうしの間隔・島どうしのすき間
const islandR = n => HOLE + STEP * Math.sqrt(n) + 55;
const categories = [...new Set(BOOKS.map(b => b.category))]
  .sort((a, b) => (a === "その他") - (b === "その他") || BOOKS.filter(x => x.category === b).length - BOOKS.filter(x => x.category === a).length);
const clusters = categories.map(name => {
  const books = BOOKS.filter(b => b.category === name);
  return { name, books, r: islandR(books.length) };
});
// 島を棚のように左から並べ、はみ出したら次の段へ
{
  const total = clusters.reduce((s, c) => s + (2 * c.r + GAP) ** 2, 0);
  const rowW = Math.max(2 * clusters[0].r + GAP, Math.sqrt(total) * 1.15);
  let x = 0, y = 0, rowH = 0, row = [];
  const flush = () => {                              // 段ごとに中央寄せ
    const used = row.reduce((s, c) => s + 2 * c.r + GAP, 0) - GAP;
    const shift = (rowW - used) / 2;
    row.forEach(c => { c.x += shift; c.y = y + rowH / 2; });
    y += rowH + GAP; x = 0; rowH = 0; row = [];
  };
  clusters.forEach(c => {
    if (row.length && x + 2 * c.r > rowW) flush();
    c.x = x + c.r; x += 2 * c.r + GAP; rowH = Math.max(rowH, 2 * c.r); row.push(c);
  });
  flush();
}
const world = $("world");
const bookEls = new Map();

clusters.forEach(cl => {
  const lab = document.createElement("div");
  lab.className = "cluster-label";
  lab.style.left = cl.x + "px"; lab.style.top = cl.y + "px";
  lab.innerHTML = `${esc(cl.name)}<small>${cl.books.length}冊</small>`;
  world.appendChild(lab);

  const rand = rng(hash(cl.name));
  const turn = rand() * Math.PI * 2;
  cl.books.forEach((b, i) => {
    const ang = turn + i * GOLDEN;
    const rad = HOLE + STEP * Math.sqrt(i + 0.6) + (rand() - 0.5) * 12;
    b._x = cl.x + Math.cos(ang) * rad;
    b._y = cl.y + Math.sin(ang) * rad * 1.12 - 20;  // 本は縦長なので上下を少し広く
    world.appendChild(makeBook(b, rand));
  });
});

function coverHTML(b, side) {
  const [bg, band, ink, sub] = PALETTE[hash(b.publisher) % PALETTE.length];
  const style = `--c-bg:${bg};--c-band:${band};--c-ink:${ink};--c-sub:${sub}`;
  if (side === "front") {
    return `<div class="cover" style="${style}"><div class="band"></div><div class="vt">${esc(b.title)}<small>${esc(b.author)}</small></div><div class="pub">${esc(b.label || b.publisher)}</div></div>`;
  }
  return `<div class="cover backside" style="${style}"><div></div><div class="meta">${esc(b.publisher)}<br>${esc(b.label || "")}<br>古書価 ${yen(b.price)}</div></div>`;
}

function makeBook(b, rand) {
  const f = FORMAT[b.format] || FORMAT.bunko;
  const el = document.createElement("div");
  el.className = "book" + (b.sold ? " sold" : "");
  el.dataset.id = b.id;
  el.style.cssText = `left:${b._x}px;top:${b._y}px;--w:${f.w}px;--ar:${f.ar};--dur:${(6 + rand() * 4).toFixed(2)}s;--delay:${(-rand() * 8).toFixed(2)}s;--r0:${(-2 + rand() * 1.5).toFixed(2)}deg;--r1:${(0.5 + rand() * 1.8).toFixed(2)}deg`;
  const front = b.front ? `<img src="${esc(b.front)}" alt="${esc(b.title)}の表紙" draggable="false" loading="lazy" decoding="async">` : coverHTML(b, "front");
  const back = b.back ? `<img src="${esc(b.back)}" alt="${esc(b.title)}の裏表紙" draggable="false" loading="lazy" decoding="async">` : coverHTML(b, "back");
  el.innerHTML = `
    <div class="float">
      <div class="flip" role="button" tabindex="0" aria-label="${esc(b.title)}を裏返す">
        <div class="flipper"><div class="face front">${front}</div><div class="face back">${back}</div></div>
      </div>
      ${b.sold ? `<div class="stamp">売約済</div>` : `<button class="pick" aria-label="${esc(b.title)}を選ぶ" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></button>`}
      ${b.sample ? `<span class="sample-tag">見本</span>` : ""}
    </div>
    <div class="shadow"></div>
    <div class="price">${b.sold ? "" : yen(b.price)}</div>
    <div class="info">
      <h3>${esc(b.title)}</h3>
      <p>${esc(b.author)} ／ ${esc(b.publisher)}${b.label ? "・" + esc(b.label) : ""}</p>
      ${b.condition ? `<div class="note">状態：${esc(b.condition)}</div>` : ""}
      <div class="row"><span class="yen">${b.sold ? "売約済" : yen(b.price)}</span>${b.sold ? "" : `<button class="btn ghost info-pick">選ぶ</button>`}</div>
    </div>`;
  const img = el.querySelector(".front img");
  if (img) {
    const fit = () => img.naturalWidth && el.style.setProperty("--ar", (img.naturalWidth / img.naturalHeight).toFixed(4));
    img.complete ? fit() : img.addEventListener("load", fit);
  }
  bookEls.set(b.id, el);
  return el;
}

/* ---------- 空間の移動（ドラッグ・ホイール・ピンチ） ---------- */
const stage = $("stage");
const view = { x: 0, y: 0, s: 1 };
const apply = () => { world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.s})`; };
const clampS = s => Math.min(1.8, Math.max(0.18, s));
function centerOn(wx, wy, s = view.s, animate = true, dur = 650) {
  const target = { s, x: innerWidth / 2 - wx * s, y: innerHeight / 2 + 40 - wy * s };
  if (!animate || matchMedia("(prefers-reduced-motion: reduce)").matches) { Object.assign(view, target); apply(); return; }
  const from = { ...view }, t0 = performance.now(), D = dur;
  const step = now => {
    const k = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - k, 3);
    view.x = from.x + (target.x - from.x) * e; view.y = from.y + (target.y - from.y) * e; view.s = from.s + (target.s - from.s) * e;
    apply(); if (k < 1 && !destroyed) rafId = requestAnimationFrame(step);
  };
  rafId = requestAnimationFrame(step);
}
function zoomAt(cx, cy, factor) {
  const ns = clampS(view.s * factor), k = ns / view.s;
  view.x = cx - (cx - view.x) * k; view.y = cy - (cy - view.y) * k; view.s = ns; apply();
}

const pointers = new Map();
let drag = null, pinch = null, moved = false, pressTimer = null, longFired = false;
const LONG_MS = 480;
const cancelPress = () => { clearTimeout(pressTimer); pressTimer = null; };
stage.addEventListener("contextmenu", e => e.preventDefault());
stage.addEventListener("pointerdown", e => {
  if (e.target.closest("button, .info")) return;
  longFired = false; cancelPress();
  if (e.isPrimary) { pointers.clear(); pinch = null; drag = null; }   // 取りこぼした前の指の記録で、ピンチ扱いにならないように
  const hitBook = (document.elementFromPoint(e.clientX, e.clientY) || e.target).closest?.(".flip");
  if (hitBook && e.isPrimary) {
    const id = hitBook.closest(".book").dataset.id;
    pressTimer = setTimeout(() => {
      if (moved || pointers.size !== 1) return;
      longFired = true; drag = null; showZoom(id);
    }, LONG_MS);
  }
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  try { stage.setPointerCapture(e.pointerId); } catch {}
  if (pointers.size === 1) { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; moved = false; }
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: view.s }; drag = null; moved = true;
  }
});
stage.addEventListener("pointermove", e => {
  if (!pointers.has(e.pointerId)) return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pinch && pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    zoomAt(mx, my, clampS(pinch.s * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d) / view.s);
  } else if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 6) { moved = true; cancelPress(); stage.classList.add("dragging"); }
    if (moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); }
  }
});
const endPointer = e => {
  if (!pointers.has(e.pointerId)) return;
  cancelPress();
  pointers.delete(e.pointerId);
  if (pointers.size < 2) pinch = null;
  if (pointers.size === 0) {
    stage.classList.remove("dragging");
    if (drag && !moved && !longFired) handleTap(e);
    drag = null;
  }
};
stage.addEventListener("pointerup", endPointer);
stage.addEventListener("pointercancel", e => { moved = true; endPointer(e); });
stage.addEventListener("lostpointercapture", e => { if (pointers.has(e.pointerId)) endPointer(e); });
stage.addEventListener("wheel", e => {
  e.preventDefault();
  if (e.ctrlKey) zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.01));
  else { view.x -= e.deltaX; view.y -= e.deltaY; apply(); }
}, { passive: false });
$("zin").onclick = () => zoomAt(innerWidth / 2, innerHeight / 2, 1.2);
$("zout").onclick = () => zoomAt(innerWidth / 2, innerHeight / 2, 1 / 1.2);

/* ---------- 拡大表示（長押し）とランダム ---------- */
const zveil = $("zveil"), zcard = $("zcard");
let zId = null, zRandom = false, lastRandomId = null;
function resetTouch() {
  for (const pid of pointers.keys()) { try { stage.releasePointerCapture(pid); } catch {} }
  pointers.clear(); drag = null; pinch = null; moved = false; cancelPress();
  stage.classList.remove("dragging");
}
function showZoom(id, fromRandom = false) {
  const b = BOOKS.find(x => x.id === id);
  if (!b) return;
  resetTouch();
  zId = id; zRandom = fromRandom; closeAll();
  const el = bookEls.get(id);
  const ar = (el && parseFloat(getComputedStyle(el).getPropertyValue("--ar"))) || (FORMAT[b.format] || FORMAT.bunko).ar;
  const face = (src, alt, side) => src ? `<img src="${esc(src)}" alt="${esc(alt)}" draggable="false">` : coverHTML(b, side);
  zcard.innerHTML = `
    <div class="zflip" style="--ar:${ar}" id="zflip" role="button" tabindex="0" aria-label="タップで裏返す">
      <div class="zflipper" id="zflipper">
        <div class="zface">${face(b.front, b.title + "の表紙", "front")}</div>
        <div class="zface zb">${face(b.back, b.title + "の裏表紙", "back")}</div>
      </div>
    </div>
    <h3 id="zTitle">${esc(b.title)}</h3>
    <p>${esc(b.author)}${b.author && b.publisher ? " ／ " : ""}${esc(b.publisher)}${b.label ? "・" + esc(b.label) : ""}</p>
    ${b.condition ? `<p>状態：${esc(b.condition)}</p>` : ""}
    <div class="zmeta">${b.sold ? "売約済" : `古書価<b>${yen(b.price)}</b>`}</div>
    <p class="zhelp">表紙をタップすると裏返ります</p>
    <div class="zrow">
      ${b.sold ? "" : `<button class="btn" id="zpick">${picked.has(id) ? "選択をやめる" : "選ぶ"}</button>`}
      ${fromRandom ? `<button class="btn ghost" id="zagain">もう1冊</button>` : ""}
      <button class="btn ghost" id="zclose">閉じる</button>
    </div>`;
  zveil.hidden = false;
  const flip = () => $("zflipper").classList.toggle("back");
  $("zflip").onclick = flip;
  $("zflip").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(); } };
  $("zclose").onclick = closeZoom;
  const pk = $("zpick");
  if (pk) pk.onclick = () => { togglePick(id); pk.textContent = picked.has(id) ? "選択をやめる" : "選ぶ"; };
  const again = $("zagain");
  if (again) again.onclick = () => randomBook();
  $("zclose").focus({ preventScroll: true });
}
function closeZoom() { zveil.hidden = true; zId = null; resetTouch(); }
zveil.addEventListener("click", e => { if (e.target === zveil) closeZoom(); });
zveil.addEventListener("contextmenu", e => e.preventDefault());
listen(window, "keydown", e => { if (e.key === "Escape" && !zveil.hidden) closeZoom(); });

function randomBook() {
  // いま絞り込み中なら、その中から。売約済は除く
  const pool = BOOKS.filter(b => !b.sold && !(bookEls.get(b.id) || {}).classList?.contains("dim"));
  if (!pool.length) return;
  let b;
  do { b = pool[Math.floor(Math.random() * pool.length)]; } while (pool.length > 1 && b.id === lastRandomId);
  lastRandomId = b.id;
  closeZoom();
  centerOn(b._x, b._y, Math.max(view.s, innerWidth < 600 ? 0.9 : 1.0));
  showZoom(b.id, true);
}
$("rnd").onclick = randomBook;

/* ---------- 裏返す・選ぶ ---------- */
function handleTap(e) {
  const hit = document.elementFromPoint(e.clientX, e.clientY);
  const flip = hit && hit.closest(".flip");
  if (flip) toggleOpen(flip.closest(".book"));
  else closeAll();
}
function closeAll(except) { root.querySelectorAll(".book.open").forEach(el => { if (el !== except) el.classList.remove("open"); }); }
function toggleOpen(el) { closeAll(el); el.classList.toggle("open"); }
world.addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("flip")) { e.preventDefault(); toggleOpen(e.target.closest(".book")); }
});

const picked = new Set();
world.addEventListener("click", e => {
  const btn = e.target.closest(".pick, .info-pick");
  if (!btn) return;
  e.stopPropagation();
  togglePick(btn.closest(".book").dataset.id);
});
function togglePick(id) {
  const b = BOOKS.find(x => x.id === id);
  if (!b || b.sold) return;
  picked.has(id) ? picked.delete(id) : picked.add(id);
  renderPicks();
}
function renderPicks() {
  bookEls.forEach((el, id) => {
    const on = picked.has(id);
    el.classList.toggle("picked", on);
    const p = el.querySelector(".pick"); if (p) p.setAttribute("aria-pressed", on);
    const ip = el.querySelector(".info-pick"); if (ip) ip.textContent = on ? "選択をやめる" : "選ぶ";
  });
  const list = BOOKS.filter(b => picked.has(b.id));
  const total = list.reduce((s, b) => s + b.price, 0);
  $("thumbs").innerHTML = list.map(b => {
    if (b.front) return `<img src="${esc(b.front)}" alt="${esc(b.title)}">`;
    const [bg, band] = PALETTE[hash(b.publisher) % PALETTE.length];
    return `<span class="mini" style="--c-bg:${bg};--c-band:${band}" title="${esc(b.title)}"></span>`;
  }).join("");
  $("trayEmpty").hidden = list.length > 0;
  $("traySum").hidden = list.length === 0;
  $("trayCount").textContent = list.length;
  $("trayTotal").textContent = yen(total);
  $("openOrder").disabled = list.length === 0;
}

/* ---------- 検索・絞り込み ---------- */
const chipsEl = $("chips");
chipsEl.innerHTML = `<button class="chip" data-cat="" aria-pressed="true">すべて</button>` +
  clusters.map(c => `<button class="chip" data-cat="${esc(c.name)}" aria-pressed="false">${esc(c.name)}</button>`).join("");
let activeCat = "";
chipsEl.addEventListener("click", e => {
  const chip = e.target.closest(".chip"); if (!chip) return;
  activeCat = chip.dataset.cat;
  chipsEl.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", c === chip));
  filter(true);
});
const qEl = $("q"), maxEl = $("maxPrice");
let qTimer; qEl.addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(() => filter(true), 250); });
maxEl.addEventListener("change", () => filter(true));

const norm = s => String(s || "").normalize("NFKC").toLowerCase().replace(/\s+/g, "");
function filter(move) {
  const q = norm(qEl.value), max = Number(maxEl.value) || Infinity;
  const hits = BOOKS.filter(b =>
    (!activeCat || b.category === activeCat) && b.price <= max &&
    (!q || norm(b.title + b.author + b.publisher + (b.label || "")).includes(q)));
  const ids = new Set(hits.map(b => b.id));
  const filtering = q || activeCat || max !== Infinity;
  bookEls.forEach((el, id) => el.classList.toggle("dim", filtering && !ids.has(id)));
  $("found").textContent = filtering ? (hits.length ? `${hits.length}冊見つかりました` : "見つかりませんでした。言葉を変えてみてください") : "";
  if (move && hits.length) {
    const xs = hits.map(b => b._x), ys = hits.map(b => b._y);
    const w = Math.max(...xs) - Math.min(...xs) + 320, h = Math.max(...ys) - Math.min(...ys) + 420;
    const s = clampS(Math.min(1.1, innerWidth / w, (innerHeight - 200) / h));
    centerOn((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, s);
  }
}

/* ---------- 注文 ---------- */
const veil = $("veil"), sheet = $("sheet");
$("openOrder").onclick = () => showOrderForm();
veil.addEventListener("click", e => { if (e.target === veil) closeSheet(); });
listen(window, "keydown", e => { if (e.key === "Escape" && !veil.hidden) closeSheet(); });
function closeSheet() { veil.hidden = true; }

const form = { name: "", contact: "", when: "", note: "" };
function showOrderForm(error) {
  const list = BOOKS.filter(b => picked.has(b.id));
  if (!list.length) { closeSheet(); return; }
  const total = list.reduce((s, b) => s + b.price, 0);
  sheet.innerHTML = `
    <h2 id="sheetTitle">取り置きの申し込み</h2>
    <p class="lead">支払いはまだ発生しません。本は受け取りのときに現金でお支払いください。</p>
    <ul class="lines">${list.map(b => `<li><div class="t">${esc(b.title)}<small>${esc(b.author)}／${esc(b.publisher)}</small></div><span class="y">${yen(b.price)}</span><button class="x" data-rm="${esc(b.id)}" aria-label="${esc(b.title)}を外す">×</button></li>`).join("")}</ul>
    <div class="total"><span>${list.length}冊</span><span>合計 ${yen(total)}</span></div>
    <div class="how">受け取りまでの流れ<ol><li>申し込みが店主に届きます</li><li>店主が本を箱に詰め、連絡先にご連絡します</li><li>約束の日に店主宅で、本と現金を交換します</li></ol></div>
    <form id="orderForm" novalidate>
      ${error ? `<p class="err">${esc(error)}</p>` : ""}
      <div class="field"><label for="f-name">お名前<span>必須</span></label><input id="f-name" name="name" autocomplete="name" value="${esc(form.name)}" required></div>
      <div class="field"><label for="f-contact">連絡先（メールまたは電話番号）<span>必須</span></label><input id="f-contact" name="contact" autocomplete="email" value="${esc(form.contact)}" required></div>
      <div class="field"><label for="f-when">受け取り希望の日時</label><input id="f-when" name="when" placeholder="例：10月12日（日）の午後" value="${esc(form.when)}"></div>
      <div class="field"><label for="f-note">ひとこと</label><textarea id="f-note" name="note">${esc(form.note)}</textarea></div>
      <div class="hp" aria-hidden="true"><label for="f-web">空欄のまま</label><input id="f-web" name="website" tabindex="-1" autocomplete="off"></div>
      <div class="actions"><button type="button" class="btn ghost" id="cancel">戻る</button><button type="submit" class="btn" id="send">この内容で申し込む</button></div>
    </form>`;
  veil.hidden = false;
  sheet.querySelectorAll("[data-rm]").forEach(x => x.onclick = () => { saveForm(); togglePick(x.dataset.rm); showOrderForm(); });
  sheet.querySelector("#cancel").onclick = () => { saveForm(); closeSheet(); };
  sheet.querySelector("#orderForm").addEventListener("submit", submitOrder);
}
function saveForm() {
  const f = sheet.querySelector("#orderForm"); if (!f) return;
  form.name = f.name.value.trim(); form.contact = f.contact.value.trim(); form.when = f.when.value.trim(); form.note = f.note.value.trim();
}

function buildOrder() {
  const list = BOOKS.filter(b => picked.has(b.id));
  return {
    shop: shopName,
    name: form.name, contact: form.contact, when: form.when, note: form.note,
    books: list.map(b => ({ id: b.id, title: b.title, author: b.author, publisher: b.publisher, label: b.label || "", price: b.price })),
    total: list.reduce((s, b) => s + b.price, 0),
    sentAt: new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }),
  };
}
function mailText(o) {
  return `【${o.shop}】取り置きの申し込み\n\nお名前：${o.name}\n連絡先：${o.contact}\n受け取り希望：${o.when || "指定なし"}\nひとこと：${o.note || "なし"}\n\n` +
    o.books.map((b, i) => `${i + 1}. ${b.title}（${b.author}／${b.publisher}${b.label ? "・" + b.label : ""}）${yen(b.price)}  [${b.id}]`).join("\n") +
    `\n\n合計 ${o.books.length}冊 ${yen(o.total)}\n申込日時：${o.sentAt}`;
}

let sending = false;
async function submitOrder(e) {
  e.preventDefault();
  if (sending) return;
  saveForm();
  if (sheet.querySelector("#f-web").value) return; // ボット対策
  if (!form.name) return showOrderForm("お名前を入れてください。");
  if (!form.contact) return showOrderForm("連絡先を入れてください。受け取りの日程を連絡するのに使います。");
  const order = buildOrder();
  if (!orderEndpoint) return showDone(order, true);
  sending = true;
  const btn = sheet.querySelector("#send"); btn.disabled = true; btn.textContent = "送信中…";
  try {
    // Apps Script はCORSの応答を返さないため no-cors で送ります
    await fetch(orderEndpoint, { method: "POST", mode: "no-cors", headers: { "Content-Type": "text/plain;charset=utf-8" }, body: JSON.stringify(order) });
    showDone(order, false);
  } catch (err) {
    showOrderForm("送信できませんでした。通信状況を確かめて、もう一度押してください。");
  } finally { sending = false; }
}
function showDone(order, demo) {
  sheet.innerHTML = `
    <div class="done">
      <div class="mark"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg></div>
      <h2 id="sheetTitle">${demo ? "送信プレビュー" : "申し込みを受け付けました"}</h2>
      <p class="lead">${demo ? "送信先が未設定のため、店主に届くメールの文面を表示しています。" : `${esc(order.name)}さん、ありがとうございます。本の準備ができたら、${esc(order.contact)} にご連絡します。`}</p>
    </div>
    ${demo ? `<pre class="preview">${esc(mailText(order))}</pre>` : ""}
    <div class="actions"><button class="btn" id="fin">閉じる</button></div>`;
  sheet.querySelector("#fin").onclick = () => {
    if (!demo) { picked.clear(); renderPicks(); Object.assign(form, { name: "", contact: "", when: "", note: "" }); }
    closeSheet();
  };
}

/* ---------- 最初の表示 ---------- */
renderPicks();
filter(false);
const home = clusters[0] || { x: 0, y: 0 };
const homeScale = innerWidth < 600 ? 0.5 : 0.62;
if (intro) {                       // 別の本棚へ「飛んできた」ように、遠くから近づく
  centerOn(home.x, home.y, 0.12, false);
  requestAnimationFrame(() => centerOn(home.x, home.y, homeScale, true, 900));
} else centerOn(home.x, home.y, homeScale, false);
listen(window, "resize", () => filter(false));

  return {
    destroy() {
      destroyed = true; cancelAnimationFrame(rafId); clearTimeout(qTimer); cancelPress();
      cleanups.forEach(fn => fn());
    },
  };
}
