"""테스트 공통 헬퍼"""

from feeds import Article


def make_article(**overrides) -> Article:
    """테스트용 Article 팩토리"""
    defaults = dict(
        id="1",
        title="테스트",
        link="https://example.com",
        pub_date="",
        author="",
        description="",
        board_name="테스트게시판",
        board_id=234,
        view_count=0,
        is_pinned=False,
        attachment_count=0,
    )
    defaults.update(overrides)
    return Article(**defaults)
