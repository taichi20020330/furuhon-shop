import { useState } from "react";
import AppBar from "../components/AppBar.jsx";

// 登録画面（見た目と入力チェックのみ）。まだ送信先（Firebase Auth）はつないでいないので、入力内容はどこにも送られない。
const emailOk = v => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
export default function SignupPage() {
  const [f, setF] = useState({ name: "", email: "", pass: "" });
  const [tried, setTried] = useState(false);
  const set = k => e => setF({ ...f, [k]: e.target.value });
  const errs = {
    name: /^[A-Za-z0-9_]{3,20}$/.test(f.name) ? "" : "3〜20文字の英数字と _ で入力してください",
    email: emailOk(f.email) ? "" : "メールアドレスの形式で入力してください",
    pass: f.pass.length >= 8 ? "" : "8文字以上にしてください",
  };
  const submit = e => { e.preventDefault(); setTried(true); };
  const show = k => tried && errs[k];
  return (
    <>
      <AppBar title="本棚をつくる" back="/shelves" />
      <form className="form-page" onSubmit={submit} noValidate>
        <h1>自分の本棚をつくる</h1>
        <p className="lead">登録しなくても、みんなの本棚は見られます。</p>
        <label>ユーザーネーム<input value={f.name} onChange={set("name")} autoCapitalize="none" autoComplete="username" placeholder="your_name" /><span className="err">{show("name")}</span></label>
        <label>メールアドレス<input type="email" value={f.email} onChange={set("email")} autoComplete="email" inputMode="email" placeholder="you@example.com" /><span className="err">{show("email")}</span></label>
        <label>パスワード<input type="password" value={f.pass} onChange={set("pass")} autoComplete="new-password" /><span className="err">{show("pass")}</span></label>
        <button className="btn" type="submit">登録する</button>
        {tried && !Object.values(errs).some(Boolean) && <div className="notice">登録機能は準備中です。入力内容は送信も保存もされていません。</div>}
        <ol className="steps"><li>登録</li><li>本の写真（表・裏）をまとめて選ぶ</li><li>しばらくすると、背景が消えた本があなたの空間に浮かぶ</li></ol>
      </form>
    </>
  );
}
