from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from media_automata.config import get_settings
from media_automata.db import init_db, session_scope
from media_automata.monitoring import check_openwa_session, run_production_check
from media_automata.platforms.base import WorkerContext
from media_automata.platforms.instagram_native import InstagramNativeWorker
from media_automata.repository import Repository
from media_automata.schemas import JobMode, Platform, PlatformContent, PlatformTaskPayload
from media_automata.storage import LocalStorage
from media_automata.worker import BrowserTaskRunner


def main() -> None:
    parser = argparse.ArgumentParser(prog="media-automata")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Create/update database tables.")

    worker_parser = subparsers.add_parser("worker", help="Run browser platform tasks.")
    worker_parser.add_argument("--loop", action="store_true", help="Run continuously.")
    worker_parser.add_argument("--platform", choices=["linkedin", "x", "instagram"], default=None)

    subparsers.add_parser("android-check", help="Check the configured ADB Android runtime.")

    production_check_parser = subparsers.add_parser(
        "production-check",
        help="Run deployment health checks for API dependencies, queue state, OpenWA, and optional native Instagram.",
    )
    production_check_parser.add_argument("--account", default="main_brand")
    production_check_parser.add_argument("--recover-openwa", action="store_true")
    production_check_parser.add_argument("--deep-instagram", action="store_true")

    monitor_parser = subparsers.add_parser(
        "monitor-once",
        help="Run one production monitor pass; intended for systemd timers.",
    )
    monitor_parser.add_argument("--account", default="main_brand")
    monitor_parser.add_argument("--no-recover-openwa", action="store_true")
    monitor_parser.add_argument("--deep-instagram", action="store_true")

    subparsers.add_parser(
        "whatsapp-session-recover",
        help="Start/recover the configured OpenWA session and report sanitized session state.",
    )

    native_auth_parser = subparsers.add_parser(
        "instagram-native-auth-check",
        help="Check the Instagram Android app auth state and store it separately from web auth.",
    )
    native_auth_parser.add_argument("--account", default="main_brand")

    native_login_parser = subparsers.add_parser(
        "instagram-native-login",
        help="Attempt Instagram Android login using configured credentials without publishing content.",
    )
    native_login_parser.add_argument("--account", default="main_brand")

    native_backup_parser = subparsers.add_parser(
        "instagram-native-backup",
        help="Back up authenticated Instagram Android app data for restore after runtime resets.",
    )
    native_backup_parser.add_argument("--account", default="main_brand")

    native_restore_parser = subparsers.add_parser(
        "instagram-native-restore",
        help="Restore Instagram Android app data from the latest or specified backup.",
    )
    native_restore_parser.add_argument("--account", default="main_brand")
    native_restore_parser.add_argument("--backup-path", default=None)

    native_story_parser = subparsers.add_parser(
        "instagram-feed-to-story",
        help="Share the latest Instagram feed post to Story through the native Android app.",
    )
    native_story_parser.add_argument("--account", default="main_brand")
    native_story_parser.add_argument("--job-id", default="manual_native_story")
    native_story_parser.add_argument("--post-url", default=None)
    native_story_parser.add_argument(
        "--actions-json",
        default="[]",
        help="JSON list of native Story editor actions.",
    )

    native_direct_story_parser = subparsers.add_parser(
        "instagram-native-direct-story",
        help="Publish a media Story through the native Android app.",
    )
    native_direct_story_parser.add_argument("media_path")
    native_direct_story_parser.add_argument("--account", default="main_brand")
    native_direct_story_parser.add_argument("--job-id", default="manual_native_direct_story")
    native_direct_story_parser.add_argument(
        "--actions-json",
        default="[]",
        help="JSON list of native Story editor actions.",
    )

    native_code_parser = subparsers.add_parser(
        "instagram-enter-code",
        help="Submit the current Instagram Android email/SMS verification code.",
    )
    native_code_parser.add_argument("code")
    native_code_parser.add_argument("--account", default="main_brand")
    native_code_parser.add_argument("--job-id", default="manual_instagram_code")

    args = parser.parse_args()
    if args.command == "migrate":
        init_db()
        print("Database schema is ready.")
    elif args.command == "worker":
        init_db()
        if args.loop:
            asyncio.run(BrowserTaskRunner(get_settings()).run_loop())
        else:
            result = asyncio.run(BrowserTaskRunner(get_settings()).run_once(platform=args.platform))
            print(json.dumps(result.__dict__, indent=2))
    elif args.command == "android-check":
        settings = get_settings()
        context = _manual_worker_context(settings, "main_brand")
        result = asyncio.run(InstagramNativeWorker().check_runtime(context))
        print(result.model_dump_json(indent=2))
    elif args.command == "production-check":
        settings = get_settings()
        result = asyncio.run(
            run_production_check(
                settings,
                recover_openwa=args.recover_openwa,
                deep_instagram=args.deep_instagram,
                account=args.account,
            )
        )
        print(json.dumps(result, indent=2))
        if result["status"] == "failed":
            sys.exit(1)
    elif args.command == "monitor-once":
        settings = get_settings()
        result = asyncio.run(
            run_production_check(
                settings,
                recover_openwa=not args.no_recover_openwa,
                deep_instagram=args.deep_instagram,
                account=args.account,
            )
        )
        print(json.dumps(result, indent=2))
    elif args.command == "whatsapp-session-recover":
        result = asyncio.run(check_openwa_session(get_settings(), recover=True))
        print(json.dumps(result, indent=2))
        if result["status"] == "fail":
            sys.exit(1)
    elif args.command == "instagram-native-auth-check":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        result = asyncio.run(InstagramNativeWorker().check_auth(context, account=args.account))
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-native-login":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        result = asyncio.run(InstagramNativeWorker().login(context, account=args.account))
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-native-backup":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        result = asyncio.run(InstagramNativeWorker().backup_app_data(context, account=args.account))
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-native-restore":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        result = asyncio.run(
            InstagramNativeWorker().restore_app_data(context, account=args.account, backup_path=args.backup_path)
        )
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-feed-to-story":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        actions = json.loads(args.actions_json)
        if not isinstance(actions, list):
            raise ValueError("--actions-json must be a JSON list.")
        payload = PlatformTaskPayload(
            job_id=args.job_id,
            platform=Platform.INSTAGRAM,
            account=args.account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(
                platform=Platform.INSTAGRAM,
                mode="story",
                extra={
                    "instagram_story_source": "feed_post",
                    "instagram_story_editor_actions": actions,
                    **({"instagram_post_url": args.post_url} if args.post_url else {}),
                },
            ),
        )
        result = asyncio.run(InstagramNativeWorker().share_latest_feed_post_to_story(payload, context))
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-native-direct-story":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        storage = LocalStorage(settings.storage_root)
        media_path = Path(args.media_path).expanduser().resolve()
        storage_root = settings.storage_root.resolve()
        try:
            media_uri = f"local://{media_path.relative_to(storage_root).as_posix()}"
        except ValueError:
            media_uri, _ = storage.save_bytes(media_path.read_bytes(), filename=media_path.name)
        actions = json.loads(args.actions_json)
        if not isinstance(actions, list):
            raise ValueError("--actions-json must be a JSON list.")
        payload = PlatformTaskPayload(
            job_id=args.job_id,
            platform=Platform.INSTAGRAM,
            account=args.account,
            mode=JobMode.PUBLISH,
            content=PlatformContent(
                platform=Platform.INSTAGRAM,
                mode="story",
                media_asset_ids=["cli_media"],
                extra={
                    "instagram_story_source": "media",
                    "instagram_story_editor_actions": actions,
                },
            ),
        )
        result = asyncio.run(
            InstagramNativeWorker().publish_direct_media_story(payload, context, {"cli_media": media_uri})
        )
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))
    elif args.command == "instagram-enter-code":
        settings = get_settings()
        context = _manual_worker_context(settings, args.account)
        result = asyncio.run(
            InstagramNativeWorker().enter_verification_code(
                args.code,
                context,
                account=args.account,
                job_id=args.job_id,
            )
        )
        _record_native_result(settings, args.account, result)
        print(result.model_dump_json(indent=2))


def _manual_worker_context(settings, account: str) -> WorkerContext:
    return WorkerContext(
        settings=settings,
        storage=LocalStorage(settings.storage_root),
        profile_path=settings.browser_profile_root / "instagram" / account,
        artifact_root=settings.artifact_root,
    )


def _record_native_result(settings, account: str, result) -> None:
    init_db()
    auth_status = str(result.raw.get("auth_status") or result.status)
    with session_scope() as session:
        repo = Repository(session, settings)
        profile = repo.ensure_browser_profile(Platform.INSTAGRAM, account)
        repo.record_profile_native_auth_check(profile, auth_status=auth_status, message=result.message)


if __name__ == "__main__":
    main()
