// データの取得口。いまは data/shelves.json と data/books.csv を読む。
// 将来 Firebase（Firestore）に替えるときは、このファイルの中身だけを差し替える。
import { parseCSV, toBooks } from "./csv.js";

let cache;
async function loadAll() {
  if (!cache) cache = (async () => {
    const [sj, csv] = await Promise.all([
      fetch("data/shelves.json", { cache: "no-cache" }).then(r => r.json()),
      fetch("data/books.csv", { cache: "no-cache" }).then(r => r.text()),
    ]);
    const all = toBooks(parseCSV(csv));
    const shelves = sj.shelves.map(s => {
      const books = s.categories?.length ? all.filter(b => s.categories.includes(b.category)) : all;
      return { ...s, books, cover: books.filter(b => b.front && !b.sold).slice(0, 4).map(b => b.front) };
    });
    return shelves;
  })();
  return cache;
}
export const OWNER_ID = "taichi";
export async function listShelves() { return (await loadAll()).map(({ books, ...s }) => ({ ...s, count: books.length })); }
export async function getShelf(id) { return (await loadAll()).find(s => s.id === id) || null; }
