# clove-daily-draw

自動完成 [Clove 線上抽卡](https://oripa.clove.jp/) 的「每日限定一抽」：每天定時開瀏覽器、抽一次，抽到的卡片若在設定點數以下就自動兌換成點數。

> ⚠️ **先讀這段**
> - 抽卡會**消耗你帳號裡的點數**，點數是有價值的資產。請自行確認每天自動消耗是你要的。
> - Clove 的服務條款可能禁止使用自動化程式操作，帳號遭停權的風險請自行評估。
> - 遇到機器人驗證（CAPTCHA）腳本會直接停下，不會嘗試繞過。
> - 本腳本與 Clove 官方無關，使用後果自負。

---

## 需求

- Windows（其他系統理論上可行，排程方式要自己改）
- Python 3.9 以上
- Google Chrome
- 一個已經登入、而且**符合卡池等級限制**的 Clove 帳號

## 安裝

```bash
pip install playwright
```

腳本預設使用電腦上已安裝的 Chrome（`channel="chrome"`）。如果你沒有 Chrome，或想用 Playwright 自己的瀏覽器，執行 `python -m playwright install chromium`，並把腳本裡兩處 `channel="chrome"` 刪掉。

## 第一次設定

### 1. 登入

```bash
python clove_draw.py --login
```

會開一個瀏覽器視窗，**自己手動登入** Clove，登入完直接關掉視窗。登入狀態會存在 `clove-profile/`，之後不用再登入。

這是獨立的瀏覽器設定檔，和你平常用的 Chrome 分開，不會互相影響。

### 2. 確認卡池參數

每個人的每日限定一抽不一樣，常見的有 500 / 1,000 / 2,000 / 5,000 pt，卡池名稱也不同。**用 `--cost` 和 `--pool` 指定你自己的**：

```bash
# 500pt 的卡池
python clove_draw.py --dry-run --cost 500 --pool "你的卡池名稱"
```

**卡池名稱怎麼查**：在 Clove 首頁找到你的每日限定一抽卡池，在卡池圖片上按右鍵 →「檢查」，看 `<img>` 標籤的 `alt` 屬性，格式是：

```
抽卡 ログインボーナス(プラチナ) | 線上抽卡就選Clove
```

中間那段就是卡池名稱。不用填完整，填一段獨特的關鍵字就可以比對到。

### 3. 測試（不會扣點）

```bash
python clove_draw.py --dry-run --cost 1000 --pool "你的卡池名稱"
```

`--dry-run` 會走完「找卡池 →按抽一次 →跳出確認視窗」，然後按**取消**，不會扣點。看到這行就代表設定正確：

```
dry-run：已看到確認視窗並按取消，沒有扣點
```

卡池有每天出現的時間（例如台灣時間 11:00），測試請在卡池出現之後、當天還沒抽的時候做。

### 4. 設定每天自動執行

Windows 工作排程器，以每天 11:05 為例（請換成你自己的參數和時間）：

```bat
schtasks /Create /SC DAILY /ST 11:05 /TN "CloveDailyDraw" /TR "C:\Path\To\python.exe C:\Path\To\clove_draw.py --cost 1000 --pool \"你的卡池名稱\""
```

- `python.exe` 要用**完整路徑**，用 `where python` 查。只寫 `python` 排程器可能找不到。
- 確認：`schtasks /Query /TN "CloveDailyDraw"`
- 刪除：`schtasks /Delete /TN "CloveDailyDraw" /F`
- 改時間（不會問密碼）：
  ```bash
  powershell -NoProfile -Command "Set-ScheduledTask -TaskName CloveDailyDraw -Trigger (New-ScheduledTaskTrigger -Daily -At 11:05)"
  ```

**排程只在電腦開機並登入 Windows 時執行**，錯過不會自動補跑。想補跑的話，到工作排程器的「設定」分頁勾選「錯過排定的開始時間後，盡快執行工作」。

## 參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `--login` | — | 開瀏覽器手動登入，登入後關掉視窗 |
| `--dry-run` | — | 跑到確認視窗就取消，不會扣點 |
| `--cost` | `5000` | 每抽幾點。也決定要按的按鈕文字（`用1,000pt抽取`） |
| `--pool` | `ログインボーナス(プラチナ)` | 卡池名稱，部分比對 |
| `--limit` | `10000` | 抽中幾點以下自動兌換成點數。設 `0` 代表都不兌換，只保留卡片 |

### 例子

```bash
# 500pt 卡池，抽到 8000pt 以下就換成點數
python clove_draw.py --cost 500 --pool "你的卡池名稱" --limit 8000

# 2000pt 卡池，不自動兌換，卡片全部保留自己決定
python clove_draw.py --cost 2000 --pool "你的卡池名稱" --limit 0
```

## 執行流程

1. 打開首頁，關掉促銷彈窗。
2. 讀取點數餘額，不足 `--cost` 就停止。
3. 找卡池 → 按「抽一次」→ 確認視窗核對金額 → 按「用 N pt抽取」。
4. 跳過抽卡動畫，進入結果頁。
5. 按「全選」讀出合計點數：
   - **≤ `--limit`**：開啟兌換視窗，核對點數變化是否等於合計，相符才按「決定」。
   - **> `--limit`**：保留卡片不兌換。
   - 任何數字對不上就停下並截圖，不會亂按。
6. 全程紀錄寫進 `logs/clove.log`，關鍵畫面存成截圖。

**不會做的事**：不會按「申請出貨」、不會連抽、不會處理 CAPTCHA、不會輸入帳號密碼。

## 疑難排解

看 `logs/clove.log` 最後幾行，以及同資料夾對應時間的截圖。

| 訊息 | 原因與處理 |
|---|---|
| `點數不足，停止` | 餘額少於 `--cost`，需要先儲值或兌換已抽到的卡 |
| `列表上找不到白金登入獎勵卡池...` | 今天已經抽過、卡池還沒開始或已結束、帳號等級不符，或 `--pool` 名稱打錯 |
| `讀不到點數餘額` | 登入狀態過期，重跑 `--login` |
| `讀不到勾選後的合計點數` | 頁面結構有變，看截圖手動兌換，並回報 issue |
| `兌換視窗的點數變化對不上` | 安全機制擋下，看截圖自行確認後手動處理 |
| `Timeout ... exceeded` | 網路慢或有新的彈窗擋住，通常隔天會自己恢復；持續發生請附截圖回報 |

## 隱私

- `clove-profile/` 是登入狀態（含 cookie），**等同你的帳號，絕對不要上傳或分享**。
- `logs/` 的截圖和紀錄含有點數餘額等個人資訊。

兩者都已寫進 `.gitignore`。fork 或改寫後上傳前，請先用 `git status` 確認它們沒有被加進去。
