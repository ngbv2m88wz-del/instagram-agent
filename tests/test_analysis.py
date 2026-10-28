from instagram_agent.analysis import analyze, insights_summary, render_report


def make_post(i, day, hour, product="FEED", media_type="IMAGE", reach=1000, likes=50, saved=5, caption=""):
    return {
        "id": str(i),
        "permalink": f"https://instagram.com/p/{i}",
        "media_type": media_type,
        "media_product_type": product,
        "timestamp": f"2026-09-{day:02d}T{hour:02d}:00:00+0000",
        "caption": caption,
        "like_count": likes,
        "comments_count": 2,
        "insights": {"reach": reach, "likes": likes, "comments": 2, "saved": saved, "shares": 1},
    }


def sample_media():
    media = []
    for i in range(4):  # Reels: больше охват и вовлечённость
        media.append(make_post(i, 1 + i * 2, 15, "REELS", "VIDEO", reach=5000, likes=400, caption="#reels #tips"))
    for i in range(4, 8):
        media.append(make_post(i, 2 + (i - 4) * 2, 9, reach=1000, likes=30, caption="Фото " * 40))
    media.append({**make_post(99, 20, 10), "media_product_type": "STORY"})
    return media


def test_formats_and_best_format():
    result = analyze(sample_media(), {"followers_count": 2000, "username": "test"}, tz="UTC")
    assert len(result["posts"]) == 8  # сторис не учитываются
    formats = {r["key"]: r for r in result["formats"]}
    assert formats["REELS"]["count"] == 4
    assert formats["REELS"]["engagement"] > formats["IMAGE"]["engagement"]
    summary = " ".join(insights_summary(result))
    assert "Reels" in summary


def test_engagement_falls_back_to_followers():
    media = sample_media()
    for item in media:
        item.pop("insights")
    result = analyze(media, {"followers_count": 1000})
    assert not result["has_insights"]
    assert result["top"][0].engagement(1000) == (400 + 2) / 1000 * 100


def test_timezone_shifts_hours():
    result = analyze(sample_media(), tz="Europe/Moscow")
    assert {r["key"] for r in result["hours"]} == {12, 18}


def test_hashtags_counted():
    result = analyze(sample_media())
    tags = {r["key"]: r["count"] for r in result["hashtags"]}
    assert tags == {"#reels": 4, "#tips": 4}


def test_report_renders():
    report = render_report(analyze(sample_media(), {"followers_count": 2000, "username": "test"}))
    assert report.startswith("# Анализ публикаций @test")
    assert "## Лучшие посты" in report
    assert "## Форматы" in report


def test_empty_media():
    assert "Нет публикаций" in render_report(analyze([]))
