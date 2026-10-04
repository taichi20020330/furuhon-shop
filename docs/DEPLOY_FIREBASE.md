# Firebase（写真処理・ルール）のデプロイ手順

1. コンソールで **Storage →「始める」**（ロケーションは asia-northeast1 / 東京）。Blaze への切替と予算アラートは設定済みの前提。
2. Mac に Firebase CLI：`npm install -g firebase-tools` → `firebase login`
3. 関数の Python 環境（Python 3.12 推奨）：
   ```
   cd functions
   python3.12 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   cd ..
   ```
4. デプロイ（リポジトリの直下で。初回は数分、API有効化の確認が出たら Y）：
   ```
   firebase deploy --only firestore:rules,storage,functions
   ```
   - 実行前に `tools/book_cutout.py` と `tools/process_photos.py` が自動で `functions/` にコピーされます。
5. 画面の「本を追加」から写真を送る → 処理されると「本の管理」に本が並ぶ → 値段を入れると空間に浮かぶ。

ログ確認：コンソール → Functions →「process_job」→ ログ。
