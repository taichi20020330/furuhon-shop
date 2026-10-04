import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AppBar from "../components/AppBar.jsx";
import { listShelves, getShelf } from "../data/repo.js";

export default function ShelfListPage() {
  const [items, setItems] = useState(null);
  useEffect(() => { listShelves().then(setItems); }, []);
  return (
    <div className="page">
      <AppBar title="みんなの本棚" back="/" />
      <main className="list">
        {!items && <p className="state">読み込み中…</p>}
        {items?.map(s => (
          <Link key={s.id} to={`/s/${s.id}`} state={{ fly: true }} className="card">
            <div className="cover">{s.cover.map((src, i) => <img key={i} src={src} alt="" loading="lazy" draggable="false" />)}</div>
            <div className="meta">
              <div className="nm"><b>{s.name}</b><span>@{s.handle}</span>{s.sample && <em>サンプル</em>}</div>
              <p>{s.bio}</p>
              <small>{s.count}冊が浮かんでいます</small>
            </div>
            <svg className="chev" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7"/></svg>
          </Link>
        ))}
        <Link to="/signup" className="card join"><b>自分の本棚をつくる</b><small>写真をまとめてアップロードすると、本が空間に浮かびます</small></Link>
      </main>
    </div>
  );
}
