// データの取得口。サンプルの本棚は data/shelves.json + data/books.csv、
// 登録ユーザーは Firestore（users）から読む。
import { collection, getDocs, query, where, limit } from "firebase/firestore";
import { db, imageUrl } from "../firebase.js";
import { parseCSV, toBooks } from "./csv.js";

let cache;
async function loadStatic() {
  if (!cache) cache = (async () => {
    const [sj, csv] = await Promise.all([
      fetch("data/shelves.json", { cache: "no-cache" }).then(r => r.json()),
      fetch("data/books.csv", { cache: "no-cache" }).then(r => r.text()),
    ]);
    const all = toBooks(parseCSV(csv));
    return sj.shelves.map(s => {
      const books = s.categories?.length ? all.filter(b => s.categories.includes(b.category)) : all;
      return { ...s, books, cover: books.filter(b => b.front && !b.sold).slice(0, 4).map(b => b.front) };
    });
  })();
  return cache;
}
// Firestore の本 → 空間エンジンが読む形。値段が未入力(0)の本は空間に出さない。
const fromBook = d => { const b = d.data(); return {
  id: d.id, title: b.title || "書名準備中", author: b.author || "", publisher: b.publisher || "", label: b.label || "",
  category: b.category || "未分類", format: b.format || "bunko", price: Number(b.price) || 0, condition: b.condition || "",
  sold: !!b.sold, sample: false, front: imageUrl(b.front), thumb: imageUrl(b.thumb), back: imageUrl(b.back),
}; };
export async function listMyBooks(uid) {
  const snap = await getDocs(collection(db, "shelves", uid, "books"));
  return snap.docs.map(d => ({ ...d.data(), id: d.id }));
}
async function loadUserBooks(uid) {
  const snap = await within(getDocs(collection(db, "shelves", uid, "books")), 8000);
  return snap.docs.map(fromBook);
}
const fromUser = d => ({ id: d.data().username, uid: d.id, name: d.data().name || d.data().username, handle: d.data().username, bio: d.data().bio || "", books: [], cover: [], registered: true });

const within = (p, ms) => Promise.race([p, new Promise((_, r) => setTimeout(() => r(new Error("timeout")), ms))]);

export const OWNER_ID = "taichi";
export async function listShelves() {
  const st = await loadStatic();
  let users = [];
  try { users = (await within(getDocs(collection(db, "users")), 5000)).docs.map(fromUser); } catch (e) { console.warn("users を読めませんでした", e); }
  return [...st, ...users].map(({ books, ...s }) => ({ ...s, count: books.length }));
}
export async function getShelf(id) {
  const hit = (await loadStatic()).find(s => s.id === id);
  if (hit) return hit;
  try {
    const q = await within(getDocs(query(collection(db, "users"), where("username", "==", id), limit(1))), 5000);
    if (q.empty) return null;
    const u = fromUser(q.docs[0]);
    const all = await loadUserBooks(u.uid);
    const shown = all.filter(b => b.price > 0 && b.front);
    return { ...u, books: shown, pending: all.length - shown.length, cover: shown.filter(b => !b.sold).slice(0, 4).map(b => b.thumb || b.front) };
  } catch { return null; }
}
