// Firebase の初期化。apiKey などは公開されても問題ない値（守るのは firestore.rules）。
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

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
