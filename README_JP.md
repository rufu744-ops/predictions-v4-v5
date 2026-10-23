# forecasting — V4-A / V4-B

2026-10-24 r2。新規Privateリポジトリ用の完全なコード一式です。
セットアップは **START_HERE_JP.md** の順に進めます。

| 操作 | 選択肢 |
|---|---|
| operation | demo / live |
| model | both / a / b |
| market | JP / US / BOTH |
| profile | standard / light |

market=BOTH・model=bothなら、JP-A / JP-B / US-A / US-Bの4計算ジョブです。
片方の失敗で他方を取り消しません。保存と結果出力は最後の1ジョブにまとめます。
同時開始の可否や待ち時間は、GitHubの実行枠に従います。

V4-Aは最尤点推定＋カルマンフィルタ、V4-Bはパラメータ不確実性を含むベイズ推定。
数式と推定方法は docs/V4A_TECHNICAL.md・V4B_TECHNICAL.md を参照。
それらは単独版の資料なので、配置・認証・入力接続は本READMEとSTART_HERE_JP.mdを優先します。

## 保存

- predictions/v4a/JP・US と predictions/v4b/JP・US：予測CSV・設定JSON。追加保存。
- evaluations/v4a/JP・US と evaluations/v4b/JP・US：実績照合。対象価格が届いたら追加。
- state/v4a/JP・US と state/v4b/JP・US：最新状態。Gitへ登録せずActionsキャッシュで再利用。

キャッシュが利用できない実行では、入力履歴から状態を再構築します。
チェックポイントは監査用の永続履歴ではありません。永続履歴は予測・評価です。
同日・同一設定の予測は二重登録しません。
デモと研究用as-of実行は本番履歴に入りません。

## 入力接続

integration/v3_source/に、元のV1〜V3リポジトリへ追加する2ファイルを同梱しています。
V3のEDINET/SEC金融履歴、調整済み株価、公表時点を守ったマクロ情報を使って、
V3と同じ特徴量履歴を市場別に出力します。V3の予測値や学習済みモデルは入力しません。

入力はCSVまたは圧縮CSVの分割ファイルとmanifest.json。
A/Bが同じコミットの入力を読みます。既存の非圧縮4ファイル形式も受け付けます。
詳しくはINPUT_CONTRACT.md。
本番ワークフローは学習窓2520セッション、予測期間1/5/20セッション。
旧版の1260では全V3特徴量に対し20セッション先の非重複観測数が不足するため拡張しました。
モデル内部の推定方法・カバー率95%・最低観測数の規則は維持します。
学習窓は経過年数であり、存在しない金融情報を過去に補って作る処理ではありません。

## ローカル実行

```bash
pip install -r requirements.txt
python tools/run_checks.py
python run.py --model both --market BOTH --demo
python run.py --model both --market BOTH --input /absolute/path/to/v4_inputs --train-sessions 2520
```

BOTHの--inputはJP/とUS/が入った親フォルダ。JPまたはUS単独ではその市場のフォルダです。
CLIで--inputを省略した場合はinputs/JP・US。CLI単独の既定学習窓は従来の1260を保ちます。
Aのlightは尤度最適化の反復上限、Bのlightは数値積分のグリッド解像度を調整します。

## ダッシュボードへ結果だけを渡す

V4アカウントにPrivateのforecasting-resultsを作成し、READMEを付けてmainを初期化します。
forecastingのSettings → Secrets and variables → Actionsに以下を設定。

| 種類 | 名前 | 値・権限 |
|---|---|---|
| Variables | RESULTS_REPOSITORY | V4アカウント名/forecasting-results |
| Variables | RESULTS_BRANCH | main |
| Secrets | RESULTS_WRITE_TOKEN | 結果専用リポジトリだけのContents: Read and write |

未設定でもV4自身への予測・評価保存とActionsの結果artifact保存は行います。
結果専用リポジトリには予測CSV・実績CSV・検証用JSONを出力します。
モデル本体、入力特徴量、係数・Q/R・事後状態は出力しません。

元のダッシュボードリポジトリへ、integration/import_v4.pyとintegration/exchange_reader.pyを追加。
integration/import-v4.yml.exampleの内容で `.github/workflows/import-v4.yml` を作成します。

| 種類 | 名前 | 値・権限 |
|---|---|---|
| Variables | V4_RESULTS_REPOSITORY | V4アカウント名/forecasting-results |
| Variables | V4_RESULTS_BRANCH | main |
| Secrets | V4_RESULTS_READ_TOKEN | 結果専用リポジトリだけのContents: Read |

取込ワークフローのconcurrencyは既存の書込処理に合わせます。
V1〜V3のモデルは維持し、V4の予測・評価を追加します。
ダッシュボードがさらに別の新しい形式へ変更済みの場合は、その実装に合わせた確認が必要です。

## 検証範囲

VALIDATION.mdを参照。合成入力での検証と実データでの稼働は区別しています。
GitHubのアカウント・リポジトリ名・Secret登録はセットアップ時に行います。
