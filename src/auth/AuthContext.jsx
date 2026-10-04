import { createContext, useContext, useEffect, useState } from "react";
import { onAuthStateChanged, signOut, sendEmailVerification } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase.js";

const Ctx = createContext({ user: null, profile: null, ready: false, verified: false, logout: () => {}, reload: () => {}, recheck: async () => false, resend: async () => {} });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [ready, setReady] = useState(false);
  const [verified, setVerified] = useState(false);

  const load = async u => {
    if (!u) return setProfile(null);
    try { const s = await getDoc(doc(db, "users", u.uid)); setProfile(s.exists() ? { id: u.uid, ...s.data() } : null); }
    catch { setProfile(null); }
  };
  useEffect(() => onAuthStateChanged(auth, async u => { setUser(u); setVerified(!!u?.emailVerified); await load(u); setReady(true); }), []);
  // メールの確認リンクを押したあと、状態を取り直す（ルールが見る確認済みの印も更新する）
  const recheck = async () => {
    const u = auth.currentUser; if (!u) return false;
    await u.reload(); await u.getIdToken(true);
    setVerified(u.emailVerified); return u.emailVerified;
  };
  const resend = () => sendEmailVerification(auth.currentUser);
  const value = { user, profile, ready, verified, logout: () => signOut(auth), reload: () => load(auth.currentUser), recheck, resend };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// Firebase のエラーを日本語にする
export function authMessage(e) {
  const m = {
    "auth/email-already-in-use": "このメールアドレスはすでに登録されています",
    "auth/invalid-email": "メールアドレスの形式が正しくありません",
    "auth/weak-password": "パスワードが短すぎます（8文字以上）",
    "auth/invalid-credential": "メールアドレスかパスワードが違います",
    "auth/user-not-found": "メールアドレスかパスワードが違います",
    "auth/wrong-password": "メールアドレスかパスワードが違います",
    "auth/too-many-requests": "試行が多すぎます。しばらくしてからやり直してください",
    "auth/network-request-failed": "通信できませんでした。電波を確認してください",
    "username-taken": "このユーザーネームはすでに使われています",
  };
  const known = m[e?.code] || m[e?.message];
  if (known) return known;
  console.error(e);
  return `うまくいきませんでした（${e?.code || e?.message || "unknown"}）`;
}
