import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { ref, uploadBytesResumable } from "firebase/storage";
import { addDoc, collection, doc, onSnapshot, serverTimestamp } from "firebase/firestore";
import AppBar from "../components/AppBar.jsx";
import { useAuth } from "../auth/AuthContext.jsx";
import { db, storage } from "../firebase.js";

const MAX = 160;   // 1回に送れる写真の上限（80冊ぶん）
export default function UploadPage() {
  const { user, profile, ready } = useAuth();
  const input = useRef(null);
  const [files, setFiles] = useState([]);
  const [phase, setPhase] = useState("pick");      // pick → uploading → processing → done / error
  const [sent, setSent] = useState(0);
  const [job, setJob] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { if (phase !== "processing" || !job) return; return onSnapshot(doc(db, "jobs", job), s => {
    const d = s.data(); if (!d) return; setMsg(d);
    if (d.status === "done") setPhase("done");
    if (d.status === "error") setPhase("error");
  }); }, [phase, job]);

  if (ready && !user) return <Navigate to="/login" replace />;

  const pick = e => {
    const list = [...e.target.files].filter(f => f.type.startsWith("image/")).sort((a, b) => a.lastModified - b.lastModified || a.name.localeCompare(b.name));
    if (list.length > MAX) { setMsg(`1回に送れるのは${MAX}枚までです。分けてください。`); setFiles(list.slice(0, MAX)); } else setMsg("");
    setFiles(list.slice(0, MAX));
  };

  const start = async () => {
    setPhase("uploading"); setSent(0); setMsg("");
    try {
      const jobId = crypto.randomUUID();
      const metas = new Array(files.length);
      let next = 0, done = 0;
      const worker = async () => {
        while (next < files.length) {
          const i = next++, f = files[i];
          const path = `users/${user.uid}/raw/${jobId}/${String(i).padStart(4, "0")}-${f.name.replace(/[^\w.\-]/g, "_")}`;
          await new Promise((res, rej) => { const t = uploadBytesResumable(ref(storage, path), f, { contentType: f.type }); t.on("state_changed", null, rej, res); });
          metas[i] = { path, taken: f.lastModified, name: f.name };
          setSent(++done);
        }
      };
      await Promise.all([worker(), worker(), worker()]);
      const jobRef = await addDoc(collection(db, "jobs"), { uid: user.uid, status: "queued", files: metas, createdAt: serverTimestamp() });
      setJob(jobRef.id); setPhase("processing");
    } catch (e) { console.error(e); setMsg({ message: `アップロードに失敗しました（${e?.code || e?.message}）` }); setPhase("error"); }
  };

  const m = typeof msg === "object" ? msg : {};
  return (
    <>
      <AppBar title="本を追加" back={profile ? `/s/${profile.username}` : "/"} />
      <main className="form-page">
        {phase === "pick" && <>
          <h1>写真をまとめて追加</h1>
          <p className="lead">本を上から、<b>表紙 → 裏表紙（バーコード）</b>の順に撮って、まとめて選んでください。何冊ぶんでも一度に送れます（1回{MAX}枚まで）。</p>
          <input ref={input} type="file" accept="image/*" multiple hidden onChange={pick} />
          <button className="btn ghost" onClick={() => input.current.click()}>写真を選ぶ</button>
          {typeof msg === "string" && msg && <div className="err">{msg}</div>}
          {files.length > 0 && <>
            <div className="notice">{files.length}枚（約{Math.ceil(files.length / 2)}冊）を選びました。撮影した順に表と裏を組にします。</div>
            <button className="btn" onClick={start}>アップロードする</button>
          </>}
          <ol className="steps"><li>アップロード後は、この画面を閉じても大丈夫です</li><li>切り抜きと書名の検索は裏で進みます（1冊あたり数秒）</li><li>終わったら「本の管理」で値段を入れると、空間に浮かびます</li></ol>
        </>}
        {phase === "uploading" && <>
          <h1>送信中…</h1><progress max={files.length} value={sent} style={{ width: "100%" }} />
          <p className="lead">{sent} / {files.length} 枚。画面を開いたままにしてください。</p>
        </>}
        {phase === "processing" && <>
          <h1>本を切り抜いています</h1>
          <progress max={m.total || files.length} value={m.done || 0} style={{ width: "100%" }} />
          <p className="lead">{m.status === "running" ? `${m.done || 0} / ${m.total} 枚　（${m.books || 0}冊できました）` : "順番を待っています…"}<br />この画面を閉じても処理は続きます。</p>
        </>}
        {phase === "done" && <>
          <h1>できました</h1>
          <p className="lead">{m.books}冊を登録しました。{m.failed?.length ? `読み込めなかった写真が${m.failed.length}枚ありました。` : ""}</p>
          <Link className="btn" to="/manage">値段を入れる</Link>
        </>}
        {phase === "error" && <>
          <h1>うまくいきませんでした</h1>
          <div className="err">{m.message || "もう一度お試しください"}</div>
          <button className="btn ghost" onClick={() => { setPhase("pick"); setFiles([]); setMsg(""); }}>やり直す</button>
        </>}
      </main>
    </>
  );
}
