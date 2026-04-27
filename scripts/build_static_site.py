from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csp_radar.dashboard import build_payload, list_reports


def make_static_html(source: str) -> str:
    html = source
    html = html.replace("fetch('/api/reports')", "fetch('data/reports.json')")
    html = html.replace("fetch('/api/report' + qs)", "fetch(date ? 'data/report-' + encodeURIComponent(date) + '.json' : 'data/report-latest.json')")
    html = re.sub(
        r"el\('scanBtn'\)\.addEventListener\('click', async \(\) => \{.*?\n    \}\);",
        "el('scanBtn').addEventListener('click', () => {\n      setStatus('Static GitHub Pages mode: data refresh runs on the scheduled GitHub Actions workflow.', 'warn');\n    });",
        html,
        flags=re.S,
    )
    html = html.replace('<button id="scanBtn" class="primary">Run Fresh Scan</button>', '<button id="scanBtn" class="primary" title="Static site: refresh runs on schedule">Scheduled Refresh</button>')
    html = html.replace(
        'Private cash-secured put dashboard. Read-only. Ranks opportunity quality; cash required is metadata, not a filter.',
        'Private cash-secured put dashboard. Read-only static snapshot; data refreshes on the scheduled GitHub Actions workflow. Ranks opportunity quality; cash required is metadata, not a filter.',
    )
    return html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='public', help='Output directory for static GitHub Pages assets')
    parser.add_argument('--web', default='web/index.html', help='Source dashboard HTML')
    args = parser.parse_args()

    out = Path(args.out)
    data_dir = out / 'data'
    if out.exists():
        shutil.rmtree(out)
    data_dir.mkdir(parents=True, exist_ok=True)

    reports = list_reports()
    if not reports:
        raise SystemExit('No reports found. Run the scanner first.')

    # Keep the reports list compact and static-friendly.
    (data_dir / 'reports.json').write_text(json.dumps(reports, indent=2) + '\n')

    latest_payload = None
    for report in reports:
        payload = build_payload(report['date'])
        if latest_payload is None:
            latest_payload = payload
        (data_dir / f"report-{report['date']}.json").write_text(json.dumps(payload, indent=2) + '\n')

    if latest_payload is None:
        raise SystemExit('No payload generated.')
    (data_dir / 'report-latest.json').write_text(json.dumps(latest_payload, indent=2) + '\n')

    source_html = Path(args.web).read_text()
    (out / 'index.html').write_text(make_static_html(source_html))
    (out / '.nojekyll').write_text('')

    print(f"built static site in {out} from {len(reports)} report(s); latest={latest_payload['date']}")


if __name__ == '__main__':
    main()
