"""테스트 공통 설정 - 환경 호환성을 위한 모듈 모킹"""

import sys
from unittest.mock import MagicMock

# google.genai와 telegram 모듈이 설치되지 않았거나 로드 불가한 환경에서도
# 테스트가 실행될 수 있도록 mock 처리
for mod_name in [
    "google",
    "google.genai",
    "telegram",
    "feedparser",
    "sgmllib",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

