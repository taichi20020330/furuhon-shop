# 本棚ネットワーク 設計メモ

ブランチ `feature/shelf-network`。「浮かぶ古本屋」を、複数人の本棚をつなぐサービスの入り口にする。

## いま動くもの（このブランチ）
- Vite + React + react-router（HashRouter）。`npm install` → `npm run dev`
- `/` たいちの本棚（最初の画面・登録不要）／`/shelves` みんなの本棚（一覧）／`/s/:id` 各人の空間／`/signup` 登録画面（見た目と入力チェックのみ。送信なし）
- 一覧をタップ → 遠くから近づく演出で相手の空間へ。左上の「‹」で一覧へ戻る
- 空間エンジンは `src/space/shelfSpace.js`（従来の動きをそのまま部品化）。従来版は `legacy/index.html` に残してある
- データは `src/data/repo.js` が `data/shelves.json` と `data/books.csv` を読む。**ここだけ差し替えれば Firebase に移れる**
- サンプルユーザーは削除済み。一覧に出るのは、お店の持ち主と、登録したユーザー（Firestore）だけ

## 1. 登録とパスワード：Firebase は必要か
**必要。** パスワードは自前で保存しない（GitHub Pages には保存先も安全に扱う仕組みもない）。
- **Firebase Authentication**：メール＋パスワード。ハッシュ化・再設定メール・ログイン保持を任せる。
- **Cloud Firestore**：`users/{uid}`（ユーザーネーム・紹介文）、`shelves/{uid}/books/{bookId}`（書名・価格・画像パス・sold）
- **Cloud Storage**：`users/{uid}/raw/…`（元写真）、`users/{uid}/cut/…`（切り抜き後 webp）
- メールアドレスは本人以外に見せない（公開ドキュメントに入れず、Auth 側だけに置く）。
- ルール案：本棚の閲覧は誰でも可、書き込みは `request.auth.uid == uid` のみ。注文メールは今の Apps Script を各人宛てに拡張（相手のアドレスは公開しない）。

## 2. 写真の一括登録（操作負荷を下げる）
- `<input type="file" multiple accept="image/*">` で**何枚でも一度に選べる**（スマホはアルバムから複数選択、PCはフォルダ内を全選択）。フォルダごとのドロップはPCのみ。
- 撮影時刻順か、裏表紙のバーコードで「表・裏」をペアにする（今の `tools/process_photos.py` と同じ考え方）。値段は一覧画面でまとめて入力。
- アップロードしたら画面を閉じてOK。**裏で処理 → 完了したら本が空間に浮かぶ**（「処理中 12/40」を表示）。
- 切り抜き処理の置き場所（要選択）：
  - A. **サーバー側（推奨）**：Storage にアップ → Cloud Functions / Cloud Run が既存の Python（`book_cutout.py`）を実行 → Firestore に登録。端末の性能に依存せず結果が安定。Blaze（従量課金）プランが必要。
  - B. 端末内：OpenCV.js で処理。無料だが、スマホで40枚はつらく機種差が出る。
- まず A で、枚数制限（例：1回40冊）から始めるのが安全。

## 3. 次の一歩（提案）
1. Firebase プロジェクト作成 → Auth/Firestore をつなぎ、`repo.js` を差し替え、`/signup` を実装
2. 写真アップロード画面 → 処理 Function → 自分の空間に反映
3. 公開：このアプリはビルドが必要なので、GitHub Pages は Actions 配信への切替が必要（main の今の公開は、切替までそのまま）
4. HAMTOHONTO 連携：受け渡し日（月1）の表示、本に「当日持っていく」印、当日の本を集めた「HAMTOHONTOの棚」空間

## スマホで試す
`npm run dev` → 同じWi-Fiのスマホで `http://<PCのIP>:5173/` を開く。
