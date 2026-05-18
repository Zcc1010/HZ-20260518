"""Test Zhipu API"""

import asyncio
import os
from openai import AsyncOpenAI

async def test_zhipu_api():
    api_key = "75e0d54e28904d9db26813c16bcfe162.vFG4Ds7ERsa87Iju"
    api_base = "https://open.bigmodel.cn/api/paas/v4"
    model = "glm-4-flash"

    print(f"Testing Zhipu API...")
    print(f"API Base: {api_base}")
    print(f"Model: {model}")
    print("-" * 50)

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Hello, please introduce yourself briefly."}
            ],
            max_tokens=100,
        )

        print(f"[OK] API call successful")
        print(f"Response: {response.choices[0].message.content}")
        print(f"Finish reason: {response.choices[0].finish_reason}")
        print(f"Usage: {response.usage}")

    except Exception as e:
        print(f"[FAIL] API call failed")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")

        # Try to get more error details
        if hasattr(e, 'response'):
            print(f"HTTP Status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")

if __name__ == "__main__":
    asyncio.run(test_zhipu_api())
