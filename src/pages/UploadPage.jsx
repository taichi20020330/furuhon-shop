import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { ref, uploadBytesResumable } from "firebase/storage";
import { doc, onSnapshot, serverTimestamp, setDoc } from "firebase/firestore";
import AppBar from "../components/AppBar.jsx";
import { useAuth } from "../auth/AuthContext.jsx";
import { db, storage } from "../firebase.js";
import { listMyBooks } from "../data/repo.js";

const MAX_BOOKS = 30;   // 1人あたりの本の上限
// crypto.randomUUID は https か localhost でしか使えない（LAN のIPで開くスマホでは undefined）ため、自前で作る
const uuid = () => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, "0")).join("");
const CHUNK = 60;  // サーバー処理は60枚ずつの依頼に分ける
export default function UploadPage() {
  const { user, profile, ready } = useAuth();
  const input = useRef(null);
  const [files, setFiles] = useState([]);
  const [phase, setPhase] = useState("pick");      // pick → uploading → processing → done / error
  const [sent, setSent] = useState(0);
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState({});
  const [msg, setMsg] = useState("");
  const [have, setHave] = useState(null);
  useEffect(() => { if (user) listMyBooks(user.uid).then(l => setHave(l.length)).catch(() => setHave(0)); }, [user]);
  const room = Math.max(0, MAX_BOOKS - (have ?? 0));
  const MAX = room * 2 + 2;   // 写真の上限（表裏で1冊＋少し余裕）

  useEffect(() => {
    if (phase !== "processing" || !jobs.length) return;
    const all = {};
    const apply = () => {
      const v = Object.values(all);
      if (v.length < jobs.length) return;
      const sum = k => v.reduce((a, d) => a + (d[k] || 0), 0);
      const m = { total: sum("total"), done: sum("done"), books: sum("books"), failed: v.flatMap(d => d.failed || []), running: v.some(d => d.status === "running") };
      setStats(m);
      if (v.every(d => d.status === "done" || d.status === "error")) {
        if (v.every(d => d.status === "error")) { setMsg({ message: v[0].message }); setPhase("error"); } else setPhase("done");
      }
    };
    const offs = jobs.map(id => onSnapshot(doc(db, "jobs", id), s => { if (s.data()) { all[id] = s.data(); apply(); } }));
    return () => offs.forEach(f => f());
  }, [phase, jobs]);

  if (ready && !user) return <Navigate to="/login" replace />;

  const pick = e => {
    const list = [...e.target.files].filter(f => f.type.startsWith("image/")).sort((a, b) => a.lastModified - b.lastModified || a.name.localeCompare(b.name));
    if (list.length > MAX) { setMsg(`あと${room}冊ぶん（${MAX}枚まで）です。多い分は外しました。`); setFiles(list.slice(0, MAX)); } else setMsg("");
    setFiles(list.slice(0, MAX));
  };

  const start = async () => {
    setPhase("uploading"); setSent(0); setMsg("");
    try {
      const jobIds = Array.from({ length: Math.ceil(files.length / CHUNK) }, () => uuid());
      const metas = new Array(files.length);
      let next = 0, done = 0;
      const worker = async () => {
        while (next < files.length) {
          const i = next++, f = files[i];
          const path = `users/${user.uid}/raw/${jobIds[Math.floor(i / CHUNK)]}/${String(i).padStart(4, "0")}-${f.name.replace(/[^\w.\-]/g, "_")}`;
          await new Promise((res, rej) => { const t = uploadBytesResumable(ref(storage, path), f, { contentType: f.type }); t.on("state_changed", null, rej, res); });
          metas[i] = { path, taken: f.lastModified, name: f.name };
          setSent(++done);
        }
      };
      await Promise.all([worker(), worker(), worker()]);
      const made = [];
      for (let c = 0; c < jobIds.length; c++) {
        const part = metas.slice(c * CHUNK, (c + 1) * CHUNK);
        await setDoc(doc(db, "jobs", jobIds[c]), { uid: user.uid, status: "queued", files: part, createdAt: serverTimestamp() });
        made.push(jobIds[c]);
      }
      setJobs(made); setPhase("processing");
    } catch (e) { console.error(e); setMsg({ message: `アップロードに失敗しました（${e?.code || e?.message}）` }); setPhase("error"); }
  };

  const m = phase === "processing" || phase === "done" ? stats : (typeof msg === "object" ? msg : {});
  return (
    <>
      <AppBar title="本を追加" back={profile ? `/s/${profile.username}` : "/"} />
      <main className="form-page">
        {phase === "pick" && <>
          <h1>写真をまとめて追加</h1>
          <p className="lead">本を上から、<b>表紙 → 裏表紙（バーコード）</b>の順に撮って、まとめて選んでください。本棚には{MAX_BOOKS}冊まで置けます（いま{have ?? "…"}冊・あと{room}冊）。</p>
          <input ref={input} type="file" accept="image/*" multiple hidden onChange={pick} />
          <button className="btn ghost" disabled={room === 0} onClick={() => input.current.click()}>写真を選ぶ</button>
          {room === 0 && <div className="err">上限に達しています。「管理」から不要な本を削除してください。</div>}
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
          <p className="lead">{m.total ? `${m.done || 0} / ${m.total} 枚　（${m.books || 0}冊できました）` : "順番を待っています…"}<br />この画面を閉じても処理は続きます。</p>
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
