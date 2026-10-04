import { Link, useNavigate } from "react-router-dom";

// 画面上部の細いバー。左：戻る（本棚→一覧）またはロゴ、右：本棚一覧／登録。
export default function AppBar({ title, sub, back }) {
  const nav = useNavigate();
  return (
    <div className="appbar">
      {back
        ? <button className="ab-back" aria-label="みんなの本棚へ戻る" onClick={() => nav(back)}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7"/></svg>
          </button>
        : <Link to="/" className="ab-logo" aria-label="トップ">浮</Link>}
      <div className="ab-title"><b>{title}</b>{sub && <span>{sub}</span>}</div>
      <nav className="ab-nav">
        {!back && <Link to="/shelves">みんなの本棚</Link>}
        <Link to="/signup" className="ab-cta">登録</Link>
      </nav>
    </div>
  );
}
