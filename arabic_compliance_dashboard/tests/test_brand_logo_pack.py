"""Brand logo pack and company resolution for Arabic compliance header."""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile

from arabic_compliance_dashboard.data import brand_logo_pack, resolve_brand_logo_company
from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company


def _tiny_png() -> SimpleUploadedFile:
    # 1x1 PNG
    raw = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc"
        b"\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return SimpleUploadedFile("logo.png", raw, content_type="image/png")


def test_brand_logo_pack_includes_root_and_subsidiary_keys(db):
    root = Company.objects.create(
        code="TSTROOT",
        name="Test Root Co",
        company_kind=COMPANY_KIND_MAIN,
        excel_company_names=["TSTROOT"],
        logo=_tiny_png(),
    )
    sub = Company.objects.create(
        code="TSTAUM",
        name="Test AUM Sub",
        company_kind=COMPANY_KIND_SUBSIDIARY,
        parent=root,
        excel_company_names=["TSTAUM"],
        logo=_tiny_png(),
    )

    logos, default_code = brand_logo_pack(root)

    assert default_code == "tstroot"
    assert "tstroot" in logos
    assert "tstaum" in logos
    assert logos["tstroot"].startswith("data:")
    assert logos["tstaum"].startswith("data:")

    resolved = resolve_brand_logo_company(root, "tstaum")
    assert resolved.pk == sub.pk
    assert resolve_brand_logo_company(root, None).pk == root.pk
    assert resolve_brand_logo_company(root, "tstroot").pk == root.pk
