import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

// 画面上部の細いバー。左：戻る（本棚→一覧）またはロゴ、右：本棚一覧／登録・ログイン／自分の本棚。
export default function AppBar({ title, sub, back, mine }) {
  const nav = useNavigate();
  const { user, profile, ready } = useAuth();
  return (
    <div className="appbar">
      {back
        ? <button className="ab-back" aria-label="戻る" onClick={() => nav(back)}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7"/></svg>
          </button>
        : <Link to="/" className="ab-logo" aria-label="トップ">浮</Link>}
      <div className="ab-title"><b>{title}</b>{sub && <span>{sub}</span>}</div>
      <nav className="ab-nav">
        {!back && <Link to="/shelves">みんなの本棚</Link>}
        {mine && <><Link to="/manage">管理</Link><Link to="/upload" className="ab-cta">本を追加</Link></>}
        {ready && !mine && (user && profile
          ? <Link to={`/s/${profile.username}`} state={{ fly: true }} className="ab-cta">{profile.name}</Link>
          : !user && <Link to="/login" className="ab-cta">ログイン</Link>)}
      </nav>
    </div>
  );
}
