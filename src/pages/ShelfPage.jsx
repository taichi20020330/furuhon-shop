import { useEffect, useState } from "react";
import { useParams, useLocation, Link } from "react-router-dom";
import AppBar from "../components/AppBar.jsx";
import ShelfSpace from "../components/ShelfSpace.jsx";
import { getShelf } from "../data/repo.js";
import { useAuth } from "../auth/AuthContext.jsx";

export default function ShelfPage({ id: fixedId, home }) {
  const params = useParams();
  const id = fixedId || params.id;
  const { state } = useLocation();
  const { user, logout } = useAuth();
  const [shelf, setShelf] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    setShelf(null); setErr(false);
    getShelf(id).then(s => s ? setShelf(s) : setErr(true)).catch(() => setErr(true));
  }, [id]);

  const mine = !!(user && shelf && user.uid === shelf.uid);
  return (
    <>
      <AppBar title={home ? "浮かぶ古本屋" : shelf ? `${shelf.name}の本棚` : "本棚"} sub={shelf ? `${shelf.books.length}冊` : ""} back={home ? null : "/shelves"} mine={mine} />
      {err && <p className="state">この本棚は見つかりませんでした。</p>}
      {!shelf && !err && <p className="state">読み込み中…</p>}
      {shelf && shelf.books.length > 0 && <ShelfSpace shelf={shelf} intro={!!state?.fly} />}
      {shelf && shelf.books.length === 0 && (
        <div className="state empty">
          <div><b>{shelf.name}</b><span> @{shelf.handle}</span></div>
          {shelf.bio && <p>{shelf.bio}</p>}
          <p>{shelf.pending ? "値段が入ると、本が浮かびます。" : "まだ本が浮かんでいません。"}</p>
          {mine && <div className="row"><Link className="btn" to="/upload">本を追加</Link>{shelf.pending > 0 && <Link className="btn ghost" to="/manage">値段を入れる</Link>}</div>}
          {mine && <button className="btn ghost" onClick={logout}>ログアウト</button>}
        </div>
      )}
    </>
  );
}
