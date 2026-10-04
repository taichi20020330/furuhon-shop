import { useEffect, useState } from "react";
import { useParams, useLocation } from "react-router-dom";
import AppBar from "../components/AppBar.jsx";
import ShelfSpace from "../components/ShelfSpace.jsx";
import { getShelf } from "../data/repo.js";

export default function ShelfPage({ id: fixedId, home }) {
  const params = useParams();
  const id = fixedId || params.id;
  const { state } = useLocation();
  const [shelf, setShelf] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    setShelf(null); setErr(false);
    getShelf(id).then(s => s ? setShelf(s) : setErr(true)).catch(() => setErr(true));
  }, [id]);

  return (
    <>
      <AppBar title={shelf ? `${shelf.name}の本棚` : "本棚"} sub={shelf ? `${shelf.books.length}冊` : ""} back={home ? null : "/shelves"} />
      {err && <p className="state">この本棚は見つかりませんでした。</p>}
      {!shelf && !err && <p className="state">読み込み中…</p>}
      {shelf && <ShelfSpace shelf={shelf} intro={!!state?.fly} />}
    </>
  );
}
