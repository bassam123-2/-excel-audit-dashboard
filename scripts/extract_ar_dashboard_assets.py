"""One-off extractor for Arabic compliance dashboard assets from reference HTML."""
from pathlib import Path

SRC = Path(
    r"d:\My Files\My Files\BTC\Audit\Website\dash-audit.alissa-ia.com"
    r"\Audit Dashboard Templates\داشبورد العربي"
    r"\dashboard-snapshot-2026-06-20 (2).html"
)
OUT = Path(__file__).resolve().parents[1] / "arabic_compliance_dashboard" / "assets"


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    s = text.index("<style>") + len("<style>")
    e = text.index("</style>", s)
    css = text[s:e]

    b0 = text.index("<body>") + len("<body>")
    sp = text.index('<script type="application/json" id="snapshot-pack">')
    body = text[b0:sp].strip()

    js_marker = text.index("const hasChartLib = typeof Chart")
    js_end = text.rindex("</script>", js_marker)
    js = text[js_marker:js_end].strip()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "styles.css").write_text(css, encoding="utf-8")
    (OUT / "body.html").write_text(body, encoding="utf-8")
    (OUT / "dashboard.js").write_text(js, encoding="utf-8")
    print(f"Wrote assets to {OUT} (css={len(css)}, body={len(body)}, js={len(js)})")


if __name__ == "__main__":
    main()
