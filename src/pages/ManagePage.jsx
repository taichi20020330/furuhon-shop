import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { doc, updateDoc, deleteDoc } from "firebase/firestore";
import AppBar from "../components/AppBar.jsx";
import { useAuth } from "../auth/AuthContext.jsx";
import { db, imageUrl } from "../firebase.js";
import { listMyBooks } from "../data/repo.js";

const CATS = ["文学", "社会学", "哲学・思想", "法・政治", "歴史・地理", "芸術・暮らし", "語学", "洋書", "科学", "産業", "その他"];
export default function ManagePage() {
  const { user, profile, ready } = useAuth();
  const [books, setBooks] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { if (user) listMyBooks(user.uid).then(l => setBooks(l.sort((a, b) => (b.createdAt?.seconds || 0) - (a.createdAt?.seconds || 0)))).catch(e => setErr(e.code || e.message)); }, [user]);
  if (ready && !user) return <Navigate to="/login" replace />;

  const patch = (id, v) => setBooks(bs => bs.map(b => b.id === id ? { ...b, ...v } : b));
  const save = async (b, v) => { patch(b.id, v); try { await updateDoc(doc(db, "shelves", user.uid, "books", b.id), v); } catch (e) { setErr(e.code || e.message); } };
  const remove = async b => { if (!confirm(`「${b.title || "書名なし"}」を削除しますか？`)) return; await deleteDoc(doc(db, "shelves", user.uid, "books", b.id)); setBooks(bs => bs.filter(x => x.id !== b.id)); };
  const unpriced = books?.filter(b => !(b.price > 0)).length || 0;

  return (
    <>
      <AppBar title="本の管理" sub={books ? `${books.length}冊` : ""} back={profile ? `/s/${profile.username}` : "/"} />
      <main className="form-page">
        {err && <div className="err">エラー：{err}</div>}
        {!books && !err && <p className="lead">読み込み中…</p>}
        {books && books.length === 0 && <p className="lead">まだ本がありません。</p>}
        {unpriced > 0 && <div className="notice">値段が未入力の本が{unpriced}冊あります。値段を入れると本棚に浮かびます。</div>}
        {books?.map(b => (
          <div key={b.id} className="mrow">
            <img src={imageUrl(b.front)} alt="" draggable="false" />
            <div className="mf">
              <input defaultValue={b.title} placeholder="書名" onBlur={e => e.target.value !== b.title && save(b, { title: e.target.value.trim() })} />
              <div className="two">
                <label>値段<input type="number" inputMode="numeric" min="0" step="50" defaultValue={b.price || ""} placeholder="円"
                  onBlur={e => { const n = Math.max(0, Math.floor(Number(e.target.value) || 0)); if (n !== b.price) save(b, { price: n }); }} /></label>
                <label>分類<select value={b.category} onChange={e => save(b, { category: e.target.value })}>
                  {[...new Set([b.category, ...CATS])].map(c => <option key={c}>{c}</option>)}</select></label>
              </div>
              {b.warnings?.length > 0 && <small className="warn">※{b.warnings.join("・")}</small>}
              <button className="del" onClick={() => remove(b)}>削除</button>
            </div>
          </div>
        ))}
      </main>
    </>
  );
}
