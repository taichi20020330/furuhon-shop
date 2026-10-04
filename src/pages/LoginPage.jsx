import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppBar from "../components/AppBar.jsx";
import { logIn } from "../auth/accounts.js";
import { authMessage } from "../auth/AuthContext.jsx";

export default function LoginPage() {
  const nav = useNavigate();
  const [f, setF] = useState({ email: "", pass: "" });
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState("");
  const set = k => e => setF({ ...f, [k]: e.target.value });
  const submit = async e => {
    e.preventDefault(); if (busy) return; setBusy(true); setFail("");
    try { await logIn({ email: f.email.trim(), password: f.pass }); nav("/shelves", { replace: true }); }
    catch (er) { setFail(authMessage(er)); setBusy(false); }
  };
  return (
    <>
      <AppBar title="ログイン" back="/" />
      <form className="form-page" onSubmit={submit}>
        <h1>ログイン</h1>
        <label>メールアドレス<input type="email" value={f.email} onChange={set("email")} autoComplete="email" inputMode="email" required /></label>
        <label>パスワード<input type="password" value={f.pass} onChange={set("pass")} autoComplete="current-password" required /></label>
        <button className="btn" type="submit" disabled={busy}>{busy ? "確認中…" : "ログイン"}</button>
        {fail && <div className="err">{fail}</div>}
        <p className="lead">はじめての方は <Link to="/signup">本棚をつくる</Link></p>
      </form>
    </>
  );
}
