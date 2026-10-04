// CSV（data/books.csv と同じ形式）を本のデータに変換する。
export function parseCSV(text) {
  text = text.replace(/^﻿/, "");
  const rows = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const head = (rows.shift() || []).map(h => h.trim());
  return rows.filter(r => r.some(v => v.trim())).map(r => Object.fromEntries(head.map((h, i) => [h, (r[i] ?? "").trim()])));
}
const truthy = v => /^(1|true|yes|済|売約済|sold|○|x)$/i.test(String(v || "").trim());
export function toBooks(rows) {
  return rows.map((r, i) => ({
    id: r.id || r.isbn || "row" + (i + 2),
    title: r.title || "書名準備中", author: r.author || "", publisher: r.publisher || "", label: r.label || "",
    category: r.category || "未分類", format: r.format || "bunko",
    price: Number(String(r.price || "").replace(/[^0-9]/g, "")),
    condition: r.condition || "", sold: truthy(r.sold), sample: truthy(r.sample),
    front: r.front || "", back: r.back || "",
  })).filter(b => b.price > 0);
}
