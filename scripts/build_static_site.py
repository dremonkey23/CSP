from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csp_radar.dashboard import build_payload, list_reports


def make_static_html(source: str) -> str:
    html = source
    html = html.replace("fetch('/api/reports')", "fetch('data/reports.json')")
    html = html.replace("fetch('/api/report' + qs)", "fetch(date ? 'data/report-' + encodeURIComponent(date) + '.json' : 'data/report-latest.json')")
    html = html.replace(
        'Private cash-secured put dashboard. Read-only. Ranks opportunity quality; cash required is metadata, not a filter.',
        'Private cash-secured put dashboard. Read-only static snapshot; data refreshes on the scheduled GitHub Actions workflow. Ranks opportunity quality; cash required is metadata, not a filter.',
    )
    # Remove any legacy backend-only scan handler if older HTML is used.
    html = re.sub(
        r"\n    el\('scanBtn'\)\.addEventListener\('click', async \(\) => \{.*?\n    \}\);\n",
        "\n",
        html,
        flags=re.S,
    )
    return html


def load_json_source(source: str | None) -> dict | None:
    if not source:
        return None
    try:
        if source.startswith(('http://', 'https://')):
            with urlopen(source, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        path = Path(source)
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text())
    except Exception as exc:
        print(f"previous snapshot unavailable: {exc}")
    return None


def row_key(row: dict) -> tuple:
    return (
        row.get('ticker'),
        row.get('expiry'),
        row.get('strike'),
        round(float(row.get('total_score') or 0), 4),
        round(float(row.get('premium_received') or 0), 4),
        row.get('delta'),
        row.get('open_interest'),
        row.get('reject_reason'),
    )


def top_symbols(payload: dict, section: str = 'best_overall', limit: int = 10) -> list[str]:
    return [f"{r.get('ticker')} {r.get('strike')}P {r.get('expiry')}" for r in (payload.get('sections', {}).get(section) or [])[:limit]]


def attach_change_summary(payload: dict, previous: dict | None) -> dict:
    current_stats = payload.get('stats', {})
    if not previous:
        payload['change_summary'] = {
            'available': False,
            'note': 'No previous published snapshot available for comparison.',
        }
        return payload

    prev_stats = previous.get('stats', {})
    sections = ['best_overall', 'highest_premium', 'best_assignment', 'rejects']
    changed_visible_rows = 0
    section_changes: dict[str, int] = {}
    for section in sections:
        cur_rows = payload.get('sections', {}).get(section) or []
        prev_rows = previous.get('sections', {}).get(section) or []
        count = 0
        for i in range(max(len(cur_rows), len(prev_rows))):
            cur_key = row_key(cur_rows[i]) if i < len(cur_rows) else None
            prev_key = row_key(prev_rows[i]) if i < len(prev_rows) else None
            if cur_key != prev_key:
                count += 1
        section_changes[section] = count
        changed_visible_rows += count

    cur_top = top_symbols(payload)
    prev_top = top_symbols(previous)
    new_top = [x for x in cur_top if x not in prev_top]
    dropped_top = [x for x in prev_top if x not in cur_top]

    payload['change_summary'] = {
        'available': True,
        'previous_updated_at': previous.get('updated_at'),
        'changed_visible_rows': changed_visible_rows,
        'section_changes': section_changes,
        'accepted_delta': int(current_stats.get('accepted_count', 0)) - int(prev_stats.get('accepted_count', 0)),
        'rejected_delta': int(current_stats.get('reject_count', 0)) - int(prev_stats.get('reject_count', 0)),
        'symbols_delta': int(current_stats.get('symbols_count', 0)) - int(prev_stats.get('symbols_count', 0)),
        'new_top_10': new_top,
        'dropped_top_10': dropped_top,
        'materially_unchanged': changed_visible_rows == 0,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='public', help='Output directory for static GitHub Pages assets')
    parser.add_argument('--web', default='web/index.html', help='Source dashboard HTML')
    parser.add_argument('--previous', default=None, help='Previous published report-latest.json file or URL for change comparison')
    args = parser.parse_args()

    out = Path(args.out)
    data_dir = out / 'data'
    if out.exists():
        shutil.rmtree(out)
    data_dir.mkdir(parents=True, exist_ok=True)

    reports = list_reports()
    if not reports:
        raise SystemExit('No reports found. Run the scanner first.')

    previous = load_json_source(args.previous)

    # Keep the reports list compact and static-friendly.
    (data_dir / 'reports.json').write_text(json.dumps(reports, indent=2) + '\n')

    latest_payload = None
    for report in reports:
        payload = build_payload(report['date'])
        if latest_payload is None:
            payload = attach_change_summary(payload, previous)
            latest_payload = payload
        (data_dir / f"report-{report['date']}.json").write_text(json.dumps(payload, indent=2) + '\n')

    if latest_payload is None:
        raise SystemExit('No payload generated.')
    (data_dir / 'report-latest.json').write_text(json.dumps(latest_payload, indent=2) + '\n')

    source_html = Path(args.web).read_text()
    (out / 'index.html').write_text(make_static_html(source_html))
    (out / '.nojekyll').write_text('')

    change = latest_payload.get('change_summary', {})
    change_msg = f"changes={change.get('changed_visible_rows')}" if change.get('available') else 'changes=baseline'
    print(f"built static site in {out} from {len(reports)} report(s); latest={latest_payload['date']}; {change_msg}")


if __name__ == '__main__':
    main()
