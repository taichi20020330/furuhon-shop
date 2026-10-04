"""写真アップロードの裏処理。
流れ：ブラウザが Storage の users/{uid}/raw/{jobId}/ に写真を置く → jobs/{jobId} を作る（status=queued）
     → この関数が起動して切り抜き・ISBN読み取り・書誌検索 → 切り抜き画像を users/{uid}/cut/ に保存し、
       shelves/{uid}/books/{bookId} に本を登録 → 元写真を削除 → jobs の status を done にする。"""
import io
import tempfile
from pathlib import Path

from firebase_admin import firestore, initialize_app, storage
from firebase_functions import firestore_fn, options

initialize_app()
from billing_guard import stop_billing  # noqa: E402,F401  予算超過で請求を止める関数もデプロイ対象にする
MAX_BOOKS = 30     # 1人あたりの本の上限
MAX_PHOTOS = 80   # 1ジョブの上限（40冊ぶん）。イベント起動の関数は最長9分のため。画面側で60枚ずつに分けて送る


def _webp_bytes(im, height, quality):
    """高さを height に縮めて webp にする（通信量を減らすため、用途ごとに小さくする）"""
    if im.height > height:
        im = im.resize((round(im.width * height / im.height), height))
    buf = io.BytesIO()
    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


@firestore_fn.on_document_created(
    document="jobs/{jobId}", region="asia-northeast1",
    memory=options.MemoryOption.GB_2, timeout_sec=540, max_instances=3,
)
def process_job(event: firestore_fn.Event[firestore_fn.DocumentSnapshot]) -> None:
    from batch import run_batch   # 重い import は起動時でなく実行時に

    job = event.data
    ref = job.reference
    d = job.to_dict() or {}
    uid, job_id = d.get("uid", ""), event.params["jobId"]
    files = d.get("files") or []
    prefix = f"users/{uid}/raw/{job_id}/"
    if not uid or d.get("status") != "queued" or not files or len(files) > MAX_PHOTOS \
            or any(not str(f.get("path", "")).startswith(prefix) for f in files):
        ref.update({"status": "error", "message": "ジョブの内容が正しくありません"})
        return

    db = firestore.client()
    bucket = storage.bucket()
    ref.update({"status": "running", "done": 0, "total": len(files), "books": 0})
    books_col = db.collection("shelves").document(uid).collection("books")
    existing = {s.id for s in books_col.select([]).stream()}

    remaining = MAX_BOOKS - len(existing)
    if remaining <= 0:
        ref.update({"status": "error", "message": f"本棚の上限（{MAX_BOOKS}冊）に達しています。不要な本を削除してください"})
        return

    tmp = Path(tempfile.mkdtemp())
    items = []
    for i, f in enumerate(files):
        p = tmp / f"{i:04d}{Path(f['path']).suffix.lower() or '.jpg'}"
        try:
            bucket.blob(f["path"]).download_to_filename(str(p))
            taken = f.get("taken")
            items.append((p, (taken / 1000.0) if taken else None, f.get("name") or p.name))
        except Exception:
            pass

    def save_book(bid, front, back, info, warns):
        base = f"users/{uid}/cut/{bid}"
        paths = {}
        # 表紙：空間用の小さい版(thumb 高さ320)と拡大用(front 高さ760)。裏表紙は拡大用のみ（開いたときだけ読み込まれる）
        for key, im, h, q in (("thumb", front, 320, 72), ("front", front, 760, 76), ("back", back, 760, 76)):
            if im is None:
                continue
            name = {"thumb": f"{base}-thumb.webp", "front": f"{base}-front.webp", "back": f"{base}-back.webp"}[key]
            blob = bucket.blob(name)
            blob.cache_control = "public, max-age=31536000"
            blob.upload_from_string(_webp_bytes(im, h, q), content_type="image/webp")
            paths[key] = name
        books_col.document(bid).set({
            "id": bid, "isbn": info.get("isbn", ""), "title": info.get("title", ""), "author": info.get("author", ""),
            "publisher": info.get("publisher", ""), "label": info.get("label", ""), "category": info.get("category", "") or "未分類",
            "format": info.get("format", "") or "bunko", "price": 0, "condition": "", "sold": False,
            "front": paths.get("front", ""), "thumb": paths.get("thumb", ""), "back": paths.get("back", ""), "warnings": warns,
            "jobId": job_id, "createdAt": firestore.SERVER_TIMESTAMP,
        })

    last = [0.0]
    def progress(n, total, made):
        import time
        if time.time() - last[0] > 2 or n == total:
            last[0] = time.time()
            ref.update({"done": n, "books": made})

    try:
        made, failed = run_batch(items, existing, save_book, progress, limit=remaining)
        ref.update({"status": "done", "books": made, "failed": failed, "done": len(files)})
    except Exception as e:  # noqa: BLE001
        ref.update({"status": "error", "message": f"処理中にエラー: {type(e).__name__}"})
        raise
    finally:
        for f in files:      # 元写真は処理後に消す（保存料金とプライバシーのため）
            try:
                bucket.blob(f["path"]).delete()
            except Exception:
                pass
