# stock_db（2026-10-15 精簡版）
| 檔案 | 內容 |
|---|---|
| pool384.zip.part00~04 | 384檔＋櫃買指數101：day_data/（日K，含IX0001加權、IX0043櫃買）＋ sj_data/（1分K） |
| excluded43.zip | 剔除43檔：day_data/＋sj_data/ |
| TXF20240422-20261008.zip | 台指期日盤1分K |

取用：git clone --depth 1 https://github.com/hub389/stock_db.git && cd stock_db && cat pool384.zip.part0* > pool384.zip && unzip -q pool384.zip

- 期間 2024-04-22～2026-10-08（601交易日）；已刪 20241201 週日異常檔
- day_data/_stocks.csv 的 day_src：還原＝還原權值日K（量含盤後）；1分K合成＝原始價、量不含盤後
- 384檔名單：2026-07-01～10-08 震幅≥4%天數≥7，並剔除電信、水泥、食品、文創
