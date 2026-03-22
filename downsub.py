import requests
import json

def download_full_original_transcript(video_url):
    api_url = 'https://api.downsub.com/download'
    headers = {
        'Authorization': 'Bearer AIzalTjrrsT1cKdr4HSWUryzgFRiqNYc8XBzztm',
        'Content-Type': 'application/json'
    }
    payload = {'url': video_url}

    try:
        # 1. طلب بيانات الترجمة
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        if data.get('status') != 'success':
            return f"Error: {data.get('message', 'فشل الطلب')}"

        # 2. الحصول على القائمة الأصلية (Subtitles) وليس المترجمة
        original_subs = data.get('data', {}).get('subtitles', [])
        
        if not original_subs:
            return "لم يتم العثور على نصوص باللغة الأصلية."

        # نختار أول نص متوفر (عادة ما يكون هو اللغة الأصلية للفيديو)
        # نفضل النص الذي لا يحتوي على كلمة "auto-generated" إذا وجد
        selected_sub = original_subs[0]
        for sub in original_subs:
            if "auto-generated" not in sub.get('language', '').lower():
                selected_sub = sub
                break
        
        print(f"جاري تحميل النص باللغة الأصلية: {selected_sub.get('language')}...")

        # 3. استخراج رابط ملف TXT
        txt_url = None
        for fmt in selected_sub.get('formats', []):
            if fmt.get('format') == 'txt':
                txt_url = fmt.get('url')
                break
        
        if txt_url:
            # 4. تحميل النص الكامل
            txt_response = requests.get(txt_url)
            txt_response.raise_for_status()
            full_text = txt_response.text
            
            # 5. حفظ النص في ملف
            filename = "original_transcript.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(full_text)
            
            return f"تم تحميل النص بنجاح! تم حفظه في الملف: {filename}"
        else:
            return "لم يتم العثور على رابط بصيغة TXT للنص الأصلي."

    except Exception as e:
        return f"حدث خطأ أثناء المعالجة: {str(e)}"

# رابط الفيديو
url = 'https://www.youtube.com/watch?v=sdlar_fHMWs'
print(download_full_original_transcript(url))

