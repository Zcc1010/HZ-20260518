"""Test nanobot provider with Zhipu"""

import asyncio
import sys
sys.path.insert(0, r"E:\workspace\nanobot-webui\.venv\Lib\site-packages")

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name

async def test_nanobot_provider():
    api_key = "75e0d54e28904d9db26813c16bcfe162.vFG4Ds7ERsa87Iju"
    api_base = "https://open.bigmodel.cn/api/paas/v4"
    model = "glm-4-flash"

    print(f"Testing nanobot provider...")
    print(f"API Base: {api_base}")
    print(f"Model: {model}")
    print("-" * 50)

    spec = find_by_name("zhipu")
    print(f"Provider spec: {spec}")

    try:
        provider = OpenAICompatProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
            spec=spec,
        )

        result = await provider.chat(
            messages=[
                {"role": "user", "content": "Hello, please introduce yourself briefly."}
            ],
            model=model,
            max_tokens=100,
        )

        print(f"[OK] Provider call successful")
        print(f"Content: {result.content}")
        print(f"Finish reason: {result.finish_reason}")
        print(f"Usage: {result.usage}")
        print(f"Tool calls: {result.tool_calls}")

    except Exception as e:
        print(f"[FAIL] Provider call failed")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")

        # Try to get more error details
        if hasattr(e, 'response'):
            print(f"HTTP Status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")

if __name__ == "__main__":
    asyncio.run(test_nanobot_provider())
