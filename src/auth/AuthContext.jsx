import { createContext, useContext, useEffect, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase.js";

const Ctx = createContext({ user: null, profile: null, ready: false, logout: () => {}, reload: () => {} });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [ready, setReady] = useState(false);

  const load = async u => {
    if (!u) return setProfile(null);
    try { const s = await getDoc(doc(db, "users", u.uid)); setProfile(s.exists() ? { id: u.uid, ...s.data() } : null); }
    catch { setProfile(null); }
  };
  useEffect(() => onAuthStateChanged(auth, async u => { setUser(u); await load(u); setReady(true); }), []);
  const value = { user, profile, ready, logout: () => signOut(auth), reload: () => load(auth.currentUser) };
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
