# forecasting 正式配布版 — 2026-10-24 r2

この一式を、新しく作るV4用のPrivateリポジトリ `forecasting` に入れます。
V1〜V3のリポジトリは継続利用します。V3側には入力出力用の2ファイルを追加します。

## 1. 新しいforecastingへアップロード

ZIPを「すべて展開」し、中のforecastingフォルダの**中身**をアップロードします。
リポジトリのトップに run.py / requirements.txt / models / common / integration が見える配置です。
アカウントを別タブで切り替えた場合は、アップロード画面を再読み込みしてください。

隠しファイルが入らなかった場合、Add file → Create new fileで次を作成します。

| 作成する名前 | 貼り付ける内容 |
|---|---|
| `.github/workflows/forecasting.yml` | `WORKFLOW_SETUP.yml` の全文 |
| `.gitignore` | `GITIGNORE_SETUP.txt` の全文 |

作成後、Actions → Forecasting V4 A+B → Run workflow。
初回は operation=demo / model=both / market=BOTH / profile=standard。
4つの計算ジョブとplanが成功することを確認します。デモの履歴は本番のpredictionsには入りません。

## 2. V3側のリポジトリへ2ファイル追加

このZIPの integration/v3_source/ を開きます。**V1〜V3が入っている元のリポジトリ**へ追加します。

| 元のリポジトリに置く場所 | このZIPのコピー元 |
|---|---|
| `scripts/export_v4_inputs.py` | `integration/v3_source/scripts/export_v4_inputs.py` |
| `.github/workflows/v4-inputs.yml` | `integration/v3_source/WORKFLOW_V4_INPUTS.yml` の全文 |

V3の main.py や既存ワークフローを置き換える必要はありません。
接続コードは stock_forecast_complete_v3_20261024_r1.zip のV3構造で確認しました。
実際のGitHub側でV3をさらに変更している場合は、その差分の確認が必要です。

元のリポジトリでActions → Export V3 inputs for V4を実行します。
market=BOTH / base_set=M3（V3で使っている情報集合とそろえる）。
V3に設定済みのFRED_API_KEYを再利用します。EDINET/SECの取得は既存V3が担当します。
このワークフロー自体はEDINET/SECの履歴同期を繰り返しません。

成功すると元のリポジトリに v4_inputs/JP/ と v4_inputs/US/ が保存されます。
圧縮CSVとmanifest.jsonで、株価・特徴量・実際の取引日程を渡します。
V3の同期がまだ終わっていない市場は、その旨を表示します。用意できた市場の入力は保存します。

## 3. forecastingから入力を読めるようにする

元のアカウントで、GitHubのSettings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new tokenを開きます。
元のV1〜V3リポジトリだけを選び、Repository permissions → Contents = Read-only。
作成した値を、新アカウントのforecastingのSecretに保存します。

forecasting → Settings → Secrets and variables → Actions。

| 種類 | 名前 | 値 |
|---|---|---|
| Variables | FEATURE_REPOSITORY | 元アカウント名/元のリポジトリ名 |
| Variables | FEATURE_BRANCH | main（実際のデフォルトブランチ名） |
| Variables | FEATURE_SUBDIR | v4_inputs |
| Secrets | FEATURES_READ_TOKEN | 上で作成した元アカウントのトークン |

トークンの値はGitHubのSecret欄に直接保存します。

## 4. 実データで確認

forecastingのActions → Forecasting V4 A+B → Run workflow。
operation=live / model=both / market=BOTH / profile=standard。
JPが準備中なら market=US で先に確認できます。

| 出力 | 場所 |
|---|---|
| 予測CSV・設定JSON | predictions/v4a/JP・US / predictions/v4b/JP・US |
| 実績との照合CSV・JSON | evaluations/v4a/JP・US / evaluations/v4b/JP・US |
| 最新の推定状態 | state/v4a/JP・US / state/v4b/JP・US（Actionsキャッシュ） |

予測・評価は追加保存。同じ日・同じ設定で再実行すると既存予測を利用します。
実績評価は対象日が到来し、その株価が入力された実行から増えます。
実データの必要な履歴や95%の銘柄カバー率が足りなければ、予測を作った扱いにはしません。

## 5. V3終了後にV4を自動で始める

手動liveで確認してから設定します。入力の生成が終わった時点で起動する方式です。

新しいV4アカウントでfine-grained tokenをもう1つ作成します。
対象はforecastingだけ、Repository permissions → Actions = Read and write。
**元のV1〜V3リポジトリ**に以下を追加します。

| 種類 | 名前 | 値 |
|---|---|---|
| Variables | V4_REPOSITORY | V4アカウント名/forecasting |
| Variables | V4_BRANCH | main |
| Variables | V4_BASE_SET | M3（V3とそろえる） |
| Variables | ENABLE_V4_DISPATCH | true |
| Secrets | V4_DISPATCH_TOKEN | V4アカウントで発行したActions書込トークン |

既存のV3 daily forecastがデフォルトブランチで正常終了
→ Export V3 inputs for V4
→ 新しい入力を保存できた市場ごとにV4-A/Bのliveを起動します。
日米を一度に手動実行する場合は、引き続きmarket=BOTHを選べます。
入力作成の終了を待つため、V4の固定時刻にデータが間に合わない問題を避けられます。
この方式ではforecasting側のENABLE_LIVEは未設定のままで構いません。

時刻で起動する方式も残しています。forecasting側でENABLE_LIVE=trueにすると、
JPは月〜金18:00 JST、USは火〜土09:00 JSTに実行します。
両方を有効にする必要はありません。入力が最新の終了セッションまで届いていない場合は停止します。

## 6. ダッシュボードへの結果取り込み

予測・評価だけを別アカウントへ渡す設定はREADME_JP.mdの後半を参照。
この接続をまだ行わなくても、V4自身のpredictions・evaluationsは保存されます。

## 確認できている範囲

ローカルで圧縮入力のA/B共通読み込み、BOTH起動、履歴と結果取込、既存の回帰検証を実施。
実際のGitHubリポジトリ・Secretの登録・実データでの稼働は、アップロード後に確認します。
「正式配布版」はコード一式の配布単位です。実データでの予測精度を保証する表示ではありません。
