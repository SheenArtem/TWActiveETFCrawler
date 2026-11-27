"""Render or verify the shared site shell and daily pages from the published JSON files."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.report_page import render_home_page, render_report_page


def render_pages(docs_dir: Path, *, check=False) -> bool:
    sources = sorted(docs_dir.glob('data_????-??-??.json'))
    different = []

    def publish(page, content):
        html = content.encode('utf-8')
        if page.exists() and page.read_bytes().replace(b'\r\n', b'\n') == html:
            return
        different.append(page.name)
        if not check:
            page.write_bytes(html)

    publish(docs_dir / 'index.html', render_home_page())
    for source in sources:
        data = json.loads(source.read_bytes())
        date = data['date']
        if source.name != f'data_{date}.json':
            raise ValueError(f'Report date does not match {source.name}')
        publish(docs_dir / f'report_{date}.html', render_report_page(data, docs_dir))
    if check and different:
        print(f'{len(different)} out-of-date pages: {", ".join(different)}', file=sys.stderr)
        return False
    print(f'{"Verified" if check else "Rendered"} the homepage and {len(sources)} report pages ({len(different)} changed).')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare every page without writing files.')
    sys.exit(0 if render_pages(ROOT / 'docs', check=parser.parse_args().check) else 1)
