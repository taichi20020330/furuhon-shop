import { createUserWithEmailAndPassword, signInWithEmailAndPassword, deleteUser } from "firebase/auth";
import { doc, runTransaction, serverTimestamp } from "firebase/firestore";
import { auth, db } from "../firebase.js";

// 登録：Auth にアカウントを作り、ユーザーネームの予約（usernames）とプロフィール（users）を同時に書く。
// メールアドレスは Firestore には保存しない（Auth だけが持つ）。
export async function signUp({ username, email, password }) {
  const name = username.toLowerCase();
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  try {
    await runTransaction(db, async tx => {
      const nameRef = doc(db, "usernames", name);
      if ((await tx.get(nameRef)).exists()) throw new Error("username-taken");
      tx.set(nameRef, { uid: cred.user.uid });
      tx.set(doc(db, "users", cred.user.uid), { username: name, name: username, bio: "", createdAt: serverTimestamp() });
    });
  } catch (e) {
    await deleteUser(cred.user).catch(() => {});   // ネーム重複などは、作りかけのアカウントを消してやり直せるように
    throw e;
  }
  return cred.user;
}
export const logIn = ({ email, password }) => signInWithEmailAndPassword(auth, email, password);
