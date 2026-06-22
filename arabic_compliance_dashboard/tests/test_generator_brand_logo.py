"""Header logo is embedded for the main tenant company regardless of subsidiary filters."""
from __future__ import annotations

import pandas as pd

from arabic_compliance_dashboard.generator import generate_ar_compliance_report


def _minimal_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "تصنيف المخاطر الكامنة": "عالي",
                "تصنيف المخاطر المتبقية": "متوسط",
                "الحالة": "مفتوح",
                "الإدارة المسؤولة": "الامتثال",
                "المشرع": "وزارة التجارة",
                "اسم النظام": "نظام الشركات",
                "الهيئة التابعة": "هيئة",
                "اللائحة": "لائحة",
                "النص النظامي": "نص",
                "حالة الالتزام": "ملتزم",
                "فئة الضوابط الرقابية": "رقابي",
                "الشركة التابعة": "aum",
            }
        ]
    )


def test_generate_report_embeds_main_header_logo():
    logo_uri = "data:image/png;base64,TESTLOGO"
    sub_uri = "data:image/png;base64,SUBLOGO"
    html = generate_ar_compliance_report(
        _minimal_df(),
        dashboard_id=1,
        brand_logos={"nat": logo_uri, "aum": sub_uri},
        default_brand_code="nat",
    )
    assert f'<img id="headerLogo" class="logo" alt="" src="{logo_uri}">' in html
    assert '"default_brand_code": "nat"' in html
    assert '"aum": "data:image/png;base64,SUBLOGO"' in html
