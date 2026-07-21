import time
import requests

import config


def call_llm(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.0,
    max_retries: int = 3,
    timeout: int = 120,
    image_b64: str = None,
    images_b64: list = None,
) -> str:
    """
    فراخوانی مشترک OpenRouter برای همه‌ی مراحل (استخراج و روایت‌نویسی).
    شامل retry با backoff نمایی برای خطاهای rate-limit (429) و خطاهای سرور (5xx).

    پشتیبانی از تصویر:
    - images_b64: لیستی از تصاویر (base64) برای یک درخواست multimodal با چند تصویر.
    - image_b64: یک تصویر تکی (legacy)؛ در صورت وجود به لیست تبدیل می‌شود.
    مدل باید قابلیت vision داشته باشد.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Bank Statement Analyzer",
    }

    # ساخت content: متن ساده یا multimodal (چند تصویر)
    images = []
    if images_b64:
        images = list(images_b64)
    if image_b64:
        images.append(image_b64)

    if images:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img}"},
            })
    else:
        content = prompt

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    # محافظ در برابر تکرنکیت خروجی — حداکثر توکن خروجی
    max_tokens = getattr(config, "MAX_OUTPUT_TOKENS", None)
    if max_tokens:
        payload["max_tokens"] = max_tokens

    last_exception = None
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = requests.post(
<<<<<<< HEAD
                url="https://openrouter.ai/api/v1/chat/completions",
=======
                url="https://openrouter-proxy.amin76tavakoli76.workers.dev/api/v1/chat/completions",
>>>>>>> a084173664107afb8cda54b75206cedbdb0a73de
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            elapsed = time.time() - start_time

            if response.status_code == 429 or response.status_code >= 500:
                wait_time = (2 ** attempt) + 1
                print(f"⏳ [api] HTTP {response.status_code} — انتظار {wait_time}s و retry (تلاش {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            # بررسی هوشمندانه‌ی finish_reason برای تشخیص تکرنکیت
            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "unknown")
            content_text = choice["message"]["content"]
            usage = data.get("usage", {})

            # هشدار اگر خروجی به‌دلیل محدودیت توکن قطع شده
            if finish_reason == "length":
                print(f"⚠️ [api] هشدار: finish_reason='length' — خروجی به‌دلیل محدودیت max_tokens تکرنکیت شده! "
                      f"ممکن است تراکنش‌هایی از قلم افتاده باشند. max_tokens={max_tokens}")
                print(f"   برای رفع: مقدار MAX_OUTPUT_TOKENS در config.py را افزایش دهید.")

            img_info = f" | تصاویر: {len(images)}" if images else ""
            print(f"🌐 [api] مدل: {model} | HTTP {response.status_code} | {elapsed:.1f}s{img_info} | "
                  f"finish={finish_reason} | prompt_tokens={usage.get('prompt_tokens', '?')} | "
                  f"completion_tokens={usage.get('completion_tokens', '?')}")

            return content_text

        except requests.exceptions.RequestException as e:
            last_exception = e
            wait_time = (2 ** attempt) + 1
            print(f"❌ [api] خطای شبکه: {e} — retry پس از {wait_time}s (تلاش {attempt + 1}/{max_retries})")
            time.sleep(wait_time)

    raise RuntimeError(f"فراخوانی API پس از {max_retries} تلاش شکست خورد: {last_exception}")
