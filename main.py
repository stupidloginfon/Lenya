#!/usr/bin/env python3
"""Lenya — CLI для пайплайна «найти хук → сгенерировать → реклама → загрузить».

Примеры:
    python main.py discover "как заработать" "фитнес лайфхаки" --limit 15
    python main.py download --all
    python main.py analyze --all
    python main.py generate 3 --topic "мой курс по Python"
    python main.py advertise 3
    python main.py upload 3 --to youtube
    python main.py list

    # Всё разом:
    python main.py run "тренды о деньгах" --topic "мой телеграм-канал" --to youtube
"""
import argparse
import sys

import config
from pipeline import advertise, analyze, db, discover, download, generate, llm, upload


def _ids(args, default_status: str) -> list[int]:
    """Список id из аргументов: либо явные, либо все на нужной стадии (--all)."""
    if getattr(args, "all", False):
        return [r["id"] for r in db.by_status(default_status)]
    return list(args.ids)


def cmd_discover(args):
    discover.discover(args.sources, limit=args.limit)


def cmd_download(args):
    for vid in _ids(args, "discovered"):
        try:
            download.download(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[download] [{vid}] ошибка: {e}")


def cmd_analyze(args):
    # Перед анализом убедимся, что ролик скачан.
    for vid in _ids(args, "discovered"):
        row = db.get(vid)
        if row and not row["download_path"]:
            try:
                download.download(vid)
            except Exception as e:  # noqa: BLE001
                print(f"[analyze] [{vid}] не удалось скачать: {e}")
                continue
        try:
            analyze.analyze(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[analyze] [{vid}] ошибка: {e}")


def cmd_generate(args):
    targets = _ids(args, "analyzed")
    for vid in targets:
        try:
            generate.generate(vid, args.topic)
        except Exception as e:  # noqa: BLE001
            print(f"[generate] [{vid}] ошибка: {e}")


def cmd_advertise(args):
    for vid in _ids(args, "generated"):
        try:
            advertise.advertise(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[advertise] [{vid}] ошибка: {e}")


def cmd_upload(args):
    for vid in _ids(args, "advertised"):
        upload.upload(vid, args.to)


def cmd_run(args):
    """Полный прогон: discover → download → analyze → generate → advertise → upload."""
    found = discover.discover(args.sources, limit=args.limit)
    for vid in found:
        try:
            download.download(vid)
            res = analyze.analyze(vid)
        except Exception as e:  # noqa: BLE001
            print(f"[run] [{vid}] анализ не удался: {e}")
            continue
        if res.get("final_score", 0) < config.HOOK_SCORE_THRESHOLD:
            continue
        try:
            generate.generate(vid, args.topic)
            advertise.advertise(vid)
            if args.to:
                upload.upload(vid, args.to)
        except Exception as e:  # noqa: BLE001
            print(f"[run] [{vid}] продакшн не удался: {e}")


def cmd_list(args):
    rows = db.connect().execute(
        "SELECT id, status, hook_score, platform, title FROM videos ORDER BY id"
    ).fetchall()
    if not rows:
        print("Пусто. Начни с `python main.py discover ...`")
        return
    for r in rows:
        score = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else "—"
        title = (r["title"] or "")[:50]
        print(f"[{r['id']:>3}] {r['status']:<11} хук={score:<4} {r['platform'] or '':<10} {title}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lenya", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="найти трендовые ролики")
    d.add_argument("sources", nargs="+", help="запросы или URL (хэштеги TikTok, каналы, Reels)")
    d.add_argument("--limit", type=int, default=20)
    d.set_defaults(func=cmd_discover)

    dl = sub.add_parser("download", help="скачать исходники")
    dl.add_argument("ids", nargs="*", type=int)
    dl.add_argument("--all", action="store_true", help="все на стадии discovered")
    dl.set_defaults(func=cmd_download)

    a = sub.add_parser("analyze", help="оценить хуки через Claude")
    a.add_argument("ids", nargs="*", type=int)
    a.add_argument("--all", action="store_true")
    a.set_defaults(func=cmd_analyze)

    g = sub.add_parser("generate", help="сгенерировать новое видео по шаблону хука")
    g.add_argument("ids", nargs="*", type=int)
    g.add_argument("--all", action="store_true", help="все принятые (analyzed)")
    g.add_argument("--topic", required=True, help="тема/продукт нового видео")
    g.set_defaults(func=cmd_generate)

    ad = sub.add_parser("advertise", help="вставить рекламу")
    ad.add_argument("ids", nargs="*", type=int)
    ad.add_argument("--all", action="store_true")
    ad.set_defaults(func=cmd_advertise)

    u = sub.add_parser("upload", help="загрузить на площадки")
    u.add_argument("ids", nargs="*", type=int)
    u.add_argument("--all", action="store_true")
    u.add_argument("--to", nargs="+", default=["youtube"],
                   choices=["youtube", "tiktok", "instagram"])
    u.set_defaults(func=cmd_upload)

    r = sub.add_parser("run", help="полный прогон end-to-end")
    r.add_argument("sources", nargs="+")
    r.add_argument("--topic", required=True)
    r.add_argument("--limit", type=int, default=10)
    r.add_argument("--to", nargs="*", default=[],
                   choices=["youtube", "tiktok", "instagram"])
    r.set_defaults(func=cmd_run)

    sub.add_parser("list", help="показать состояние пайплайна").set_defaults(func=cmd_list)
    return p


def main():
    args = build_parser().parse_args()
    if args.cmd in {"analyze", "generate", "run"}:
        ok, hint = llm.is_ready()
        if not ok:
            sys.exit(f"LLM-провайдер не настроен ({config.LLM_PROVIDER}): {hint}")
    config.ensure_dirs()
    args.func(args)


if __name__ == "__main__":
    main()
