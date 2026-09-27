import streamlit as st
import pandas as pd
import json
import io
from PIL import Image
from google import genai
from google.genai import types

st.set_page_config(page_title="嬰幼兒聽知覺實驗報表分析系統", layout="wide")

st.title("👶 嬰幼兒聽知覺實驗報表分析系統")
st.markdown("自動排除 `abort` 與 `wake-up` 試次，辨識印刷與手寫塗改，判斷是否達成連續 7 次正確（Hit 或 Correct Reject）。")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input("請輸入 Gemini API Key", type="password", help="用於辨識照片表格與手寫筆跡")
    st.markdown("[👉 點此免費取得 Gemini API Key](https://aistudio.google.com/app/apikey)")

def calculate_criterion_7(trials):
    """計算連續 7 次正確邏輯"""
    valid_trials = []
    for t in trials:
        t_type = str(t.get("trial_type", "")).lower()
        res = str(t.get("result", "")).lower()
        
        # 排除包含 abort 與 wake-up 的試次
        if "abort" in res or "abort" in t_type or "wake-up" in t_type or "wakeup" in t_type:
            continue
        
        is_corr = (res == "hit" or res == "correct reject")
        valid_trials.append({
            "num": t.get("trial_num"),
            "result": res,
            "type": t_type,
            "is_correct": is_corr
        })

    streak = 0
    max_streak = 0
    reach_trial = None
    reach_interval = None
    streak_history = []

    for item in valid_trials:
        if item["is_correct"]:
            streak += 1
            streak_history.append(item["num"])
            if streak > max_streak:
                max_streak = streak
            if streak == 7 and reach_trial is None:
                reach_trial = item["num"]
                reach_interval = f"Trial {streak_history[-7]} ~ {item['num']}"
        else:
            streak = 0
            streak_history = []

    return {
        "is_pass": (max_streak >= 7),
        "reach_trial": reach_trial if reach_trial else "-",
        "reach_interval": reach_interval if reach_interval else "-",
        "max_streak": max_streak,
        "valid_count": len(valid_trials)
    }

# 檔案上傳區
uploaded_files = st.file_uploader(
    "請選擇或拖曳上傳報表照片（支援多張同時上傳）", 
    type=["jpg", "jpeg", "png"], 
    accept_multiple_files=True
)

if uploaded_files:
    if not api_key:
        st.warning("⚠️ 請先在左側欄位輸入 Gemini API Key 才能開始辨識分析。")
    else:
        if st.button("🚀 開始批次辨識與分析", type="primary"):
            client = genai.Client(api_key=api_key)
            results = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            prompt = """
            請分析這份嬰幼兒聽知覺實驗報表。提取以下資訊並輸出成純 JSON 格式（不要包含 markdown）：
            {
              "subject_id": "受試者代號",
              "experiment_id": "實驗編號",
              "handwritten_notes": "若有手寫塗改修正請說明（例如：#14 miss 修改為 hit），無則填無",
              "trials": [
                {
                  "trial_num": 題號數字,
                  "trial_type": "control 或 target #0 或 wake-up #0",
                  "result": "hit 或 miss 或 correct reject 或 false alarm 或 abort（若有手寫塗改修正以手寫為準）"
                }
              ]
            }
            注意：
            1. 仔細辨識印刷文字與原子筆手寫註記（劃掉的 abort 請將 result 標註為 abort）。
            2. 如果題號有被劃掉重寫，依實際標記狀態解析。
            """

            for idx, file in enumerate(uploaded_files):
                status_text.text(f"正在分析第 {idx + 1}/{len(uploaded_files)} 張報表：{file.name}...")
                try:
                    bytes_data = file.read()
                    mime_type = file.type or "image/jpeg"

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[
                            types.Part.from_bytes(data=bytes_data, mime_type=mime_type),
                            prompt
                        ],
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    data = json.loads(response.text)
                    stats = calculate_criterion_7(data.get("trials", []))

                    results.append({
                        "原始檔名": file.name,
                        "受試者ID": data.get("subject_id", "未知"),
                        "實驗編號": data.get("experiment_id", "未知"),
                        "是否達成連續7次正確": "✔ 是" if stats["is_pass"] else "✘ 否",
                        "達成時Trial": stats["reach_trial"],
                        "達成區間": stats["reach_interval"],
                        "最高連續次數": stats["max_streak"],
                        "有效試次數": stats["valid_count"],
                        "手寫修正備註": data.get("handwritten_notes", "無")
                    })
                except Exception as e:
                    results.append({
                        "原始檔名": file.name,
                        "受試者ID": "解析失敗",
                        "實驗編號": "-",
                        "是否達成連續7次正確": "✘ 否",
                        "達成時Trial": "-",
                        "達成區間": "-",
                        "最高連續次數": 0,
                        "有效試次數": 0,
                        "手寫修正備註": str(e)
                    })

                progress_bar.progress((idx + 1) / len(uploaded_files))

            status_text.success("🎉 所有報表分析完成！")
            
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)

            # 匯出 Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name="統計成果")
            excel_data = output.getvalue()

            st.download_button(
                label="📥 下載 Excel 分析成果表",
                data=excel_data,
                file_name="實驗連續7次正確判定結果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
