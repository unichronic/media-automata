from media_automata.platforms import instagram as instagram_module


def test_upload_crop_ratio_order_prefers_original_for_feed() -> None:
    assert instagram_module.upload_crop_ratio_labels(reel_portrait=False) == ("Original", "4:5")


def test_upload_crop_ratio_order_prefers_nine_sixteen_for_portrait_reels() -> None:
    assert instagram_module.upload_crop_ratio_labels(reel_portrait=True) == ("9:16", "Original")
