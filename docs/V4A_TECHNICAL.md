元の単独版の技術資料です。統合版の配置・起動・認証設定はルートREADME_JP.mdを優先してください。

# 株価予測 V4-A — 別アカウントで動く状態空間モデル

V3で整えた市場・マクロ・企業特徴量を入力し、銘柄ごとに予測係数が変化する線形ガウス状態空間モデルで、1・5・20営業日先を予測します。
V1〜V3の推定コードと既存ダッシュボードの表示コードは変更しません。

**この一式は、V4-A本体＋CSV入出力＋非公開アカウント間の結果連携コードです。V3の実データ取得処理そのものは含みません。**
V3側から特徴量を渡す入力仕様・変換ツールを同梱しています。最新V3コードとの実接続は、V3の完成版に合わせた確認が必要です。

## アカウントを分ける構成

| 場所 | 保存するもの |
|---|---|
| V4用アカウント：モデル用Privateリポジトリ | このコード、カルマン状態、推定パラメータ、非公開ログ |
| V4用アカウント：結果専用Privateリポジトリ | 予測CSV、実績照合CSV、整合性確認用JSON |
| 既存アカウント：ダッシュボードリポジトリ | V1〜V3の既存結果＋読み込んだV4-Aの結果 |

結果専用リポジトリを設けることで、ダッシュボード側にモデル本体のリポジトリを読む権限を渡す必要がありません。
別アカウントのPrivateリポジトリには通常のGITHUB_TOKENだけではアクセスできないため、対象リポジトリ限定のトークンを設定します。
取り込んだ結果の閲覧範囲は、取り込み先のリポジトリ・ダッシュボードの公開設定に従います。非公開運用を基本にしてください。
この成果物は、アカウント作成、トークン作成、リポジトリへのpush、外部公開を実行していません。

## 最初の動作確認

Python 3.11 / 3.12を想定します。このフォルダの中で実行してください。

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python demo.py --market BOTH
```

デモは合成データです。実際のJPX/NYSEカレンダーではなく、平日だけの模擬カレンダーを使います。
予測・実績・状態は `output/demo/` に隔離し、本番CSVの受け渡し処理は合成データを除外します。
実株価の予測力を確認した結果ではありません。

## モデル

h営業日先の累積リターンについて、銘柄iごと・予測期間hごとに次を推定します。

\[
y^{(h)}_{i,t}=\frac{P^{adj}_{i,t}}{P^{adj}_{i,t-h}}-1
=x_{i,t-h}^{\prime}\beta^{(h)}_{i,t}+\varepsilon^{(h)}_{i,t},
\qquad \varepsilon^{(h)}_{i,t}\sim N(0,R^{(h)}_i).
\]

\[
\beta^{(h)}_{i,t}=\beta^{(h)}_{i,t-1}+\eta^{(h)}_{i,t},
\qquad \eta^{(h)}_{i,t}\sim N(0,Q^{(h)}_i).
\]

xは切片とV3から引き継ぐ特徴量です。h=1では通常の翌営業日TVP回帰になります。
係数はカルマンフィルタで更新し、Q=qI・R=rの2つのノイズ規模を月初の最初の実行時に最尤推定します。
Q/Rを1次元で最適化し、Rは尤度から解析的に求めることで計算量を抑えています。
初期状態は平均ゼロ、共分散10RIのproper Gaussian初期化です。V4-Bのようなパラメータの事後分布は推定しません。

- **日々の更新**：新しく実現した、採用対象のラベルだけを逐次同化します。同じ結果を2回学習しません。
- **月次の再推定**：最大1260営業日の履歴で、標準化・欠測補完・Q/R推定・フィルタを再計算します。
- **複数営業日先**：h=5/20のラベルは期間が重複しない固定位相のものだけを尤度へ入れます。観測誤差を独立とするモデルに、重なったリターンをそのまま大量投入しません。
- **日次の予測**：h=5/20も毎営業日出します。採用ラベルの実現がない日は、状態の時間経過に伴う共分散を加えて予測します。
- **予測区間**：フィルタ状態の不確実性・将来の状態ノイズ・観測ノイズを反映した条件付き95%区間。Q/Rの推定誤差やモデル誤特定は含みません。

5・20日先の予測のために、未知の将来特徴量を仮定したり、翌日予測を20倍したりしません。
観測日uで、既知のx_uとフィルタ済み状態から終点u+hの累積リターンを直接予測します。

`--light` は尤度最適化の反復上限を32→24にします。銘柄数・特徴量・予測期間は減らしません。
フルサイズの日米約1000銘柄での処理時間は未計測です。初回・月次は日次状態更新より重くなります。

最初のV4-Aは銘柄別推定です。産業・市場階層を通じた情報共有、一般の遷移行列Aの推定、ベイズ推定は実装していません。

## V3から渡す入力

市場ごとに4ファイルを用意します。取得元のデータ処理はV3側で完了させます。

| ファイル | 必須列・内容 |
|---|---|
| `sessions.csv` | `date,close_at_utc`。連続した実取引所セッション。将来20営業日以上も含める |
| `prices.csv` | `date,ticker,adjusted_close`。同じ取得時点の配当・分割調整済み終値。欠けた日は行を作らない |
| `features.csv` | `date,ticker,available_at_utc,f_...`。特徴量の利用可能日時を記録 |
| `manifest.json` | 市場・特徴量一覧・対象銘柄一覧・出典・point_in_time宣言・各CSVのSHA-256 |

`available_at_utc` はその行の特徴量に必要な情報がすべて利用可能となった日時です。
V3の財務・マクロの公表日時を守り、各営業日の引け以前に利用可能な値だけを書いてください。
取得した現在値を過去へ埋める機能は用意していません。入力側の公表事実を独立に確認する機能もありません。
日時には `Z` または `+00:00` 等のタイムゾーンが必要です。

V3の結合済みパネルから作るコマンド例：

```bash
python tools/export_v3_input.py \
  --panel v3_panel.csv --sessions exchange_sessions.csv \
  --universe official_universe.csv --market JP \
  --features ret1 ret20 roe revenue_growth \
  --close-column Close --available-column available_at_utc \
  --source V3_exporter_v1 --output inputs/JP
```

`official_universe.csv` の列は `ticker`。実行例の特徴量4個は説明用で、実際にはV3と比較する入力列をすべて指定します。
ツールは列名にf_を付けて分割し、整合性検証用JSONを作ります。カレンダーや財務公表日時を捏造して補いません。
株価は過去の対象銘柄・除外銘柄の予測評価に必要なものも含めて継続供給してください。

**カレンダーの先頭を固定してください。** 非重複ラベルの位相を固定するため、毎回過去部分を切り落とさず同じ先頭から渡します。
訂正や分割によって既に学習した履歴が変わる場合はハッシュで検知し、現在の予測時点までで再推定します。過去に保存した予測は変更しません。

各銘柄・各hで最低 `max(30, 特徴量数+5)` 本の非重複実現ラベルが必要です。
例えばh=20で最低30本なら、欠測がなくても約600営業日以上の履歴が必要になります。
1260営業日の窓に必要数が入らない場合は、特徴量・学習窓の設計を見直してください。
期待する銘柄の95%以上で全指定hの予測がそろわなければ、予測CSVを保存せず理由を `output/status/` に記録します。

## 本番実行

```bash
python run.py --market JP --input inputs/JP --light
python run.py --market US --input inputs/US --light
```

初日だけ長期履歴からQ/Rと状態を推定し、その後は `state/v4a/` を再利用します。
状態ファイルと各種履歴をPrivateリポジトリに保存して、次回のActionsでも引き継ぎます。
月次再推定、または入力履歴の訂正を検知した場合はその状態を再構築します。

保存先：

- `predictions/v4a/JP/` 等：予測CSV＋JSON。不変。
- `evaluations/v4a/JP/` 等：実現値CSV＋JSON。不変。
- `state/v4a/JP/` 等：再利用するカルマン状態。更新可能・モデル側だけに保持。
- `exchange/`：他アカウントへ渡す結果だけのCSV＋JSON。

評価は予測した対象セッションに株価がある場合だけ実施します。
起点と対象日の株価を同じ調整系列から取り、分割時の基準差を避けます。対象日に欠測なら未評価のまま保持します。

```bash
python run.py --market JP --input inputs/JP --evaluate-only
python run.py --market JP --input inputs/JP --as-of 2025-12-30
```

`--as-of` は研究用で `output/research/` へ隔離し、結果専用リポジトリには出しません。
これは単一過去時点を再計算する機能です。現在の構成銘柄や改訂後の入力では、完全な当時再現バックテストにはなりません。

## GitHub Actionsの設定

モデル用Privateリポジトリ直下にこのフォルダの**中身**を置きます。
結果用Privateリポジトリは事前にREADME等を追加して初期化し、mainブランチを作っておきます。
V3側の入力供給用リポジトリに `v4a_inputs/JP/`・`US/` を置きます。

モデル用リポジトリのVariables：

| 名前 | 値 |
|---|---|
| FEATURE_REPOSITORY | 入力供給元の `owner/repo` |
| FEATURE_BRANCH | 入力供給元ブランチ。省略時main |
| RESULTS_REPOSITORY | 結果専用の `owner/repo` |
| RESULTS_BRANCH | 結果専用ブランチ。省略時main |

モデル用リポジトリのSecrets：

| 名前 | 権限 |
|---|---|
| FEATURES_READ_TOKEN | 入力供給元だけのContents: Read |
| RESULTS_WRITE_TOKEN | 結果専用リポジトリだけのContents: Read and write |

Actionsにモデル用リポジトリ自身への書き込みも許可します。
スケジュールはJPが月〜金18:00 JST、USが日本時間火〜土09:00 JST。
入力生成完了を確認するイベント連携ではないため、V3の処理時間に合わせて実行時刻を調整してください。
新しい最終完了セッションの入力がなければ、古い入力で勝手に最新日へ予測を伸ばすことはしません。
GitHubの予約実行が遅れたり、処理が長引いて次の読み込みに間に合わなければ、次回取り込みで反映されます。

## 既存ダッシュボードへの取り込み

次のファイルを**ダッシュボード側**に追加します。

1. `integration/import_v4a.py`
2. `integration/exchange_reader.py`
3. `integration/import-v4a.yml.example` を `.github/workflows/import-v4a.yml` として配置

ダッシュボード側にVariable `V4_RESULTS_REPOSITORY`（結果専用owner/repo）、
必要なら `V4_RESULTS_BRANCH`、Secret `V4_RESULTS_READ_TOKEN`（結果専用リポジトリContents: Read）を設定します。
既存の書込ワークフローと同じconcurrencyグループを使って、共通表示データのpush競合を避けてください。
例のグループ名は、統合版で使う `stock-forecast-${{ github.ref }}` です。実際の完成版が違う場合は合わせます。

取り込みはローカルでも可能です。

```bash
python integration/import_v4a.py --source /path/to/results-only-repo --destination /path/to/dashboard-repo
```

V4-Aの係数・Q/R・状態・特徴量は取り込みません。
取り込んだ `predictions/v4a/`・`evaluations/v4a/` は既存の共通アダプタが読む形式です。
予測は `horizon_sessions/predicted_return`、評価には互換用の `horizon/actual` も保存します。
`model_version` は `v4a.0.1`、モデル名は `TVP_Kalman`。
現行正規化の `system_version` はV4という大分類になりますが、グラフのversion欄はv4a.0.1として区別できます。

CSVに加え、JSONにはファイル一覧とSHA-256を保存します。
同一ファイルの変更や不完全な組、許可外パスは取り込みを停止します。
元のモデル側ファイルとは列を絞った別の結果投影であり、取り込み後の結果ファイルは上書きしません。

## 検証範囲と次の接続作業

カルマン更新と尤度の独立検算、未来情報を使わないこと、非重複ラベル、日次再利用/月次再推定、
保存の不変性、満期後評価、結果だけの取り込みを合成データで検証しています。
具体的な結果は `VALIDATION.md` を参照してください。

**未実施**：最新V3からの日米全銘柄の実データ接続、本番の予測力評価、別アカウント間の認証・Actions実行。
V3側担当へは `INPUT_CONTRACT.md` と `tools/export_v3_input.py` を渡せば、入力の接続箇所を確認できます。
V1〜V3との情報集合比較では、特徴量だけでなく銘柄・学習期間・非重複標本の違いにも注意してください。

一次資料：[状態空間モデルとカルマン尤度](https://www.statsmodels.org/stable/statespace.html)、
[GitHub Checkoutの別Privateリポジトリへの接続](https://github.com/actions/checkout#checkout-multiple-repos-private)。
