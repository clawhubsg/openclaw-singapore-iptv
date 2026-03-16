---
name: "openclaw-singapore-iptv"
description: "Fetch Singapore IPTV playlists from iptv-org, filter Singapore and Singapore-related channels, and generate browser or VLC launcher links for mobile or desktop. Use when the user wants Singapore TV streams, a Singapore IPTV playlist, SG-only filtering from iptv-org, or launch URLs for VLC on Android, iPhone, iPad, desktop, or a web browser."
---

# Openclaw Singapore IPTV

## Overview

Use the bundled helper to fetch live Singapore playlist data from `iptv-org/iptv`, then return a compact channel list or launcher links. Prefer the published country playlist for end-user output and the raw SG streams file only when you want every upstream SG-tagged stream candidate.

## Workflow

1. Choose the source:
- Default to `--source countries` for a deduplicated user-facing playlist from `https://iptv-org.github.io/iptv/countries/sg.m3u`.
- Use `--source streams` for the raw upstream SG stream file from `https://raw.githubusercontent.com/iptv-org/iptv/master/streams/sg.m3u`.

2. Run the helper:

```bash
python3 /home/dreamtcs/openclaw-skills/openclaw-singapore-iptv/scripts/fetch_singapore_iptv.py --source countries
```

3. Add filters only when needed:
- `--strict-sg` removes cross-border entries that can appear in the published Singapore playlist.
- `--exclude-geoblocked` drops entries labeled `[Geo-blocked]`.
- `--channel cna` narrows the result to matching channel names.

4. Pick the output format:
- `--format table` for terminal-friendly review.
- `--format json` for structured downstream use.
- `--format markdown` for a user reply with clickable links.
- `--format html --output /tmp/sg-iptv.html` for a launcher page with browser and VLC links.
- `--format m3u --output /tmp/sg-iptv.m3u` for a filtered playlist file.

## Launcher Guidance

- The helper emits three launcher forms:
  - Direct browser URL to the playlist or stream
  - `vlc://...` URL for VLC
  - `vlc-x-callback://x-callback-url/stream?url=...` for VLC on iOS
- Browser playback depends on native HLS or DASH support. VLC is usually more reliable for `.m3u8` and `.mpd` streams.
- The published `countries/sg.m3u` playlist may include a few non-`.sg` entries relevant to the Singapore market. Use `--strict-sg` when the user wants only channels whose upstream `tvg-id` is tagged `sg`.

## Output Guidance

Keep the reply practical:
- State which upstream source you used.
- Call out whether geoblocked entries were kept or removed.
- If the user asked for launch links, include the playlist-level launchers first, then per-channel launchers only for the channels they asked about.
- Do not claim that any stream will always play. These URLs are upstream public links and can change or fail.
