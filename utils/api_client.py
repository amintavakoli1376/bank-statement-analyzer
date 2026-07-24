import time
import itertools
import threading
import requests

import config

_proxy_lock = threading.Lock()
_proxy_cycle = itertools.cycle(config.PROXY_URLS)
_current_proxy = next(_proxy_cycle)


def _get_current_proxy() -> str:
    with _proxy_lock:
        return _current_proxy


def _rotate_proxy() -> str:
    global _current_proxy
    with _proxy_lock:
        _current_proxy = next(_proxy_cycle)
        print(f"🔄 [api] تعویض پروکسی → {_current_proxy}")
        return _current_proxy

def call_llm(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.0,
    max_retries: int = 3,
    timeout: int = 180,
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
        proxy_base = _get_current_proxy()
        # اگر پروکسی تنظیم نشده، مستقیم به OpenRouter می‌زنیم
        url = f"{proxy_base}/api/v1/chat/completions" if proxy_base else "https://openrouter.ai/api/v1/chat/completions"

        try:
            start_time = time.time()
            response = requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            elapsed = time.time() - start_time

            if response.status_code == 429 or response.status_code >= 500:
                print(f"⏳ [api] HTTP {response.status_code} از {proxy_base or 'مستقیم'}")
                if proxy_base:
                    _rotate_proxy()  # پروکسی فعلی مشکل داره، برو سراغ بعدی
                wait_time = (2 ** attempt) + 1
                print(f"⏳ [api] انتظار {wait_time}s و retry (تلاش {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "unknown")
            content_text = choice["message"]["content"]
            usage = data.get("usage", {})

            if finish_reason == "length":
                print(f"⚠️ [api] هشدار: finish_reason='length' — max_tokens={max_tokens}")
                raise RuntimeError(
                    f"TruncatedResponse: خروجی LLM ناقص است (finish_reason=length). "
                    f"MAX_OUTPUT_TOKENS={max_tokens} را افزایش دهید یا PAGES_PER_CHUNK را کاهش دهید."
                )

            img_info = f" | تصاویر: {len(images)}" if images else ""
            print(f"🌐 [api] مدل: {model} | پروکسی: {proxy_base} | HTTP {response.status_code} | "
                  f"{elapsed:.1f}s{img_info} | finish={finish_reason} | "
                  f"prompt_tokens={usage.get('prompt_tokens', '?')} | "
                  f"completion_tokens={usage.get('completion_tokens', '?')}")

            return content_text

        except requests.exceptions.RequestException as e:
            last_exception = e
            print(f"❌ [api] خطای شبکه روی {proxy_base}: {e}")
            _rotate_proxy()  # ⭐ اینجا proxy عوض میشه
            wait_time = (2 ** attempt) + 1
            print(f"❌ [api] retry پس از {wait_time}s با پروکسی جدید (تلاش {attempt + 1}/{max_retries})")
            time.sleep(wait_time)

    raise RuntimeError(f"فراخوانی API پس از {max_retries} تلاش شکست خورد: {last_exception}")