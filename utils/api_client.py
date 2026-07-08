import time
import requests


def call_llm(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.0,
    max_retries: int = 3,
    timeout: int = 120,
    image_b64: str = None,
) -> str:
    """
    فراخوانی مشترک OpenRouter برای همه‌ی مراحل (استخراج و روایت‌نویسی).
    شامل retry با backoff نمایی برای خطاهای rate-limit (429) و خطاهای سرور (5xx).

    اگر image_b64 ارسال شود، پیام به‌صورت multimodal (text + image) ساخته می‌شود
    و مدل باید قابلیت vision داشته باشد.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Bank Statement Analyzer",
    }

    # ساخت content: متن ساده یا multimodal
    if image_b64:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    else:
        content = prompt

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    last_exception = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if response.status_code == 429 or response.status_code >= 500:
                wait_time = (2 ** attempt) + 1
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.RequestException as e:
            last_exception = e
            time.sleep((2 ** attempt) + 1)

    raise RuntimeError(f"فراخوانی API پس از {max_retries} تلاش شکست خورد: {last_exception}")
