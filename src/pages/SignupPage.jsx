import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppBar from "../components/AppBar.jsx";
import { signUp } from "../auth/accounts.js";
import { authMessage, useAuth } from "../auth/AuthContext.jsx";

const emailOk = v => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
const RESERVED = ["taichi", "mio", "ren", "hana", "sou", "admin", "shelves", "signup", "login"];
export default function SignupPage() {
  const nav = useNavigate();
  const { reload } = useAuth();
  const [f, setF] = useState({ name: "", email: "", pass: "" });
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState("");
  const set = k => e => setF({ ...f, [k]: e.target.value });
  const errs = {
    name: !/^[A-Za-z0-9_]{3,20}$/.test(f.name) ? "3〜20文字の英数字と _ で入力してください" : RESERVED.includes(f.name.toLowerCase()) ? "このユーザーネームは使えません" : "",
    email: emailOk(f.email) ? "" : "メールアドレスの形式で入力してください",
    pass: f.pass.length >= 8 ? "" : "8文字以上にしてください",
  };
  const submit = async e => {
    e.preventDefault(); setTried(true); setFail("");
    if (Object.values(errs).some(Boolean) || busy) return;
    setBusy(true);
    try { await signUp({ username: f.name, email: f.email.trim(), password: f.pass }); await reload(); nav(`/s/${f.name.toLowerCase()}`, { replace: true, state: { fly: true } }); }
    catch (er) { setFail(authMessage(er)); setBusy(false); }
  };
  const show = k => tried && errs[k];
  return (
    <>
      <AppBar title="本棚をつくる" back="/shelves" />
      <form className="form-page" onSubmit={submit} noValidate>
        <h1>自分の本棚をつくる</h1>
        <p className="lead">登録しなくても、みんなの本棚は見られます。</p>
        <label>ユーザーネーム<input value={f.name} onChange={set("name")} autoCapitalize="none" autoComplete="username" placeholder="your_name" /><span className="err">{show("name")}</span></label>
        <label>メールアドレス（公開されません）<input type="email" value={f.email} onChange={set("email")} autoComplete="email" inputMode="email" placeholder="you@example.com" /><span className="err">{show("email")}</span></label>
        <label>パスワード<input type="password" value={f.pass} onChange={set("pass")} autoComplete="new-password" /><span className="err">{show("pass")}</span></label>
        <button className="btn" type="submit" disabled={busy}>{busy ? "登録中…" : "登録する"}</button>
        {fail && <div className="err">{fail}</div>}
        <p className="lead">すでに登録済みの方は <Link to="/login">ログイン</Link></p>
        <ol className="steps"><li>登録</li><li>本の写真（表・裏）をまとめて選ぶ（準備中）</li><li>しばらくすると、背景が消えた本があなたの空間に浮かぶ</li></ol>
      </form>
    </>
  );
}
