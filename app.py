import streamlit as st
import pandas as pd
import json
import io
import re
import pypdfium2 as pdfium
from PIL import Image
from google import genai
from google.genai import types

st.set_page_config(page_title="嬰幼兒聽知覺實驗報表分析系統", layout="wide")

st.title("👶 嬰幼兒聽知覺實驗報表分析系統")
st.markdown("支援 **PDF（自動合併 Page 1 與 Page 2）** 及一般圖片。自動排除 `abort` 與 `wake-up` 試次，辨識手寫塗改並計算連續 7 次正確。")

with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input("請輸入 Gemini API Key", type="password", help="用於辨識報表與手寫筆跡")
    st.markdown("[👉 點此免費取得 Gemini API Key](https://aistudio.google.com/app/apikey)")

def calculate_criterion_7(trials):
    valid_trials = []
    for t in trials:
        t_type = str(t.get("trial_type", "")).lower()
        res = str(t.get("result", "")).lower()
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

def convert_pdf_to_images(pdf_bytes):
    pdf = pdfium.PdfDocument(pdf_bytes)
    images = []
    for page in pdf:
        bitmap = page.render(scale=2.0)
        pil_image = bitmap.to_pil()
        images.append(pil_image)
    return images

uploaded_files = st.file_uploader(
    "請選擇或拖曳上傳報表（支援 2 頁式 PDF 或多張 JPG/PNG 圖片）", 
    type=["pdf", "jpg", "jpeg", "png"], 
    accept_multiple_files=True
)

if uploaded_files:
    if not api_key:
        st.warning("⚠️ 請先在左側欄位輸入 Gemini API Key 才能開始辨識分析。")
    else:
        if st.button("🚀 開始批次辨識與分析", type="primary"):
            cleaned_key = api_key.strip()
            client = genai.Client(api_key=cleaned_key)
            
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            prompt = """
            請分析這份嬰幼兒聽知覺實驗報表（若有多頁請跨頁合併所有試次，通常有 30 題左右）。
            提取以下資訊並輸出成純 JSON 格式（不要包含 markdown）：
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
            1. 請依序整合 Page 1 與 Page 2 的試次。
            2. 仔細辨識印刷文字與原子筆手寫註記（被劃掉的 abort 標註為 abort；手寫修改箭頭以修改後的結果為準）。
            """

            for idx, file in enumerate(uploaded_files):
                status_text.text(f"正在分析第 {idx + 1}/{len(uploaded_files)} 個檔案：{file.name}...")
                try:
                    file_bytes = file.read()
                    content_parts = []

                    if file.name.lower().endswith('.pdf'):
                        pil_images = convert_pdf_to_images(file_bytes)
                        for img in pil_images:
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG")
                            content_parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
                    else:
                        mime_type = file.type or "image/jpeg"
                        content_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))

                    content_parts.append(prompt)

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=content_parts,
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
