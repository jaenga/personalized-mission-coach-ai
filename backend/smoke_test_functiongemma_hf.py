"""FunctionGemma(HF) 간단 스모크 테스트 (가독성 출력)."""

import json
from functiongemma_hf_client import get_functiongemma_client, initialize_functiongemma_client

SAMPLES = [
    "오늘 미션 다 했어요!",
    "비가 와서 밖에 못 나가겠어요",
    "줄넘기 대신 자전거 타도 인정되나요?",
    "지금까지 몇 번 성공했는지 알려줘",
]


def _truncate(text: str, width: int = 96) -> str:
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def _pretty_parsed(parsed: dict | None) -> str:
    if parsed is None:
        return "None"
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)


def main() -> None:
    initialize_functiongemma_client()
    client = get_functiongemma_client()

    print("=" * 92)
    print("FunctionGemma HF Smoke Test")
    print("=" * 92)

    for idx, text in enumerate(SAMPLES, start=1):
        raw, parsed = client.predict_with_raw(text)
        fn_name = parsed.get("name") if parsed else "None"
        status = "FUNCTION" if parsed else "NO_FUNCTION"

        print(f"\n[{idx:02d}] {status}")
        print(f"Input   : {text}")
        print(f"Name    : {fn_name}")
        print(f"Raw     : {_truncate(raw)}")
        print("Parsed  :")
        print(_pretty_parsed(parsed))
        print("-" * 92)


if __name__ == "__main__":
    main()
