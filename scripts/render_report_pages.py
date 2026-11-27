"""Render or verify the static daily pages using only the published JSON files."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.report_page import render_report_page


def render_pages(docs_dir: Path, *, check=False) -> bool:
    sources = sorted(docs_dir.glob('data_????-??-??.json'))
    different = []
    for source in sources:
        data = json.loads(source.read_bytes())
        date = data['date']
        if source.name != f'data_{date}.json':
            raise ValueError(f'Report date does not match {source.name}')
        page = docs_dir / f'report_{date}.html'
        html = render_report_page(data, docs_dir).encode('utf-8')
        if page.exists() and page.read_bytes().replace(b'\r\n', b'\n') == html:
            continue
        different.append(page.name)
        if not check:
            page.write_bytes(html)
    if check and different:
        print(f'{len(different)} out-of-date report pages: {", ".join(different)}', file=sys.stderr)
        return False
    print(f'{"Verified" if check else "Rendered"} {len(sources)} report pages ({len(different)} changed).')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare every page without writing files.')
    sys.exit(0 if render_pages(ROOT / 'docs', check=parser.parse_args().check) else 1)
