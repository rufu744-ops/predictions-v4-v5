元の単独版の技術資料です。統合版の配置・起動・認証設定はルートREADME_JP.mdを優先してください。

# 株価予測 V4-B — パラメータの不確実性も扱うベイズ状態空間

V4-Aと同じ特徴量、同じランダムウォーク係数、同じ1・5・20営業日先リターンを使います。
V4-Aで点推定していたノイズパラメータQ/Rを、V4-Bでは事後分布として扱います。
予測平均・標準偏差・95%予測区間をCSVへ保存し、既存ダッシュボードに結果だけを取り込めます。

**モデル本体・CSV入出力・非公開アカウント間の結果連携をまとめた独立パッケージです。**
V3の実データ取得処理は含めません。V4-Aと同じ入力4ファイルをそのまま利用できます。
V3完成版との実データ接続や、別アカウント間の認証設定は別途必要です。

## V4-Aとの違い

| 項目 | V4-A | このV4-B |
|---|---|---|
| 状態方程式 | 係数のランダムウォーク | 同じ |
| 入力・ラベル | V3特徴量、非重複累積リターン | 同じ |
| Q/R | 月次の最尤点推定 | 月次の事後分布再構築、日次のベイズ更新 |
| 係数状態 | 点推定パラメータに条件付けたカルマン分布 | パラメータごとのカルマン分布の混合 |
| 予測区間 | 状態・観測ノイズ | 状態・観測ノイズ＋Q/Rの不確実性 |
| 推定法 | 最尤法 | 1次元数値積分＋共役更新。MCMC不要 |
| 計算・保存量 | 比較的小さい | 積分点ごとに状態を保持する分だけ大きい |

ベイズ化によって精度が上がることや、区間が必ず広がることは保証しません。
事前分布による縮小とパラメータの不確実性の両方が働くため、V4-Aと実績で比較します。

## 動かす

Python 3.11 / 3.12を想定。このフォルダ内で実行します。

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python demo.py --market BOTH --tickers 1
```

デモは価格・特徴量・カレンダーを含めてすべて合成です。実データの予測精度ではありません。
`output/demo/` に隔離し、他アカウントへ渡す本番結果には含めません。

本番入力を用意した場合：

```bash
python run.py --market JP --input inputs/JP --light
python run.py --market US --input inputs/US --light
```

V4-Aの入力フォルダを直接指定しても読み込めます。価格や特徴量を重複取得する必要はありません。

## モデルと事前分布

銘柄i・予測期間hごとに、

\[
y^{(h)}_{i,t}=P^{adj}_{i,t}/P^{adj}_{i,t-h}-1
=x_{i,t-h}'\beta^{(h)}_{i,t}+\varepsilon^{(h)}_{i,t},\qquad
\varepsilon^{(h)}_{i,t}\sim N(0,R_i^{(h)}),
\]

\[
\beta^{(h)}_{i,t}=\beta^{(h)}_{i,t-1}+\eta^{(h)}_{i,t},\qquad
\eta^{(h)}_{i,t}\sim N(0,Q_i^{(h)}),\qquad Q_i^{(h)}=\lambda_i^{(h)}R_i^{(h)}I.
\]

A=Iは固定です。状態の階層化、非線形モデル、一般の共分散行列Qの推定はこの版には含めません。

\[
\log\lambda\sim N(\log(10^{-4}),2^2),\qquad
R\sim IG(a_0,b_0),\quad a_0=2.5,\quad b_0=1.5\times10^{-4}h.
\]

IGの密度は `p(R) ∝ R^(-a-1) exp(-b/R)`。
初期状態はV4-Aと同様、`beta_0 | R ~ N(0, 10 R I)` です。
標準化後の係数に対する事前分布で、ハイパーパラメータは固定値です。
事前分布の値はデータから最適化したものではありません。CLIで変更できます。

### MCMCを使わない理由

λを固定すると、Rを1に正規化したカルマンフィルタから、イノベーションeと分散Fが計算できます。

\[
a_n=a_0+n/2,\qquad b_n=b_0+\tfrac12\sum_t e_t^2/F_t,\qquad
R\mid\lambda,D\sim IG(a_n,b_n).
\]

Rと潜在状態を積分した周辺尤度を使い、logλの1次元事後分布を台形則で積分します。
その各積分点の条件付き予測はStudent-t分布になります。

\[
y_*\mid\lambda,D\sim t_{2a_n}(m_\lambda,\ (b_n/a_n)F_{*,\lambda}).
\]

式の第2引数はscaleの2乗です。予測区間は、これらStudent-t分布を事後重みで混合したCDFの2.5%・97.5%点を数値的に解きます。
平均・分散は全期待値・全分散の法則で求めます。事後平均パラメータを1個だけ代入する処理ではありません。

数値積分は有限グリッド近似です。厳密な閉形式の完全積分とは区別してください。
事前ハイパーパラメータ、特徴量の欠測補完・標準化、モデルの構造自体の不確実性は積分しません。

### 積分精度

- 通常：65→129→最大257点。必要な場合だけ細分化。
- `--light`：33→65→最大129点。銘柄・特徴量・期間は減らしません。
- 事後の正規化定数、logλの事後平均、現在の予測平均・標準偏差・区間端点の変化を比較します。
- 通常の誤差許容値は0.002、lightは0.01。予測量は予測標準偏差で正規化して比較します。
- 積分区間はlogλの事前平均±6事前標準偏差。端の2点ずつの事後質量合計が0.001未満であることも確認します。
- 最大事後重みが0.35以上の場合も細分化を要求します。未解像の積分を成功として保存しません。

```bash
python run.py --market JP --input inputs/JP \
  --grid-points 65 --max-grid-points 1025 --quadrature-tolerance 0.001 \
  --prior-width-sd 8
```

積分範囲外の小さな事前裾を切っています。端点の診断は範囲外質量が絶対にないことの数学的証明ではありません。
推定結果が事前分布に敏感な場合は、事前分布・範囲・解像度を変えて比較してください。
MCMCを使わないためR-hatやMCMCのESSは計算しません。`effective_grid_nodes` は重みの集中度であり、独立サンプル数ではありません。

## 日々の更新

1. 初回・月替わりに、過去最大1260営業日で標準化と事後分布を再構築します。
2. 日次は積分点ごとにカルマン状態とIGの形状・尺度を更新し、実現値の予測尤度でλの重みを更新します。
3. 同じラベルを再同化せず、h=5/20はV4-Aと同じ非重複の区間だけを学習します。予測自体は毎営業日出します。
4. 日次の重みが端へ寄ったり、1点へ集中した場合は、その日の利用可能な履歴で再構築します。
5. 既に学習した入力の訂正を検知した場合も再構築し、保存済み予測は変更しません。

日次更新は、最後に精度確認したグリッド上でのベイズ更新です。毎日全グリッドを細分化して比較するわけではありません。
日次の精度診断は端点質量と最大重みによるもので、CSVの `calibration_quadrature_error` は直近再構築時の値です。

事後状態は `state/v4b/` の圧縮NPZ＋JSONへ保存します。V4-Aより状態量が増えるため、
付属Actionsではモデルのソースリポジトリに毎回コミットせず、PrivateのActionsキャッシュで引き継ぎます。
キャッシュが使えない場合は履歴から再構築します。予測・評価ログは引き続きリポジトリへ保存します。

## 入力と出力

入力はV4-Aと同じ `sessions.csv, prices.csv, features.csv, manifest.json`。
詳しくは `INPUT_CONTRACT.md` を参照してください。

- 実取引所カレンダーを使い、先頭を固定して将来20セッション以上まで含める。
- `available_at_utc` が各引け以前の、公表時点を守った特徴量だけを使う。
- 同一取得時点の配当・分割調整済み終値を使う。
- 各銘柄・hで最低 `max(30, 特徴量数+5)` 本の非重複実現ラベルが必要。
- 全指定hで、期待銘柄の95%以上がそろわない場合は予測を保存しない。

| 保存先 | 内容 |
|---|---|
| predictions/v4b/JP等 | 予測CSV＋JSON。不変 |
| evaluations/v4b/JP等 | 満期後の実績照合。不変 |
| state/v4b/JP等 | 私有の事後分布・状態。更新可能 |
| exchange/ | 別アカウントへ渡す結果だけ |
| output/status/ | カバレッジ不足、積分未解像等の理由 |

`predicted_return` は事後予測平均、`prediction_std` は予測標準偏差。
`lower_95/upper_95` はパラメータ不確実性込みの95%予測区間です。
モデル側CSVには `probability_positive`（上昇確率）とパラメータ事後平均・積分診断も記録します。
交換用CSVはV4-Aと同じ列に絞り、パラメータ・状態・特徴量を渡しません。
現行共通ダッシュボードは平均予測・精度比較に接続できます。予測区間を画面に描く場合は表示側の追加対応が必要です。

評価は予測対象日と同じセッションの終値だけを使い、未成熟・引け前・欠測の結果を評価しません。
同じ予測を上書き・二重保存しません。過去時点の研究用実行は `--as-of YYYY-MM-DD` とし、`output/research/` に隔離します。

## 別アカウント・ダッシュボードとの連携

V4-Bのモデル用Privateリポジトリと、結果だけを置くPrivateリポジトリまたは専用ブランチを用意します。
**V4-AとV4-Bの出力先を同じリポジトリ・同じブランチにはしないでください。**
それぞれのファイル一覧indexを独立して更新するため、例えば `v4a-results` と `v4b-results` に分けます。
別々の取込処理で、ダッシュボードの `predictions/v4a/` と `predictions/v4b/` へ集約できます。

### V4-Bモデル側

このZIPのフォルダの**中身**を新しいモデル用Privateリポジトリ直下へ配置します。
入力供給元には、同じ4ファイルを `v4b_inputs/JP/`・`US/` として置きます。
V4-Aと同じ実データを使う場合は供給側で同じ内容を出力するか、workflowのパスを `v4a_inputs` に変更して共有できます。

Variables：

| 名前 | 値 |
|---|---|
| FEATURE_REPOSITORY | 入力供給元owner/repo |
| FEATURE_BRANCH | 省略時main |
| RESULTS_REPOSITORY | V4-B結果専用owner/repo |
| RESULTS_BRANCH | 結果専用ブランチ。省略時main |

Secrets：`FEATURES_READ_TOKEN`（入力元Contents: Read）、`RESULTS_WRITE_TOKEN`（結果専用Contents: Read and write）。
結果専用リポジトリは事前にREADME等で初期化し、対象ブランチを作っておきます。
モデル側Actionsに自身のリポジトリの書込権限も許可してください。

### ダッシュボード側

次の追加ファイルを配置します。V4-Aの取込ファイルは残します。

- `integration/import_v4b.py`
- `integration/v4b_exchange_reader.py`
- `integration/import-v4b.yml.example` → `.github/workflows/import-v4b.yml`

ダッシュボード側にVariable `V4B_RESULTS_REPOSITORY`、必要なら `V4B_RESULTS_BRANCH`、
Secret `V4B_RESULTS_READ_TOKEN`（V4-B結果専用リポジトリContents: Read）を設定します。

```bash
python integration/import_v4b.py --source /path/to/v4b-results --destination /path/to/dashboard
```

現在のダッシュボードの表示コードやV1〜V3のモデルは変更しません。
取り込まれる版は `v4b.0.1`、モデル名は `Bayesian_TVP_Kalman` です。
V4-Aの `v4a.0.1 / TVP_Kalman` と区別して同じ市場・期間で比較できます。
正規化のsystem_version大分類はV4ですが、version欄ではA/Bを区別できます。

予約処理はJPが月〜金18:00 JST、USが日本時間火〜土09:00 JSTです。
V3の入力生成が間に合うよう時刻を調整してください。ダッシュボード取込はモデル実行後の別スケジュールです。
モデル本体・事後状態はV4側に残し、ダッシュボードには結果のみ渡します。
取り込んだ結果の閲覧範囲は、取り込み先のリポジトリとダッシュボードの公開設定に従います。非公開運用を基本にしてください。
このZIPでアカウント作成・認証設定・外部push・公開は実行していません。

## 検証範囲

事後尤度の独立検算、数値積分の別算法との一致、逐次更新と一括更新の一致、予測分布の分位点、
未来情報を使わないこと、保存不変性、V4-A/Bの共通ダッシュボード接続を合成データで確認しています。
詳しくは `VALIDATION.md` を参照してください。
実データの日米約1000銘柄での計算時間・予測力・予測区間の実際の被覆率は未確認です。

参照：[SciPy inverse-gamma](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.invgamma.html)、
[Student-t](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html)、
[状態空間モデル](https://www.statsmodels.org/stable/statespace.html)。
