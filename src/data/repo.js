// データの取得口。サンプルの本棚は data/shelves.json + data/books.csv、
// 登録ユーザーは Firestore（users）から読む。
import { collection, getDocs, query, where, limit } from "firebase/firestore";
import { db } from "../firebase.js";
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
    return q.empty ? null : fromUser(q.docs[0]);
  } catch { return null; }
}
