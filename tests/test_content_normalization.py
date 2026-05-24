from media_automata.agents.graph import split_x_post


def test_split_x_post_keeps_parts_within_limit() -> None:
    text = " ".join(["browser automation"] * 40)

    posts = split_x_post(text)

    assert len(posts) > 1
    assert all(len(post) <= 280 for post in posts)
    assert " ".join(posts) == text
