from __future__ import annotations

from typing import Any, Dict

from instaloader import Instaloader, Profile


def fetch_creator_profile(username: str, session: tuple[str | None, str | None] = (None, None)) -> Dict[str, Any]:
    loader = Instaloader(quiet=True)
    session_username, session_file = session
    try:
        if session_username and session_file:
            loader.load_session_from_file(session_username, session_file)
        profile = Profile.from_username(loader.context, username)
        return {
            "username": profile.username,
            "full_name": profile.full_name,
            "avatar_url": profile.profile_pic_url,
            "biography": profile.biography,
            "is_private": profile.is_private,
            "is_verified": profile.is_verified,
            "followers": profile.followers,
            "followees": profile.followees,
            "mediacount": profile.mediacount,
        }
    finally:
        loader.close()
