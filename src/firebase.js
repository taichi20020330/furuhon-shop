// Firebase の初期化。apiKey などは公開されても問題ない値（守るのは firestore.rules）。
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";
import { getStorage } from "firebase/storage";

const firebaseConfig = {
  apiKey: "AIzaSyAJGJSRAbO-h8qUmfLZLxk0fWEfDh_jS3Y",
  authDomain: "furuhon-shop.firebaseapp.com",
  projectId: "furuhon-shop",
  storageBucket: "furuhon-shop.firebasestorage.app",
  messagingSenderId: "944746790992",
  appId: "1:944746790992:web:301d82c1c688ff299b9155",
};

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);
export const storage = getStorage(app);
// 切り抜き後の画像（誰でも見られる）の URL
export const imageUrl = path => path ? `https://firebasestorage.googleapis.com/v0/b/${firebaseConfig.storageBucket}/o/${encodeURIComponent(path)}?alt=media` : "";
