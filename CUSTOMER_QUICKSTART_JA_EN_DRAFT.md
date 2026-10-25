# Workflow Automation Hub -2 — customer quick-start (JA / EN, DRAFT)

**Review document only. Not approved for public Store listing.**

## 日本語

### できること（試験段階）
1. 「Google接続」でご自身のBloggerアカウントのOAuth認証を行い、ブログ一覧を確認します。現状の開発用ビルドでは、開発者用Google OAuth Desktop JSONの事前登録が必要です。一般購入者向けの簡単接続は未完成です。
2. 「投稿・下書き（試験）」で **Blogger** を選び、.txtまたは.mdの記事ファイル、投稿先ブログ、タイトルを指定します。
3. 「投稿内容を確認」で、記事を読み取り、元ファイルの変更チェックを行います。
4. 下書き保存ボタンは、接続・ブログ確認・プレビューの条件が揃うまで無効です。本人が確認ダイアログで明示承認した場合のみ、Bloggerへ非公開の下書きを1件作る処理を開始します。
5. 「投稿履歴・結果不明を確認」を開き、記録された状態とBlogger記事IDを確認できます。

### 誤送信しないために
- **公開投稿は行いません**。Bloggerに非公開の下書きを作る実験的な機能です。
- ファイルを変えた場合は再確認が必要です。同じ記事・同じ投稿先の自動再送は禁止しています。
- 通信切断時、結果不明の記録が残る場合があります。Google Bloggerの実際の下書き一覧を確認し、同じ投稿を繰り返さないでください。
- YouTubeはローカルの動画情報プレビューのみ。アップロードや予約投稿にはまだ対応していません。
- パソコンを終了しても投稿を自動実行するクラウド機能はありません。

### ローカル保存する内容
- OAuthトークンおよびGoogle Desktop OAuth設定はWindows DPAPIによる保護を実装済みです。
- 投稿履歴はアプリ専用のローカルSQLiteに、日時、投稿先ブログID、記事タイトル、ファイル名、処理状態、確認できた記事IDを保存します。記事本文やGoogleパスワードは履歴に保存しません。
- アカウント接続の解除方法、保存履歴の削除、サポート窓口、公開プライバシーポリシーは正式販売前に用意し、実機で確認する必要があります。

## English

### Current experimental workflow
1. In **Google connection**, connect your own authorized Blogger account via OAuth and verify the blog list. The current developer build requires a preconfigured Google OAuth Desktop client JSON; easy consumer onboarding is not finished.
2. In **Post & draft (beta)**, select Blogger, a UTF-8 .txt/.md file, an authorized blog, and a title.
3. Preview and confirm the selected file and destination.
4. The draft button remains disabled until the preview and account checks pass; one explicit confirmation starts one remote Blogger *draft* request.
5. Open **Publishing history** to see actual local attempt records and confirmed Blogger post IDs.

### Safety and limitations
- No public Blogger publishing, no automatic retry of ambiguous requests, no YouTube uploads, and no unattended cloud scheduler.
- An interrupted request might have succeeded; inspect Blogger before taking further action.
- The application stores local posting metadata (file name, title, blog ID, timestamp, status, confirmed post ID) but not article content or OAuth tokens in the history database.
- Support contact, public privacy policy, in-app data removal workflow, Google verification and all Microsoft Store packaging gates are still pending.

Official API reference: https://developers.google.com/blogger/docs/3.0/reference/posts/insert
