# V3 → V4 入力仕様

A/Bは同じ入力コミットを使います。モデル予測値ではなく、V3が公表時点を守って結合した特徴量履歴を使います。
新しい出力コードは integration/v3_source/scripts/export_v4_inputs.py。
対応を確認したV3は stock_forecast_complete_v3_20261024_r1.zip の models/v3/ 構造です。

市場別に v4_inputs/JP/ と v4_inputs/US/ を作成します。

| 論理データ | 必須列 |
|---|---|
| sessions | date（YYYY-MM-DD）, close_at_utc（実際の取引所引け、UTC） |
| prices | date, ticker, adjusted_close（分割・配当調整済み終値） |
| features | date, ticker, available_at_utc, f_で始まる明示的な特徴量列 |

正式版の出力は各データを50,000行ずつの `.csv.gz` に分割します。
manifest.jsonのfilesで各データに対応するファイル一覧を指定します。
大きい特徴量履歴をGitの単一ファイルへ詰め込まないための分割で、銘柄は除外しません。
旧形式の sessions.csv / prices.csv / features.csv + manifest.jsonも引き続き読み込めます。

manifestの主要項目：

```json
{
  "schema_version": 1,
  "market": "JP",
  "return_basis": "adjusted_close_ratio",
  "point_in_time": true,
  "synthetic": false,
  "source": "V3_publication_time_export_v1",
  "feature_columns": ["f_ret1", "f_fin_roa_annualized"],
  "expected_tickers": ["実際のユニバースの銘柄コード"],
  "files": {
    "sessions": ["sessions-00000.csv.gz"],
    "prices": ["prices-00000.csv.gz"],
    "features": ["features-00000.csv.gz"]
  },
  "sha256": {
    "sessions-00000.csv.gz": "実ファイルから計算",
    "prices-00000.csv.gz": "実ファイルから計算",
    "features-00000.csv.gz": "実ファイルから計算"
  }
}
```

- JPの企業情報は既存V3のEDINET、USはSECの開示履歴を再利用します。V4用に履歴同期を重ねません。
- V3のas-of結合後の行だけを渡します。財務情報が利用可能な行と、ベース特徴量がそろった行を使います。
- optionalな財務項目の欠測はV3と同じ欠測指標とともに保持。企業情報を取得時点より前へ補いません。
- available_at_utcはその日の実際の引け。金融・マクロ情報はV3側で公表時点に基づいて結合済みで、
  終値が確定する引けをその日次行全体の利用可能時点として明示します。
- target_* や label_end_* は特徴量一覧へ入れません。
- カレンダーはV3と同じSTARTから固定し、将来20セッション以上を含めます。
- 価格はV3の調整済みClose。欠測価格を前方補完しません。
- 期待銘柄は元のユニバースを維持し、財務カバー率が低いからといって小さい銘柄集合へ置換しません。
- 既存のV4入力に価格履歴がある除外銘柄も価格取得対象に含め、既存予測の評価に使います。
- JPX/S&P構成銘柄の取得元・品質はV3の処理を引き継ぎます。V4接続により出典が別の公式データになるわけではありません。
- 1/5/20セッション先ごとに、非重複の成熟済み観測がmax(30, 特徴量数+5)以上必要です。
  本番ワークフローは2520セッションの窓を使います。履歴自体が不足すれば予測は作成しません。
- 新規上場等を含め95%の予測カバー率に達しなければ、その市場・モデルの予測保存は停止します。
- APIキー・V3モデル本体・学習済み重みは渡しません。

公開時点の取引所価格・企業情報・マクロデータを再構成する品質は、元のV3データ源と処理の制約に従います。
