/**
 * 浮かぶ古本屋：注文メール送信用 Google Apps Script
 * サイトから届いた取り置きの申し込みを、店主のGmailへメールで送ります。
 * 使い方は README.md の「2. 注文メールの設定」を見てください。
 */
// 送り先は、このスクリプトを作った（デプロイした）Googleアカウントのメールアドレスです。
// アドレスをコードに書かないので、GitHubに上げても公開されません。
const OWNER_EMAIL = Session.getEffectiveUser().getEmail();
const MAX_PER_HOUR = 20;   // 1時間に受け付ける申し込みの上限（いたずら・連打対策）

function doPost(e) {
  try {
    if (!allow_()) return json_({ ok: false, error: 'busy' });
    const o = JSON.parse(e.postData.contents);
    if (!o || !o.name || !o.contact || !Array.isArray(o.books) || o.books.length === 0) {
      return json_({ ok: false, error: 'invalid' });
    }
    // いたずら対策：1回の申し込みは50冊まで、文字数も制限
    const clip = (s, n) => String(s || '').slice(0, n);
    const books = o.books.slice(0, 50);
    const total = books.reduce((s, b) => s + (Number(b.price) || 0), 0);
    const yen = n => '¥' + Number(n).toLocaleString('ja-JP');

    const lines = books.map((b, i) =>
      `${i + 1}. ${clip(b.title, 120)}（${clip(b.author, 60)}／${clip(b.publisher, 60)}${b.label ? '・' + clip(b.label, 40) : ''}）${yen(b.price)}  [${clip(b.id, 20)}]`
    ).join('\n');

    const body =
`取り置きの申し込みが届きました。

お名前：${clip(o.name, 80)}
連絡先：${clip(o.contact, 120)}
受け取り希望：${clip(o.when, 120) || '指定なし'}
ひとこと：${clip(o.note, 1000) || 'なし'}

${lines}

合計 ${books.length}冊 ${yen(total)}
申込日時：${clip(o.sentAt, 40)}
`;

    MailApp.sendEmail({
      to: OWNER_EMAIL,
      subject: `【取り置き】${clip(o.name, 40)}さん ${books.length}冊 ${yen(total)}`,
      body: body,
      name: clip(o.shop, 40) || '古本屋',
    });

    // 申し込みの記録をスプレッドシートにも残したい場合は、下の行のコメントを外して設定してください
    // logToSheet_(o, books, total);

    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// ブラウザでURLを開いたときの確認用
function doGet() {
  return ContentService.createTextOutput('注文受付スクリプトは動いています。');
}

// 1時間あたりの受付数を数えて、上限を超えたら受け付けない
function allow_() {
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const cache = CacheService.getScriptCache();
    const n = Number(cache.get('count') || 0);
    if (n >= MAX_PER_HOUR) return false;
    cache.put('count', String(n + 1), 3600);
    return true;
  } finally {
    lock.releaseLock();
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// 最初に一度だけ実行して、Gmail送信の許可を出すための関数
function testMail() {
  MailApp.sendEmail(OWNER_EMAIL, 'テスト：注文メールの設定', 'この通知が届けば設定は完了です。');
}
