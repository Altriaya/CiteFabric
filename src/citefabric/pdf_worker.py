"""Isolated, killable PDF text extraction. Never fetches or executes PDF content."""

import json
import sys


def main():
    from pypdf import PdfReader, __version__

    request = json.loads(sys.stdin.read(8192))
    try:
        # Linux supports reliable address-space limits; other systems rely on the
        # parent's byte/page/wall-time limits and killable process boundary.
        if sys.platform.startswith("linux"):
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        reader = PdfReader(request["path"])
        if reader.is_encrypted:
            print(json.dumps({"error": "permission_denied"}))
            return
        if len(reader.pages) > request["max_pages"]:
            print(json.dumps({"error": "resource_limit"}))
            return
        units, failed, size = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
                size += len(text.encode("utf-8"))
                if size > 4 * 1024 * 1024:
                    print(json.dumps({"error": "resource_limit"}))
                    return
                if text.strip():
                    units.append(dict(text_unit_id=f"page:{number}", page=number, text=text))
                else:
                    failed.append(number)
            except Exception:
                failed.append(number)
        print(
            json.dumps(
                dict(
                    units=units,
                    pages_total=len(reader.pages),
                    pages_failed=failed,
                    parser_version=__version__,
                ),
                ensure_ascii=False,
            )
        )
    except Exception:
        print(json.dumps({"error": "parse_failed"}))


if __name__ == "__main__":
    main()
