#!/usr/bin/env python3
"""Fetch Singapore IPTV entries from iptv-org and emit launcher links."""

from __future__ import annotations

import argparse
import dataclasses
import html
import json
import os
import re
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from pathlib import Path


COUNTRY_PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/sg.m3u"
RAW_STREAMS_URL = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/sg.m3u"
CACHE_DIR = Path.home() / ".cache" / "openclaw-singapore-iptv"
ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
QUALITY_RE = re.compile(r"\(([^()]+)\)")
COUNTRY_RE = re.compile(r"\.([a-z]{2,3})(?:@|$)", re.IGNORECASE)


@dataclasses.dataclass
class Channel:
    name: str
    display_name: str
    tvg_id: str | None
    logo: str | None
    group_title: str | None
    stream_url: str
    stream_type: str
    geo_blocked: bool
    quality: str | None
    origin_country: str | None
    variant: str | None

    def launchers(self) -> dict[str, str]:
        quoted = urllib.parse.quote(self.stream_url, safe="")
        return {
            "browser": self.stream_url,
            "vlc": f"vlc://{self.stream_url}",
            "ios_vlc_x_callback": f"vlc-x-callback://x-callback-url/stream?url={quoted}",
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "tvg_id": self.tvg_id,
            "logo": self.logo,
            "group_title": self.group_title,
            "stream_url": self.stream_url,
            "stream_type": self.stream_type,
            "geo_blocked": self.geo_blocked,
            "quality": self.quality,
            "origin_country": self.origin_country,
            "variant": self.variant,
            "launchers": self.launchers(),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the published Singapore playlist or the raw Singapore streams "
            "file from iptv-org and generate browser/VLC launcher links."
        )
    )
    parser.add_argument(
        "--source",
        choices=("countries", "streams"),
        default="countries",
        help=(
            "'countries' uses the published Singapore playlist, which is deduplicated "
            "and user-facing. 'streams' uses the raw SG upstream stream list."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "markdown", "m3u", "html"),
        default="table",
        help="Choose the output format.",
    )
    parser.add_argument(
        "--channel",
        help="Filter channels by case-insensitive substring in the display name.",
    )
    parser.add_argument(
        "--strict-sg",
        action="store_true",
        help=(
            "Only keep entries whose tvg-id origin country is 'sg'. Useful because "
            "the published Singapore playlist can include nearby cross-border channels."
        ),
    )
    parser.add_argument(
        "--exclude-geoblocked",
        action="store_true",
        help="Drop entries marked '[Geo-blocked]'.",
    )
    parser.add_argument(
        "--cache-max-age",
        type=int,
        default=3600,
        help="Reuse cached upstream data newer than this many seconds. Default: 3600.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Always fetch fresh upstream data.",
    )
    parser.add_argument(
        "--output",
        help="Write the rendered output to a file instead of stdout.",
    )
    return parser.parse_args()


def get_source_details(source: str) -> tuple[str, str]:
    if source == "countries":
        return ("countries", COUNTRY_PLAYLIST_URL)
    return ("streams", RAW_STREAMS_URL)


def fetch_text(source: str, url: str, cache_max_age: int, no_cache: bool) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{source}.m3u"

    if not no_cache and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age <= cache_max_age:
            return cache_path.read_text(encoding="utf-8")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "openclaw-singapore-iptv/1.0 (+https://github.com/iptv-org/iptv)"
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read().decode("utf-8")
    cache_path.write_text(data, encoding="utf-8")
    return data


def parse_playlist(text: str) -> list[Channel]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    channels: list[Channel] = []
    current_info: str | None = None

    for line in lines:
        if line.startswith("#EXTINF:"):
            current_info = line
            continue
        if line.startswith("#"):
            continue
        if current_info is None:
            continue
        channels.append(parse_channel(current_info, line))
        current_info = None

    return channels


def parse_channel(info_line: str, stream_url: str) -> Channel:
    attrs_part, name = split_extinf(info_line)
    attrs = dict(ATTR_RE.findall(attrs_part))
    display_name = clean_name(name)
    tvg_id = attrs.get("tvg-id")
    origin_country = parse_origin_country(tvg_id)
    variant = parse_variant(tvg_id)
    return Channel(
        name=name,
        display_name=display_name,
        tvg_id=tvg_id,
        logo=attrs.get("tvg-logo"),
        group_title=attrs.get("group-title"),
        stream_url=stream_url,
        stream_type=parse_stream_type(stream_url),
        geo_blocked="[Geo-blocked]" in name,
        quality=parse_quality(name),
        origin_country=origin_country,
        variant=variant,
    )


def split_extinf(info_line: str) -> tuple[str, str]:
    prefix = "#EXTINF:-1"
    if not info_line.startswith(prefix):
        return ("", info_line)
    body = info_line[len(prefix) :].strip()
    if "," not in body:
        return (body, body)
    attrs_part, name = body.rsplit(",", 1)
    return (attrs_part.strip(), name.strip())


def clean_name(name: str) -> str:
    cleaned = name.replace("[Geo-blocked]", "").strip()
    cleaned = QUALITY_RE.sub("", cleaned).strip()
    return " ".join(cleaned.split())


def parse_quality(name: str) -> str | None:
    match = QUALITY_RE.search(name)
    if not match:
        return None
    return match.group(1).strip()


def parse_origin_country(tvg_id: str | None) -> str | None:
    if not tvg_id:
        return None
    match = COUNTRY_RE.search(tvg_id)
    if not match:
        return None
    return match.group(1).lower()


def parse_variant(tvg_id: str | None) -> str | None:
    if not tvg_id or "@" not in tvg_id:
        return None
    return tvg_id.split("@", 1)[1]


def parse_stream_type(stream_url: str) -> str:
    lowered = stream_url.lower()
    if ".m3u8" in lowered:
        return "hls"
    if ".mpd" in lowered:
        return "dash"
    return "unknown"


def filter_channels(channels: list[Channel], args: argparse.Namespace) -> list[Channel]:
    filtered = channels
    if args.channel:
        needle = args.channel.lower()
        filtered = [channel for channel in filtered if needle in channel.display_name.lower()]
    if args.strict_sg:
        filtered = [channel for channel in filtered if channel.origin_country == "sg"]
    if args.exclude_geoblocked:
        filtered = [channel for channel in filtered if not channel.geo_blocked]
    return filtered


def playlist_launchers(source_url: str) -> dict[str, str]:
    quoted = urllib.parse.quote(source_url, safe="")
    return {
        "browser": source_url,
        "vlc": f"vlc://{source_url}",
        "ios_vlc_x_callback": f"vlc-x-callback://x-callback-url/stream?url={quoted}",
    }


def render_table(source_label: str, source_url: str, channels: list[Channel]) -> str:
    playlist = playlist_launchers(source_url)
    rows = [
        ["Channel", "Category", "Type", "Geo", "Origin"],
        ["-------", "--------", "----", "---", "------"],
    ]
    for channel in channels:
        rows.append(
            [
                channel.display_name,
                channel.group_title or "-",
                channel.stream_type,
                "yes" if channel.geo_blocked else "no",
                channel.origin_country or "-",
            ]
        )

    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        f"Source: {source_label} ({source_url})",
        f"Playlist in browser: {playlist['browser']}",
        f"Playlist in VLC: {playlist['vlc']}",
        f"Playlist in VLC iOS x-callback: {playlist['ios_vlc_x_callback']}",
        "",
    ]
    for row in rows:
        parts = [value.ljust(widths[index]) for index, value in enumerate(row)]
        lines.append("  ".join(parts))
    return "\n".join(lines)


def render_markdown(source_label: str, source_url: str, channels: list[Channel]) -> str:
    playlist = playlist_launchers(source_url)
    lines = [
        f"# Singapore IPTV",
        "",
        f"- Source: `{source_label}`",
        f"- Upstream: `{source_url}`",
        f"- Playlist browser URL: `{playlist['browser']}`",
        f"- Playlist VLC URL: `{playlist['vlc']}`",
        f"- Playlist VLC iOS x-callback: `{playlist['ios_vlc_x_callback']}`",
        "",
        "| Channel | Category | Type | Geo-blocked | Browser | VLC |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for channel in channels:
        launchers = channel.launchers()
        lines.append(
            "| {name} | {group} | {stype} | {geo} | {browser} | {vlc} |".format(
                name=escape_pipes(channel.display_name),
                group=escape_pipes(channel.group_title or "-"),
                stype=channel.stream_type,
                geo="yes" if channel.geo_blocked else "no",
                browser=f"[open]({launchers['browser']})",
                vlc=f"[open]({launchers['vlc']})",
            )
        )
    return "\n".join(lines)


def escape_pipes(value: str) -> str:
    return value.replace("|", "\\|")


def render_json(source_label: str, source_url: str, channels: list[Channel]) -> str:
    payload = {
        "source": source_label,
        "upstream_url": source_url,
        "playlist_launchers": playlist_launchers(source_url),
        "channels": [channel.as_dict() for channel in channels],
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)


def render_m3u(channels: list[Channel]) -> str:
    lines = ["#EXTM3U"]
    for channel in channels:
        attrs = []
        if channel.tvg_id:
            attrs.append(f'tvg-id="{channel.tvg_id}"')
        if channel.logo:
            attrs.append(f'tvg-logo="{channel.logo}"')
        if channel.group_title:
            attrs.append(f'group-title="{channel.group_title}"')
        attrs_text = " ".join(attrs)
        if attrs_text:
            lines.append(f"#EXTINF:-1 {attrs_text},{channel.name}")
        else:
            lines.append(f"#EXTINF:-1,{channel.name}")
        lines.append(channel.stream_url)
    return "\n".join(lines) + "\n"


def render_html(source_label: str, source_url: str, channels: list[Channel]) -> str:
    playlist = playlist_launchers(source_url)
    cards = []
    for channel in channels:
        launchers = channel.launchers()
        quality = f"<span class=\"tag\">{html.escape(channel.quality)}</span>" if channel.quality else ""
        geo = "<span class=\"tag danger\">Geo-blocked</span>" if channel.geo_blocked else ""
        group = channel.group_title or "Uncategorized"
        cards.append(
            f"""
            <article class="card">
              <div class="meta">
                <p class="eyebrow">{html.escape(group)} · {html.escape(channel.stream_type)}</p>
                <h2>{html.escape(channel.display_name)}</h2>
                <div class="tags">{quality}{geo}</div>
              </div>
              <div class="actions">
                <a href="{html.escape(launchers['browser'])}">Open in browser</a>
                <a href="{html.escape(launchers['vlc'])}">Open in VLC</a>
                <a href="{html.escape(launchers['ios_vlc_x_callback'])}">Open in VLC iOS</a>
              </div>
            </article>
            """
        )

    return textwrap.dedent(
        f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Singapore IPTV Launcher</title>
          <style>
            :root {{
              color-scheme: light;
              --bg: #f5f0e8;
              --panel: #fffaf3;
              --line: #dbcdb7;
              --ink: #182126;
              --muted: #6a6e64;
              --accent: #006a5b;
              --danger: #9d2b2b;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0;
              font-family: Georgia, "Times New Roman", serif;
              background:
                radial-gradient(circle at top right, #f0dac3, transparent 30%),
                linear-gradient(180deg, #f5f0e8, #efe4d2);
              color: var(--ink);
            }}
            main {{
              max-width: 980px;
              margin: 0 auto;
              padding: 32px 20px 56px;
            }}
            .hero, .card {{
              background: rgba(255, 250, 243, 0.92);
              border: 1px solid var(--line);
              border-radius: 20px;
              box-shadow: 0 18px 50px rgba(24, 33, 38, 0.08);
            }}
            .hero {{
              padding: 28px;
              margin-bottom: 24px;
            }}
            h1, h2 {{ margin: 0; }}
            p {{ line-height: 1.5; }}
            .subtitle {{ color: var(--muted); margin-top: 10px; }}
            .playlist-actions, .actions {{
              display: flex;
              flex-wrap: wrap;
              gap: 10px;
              margin-top: 16px;
            }}
            a {{
              display: inline-flex;
              align-items: center;
              justify-content: center;
              padding: 10px 14px;
              border-radius: 999px;
              border: 1px solid var(--accent);
              color: var(--accent);
              text-decoration: none;
            }}
            .cards {{
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
              gap: 18px;
            }}
            .card {{
              padding: 18px;
              display: flex;
              flex-direction: column;
              justify-content: space-between;
              min-height: 220px;
            }}
            .eyebrow {{
              color: var(--muted);
              text-transform: uppercase;
              letter-spacing: 0.08em;
              font-size: 0.78rem;
              margin-bottom: 8px;
            }}
            .tags {{
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              margin-top: 12px;
            }}
            .tag {{
              border: 1px solid var(--line);
              border-radius: 999px;
              padding: 4px 9px;
              font-size: 0.82rem;
            }}
            .tag.danger {{
              border-color: color-mix(in srgb, var(--danger) 50%, white);
              color: var(--danger);
            }}
          </style>
        </head>
        <body>
          <main>
            <section class="hero">
              <h1>Singapore IPTV Launcher</h1>
              <p class="subtitle">
                Source: {html.escape(source_label)} from
                <a href="{html.escape(source_url)}">{html.escape(source_url)}</a>.
                Direct browser playback depends on native HLS or DASH support.
                VLC is usually the safer launcher.
              </p>
              <div class="playlist-actions">
                <a href="{html.escape(playlist['browser'])}">Open playlist in browser</a>
                <a href="{html.escape(playlist['vlc'])}">Open playlist in VLC</a>
                <a href="{html.escape(playlist['ios_vlc_x_callback'])}">Open playlist in VLC iOS</a>
              </div>
            </section>
            <section class="cards">
              {"".join(cards)}
            </section>
          </main>
        </body>
        </html>
        """
    )


def write_output(text: str, output_path: str | None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def main() -> int:
    args = parse_args()
    source_label, source_url = get_source_details(args.source)
    text = fetch_text(source_label, source_url, args.cache_max_age, args.no_cache)
    channels = filter_channels(parse_playlist(text), args)
    channels.sort(key=lambda channel: channel.display_name.lower())

    if args.format == "table":
        rendered = render_table(source_label, source_url, channels)
    elif args.format == "json":
        rendered = render_json(source_label, source_url, channels)
    elif args.format == "markdown":
        rendered = render_markdown(source_label, source_url, channels)
    elif args.format == "m3u":
        rendered = render_m3u(channels)
    else:
        rendered = render_html(source_label, source_url, channels)

    write_output(rendered, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
