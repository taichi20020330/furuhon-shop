# 不正アクセス・使いすぎ対策

## すでに入っているもの（コード）
- 写真は本人のみ・画像のみ・1枚20MBまで／1人30冊まで／1回の依頼は60枚まで／関数は同時3つまで
- **メール確認が済んだ人だけ**写真を送れる（ルールで強制）
- 画像は小さく配信：空間では表紙の小さい版（約12KB）だけを読み、裏表紙・拡大は開いたときにだけ読む（従来の約1/5〜1/10）

## 1. メール確認（コンソール作業は不要）
- 登録すると確認メールが届く。メールの文面は Authentication →「テンプレート」で日本語にできる（任意）。
- `firestore.rules` と `storage.rules` が変わったので再デプロイ：`firebase deploy --only firestore:rules,storage,functions`

## 2. App Check（このアプリ以外からの通信を弾く）
1. https://www.google.com/recaptcha/admin で **reCAPTCHA v3** のサイトを作る（ドメイン：taichi20020330.github.io と localhost）。「サイトキー」と「シークレットキー」が出る。
2. Firebase コンソール → App Check → アプリを選び →「reCAPTCHA」→ **シークレットキー**を貼って登録。
3. `src/firebase.js` の `APPCHECK_SITE_KEY` に **サイトキー**を入れる。
4. 開発中（localhost / LAN のIP）：ブラウザのコンソールに「App Check debug token」が出る → App Check →「デバッグトークンを管理」に登録。
5. App Check の画面で **Cloud Firestore だけ**「適用（Enforce）」を押す。
   - Storage は適用しない（画像を `<img>` で直接読むため、適用すると画像が出なくなる）。Storage は「ログイン済み＋メール確認済み＋サイズ制限」で守る。
   - 適用する前に、メトリクスで正常なアクセスが通っていることを数日見るのが安全。

## 3. 請求の自動停止
予算を超えたら、プロジェクトと請求先の紐づけを外して有料サービスを止める。
1. Google Cloud コンソール → APIとサービス → **Cloud Billing API** を有効化。
2. `firebase deploy --only functions` で `stop_billing` が作られる（Pub/Sub のトピック `budget-alerts` も自動で作られる）。
3. お支払い → 予算とアラート → **新しい予算**（例：1,000円）→「Pub/Sub トピックを接続する」で `budget-alerts` を選ぶ。（いまの500円アラートは通知用にそのまま残す）
4. 権限：お支払い → アカウント管理 →「権限」で、関数のサービスアカウント（`944746790992-compute@developer.gserviceaccount.com`）に **「Billing Account Administrator（請求先アカウント管理者）」** を付ける。
5. 止まったあと：お支払いからプロジェクトに請求先を再リンクすれば復旧できる（Firebase を Blaze に戻す操作が必要な場合あり）。

注意：予算の通知は数時間遅れることがあり、**厳密な上限ではない**（超えた直後に止まるわけではない）。それでも、青天井になるのは防げる。
