const __arCfg = window.__AR_DASHBOARD__ || {};
        const __arApiBase = String(__arCfg.apiBase || "").replace(/\/+$/, "");
        function arApiUrl(path) {
            const p = path.startsWith("/") ? path : "/" + path;
            if (__arApiBase) return __arApiBase + p;
            return "/api" + (p.startsWith("/api") ? p.slice(4) : p);
        }

        const hasChartLib = typeof Chart !== "undefined";
        const hasChartDataLabels = typeof ChartDataLabels !== "undefined";
        if (hasChartLib && hasChartDataLabels) {
            Chart.register(ChartDataLabels);
        }

        (function installSnapshotFetchShim() {
            const packEl = document.getElementById("snapshot-pack");
            if (!packEl) return;
            let pack;
            try {
                pack = JSON.parse(packEl.textContent || "{}");
            } catch {
                return;
            }
            const BLANK = "(blank)";
            const COL_YEAR = "السنة";
            const COL_TARGET = "تاريخ التصحيح المستهدف";
            const COL_MODIFIED = "تاريخ التصحيح المعدل";
            const COL_STATUS = "الحالة";
            const COL_RESIDUAL = "تصنيف المخاطر المتبقية";
            const COL_INHERENT = "تصنيف المخاطر الكامنة";
            const PARAM_TO_COL = {
                inherent: "تصنيف المخاطر الكامنة",
                residual: "تصنيف المخاطر المتبقية",
                status: "الحالة",
                year: "السنة",
                department: "الإدارة المسؤولة",
                legislator: "المشرع",
                system_name: "اسم النظام",
                authority: "الهيئة التابعة",
                regulation: "اللائحة",
                legal_text: "النص النظامي",
                compliance_status: "حالة الالتزام",
                control_category: "فئة الضوابط الرقابية",
                subsidiary_company: "الشركة التابعة",
                holding_company: "الشركة القابضة"
            };
            const GROUP_DIMS = Object.values(PARAM_TO_COL);
            const selectedFromParams = (sp) => {
                const out = {};
                Object.entries(PARAM_TO_COL).forEach(([p, col]) => {
                    out[col] = sp.getAll(p).map((v) => String(v).trim()).filter(Boolean);
                });
                return out;
            };
            const rowValue = (row, col) => {
                const v = row[col];
                return v === undefined || v === null || v === "" ? BLANK : String(v);
            };
            const yearFromDateCell = (value) => {
                if (!value || value === BLANK) return BLANK;
                const s = String(value).trim();
                if (/^-?\d+(?:\.\d+)?$/.test(s)) {
                    const n = Number(s);
                    if (Number.isFinite(n)) {
                        let ms = null;
                        if (n >= 1e12) ms = n;
                        else if (n >= 1e9) ms = n * 1000;
                        if (ms != null) {
                            const dEpoch = new Date(ms);
                            if (!Number.isNaN(dEpoch.getTime())) return String(dEpoch.getUTCFullYear());
                        }
                    }
                }
                const d = new Date(`${s.slice(0, 10)}T12:00:00`);
                return Number.isNaN(d.getTime()) ? BLANK : String(d.getFullYear());
            };
            const enrichRowYear = (row) => {
                const existing = rowValue(row, COL_YEAR);
                if (existing !== BLANK) return row;
                row[COL_YEAR] = yearFromDateCell(rowValue(row, COL_TARGET));
                return row;
            };
            const applyFilters = (rows, selected, skipCol) =>
                rows.filter((row) =>
                    Object.entries(selected).every(([col, vals]) => col === skipCol || !vals?.length || vals.includes(rowValue(row, col)))
                );
            const sortGroup = (key, values) => {
                if (key === COL_YEAR) {
                    const numeric = values.filter((v) => /^\d+$/.test(v)).sort((a, b) => Number(a) - Number(b));
                    const rest = values.filter((v) => !/^\d+$/.test(v) && v !== BLANK).sort((a, b) => a.localeCompare(b, "ar"));
                    return values.includes(BLANK) ? [BLANK, ...numeric, ...rest] : [...numeric, ...rest];
                }
                return [...values].sort((a, b) => a.localeCompare(b, "ar"));
            };
            const buildSummary = (rows, selected) => {
                const fully = applyFilters(rows, selected, null);
                const groups = {};
                const availableDims = GROUP_DIMS.filter((dim) =>
                    rows.some((r) => Object.prototype.hasOwnProperty.call(r, dim))
                );
                availableDims.forEach((dim) => {
                    const counts = {};
                    applyFilters(rows, selected, dim).forEach((r) => {
                        const k = rowValue(r, dim);
                        counts[k] = (counts[k] || 0) + 1;
                    });
                    groups[dim] = sortGroup(dim, Object.keys(counts)).map((k) => ({ key: k, label: k, count: counts[k] }));
                });
                const company_columns = {
                    holding: availableDims.includes("الشركة القابضة"),
                    subsidiary: availableDims.includes("الشركة التابعة")
                };
                return { total: fully.length, selected, groups, company_columns };
            };
            const detailFields = [
                ["email", "البريد الإلكتروني (email)"],
                ["الحالة", "الحالة"],
                ["تصنيف المخاطر المتبقية", "تصنيف المخاطر المتبقية"],
                ["فئة الضوابط الرقابية", "فئة الضوابط الرقابية"],
                ["تاريخ التصحيح المستهدف", "تاريخ التصحيح المستهدف"],
                ["تاريخ التصحيح المعدل", "تاريخ التصحيح المعدل"],
                ["مالك المهمة / مالك الإجراء", "مالك المهمة / مالك الإجراء"],
                ["الشخص المسؤول", "الشخص المسؤول"],
                ["الخطة التصحيحية", "الخطة التصحيحية"],
                ["ملاحظات الإدارة.1", "ملاحظات الإدارة"],
                ["ملاحظات الإلتزام", "ملاحظات الإلتزام"]
            ];
            const pickBestLegalRow = (matches) => {
                if (!matches.length) return null;
                const withMail = matches.filter((r) => {
                    const e = rowValue(r, "email");
                    return e !== BLANK && String(e).includes("@");
                });
                const pool = withMail.length ? withMail : matches;
                let best = pool[0];
                let bestScore = -1;
                pool.forEach((r) => {
                    let s = 0;
                    detailFields.forEach(([col]) => {
                        const v = rowValue(r, col);
                        if (v !== BLANK) s += 1;
                    });
                    if (s > bestScore) {
                        bestScore = s;
                        best = r;
                    }
                });
                return best;
            };
            const legalDetailsFromRows = (text) => {
                const matches = rows.filter((r) => rowValue(r, "النص النظامي") === text);
                if (!matches.length) return null;
                const row = pickBestLegalRow(matches);
                const fields = detailFields.map(([col, label]) => ({
                    label,
                    value: rowValue(row, col) === BLANK ? "" : rowValue(row, col)
                }));
                const em = rowValue(row, "email");
                const recipient_email =
                    em !== BLANK && String(em).includes("@") ? String(em).trim() : "";
                return {
                    legal_text: text,
                    excel_row: 0,
                    picked_row_index: 0,
                    recipient_email,
                    fields,
                    images: []
                };
            };
            const normNFKC = (s) => String(s || "").normalize("NFKC");
            const isWithinCorrectionStatus = (statusText) => {
                const t = normNFKC(statusText).replace(/\s+/g, " ");
                if (!t.includes("مفتوح")) return false;
                return t.includes("ضمن") && t.includes("تاريخ") && t.includes("التصحيح");
            };
            const isPastCorrectionStatus = (statusText) => {
                const t = normNFKC(statusText).replace(/\s+/g, " ");
                if (!t.includes("مفتوح")) return false;
                return t.includes("تجاوز") && t.includes("تاريخ") && t.includes("التصحيح");
            };
            const isOpenStatusForAging = (statusText) =>
                isWithinCorrectionStatus(statusText) || isPastCorrectionStatus(statusText);
            const agingRowRiskText = (row) => {
                const residual = rowValue(row, COL_RESIDUAL);
                if (residual !== BLANK) return residual;
                return rowValue(row, COL_INHERENT);
            };
            const agingRiskKey = (residualNorm) => {
                if (residualNorm === BLANK) return null;
                let t = normNFKC(String(residualNorm || "").trim()).replace(/\u00a0/g, " ");
                if (!t) return null;
                t = t.replace(/\s+/g, " ").trim();
                [
                    ["مرنفع", "مرتفع"],
                    ["مرتفغ", "مرتفع"],
                    ["مرتفاع", "مرتفع"],
                    ["مرنفغ", "مرتفع"],
                    ["مرتفغ جدا", "مرتفع جدا"],
                    ["عاليه", "عالية"]
                ].forEach(([bad, good]) => (t = t.split(bad).join(good)));
                if (t.includes("متدني") && /انخفاض|انخفاظ|انخغاض|انخفاق/.test(t)) return "very_low";
                if ((t.includes("جدا") || t.includes("جداً") || t.includes("جدآ")) && (t.includes("مرتفع") || t.includes("مرفع") || t.includes("عالي") || t.includes("عالية"))) return "very_high";
                if (t.includes("متوسط")) return "medium";
                if (t.includes("منخفض") && !t.includes("متدني")) return "low";
                if (t.includes("مرتفع") || t.includes("مرفع")) return "high";
                if (/^(عالي|عالية)$/.test(t) || /(^|\s)عالي(?:ة)?($|\s)/.test(t)) return "high";
                return null;
            };
            const parseDateAtNoon = (dstr) => {
                if (!dstr || dstr === BLANK) return null;
                const s = String(dstr).trim();
                if (/^-?\d+(?:\.\d+)?$/.test(s)) {
                    const n = Number(s);
                    if (Number.isFinite(n)) {
                        let ms = null;
                        if (n >= 1e12) ms = n;
                        else if (n >= 1e9) ms = n * 1000;
                        if (ms != null) {
                            const dEpoch = new Date(ms);
                            if (!Number.isNaN(dEpoch.getTime())) {
                                return new Date(dEpoch.getFullYear(), dEpoch.getMonth(), dEpoch.getDate());
                            }
                        }
                    }
                }
                const d = new Date(`${s.slice(0, 10)}T12:00:00`);
                return Number.isNaN(d.getTime()) ? null : d;
            };
            const agingOverdueBucket = (compare, reference) => {
                if (!compare || !reference) return null;
                const cref = new Date(compare.getFullYear(), compare.getMonth(), compare.getDate());
                const rref = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate());
                const overdueDays = Math.floor((rref - cref) / (1000 * 60 * 60 * 24));
                if (overdueDays < 183) return "lt_6m";
                if (overdueDays < 365) return "lt_1y";
                return "ge_1y";
            };
            const computeAging = (rows, selected, referenceRaw, dateSource) => {
                const ref = parseDateAtNoon(referenceRaw);
                if (!ref) return { error: "Invalid reference date" };
                const dateCol = dateSource === "modified" ? COL_MODIFIED : COL_TARGET;
                const cfg = pack.aging_config || { risk_columns: [], time_rows: [] };
                const riskKeys = (cfg.risk_columns || []).map((x) => x.id);
                const matrix = {};
                (cfg.time_rows || []).forEach((tr) => {
                    matrix[tr.id] = {};
                    riskKeys.forEach((rk) => (matrix[tr.id][rk] = 0));
                });
                let skippedOther = 0;
                let unknownTime = 0;
                applyFilters(rows, selected, null).forEach((row) => {
                    const st = rowValue(row, COL_STATUS);
                    const rkey = agingRiskKey(agingRowRiskText(row)) || "other";
                    if (isWithinCorrectionStatus(st)) {
                        if (matrix.not_due) matrix.not_due[rkey] = (matrix.not_due[rkey] || 0) + 1;
                        return;
                    }
                    if (isPastCorrectionStatus(st)) {
                        const cdt = parseDateAtNoon(rowValue(row, dateCol));
                        if (!cdt) {
                            unknownTime += 1;
                            return;
                        }
                        const tkey = agingOverdueBucket(cdt, ref);
                        if (!tkey || !matrix[tkey]) {
                            unknownTime += 1;
                            return;
                        }
                        matrix[tkey][rkey] = (matrix[tkey][rkey] || 0) + 1;
                        return;
                    }
                    skippedOther += 1;
                });
                const time_rows = (cfg.time_rows || []).map((tr) => {
                    const cells = matrix[tr.id] || {};
                    const total = riskKeys.reduce((s, k) => s + (cells[k] || 0), 0);
                    return { id: tr.id, label: tr.label, cells, total };
                });
                const column_totals = {};
                riskKeys.forEach((k) => {
                    column_totals[k] = (cfg.time_rows || []).reduce((s, tr) => s + ((matrix[tr.id] || {})[k] || 0), 0);
                });
                const grand_total = riskKeys.reduce((s, k) => s + (column_totals[k] || 0), 0);
                return {
                    reference: referenceRaw.slice(0, 10),
                    date_field: dateCol,
                    date_source: dateSource,
                    risk_columns: cfg.risk_columns || [],
                    time_rows,
                    column_totals,
                    grand_total,
                    status_filter: "open_only",
                    skipped_other_status: skippedOther,
                    skipped_unknown_time: unknownTime
                };
            };
            const parseFetch = (url) => {
                if (url.includes("://")) {
                    const u = new URL(url);
                    return { path: u.pathname, sp: u.searchParams };
                }
                const [path, q = ""] = url.split("?");
                return { path, sp: new URLSearchParams(q) };
            };
            const jsonResponse = (obj, code = 200) =>
                Promise.resolve(new Response(JSON.stringify(obj), { status: code, headers: { "Content-Type": "application/json" } }));
            const rows = (pack.rows || []).map((row) => enrichRowYear({ ...row }));
            const OFFLINE_SERVER_BASE =
                localStorage.getItem("excelArabicServerBase") ||
                "http://127.0.0.1:8765";
            const origFetch = window.fetch.bind(window);
            window.fetch = function (input, init) {
                const url = typeof input === "string" ? input : input.url;
                const isArApi = /\/ar-api(\/|$|\?)/.test(url || "");
                if (!url || (!url.includes("/api/") && !isArApi)) return origFetch(input, init);
                const { path, sp } = parseFetch(url);
                if (path.includes("/ar-api/summary") || path.endsWith("/api/summary")) {
                    return jsonResponse(buildSummary(rows, selectedFromParams(sp)));
                }
                if (path.includes("/api/legal-text-row-images") || path.includes("/ar-api/legal-text-row-images")) {
                    const excelRow = String(sp.get("excel_row") || "").trim();
                    const images = (pack.row_images && pack.row_images[excelRow]) || [];
                    return jsonResponse({ images });
                }
                if (path.includes(arApiUrl('/send-legal-text-email'))) {
                    const target = `${OFFLINE_SERVER_BASE.replace(/\/+$/, "")}/api/send-legal-text-email`;
                    const forwardedInit = Object.assign({}, init || {}, { credentials: "omit" });
                    return origFetch(target, forwardedInit);
                }
                if (path.includes(arApiUrl('/export-legal-text-pptx'))) {
                    const target = `${OFFLINE_SERVER_BASE.replace(/\/+$/, "")}/api/export-legal-text-pptx`;
                    const forwardedInit = Object.assign({}, init || {}, { credentials: "omit" });
                    return origFetch(target, forwardedInit);
                }
                if (path.includes("/ar-api/legal-text-details") || path.includes(arApiUrl("/legal-text-details"))) {
                    let txt = (sp.get("text") || "").trim();
                    if (!txt && init?.body && typeof init.body === "string") {
                        try { txt = JSON.parse(init.body).text || ""; } catch {}
                    }
                    let rec = legalDetailsFromRows(txt);
                    if (!rec && (pack.legal_details || {})[txt]) {
                        const ld = (pack.legal_details || {})[txt];
                        const fields = ld.fields || [];
                        const emf = fields.find((f) => String(f.label || "").toLowerCase().includes("email"));
                        rec = {
                            legal_text: txt,
                            excel_row: ld.excel_row || 0,
                            picked_row_index: 0,
                            recipient_email: (emf && emf.value) || "",
                            fields,
                            images: ld.images || []
                        };
                    }
                    return rec ? jsonResponse(rec) : jsonResponse({ error: "Not found" }, 404);
                }
                if (path.includes("/api/audit-plan-panel") || path.includes("/ar-api/audit-plan-panel")) {
                    const selected = selectedFromParams(sp);
                    const filtered = applyFilters(rows, selected, null);
                    const columns = (pack.audit_columns || []).map((col) => {
                        const counts = {};
                        let nonNull = 0;
                        filtered.forEach((r) => {
                            const v = rowValue(r, col);
                            counts[v] = (counts[v] || 0) + 1;
                            if (v !== BLANK) nonNull += 1;
                        });
                        const ordered = Object.entries(counts).sort((a, b) => b[1] - a[1]);
                        return { name: col, entries: ordered.slice(0, 80).map(([label, count]) => ({ label, count })), truncated: ordered.length > 80, distinct: ordered.length, non_null: nonNull };
                    });
                    return jsonResponse({ total_rows: filtered.length, columns });
                }
                if (path.includes("/api/aging-summary") || path.includes("/ar-api/aging-summary")) {
                    const ref = (sp.get("reference") || "").trim();
                    const dateSource = ((sp.get("aging_date_source") || "target") + "").toLowerCase();
                    if (!ref) return jsonResponse({ error: "Missing reference date" }, 400);
                    const out = computeAging(rows, selectedFromParams(sp), ref, dateSource === "modified" ? "modified" : "target");
                    if (out.error) return jsonResponse({ error: out.error }, 400);
                    return jsonResponse(out);
                }
                return origFetch(input, init);
            };
        })();


        const state = {
            control_category: [],
            residual: [],
            status: [],
            year: [],
            department: [],
            legislator: [],
            compliance_status: [],
            system_name: [],
            authority: [],
            regulation: [],
            legal_text: [],
            subsidiary_company: [],
            holding_company: []
        };
        let activeFieldKey = "";

        function buildFilterQueryString(st) {
            const qs = new URLSearchParams();
            Object.entries(st).forEach(([key, vals]) => {
                if (!Array.isArray(vals)) {
                    return;
                }
                vals.forEach((v) => {
                    if (v !== "" && v != null) {
                        qs.append(key, v);
                    }
                });
            });
            return qs;
        }

        const BRAND_LOGO_CODES = new Set(["nat", "aum", "saco", "autostar", "btc"]);

        function resolveMainBrandLogoCode() {
            const pack = getSnapshotPack();
            if (!pack || pack.default_brand_code == null || pack.default_brand_code === "") {
                return null;
            }
            const code = String(pack.default_brand_code).trim().toLowerCase();
            return code || null;
        }

        function normalizeBrandLogoKey(raw) {
            const code = String(raw || "").trim();
            if (!code) {
                return "";
            }
            const lower = code.toLowerCase();
            return BRAND_LOGO_CODES.has(lower) ? lower : lower;
        }

        function lookupBrandLogoUri(logos, code) {
            if (!logos || !code) {
                return null;
            }
            const key = String(code).trim();
            return logos[key] || logos[key.toLowerCase()] || logos[key.toUpperCase()] || null;
        }

        function resolveSelectedSingleBrandCode() {
            const stateKey = companyBrandStateKey();
            const values = state[stateKey];
            if (!Array.isArray(values) || values.length !== 1) {
                return null;
            }
            const normalized = normalizeBrandLogoKey(values[0]);
            return normalized || null;
        }

        function resolveActiveBrandLogoCode() {
            return resolveSelectedSingleBrandCode() || resolveMainBrandLogoCode();
        }

        function hasVisibleBrandLogo(img) {
            const src = img.getAttribute("src") || "";
            return Boolean(src) && !img.hidden;
        }

        function clearBrandLogo() {
            const img = document.getElementById("headerLogo");
            if (!img) {
                return;
            }
            if (brandLogoObjectUrl) {
                URL.revokeObjectURL(brandLogoObjectUrl);
                brandLogoObjectUrl = null;
            }
            img.hidden = true;
            img.removeAttribute("src");
        }

        let brandLogoObjectUrl = null;
        let lastBrandLogoCode = null;

        function getSnapshotPack() {
            const packEl = document.getElementById("snapshot-pack");
            if (!packEl) {
                return null;
            }
            try {
                return JSON.parse(packEl.textContent || "{}");
            } catch {
                return null;
            }
        }

        function resolveSnapshotBrandLogoDataUrl() {
            const pack = getSnapshotPack();
            if (!pack || !pack.brand_logos) {
                return null;
            }
            const activeCode = resolveActiveBrandLogoCode();
            const mainCode = resolveMainBrandLogoCode();
            if (!activeCode) {
                return null;
            }
            return (
                lookupBrandLogoUri(pack.brand_logos, activeCode) ||
                (activeCode !== mainCode ? lookupBrandLogoUri(pack.brand_logos, mainCode) : null)
            );
        }

        async function updateBrandLogo() {
            const img = document.getElementById("headerLogo");
            if (!img) {
                return;
            }
            const activeCode = resolveActiveBrandLogoCode();
            const mainCode = resolveMainBrandLogoCode();
            if (!activeCode && !mainCode) {
                if (!hasVisibleBrandLogo(img)) {
                    clearBrandLogo();
                }
                lastBrandLogoCode = null;
                return;
            }
            const code = activeCode || mainCode;
            const embeddedLogo = resolveSnapshotBrandLogoDataUrl();
            if (embeddedLogo) {
                if (brandLogoObjectUrl) {
                    URL.revokeObjectURL(brandLogoObjectUrl);
                    brandLogoObjectUrl = null;
                }
                img.src = embeddedLogo;
                img.hidden = false;
                lastBrandLogoCode = code;
                return;
            }
            if (lastBrandLogoCode === code && hasVisibleBrandLogo(img)) {
                return;
            }
            const codesToTry = code === mainCode || !mainCode ? [code] : [code, mainCode];
            for (const tryCode of codesToTry) {
                if (brandLogoObjectUrl) {
                    URL.revokeObjectURL(brandLogoObjectUrl);
                    brandLogoObjectUrl = null;
                }
                const url = `${arApiUrl('/brand-logo')}?code=${encodeURIComponent(tryCode)}`;
                try {
                    const response = await fetch(url, { credentials: "same-origin" });
                    if (!response.ok || response.status === 204) {
                        continue;
                    }
                    const blob = await response.blob();
                    if (!blob.size) {
                        continue;
                    }
                    brandLogoObjectUrl = URL.createObjectURL(blob);
                    img.src = brandLogoObjectUrl;
                    img.hidden = false;
                    lastBrandLogoCode = tryCode;
                    return;
                } catch {
                    continue;
                }
            }
        }

        function toggleFilterValue(arr, value) {
            const i = arr.indexOf(value);
            if (i >= 0) {
                arr.splice(i, 1);
            } else {
                arr.push(value);
            }
        }

        const groupMeta = {
            control_category: {
                apiKey: "فئة الضوابط الرقابية",
                elementId: "row-control-category",
                colors: ["#2c9a59", "#25774a", "#38b76b", "#50c878", "#7ad39d", "#a0dfb8", "#c6ecd0"]
            },
            residual: {
                apiKey: "تصنيف المخاطر المتبقية",
                elementId: "row-residual",
                colors: ["#16a34a", "#eab308", "#dc2626", "#b91c1c", "#15803d", "#64748b"]
            },
            status: {
                apiKey: "الحالة",
                elementId: "row-status",
                colors: ["#0a8f2c", "#1fa741", "#6fb54e", "#fbbf24", "#f97316", "#dc2626", "#9ca3af"]
            },
            year: {
                apiKey: "السنة",
                elementId: "row-year",
                colors: ["#1e3a8a", "#2748a2", "#3359bb", "#436fd0", "#5e88d9", "#7ea4e2", "#a0bfe9", "#c5d9f3"]
            },
        };
        const SUBSIDIARY_API_KEY = "الشركة التابعة";
        const HOLDING_API_KEY = "الشركة القابضة";
        const SUBSIDIARY_BRAND_ORDER = ["nat", "aum", "saco", "autostar", "btc"];
        let companyBrandMode = "subsidiary";
        let subsidiaryListBound = false;

        function companyBrandApiKey() {
            return companyBrandMode === "holding" ? HOLDING_API_KEY : SUBSIDIARY_API_KEY;
        }

        function companyBrandStateKey() {
            return companyBrandMode === "holding" ? "holding_company" : "subsidiary_company";
        }

        function resolveCompanyBrandMode(flags) {
            if (flags && flags.subsidiary) {
                return "subsidiary";
            }
            if (flags && flags.holding) {
                return "holding";
            }
            return "";
        }
        const fieldMeta = {
            department: { apiKey: "الإدارة المسؤولة", label: "الإدارة" },
            legislator: { apiKey: "المشرع", label: "المشرع" },
            system_name: { apiKey: "اسم النظام", label: "النظام" },
            regulation: { apiKey: "اللائحة", label: "اللائحة" },
            authority: { apiKey: "الهيئة التابعة", label: "الهيئة التابعة" }
        };
        const standaloneSelectMeta = {
            legal_text: { apiKey: "النص النظامي", elementId: "legalTextFilter" }
        };
        const charts = {};
        let summaryFetchController = null;
        let legalDetailsController = null;
        const chartToStateKey = {
            statusChart: "status",
            yearChart: "year",
            residualChart: "residual",
            controlCategoryChart: "control_category"
        };

        function toEnglishNumber(value) {
            return Number(value).toLocaleString("en-US");
        }

        function escapeHtml(value) {
            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function colorFor(groupName, index) {
            const palette = groupMeta[groupName].colors;
            return palette[index % palette.length];
        }

        function stripArabicTashkeel(s) {
            return String(s || "")
                .normalize("NFKC")
                .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g, "");
        }

        function statusColorByLabel(label, fallbackColor) {
            const text = stripArabicTashkeel(String(label || "").trim());
            if (text.includes("مقفل")) {
                return "#16a34a";
            }
            if (text.includes("مفتوح") && text.includes("تجاوز تاريخ التصحيح")) {
                return "#dc2626";
            }
            if (text.includes("مفتوح") && text.includes("ضمن تاريخ التصحيح")) {
                return "#fbbf24";
            }
            return fallbackColor;
        }

        const BLANK_TOKEN = "(blank)";

        function complianceRank(label) {
            const t = String(label || "").trim();
            if (t === BLANK_TOKEN) {
                return 9000;
            }
            const n = t.normalize("NFKC");
            if (n.includes("متدني") && /انخفاض|انخفاظ|انخفاق|انخغاض/.test(n)) {
                return 45;
            }
            if ((n.includes("جدا") || n.includes("جداً") || n.includes("جدآ")) && (n.includes("مرتفع") || n.includes("مرفع"))) {
                return 12;
            }
            if (n.includes("مرتفع") || n.includes("مرفع")) {
                return 22;
            }
            if (n.includes("متوسط")) {
                return 32;
            }
            if (n.includes("منخفض") && !n.includes("متدني")) {
                return 52;
            }
            return 200 + [...n].reduce((s, ch) => s + ch.charCodeAt(0), 0) % 500;
        }

        function sortComplianceItems(items) {
            return [...items].sort(
                (a, b) =>
                    complianceRank(a.key) - complianceRank(b.key) ||
                    String(a.key).localeCompare(String(b.key), "ar")
            );
        }

        /** ترتيب شريط «تصنيف المخاطر المتبقية» في RTL: أول عنصر = أقصى اليمين — منخفض (أخضر) ثم متوسط ثم مرتفع ثم مرتفع جداً */
        function residualRiskSortRank(label) {
            const raw = String(label ?? "").trim();
            if (raw === BLANK_TOKEN) {
                return 8000;
            }
            const t = stripArabicTashkeel(raw).normalize("NFKC").replace(/\s+/g, " ");
            if (t.includes("متدني") && /انخفاض|انخفاظ|انخغاض|انخفاق/.test(t)) {
                return 5;
            }
            if (t.includes("منخفض") && !t.includes("متدني")) {
                return 15;
            }
            if (t.includes("متوسط")) {
                return 25;
            }
            if ((t.includes("جدا") || t.includes("جداً") || t.includes("جدآ")) && (t.includes("مرتفع") || t.includes("مرفع") || t.includes("مرتفغ") || t.includes("مرنفع"))) {
                return 45;
            }
            if (t.includes("مرتفع") || t.includes("مرفع") || t.includes("مرتفغ") || t.includes("مرنفع")) {
                return 35;
            }
            return 200 + [...t].reduce((s, ch) => s + ch.charCodeAt(0), 0) % 500;
        }

        function sortResidualItems(items) {
            return [...items].sort(
                (a, b) =>
                    residualRiskSortRank(a.key) - residualRiskSortRank(b.key) ||
                    String(a.key).localeCompare(String(b.key), "ar")
            );
        }

        /** ألوان ثابتة: منخفض أخضر، متوسط أصفر، مرتفع أحمر، مرتفع جداً أحمر داكن */
        function residualRiskSegmentStyle(label) {
            const raw = String(label ?? "").trim();
            if (raw === BLANK_TOKEN) {
                return { background: "#64748b", color: "#ffffff" };
            }
            const t = stripArabicTashkeel(raw).normalize("NFKC").replace(/\s+/g, " ");
            if (t.includes("متدني") && /انخفاض|انخفاظ|انخغاض|انخفاق/.test(t)) {
                return { background: "#15803d", color: "#ffffff" };
            }
            if ((t.includes("جدا") || t.includes("جداً") || t.includes("جدآ")) && (t.includes("مرتفع") || t.includes("مرفع") || t.includes("مرتفغ") || t.includes("مرنفع"))) {
                return { background: "#b91c1c", color: "#ffffff" };
            }
            if (t.includes("مرتفع") || t.includes("مرفع") || t.includes("مرتفغ") || t.includes("مرنفع")) {
                return { background: "#dc2626", color: "#ffffff" };
            }
            if (t.includes("متوسط")) {
                return { background: "#eab308", color: "#1f2937" };
            }
            if (t.includes("منخفض") && !t.includes("متدني")) {
                return { background: "#16a34a", color: "#ffffff" };
            }
            return { background: "#64748b", color: "#ffffff" };
        }

        function complianceSegmentStyle(label, isTotal) {
            if (isTotal) {
                return { background: "#061534", color: "#ffffff" };
            }
            const t = stripArabicTashkeel(String(label || "").trim()).normalize("NFKC");
            const compact = t.replace(/\s/g, "");
            if (t === BLANK_TOKEN) {
                return { background: "#64748b", color: "#ffffff" };
            }
            if (compact.includes("غيرملتزم") || /غير\s+ملتزم/.test(t)) {
                return { background: "#dc2626", color: "#ffffff" };
            }
            if (t.includes("متدني") && /انخفاض|انخفاظ|انخفاق|انخغاض/.test(t)) {
                return { background: "#16a34a", color: "#ffffff" };
            }
            if ((t.includes("جدا") || t.includes("جداً") || t.includes("جدآ")) && (t.includes("مرتفع") || t.includes("مرفع"))) {
                return { background: "#b91c1c", color: "#ffffff" };
            }
            if (t.includes("مرتفع") || t.includes("مرفع")) {
                return { background: "#ea580c", color: "#ffffff" };
            }
            if (t.includes("متوسط")) {
                return { background: "#ca8a04", color: "#ffffff" };
            }
            if (t.includes("منخفض") && !t.includes("متدني")) {
                return { background: "#16a34a", color: "#ffffff" };
            }
            if (t.includes("ملتزم جزئي")) {
                return { background: "#ca8a04", color: "#ffffff" };
            }
            if (t === "جزئي" || t.includes("جزئي")) {
                return { background: "#ea580c", color: "#ffffff" };
            }
            if (t.includes("ملتزم")) {
                return { background: "#16a34a", color: "#ffffff" };
            }
            return { background: "#64748b", color: "#ffffff" };
        }

        function updateComplianceLineChart(sortedItems) {
            const canvas = document.getElementById("complianceStatusLineChart");
            if (!canvas) {
                return;
            }
            if (charts.complianceStatusLine) {
                charts.complianceStatusLine.destroy();
                delete charts.complianceStatusLine;
            }
            if (!hasChartLib || !sortedItems.length) {
                return;
            }
            const labels = sortedItems.map((x) => x.label);
            const values = sortedItems.map((x) => Number(x.count || 0));
            const keys = sortedItems.map((x) => x.key);
            const barColors = sortedItems.map((x) => complianceSegmentStyle(x.label, false).background);
            charts.complianceStatusLine = new Chart(canvas, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            data: values,
                            backgroundColor: barColors,
                            borderColor: "#ffffff",
                            borderWidth: 1,
                            borderRadius: 6,
                            maxBarThickness: 38
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: { top: 22, bottom: 4 }
                    },
                    plugins: {
                        legend: { display: false },
                        datalabels: {
                            display: (ctx) => Boolean(labels[ctx.dataIndex]),
                            anchor: "end",
                            align: "top",
                            offset: 6,
                            color: "#374151",
                            font: { size: 10, weight: "600" },
                            clip: false,
                            formatter: (_value, ctx) => labels[ctx.dataIndex] || ""
                        }
                    },
                    scales: {
                        x: {
                            display: true,
                            ticks: { display: false },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                color: "#6b7280",
                                font: { size: 10, weight: "600" },
                                precision: 0
                            },
                            grid: {
                                color: "rgba(148, 163, 184, 0.25)"
                            }
                        }
                    },
                    onClick: (_evt, elements) => {
                        if (!elements.length) {
                            return;
                        }
                        const i = elements[0].index;
                        toggleFilterValue(state.compliance_status, keys[i]);
                        fetchSummary();
                    }
                }
            });
        }

        function renderComplianceStatusRow(data) {
            const apiKey = "حالة الالتزام";
            const wrap = document.getElementById("complianceSegBar");
            if (!wrap) {
                return;
            }
            const raw = data.groups[apiKey] || [];
            const sorted = sortComplianceItems(raw);
            wrap.innerHTML = "";

            sorted.forEach((item) => {
                const seg = document.createElement("button");
                seg.type = "button";
                seg.className = "tile";
                if (state.compliance_status.includes(item.key)) {
                    seg.classList.add("selected");
                }
                const vis = complianceSegmentStyle(item.label, false);
                seg.style.background = vis.background;
                seg.style.color = vis.color;
                seg.innerHTML = `<div class="tile-number">${toEnglishNumber(item.count)}</div><div class="tile-label">${escapeHtml(
                    item.label
                )}</div>`;
                seg.title = `فلترة: ${item.label}`;
                seg.addEventListener("click", () => {
                    toggleFilterValue(state.compliance_status, item.key);
                    fetchSummary();
                });
                wrap.appendChild(seg);
            });

            const totalSeg = document.createElement("button");
            totalSeg.type = "button";
            totalSeg.className = "tile tile-total";
            totalSeg.title = "مسح فلتر حالة الالتزام";
            totalSeg.innerHTML = `<div class="tile-number">${toEnglishNumber(data.total || 0)}</div><div class="tile-label">Total</div>`;
            totalSeg.addEventListener("click", () => {
                state.compliance_status.length = 0;
                fetchSummary();
            });
            wrap.appendChild(totalSeg);

            updateComplianceLineChart(sorted);
        }

        function buildTile(groupName, item, index, totalCount) {
            const tile = document.createElement("button");
            tile.type = "button";
            tile.className = "tile";
            let baseColor = colorFor(groupName, index);
            if (groupName === "residual") {
                const vis = residualRiskSegmentStyle(item.label);
                tile.style.background = vis.background;
                tile.style.color = vis.color;
            } else {
                tile.style.background = groupName === "status" ? statusColorByLabel(item.label, baseColor) : baseColor;
            }
            tile.dataset.value = item.key;
            tile.dataset.group = groupName;

            if (state[groupName].includes(item.key)) {
                tile.classList.add("selected");
            }

            const value = document.createElement("div");
            value.className = "tile-number";
            value.textContent = toEnglishNumber(item.count);

            const label = document.createElement("div");
            label.className = "tile-label";
            label.textContent = item.label;

            tile.appendChild(value);
            tile.appendChild(label);
            tile.title = `فلترة: ${item.label}`;
            tile.addEventListener("click", () => {
                toggleFilterValue(state[groupName], item.key);
                fetchSummary();
            });

            const track = document.getElementById(groupMeta[groupName].elementId);
            track.appendChild(tile);

            if (index === totalCount - 1) {
                const totalTile = document.createElement("button");
                totalTile.type = "button";
                totalTile.className = "tile tile-total";

                const totalValue = document.createElement("div");
                totalValue.className = "tile-number";
                totalValue.textContent = toEnglishNumber(window.currentTotal || 0);

                const totalLabel = document.createElement("div");
                totalLabel.className = "tile-label";
                totalLabel.textContent = "Total";

                totalTile.appendChild(totalValue);
                totalTile.appendChild(totalLabel);
                track.appendChild(totalTile);
            }
        }

        function pruneStaleFilters(data) {
            const groups = data.groups || {};
            const prune = (stateKey, apiKey) => {
                if (!Array.isArray(state[stateKey])) {
                    return;
                }
                if (!(apiKey in groups)) {
                    state[stateKey].length = 0;
                    return;
                }
                const valid = new Set((groups[apiKey] || []).map((item) => item.key));
                state[stateKey] = state[stateKey].filter((v) => valid.has(v));
            };
            Object.entries(groupMeta).forEach(([stateKey, meta]) => prune(stateKey, meta.apiKey));
            Object.entries(fieldMeta).forEach(([stateKey, meta]) => prune(stateKey, meta.apiKey));
            prune("subsidiary_company", SUBSIDIARY_API_KEY);
            prune("holding_company", HOLDING_API_KEY);
            prune("compliance_status", "حالة الالتزام");
            prune("legal_text", "النص النظامي");
        }

        function subsidiaryDisplayLabel(key) {
            const code = String(key || "").trim();
            if (BRAND_LOGO_CODES.has(code)) {
                return code.toUpperCase();
            }
            return code;
        }

        function sortSubsidiaryItems(items) {
            const rank = (key) => {
                const k = String(key).trim().toLowerCase();
                const idx = SUBSIDIARY_BRAND_ORDER.indexOf(k);
                return idx >= 0 ? idx : 100 + [...String(key)].reduce((s, ch) => s + ch.charCodeAt(0), 0);
            };
            return [...items]
                .filter((item) => item.key !== BLANK_TOKEN)
                .sort((a, b) => rank(a.key) - rank(b.key) || String(a.key).localeCompare(String(b.key), "ar"));
        }

        function syncSubsidiaryListSelection() {
            const list = document.getElementById("subsidiaryList");
            if (!list) {
                return;
            }
            const selected = new Set(state[companyBrandStateKey()]);
            list.querySelectorAll(".subsidiary-list-item").forEach((btn) => {
                const on = selected.has(btn.dataset.value);
                btn.classList.toggle("selected", on);
                btn.setAttribute("aria-selected", on ? "true" : "false");
            });
        }

        function readSubsidiaryListSelection() {
            const list = document.getElementById("subsidiaryList");
            if (!list) {
                return;
            }
            state[companyBrandStateKey()] = Array.from(list.querySelectorAll(".subsidiary-list-item.selected")).map(
                (btn) => btn.dataset.value
            );
        }

        function updateSubsidiaryStatusPill() {
            const pill = document.getElementById("subsidiaryStatusPill");
            if (!pill) {
                return;
            }
            const selected = state[companyBrandStateKey()];
            const allLabel =
                companyBrandMode === "holding"
                    ? "جميع الشركات القابضة (الفلتر اختياري — غير مفعّل)"
                    : "جميع الشركات التابعة (الفلتر اختياري — غير مفعّل)";
            if (!selected.length) {
                pill.textContent = allLabel;
                pill.classList.remove("active");
                return;
            }
            const labels = selected.map(subsidiaryDisplayLabel).join(", ");
            pill.textContent = `مفعّل: ${labels}`;
            pill.classList.add("active");
        }

        function applySubsidiaryFilterFromList() {
            readSubsidiaryListSelection();
            updateSubsidiaryStatusPill();
            fetchSummary();
        }

        function bindSubsidiaryListOnce() {
            if (subsidiaryListBound) {
                return;
            }
            const list = document.getElementById("subsidiaryList");
            const selectAllBtn = document.getElementById("subsidiarySelectAllBtn");
            const deselectAllBtn = document.getElementById("subsidiaryDeselectAllBtn");
            const changeBtn = document.getElementById("subsidiaryChangeBtn");
            if (!list) {
                return;
            }
            subsidiaryListBound = true;
            list.addEventListener("click", (event) => {
                const item = event.target.closest(".subsidiary-list-item");
                if (!item) {
                    return;
                }
                item.classList.toggle("selected");
                applySubsidiaryFilterFromList();
            });
            if (selectAllBtn) {
                selectAllBtn.addEventListener("click", () => {
                    list.querySelectorAll(".subsidiary-list-item").forEach((btn) => {
                        btn.classList.add("selected");
                    });
                    applySubsidiaryFilterFromList();
                });
            }
            if (deselectAllBtn) {
                deselectAllBtn.addEventListener("click", () => {
                    list.querySelectorAll(".subsidiary-list-item").forEach((btn) => {
                        btn.classList.remove("selected");
                    });
                    applySubsidiaryFilterFromList();
                });
            }
            if (changeBtn) {
                changeBtn.addEventListener("click", () => {
                    list.focus();
                });
            }
        }

        function renderSubsidiaryCompanyPanel(data) {
            const section = document.getElementById("subsidiary-company-section");
            const pageTop = section && section.closest(".page-top");
            const list = document.getElementById("subsidiaryList");
            const titleEl = document.getElementById("companyBrandTitle");
            const subtitleEl = document.getElementById("companyBrandSubtitle");
            if (!section || !list) {
                return;
            }
            const flags = data.company_columns || {};
            companyBrandMode = resolveCompanyBrandMode(flags);
            const visible = Boolean(companyBrandMode);
            section.hidden = !visible;
            if (pageTop) {
                pageTop.hidden = !visible;
            }
            if (!visible) {
                return;
            }
            if (titleEl) {
                titleEl.textContent = companyBrandMode === "holding" ? "الشركة القابضة" : "الشركة التابعة";
            }
            if (subtitleEl) {
                subtitleEl.textContent = companyBrandMode === "holding" ? "HOLDING" : "SUBCOMPANY";
            }
            list.setAttribute("aria-label", titleEl ? titleEl.textContent : "شركة");
            bindSubsidiaryListOnce();
            const apiKey = companyBrandApiKey();
            const items = sortSubsidiaryItems((data.groups && data.groups[apiKey]) || []);
            const previous = new Set(state[companyBrandStateKey()]);
            list.innerHTML = "";
            if (!items.length) {
                const emptyMsg =
                    companyBrandMode === "holding"
                        ? "لا توجد شركات قابضة في البيانات الحالية"
                        : "لا توجد شركات تابعة في البيانات الحالية";
                list.innerHTML = `<div class="subsidiary-list-empty">${emptyMsg}</div>`;
            } else {
                items.forEach((item) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = `subsidiary-list-item${previous.has(item.key) ? " selected" : ""}`;
                    btn.dataset.value = item.key;
                    btn.textContent = subsidiaryDisplayLabel(item.key);
                    btn.setAttribute("role", "option");
                    btn.setAttribute("aria-selected", previous.has(item.key) ? "true" : "false");
                    list.appendChild(btn);
                });
            }
            syncSubsidiaryListSelection();
            updateSubsidiaryStatusPill();
        }

        function renderFilterGroups(data) {
            Object.keys(groupMeta).forEach((groupName) => {
                const meta = groupMeta[groupName];
                renderGroup(groupName, (data.groups && data.groups[meta.apiKey]) || []);
            });
        }

        function renderGroup(groupName, items) {
            const track = document.getElementById(groupMeta[groupName].elementId);
            if (!track) {
                return;
            }
            track.innerHTML = "";
            const list = groupName === "residual" ? sortResidualItems(items) : items;
            list.forEach((item, index) => buildTile(groupName, item, index, list.length));
        }

        function renderFieldBoxes(data) {
            const wrap = document.getElementById("fieldBoxes");
            wrap.innerHTML = "";

            Object.keys(fieldMeta).forEach((stateKey) => {
                const apiKey = fieldMeta[stateKey].apiKey;
                if (!(apiKey in data.groups)) {
                    return;
                }
                const groupItems = data.groups[apiKey] || [];
                const total = groupItems.length;

                const box = document.createElement("button");
                box.type = "button";
                box.className = `field-box${activeFieldKey === stateKey ? " active" : ""}`;
                box.innerHTML = `
                    <div class="field-box-number">${toEnglishNumber(total)}</div>
                    <div class="field-box-label">${fieldMeta[stateKey].label}</div>
                `;
                box.addEventListener("click", () => {
                    activeFieldKey = activeFieldKey === stateKey ? "" : stateKey;
                    renderFieldOptions(data);
                    renderFieldBoxes(data);
                });
                wrap.appendChild(box);
            });
        }

        function renderFieldOptions(data) {
            const panel = document.getElementById("fieldOptions");
            if (!activeFieldKey) {
                panel.style.display = "none";
                panel.innerHTML = "";
                return;
            }

            const meta = fieldMeta[activeFieldKey];
            const items = data.groups[meta.apiKey] || [];
            panel.style.display = "block";
            panel.innerHTML = `
                <h3 class="field-options-title">اختيار من: ${meta.label}</h3>
                <ul id="optionList" class="option-list"></ul>
            `;

            const list = panel.querySelector("#optionList");
            const allItem = document.createElement("li");
            allItem.className = "option-item";
            const allBtn = document.createElement("button");
            allBtn.type = "button";
            allBtn.className = `option-btn${state[activeFieldKey].length === 0 ? " selected" : ""}`;
            allBtn.innerHTML = `<span>الكل</span>`;
            allBtn.addEventListener("click", () => {
                state[activeFieldKey].length = 0;
                fetchSummary();
            });
            allItem.appendChild(allBtn);
            list.appendChild(allItem);

            items.forEach((item) => {
                const li = document.createElement("li");
                li.className = "option-item";
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = `option-btn${state[activeFieldKey].includes(item.key) ? " selected" : ""}`;
                btn.innerHTML = `
                    <span>${item.label}</span>
                    <span class="option-count">${toEnglishNumber(item.count)}</span>
                `;
                btn.addEventListener("click", () => {
                    toggleFilterValue(state[activeFieldKey], item.key);
                    fetchSummary();
                });
                li.appendChild(btn);
                list.appendChild(li);
            });
        }

        function createInsideChartLabelsPlugin(total) {
            return {
                id: "insideChartLabels",
                afterDatasetsDraw(chart) {
                    const chartType = chart.config.type;
                    const dataset = chart.data.datasets[0];
                    const meta = chart.getDatasetMeta(0);
                    if (!dataset || !meta || !meta.data.length) {
                        return;
                    }
                    const { ctx } = chart;

                    if (chartType === "doughnut" || chartType === "pie") {
                        meta.data.forEach((arc, index) => {
                            const value = Number(dataset.data[index] || 0);
                            if (value <= 0) {
                                return;
                            }
                            const pct = total ? ((value / total) * 100).toFixed(1) : "0.0";
                            const props = arc.getProps(
                                ["x", "y", "startAngle", "endAngle", "innerRadius", "outerRadius"],
                                true
                            );
                            const angle = (props.startAngle + props.endAngle) / 2;
                            const radius = (props.innerRadius + props.outerRadius) / 2;
                            const labelX = props.x + Math.cos(angle) * radius;
                            const labelY = props.y + Math.sin(angle) * radius;
                            ctx.save();
                            ctx.fillStyle = "#0b1d38";
                            ctx.font = "700 11px sans-serif";
                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillText(`${pct}%`, labelX, labelY);
                            ctx.restore();
                        });
                        return;
                    }

                    if (chartType === "bar") {
                        meta.data.forEach((bar, index) => {
                            const value = Number(dataset.data[index] || 0);
                            if (value <= 0) {
                                return;
                            }
                            const pct = total ? ((value / total) * 100).toFixed(1) : "0.0";
                            const props = bar.getProps(["x", "y", "base"], true);
                            const top = Math.min(props.y, props.base);
                            const bottom = Math.max(props.y, props.base);
                            const centerX = props.x;
                            const centerY = top + (bottom - top) / 2;
                            ctx.save();
                            ctx.fillStyle = "#0b1d38";
                            ctx.font = "700 11px sans-serif";
                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillText(`${pct}%`, centerX, centerY);
                            ctx.restore();
                        });
                    }
                }
            };
        }

        function buildChartConfig(type, labels, values, colors, stateKey) {
            const total = values.reduce((sum, v) => sum + Number(v || 0), 0);
            const isArc = type === "doughnut" || type === "pie";
            const isBar = type === "bar";
            const useInsideLabels = isArc || isBar;
            const config = {
                type,
                data: {
                    labels,
                    datasets: [{ data: values, backgroundColor: colors, borderWidth: 1 }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: (_event, elements) => {
                        if (!elements.length) {
                            return;
                        }
                        const idx = elements[0].index;
                        const clickedLabel = labels[idx];
                        toggleFilterValue(state[stateKey], clickedLabel);
                        fetchSummary();
                    },
                    plugins: {
                        legend: isBar
                            ? { display: false }
                            : {
                                  position: "bottom",
                                  labels: { boxWidth: 10, font: { size: 11 } }
                              },
                        datalabels: useInsideLabels
                            ? { display: false }
                            : {
                                  color: "#0b1d38",
                                  font: { weight: "700", size: 11 },
                                  formatter: (value) => {
                                      if (!total) {
                                          return "0%";
                                      }
                                      const pct = (Number(value) / total) * 100;
                                      return `${pct.toFixed(1)}%`;
                                  },
                                  display: (ctx) => Number(ctx.dataset.data[ctx.dataIndex] || 0) > 0
                              }
                    }
                }
            };
            if (useInsideLabels) {
                config.plugins = [createInsideChartLabelsPlugin(total)];
            }
            return config;
        }

        function renderOrUpdateChart(id, config) {
            if (!hasChartLib) {
                return;
            }
            const canvas = document.getElementById(id);
            if (!canvas) {
                return;
            }
            if (charts[id]) {
                charts[id].destroy();
                delete charts[id];
            }
            charts[id] = new Chart(canvas, config);
        }

        function updateTopCharts(data) {
            const statusItems = data.groups[groupMeta.status.apiKey] || [];
            const residualItems = sortResidualItems(data.groups[groupMeta.residual.apiKey] || []);
            const controlItems = data.groups[groupMeta.control_category.apiKey] || [];
            const yearItems = data.groups[groupMeta.year.apiKey] || [];

            renderOrUpdateChart(
                "statusChart",
                buildChartConfig(
                    "doughnut",
                    statusItems.map((x) => x.label),
                    statusItems.map((x) => x.count),
                    statusItems.map((x, i) => statusColorByLabel(x.label, colorFor("status", i))),
                    chartToStateKey.statusChart
                )
            );

            renderOrUpdateChart(
                "yearChart",
                buildChartConfig(
                    "pie",
                    yearItems.map((x) => x.label),
                    yearItems.map((x) => x.count),
                    yearItems.map((_, i) => colorFor("year", i)),
                    chartToStateKey.yearChart
                )
            );

            renderOrUpdateChart(
                "residualChart",
                buildChartConfig(
                    "doughnut",
                    residualItems.map((x) => x.label),
                    residualItems.map((x) => x.count),
                    residualItems.map((x) => residualRiskSegmentStyle(x.label).background),
                    chartToStateKey.residualChart
                )
            );

            renderOrUpdateChart(
                "controlCategoryChart",
                buildChartConfig(
                    "bar",
                    controlItems.map((x) => x.label),
                    controlItems.map((x) => x.count),
                    controlItems.map((_, i) => colorFor("control_category", i)),
                    chartToStateKey.controlCategoryChart
                )
            );
        }

        const compliancePlanModal = document.getElementById("compliancePlanModal");
        const compliancePlanEditor = document.getElementById("compliancePlanEditor");
        const compliancePlanFileInput = document.getElementById("compliancePlanFileInput");
        const compliancePlanSheetSelect = document.getElementById("compliancePlanSheetSelect");
        const compliancePlanColorInput = document.getElementById("compliancePlanColor");
        let complianceWorkbook = null;
        const compliancePlanState = {
            sheetName: "",
            headers: [],
            rows: [],
            styles: {},
            selectedCell: null
        };

        function restoreCompliancePlanState() {
            try {
                const embedded = document.getElementById("compliance-plan-seed");
                if (!embedded || !embedded.textContent) {
                    return;
                }
                const parsed = JSON.parse(embedded.textContent);
                if (!parsed || typeof parsed !== "object") return;
                compliancePlanState.sheetName = String(parsed.sheetName || "");
                compliancePlanState.headers = Array.isArray(parsed.headers) ? parsed.headers.map((x) => String(x ?? "")) : [];
                compliancePlanState.rows = Array.isArray(parsed.rows)
                    ? parsed.rows.map((r) => (Array.isArray(r) ? r.map((x) => String(x ?? "")) : []))
                    : [];
                compliancePlanState.styles = parsed.styles && typeof parsed.styles === "object" ? parsed.styles : {};
                compliancePlanState.selectedCell = parsed.selectedCell ? String(parsed.selectedCell) : null;
                compliancePlanSheetSelect.innerHTML = "";
                if (compliancePlanState.sheetName) {
                    const opt = document.createElement("option");
                    opt.value = compliancePlanState.sheetName;
                    opt.textContent = `${compliancePlanState.sheetName} (محفوظ)`;
                    opt.selected = true;
                    compliancePlanSheetSelect.appendChild(opt);
                }
            } catch (_e) {}
        }

        function closeCompliancePlanModal() {
            compliancePlanModal.style.display = "none";
            document.getElementById("compliancePlanToggle").checked = false;
        }

        function renderCompliancePlanTable() {
            if (!compliancePlanState.rows.length) {
                compliancePlanEditor.innerHTML = `<div class="empty-hint">ارفع ملف إكسل لبدء التحرير.</div>`;
                return;
            }
            const headers = compliancePlanState.headers;
            const rows = compliancePlanState.rows;
            let thead = "<tr>";
            headers.forEach((h) => {
                thead += `<th>${escapeHtml(h || "")}</th>`;
            });
            thead += "</tr>";
            let tbody = "";
            rows.forEach((row, rIdx) => {
                tbody += "<tr>";
                headers.forEach((_h, cIdx) => {
                    const key = `${rIdx},${cIdx}`;
                    const bg = compliancePlanState.styles[key] || "";
                    const active = compliancePlanState.selectedCell === key ? "outline:2px solid #1d4ed8;" : "";
                    const styleAttr = `${bg ? `background:${bg};` : ""}${active}`;
                    tbody += `<td contenteditable="true" data-r="${rIdx}" data-c="${cIdx}" style="${styleAttr}">${escapeHtml(
                        String(row[cIdx] ?? "")
                    )}</td>`;
                });
                tbody += "</tr>";
            });
            compliancePlanEditor.innerHTML = `<table class="audit-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
            const highlightSelected = () => {
                const selected = compliancePlanState.selectedCell;
                compliancePlanEditor.querySelectorAll("td[data-r][data-c]").forEach((cell) => {
                    const key = `${cell.dataset.r},${cell.dataset.c}`;
                    cell.style.outline = selected === key ? "2px solid #1d4ed8" : "";
                });
            };
            compliancePlanEditor.querySelectorAll("td").forEach((td) => {
                td.addEventListener("click", () => {
                    const r = Number(td.dataset.r);
                    const c = Number(td.dataset.c);
                    compliancePlanState.selectedCell = `${r},${c}`;
                    highlightSelected();
                });
                td.addEventListener("input", () => {
                    const r = Number(td.dataset.r);
                    const c = Number(td.dataset.c);
                    compliancePlanState.rows[r][c] = td.textContent || "";
                });
            });
            highlightSelected();
        }

        function loadComplianceSheet(sheetName) {
            if (!complianceWorkbook || !sheetName) return;
            const ws = complianceWorkbook.Sheets[sheetName];
            const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
            const headers = (aoa[0] || []).map((x) => String(x ?? "").trim());
            const rows = aoa.slice(1).map((r) => headers.map((_h, i) => String(r[i] ?? "")));
            compliancePlanState.sheetName = sheetName;
            compliancePlanState.headers = headers;
            compliancePlanState.rows = rows;
            compliancePlanState.styles = {};
            compliancePlanState.selectedCell = null;
            renderCompliancePlanTable();
        }

        compliancePlanFileInput.addEventListener("change", async () => {
            const f = compliancePlanFileInput.files && compliancePlanFileInput.files[0];
            if (!f) return;
            const buff = await f.arrayBuffer();
            complianceWorkbook = XLSX.read(buff, { type: "array" });
            compliancePlanSheetSelect.innerHTML = "";
            (complianceWorkbook.SheetNames || []).forEach((s, idx) => {
                const opt = document.createElement("option");
                opt.value = s;
                opt.textContent = s;
                if (idx === 0) opt.selected = true;
                compliancePlanSheetSelect.appendChild(opt);
            });
            loadComplianceSheet(compliancePlanSheetSelect.value);
        });

        compliancePlanSheetSelect.addEventListener("change", () => loadComplianceSheet(compliancePlanSheetSelect.value));
        document.getElementById("compliancePlanApplyColorBtn").addEventListener("click", () => {
            if (!compliancePlanState.selectedCell) return;
            compliancePlanState.styles[compliancePlanState.selectedCell] = compliancePlanColorInput.value;
            renderCompliancePlanTable();
        });
        document.getElementById("compliancePlanClearColorBtn").addEventListener("click", () => {
            if (!compliancePlanState.selectedCell) return;
            delete compliancePlanState.styles[compliancePlanState.selectedCell];
            renderCompliancePlanTable();
        });

        document.getElementById("compliancePlanSaveHtmlBtn").addEventListener("click", async () => {
            await downloadInteractiveSnapshot();
        });
        document.getElementById("compliancePlanModalClose").addEventListener("click", closeCompliancePlanModal);
        compliancePlanModal.addEventListener("click", (event) => {
            if (event.target === compliancePlanModal) closeCompliancePlanModal();
        });
        document.getElementById("compliancePlanToggle").addEventListener("change", (event) => {
            if (event.target.checked) {
                compliancePlanModal.style.display = "flex";
                renderCompliancePlanTable();
            } else {
                closeCompliancePlanModal();
            }
        });
        restoreCompliancePlanState();
        try {
            localStorage.removeItem("compliancePlanEditor.v1");
        } catch (_e) {}
        renderCompliancePlanTable();

        async function fetchSummary() {
            const clearBtn = document.getElementById("clearFiltersBtn");
            clearBtn.disabled = true;
            const qs = buildFilterQueryString(state);
            if (summaryFetchController) {
                summaryFetchController.abort();
            }
            summaryFetchController = new AbortController();
            let response;
            let data;
            try {
                response = await fetch(`${arApiUrl('/summary')}?${qs.toString()}`, {
                    signal: summaryFetchController.signal,
                    credentials: "same-origin"
                });
                data = await response.json();
            } catch (err) {
                if (err && err.name === "AbortError") {
                    return;
                }
                clearBtn.disabled = false;
                throw err;
            } finally {
                summaryFetchController = null;
            }

            if (!response.ok) {
                alert("تعذر تحميل بيانات التحليل. ارفع الملف مرة أخرى.");
                window.location.href = "/";
                return;
            }

            window.currentTotal = data.total;
            window.lastSummaryData = data;
            pruneStaleFilters(data);
            renderComplianceStatusRow(data);
            renderSubsidiaryCompanyPanel(data);
            renderFilterGroups(data);
            updateTopCharts(data);
            renderFieldBoxes(data);
            renderFieldOptions(data);
            await updateBrandLogo();
            Object.keys(standaloneSelectMeta).forEach((stateKey) => {
                renderStandaloneSelect(stateKey, data.groups[standaloneSelectMeta[stateKey].apiKey] || []);
            });
            clearBtn.disabled = false;
            if (document.getElementById("agingToggle")?.checked && isAgingModalOpen()) {
                await refreshAgingSummary();
            }
            // no-op: compliance plan editor is local (no server refresh required)
        }

        function renderStandaloneSelect(stateKey, items) {
            const meta = standaloneSelectMeta[stateKey];
            const current = state[stateKey];
            if (stateKey !== "legal_text") {
                return;
            }
            const dropdown = document.getElementById("legalTextDropdown");
            const menu = document.getElementById("legalTextDropdownMenu");
            const btn = document.getElementById("legalTextDropdownBtn");
            menu.innerHTML = "";
            const tools = document.createElement("div");
            tools.className = "legal-menu-tools";
            tools.innerHTML = `
                <input id="legalSearchInput" class="legal-search" type="text" placeholder="بحث داخل النص النظامي..." />
                <div class="legal-actions">
                    <button id="legalClearBtn" type="button" class="legal-clear-btn">مسح التحديد</button>
                    <span id="legalVisibleCount" class="legal-count"></span>
                </div>
            `;
            menu.appendChild(tools);
            const searchInput = tools.querySelector("#legalSearchInput");
            const clearBtn = tools.querySelector("#legalClearBtn");
            const visibleCount = tools.querySelector("#legalVisibleCount");
            const listContainer = document.createElement("div");
            menu.appendChild(listContainer);

            const allRow = document.createElement("label");
            allRow.className = "legal-option" + (current.length === 0 ? " selected-option" : "");
            allRow.innerHTML = `<input type="checkbox" ${current.length === 0 ? "checked" : ""} /><span>الكل</span>`;
            allRow.addEventListener("click", (event) => {
                event.preventDefault();
                state.legal_text.length = 0;
                fetchSummary();
                closeLegalDropdown();
            });
            listContainer.appendChild(allRow);

            const rows = [];
            const listFrag = document.createDocumentFragment();
            items.forEach((item) => {
                const row = document.createElement("label");
                row.className = "legal-option" + (current.includes(item.key) ? " selected-option" : "");
                row.dataset.label = String(item.label || "").toLowerCase();
                row.innerHTML = `
                    <input type="checkbox" ${current.includes(item.key) ? "checked" : ""} />
                    <span>${item.label}</span>
                    <span class="legal-option-count">(${toEnglishNumber(item.count)})</span>
                `;
                row.title = String(item.label || "");
                row.addEventListener("click", (event) => {
                    event.preventDefault();
                    // اختيار نص واحد فقط لكل نقرة: ينتقل التفاصيل فوراً بين النصوص ولا يبقى وضع «نصّان محددان» يغلق النافذة أو يربك الفلتر.
                    const keyStr = String(item.key);
                    const sole = state.legal_text.length === 1 ? String(state.legal_text[0]) : null;
                    if (sole === keyStr) {
                        state.legal_text.length = 0;
                        fetchSummary();
                        closeLegalModal();
                        return;
                    }
                    state.legal_text.length = 0;
                    state.legal_text.push(item.key);
                    fetchSummary();
                    openLegalDetails(item.key);
                });
                rows.push(row);
                listFrag.appendChild(row);
            });
            listContainer.appendChild(listFrag);

            const updateVisibleCount = () => {
                const v = rows.filter((r) => r.style.display !== "none").length;
                visibleCount.textContent = `المعروض: ${toEnglishNumber(v)} / ${toEnglishNumber(items.length)}`;
            };
            searchInput.addEventListener("input", () => {
                const q = String(searchInput.value || "").trim().toLowerCase();
                rows.forEach((r) => {
                    r.style.display = !q || r.dataset.label.includes(q) ? "" : "none";
                });
                updateVisibleCount();
            });
            clearBtn.addEventListener("click", () => {
                state.legal_text.length = 0;
                fetchSummary();
            });
            updateVisibleCount();
            if (current.length) {
                btn.innerHTML = `<span class="legal-btn-main">النصوص المحددة</span><span class="legal-btn-sub">محدد (${toEnglishNumber(
                    current.length
                )})</span>`;
            } else {
                btn.innerHTML = `<span class="legal-btn-main">النصوص النظامية</span><span class="legal-btn-sub">الكل (${toEnglishNumber(
                    items.length
                )})</span>`;
            }
        }

        function closeLegalDropdown() {
            const dropdown = document.getElementById("legalTextDropdown");
            dropdown.classList.remove("open");
        }

        const legalModal = document.getElementById("legalModal");
        const legalModalDetailMount = document.getElementById("legalModalDetailMount");
        function setLegalModalMainContent(html) {
            if (legalModalDetailMount) {
                legalModalDetailMount.innerHTML = html;
            }
        }
        const legalModalTitle = document.getElementById("legalModalTitle");
        const legalModalTextPanel = document.getElementById("legalModalTextPanel");
        const legalModalFullText = document.getElementById("legalModalFullText");
        function setLegalModalTitleText(text, loading) {
            legalModalTitle.textContent = "النص النظامي";
            legalModalTitle.removeAttribute("title");
            if (!legalModalTextPanel || !legalModalFullText) {
                return;
            }
            if (loading) {
                legalModalTextPanel.hidden = true;
                legalModalFullText.textContent = "—";
                return;
            }
            const t = text == null ? "" : String(text).trim();
            if (!t) {
                legalModalTextPanel.hidden = true;
                legalModalFullText.textContent = "—";
                return;
            }
            legalModalTextPanel.hidden = false;
            legalModalFullText.textContent = t;
        }
        const legalModalSendEmail = document.getElementById("legalModalSendEmail");
        const legalModalDownloadPptx = document.getElementById("legalModalDownloadPptx");
        const isSnapshotPackPage = !!document.getElementById("snapshot-pack");
        let legalModalCurrentText = "";
        let legalModalCurrentRecipientEmail = "";

        function setLegalModalPptxEnabled(enabled) {
            if (!legalModalDownloadPptx) {
                return;
            }
            legalModalDownloadPptx.disabled = !enabled;
        }
        if (legalModalSendEmail && isSnapshotPackPage) {
            legalModalSendEmail.disabled = false;
            legalModalSendEmail.setAttribute("title", "سيتم الإرسال عبر السيرفر المحلي.");
        }

        const legalModalEmailPreview = document.getElementById("legalModalEmailPreview");
        function setLegalModalEmailPreview(value) {
            if (!legalModalEmailPreview) {
                return;
            }
            const t = value === undefined || value === null ? "" : String(value).trim();
            legalModalEmailPreview.textContent = t || "—";
        }

        function closeLegalModal() {
            legalModal.style.display = "none";
            if (legalModalDetailMount) {
                legalModalDetailMount.innerHTML = "";
            }
            legalModalCurrentRecipientEmail = "";
            setLegalModalPptxEnabled(false);
            setLegalModalEmailPreview("—");
            setLegalModalTitleText("", true);
        }

        document.getElementById("legalModalClose").addEventListener("click", closeLegalModal);
        if (legalModalSendEmail) {
            legalModalSendEmail.addEventListener("click", async () => {
                const t = legalModalCurrentText;
                if (!t) {
                    return;
                }
                legalModalSendEmail.disabled = true;
                try {
                    const payload = { text: t };
                    if (isSnapshotPackPage && legalModalCurrentRecipientEmail) {
                        payload.to = legalModalCurrentRecipientEmail;
                    }
                    const r = await fetch(arApiUrl('/send-legal-text-email'), {
                        method: "POST",
                        credentials: isSnapshotPackPage ? "omit" : "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    let j = {};
                    try {
                        j = await r.json();
                    } catch {
                        j = {};
                    }
                    if (!r.ok) {
                        alert(j.error || "تعذر إرسال البريد.");
                        return;
                    }
                    alert(`تم الإرسال إلى ${j.to || ""}`);
                } catch {
                    alert("تعذر إرسال البريد.");
                } finally {
                    legalModalSendEmail.disabled = false;
                }
            });
        }
        if (legalModalDownloadPptx) {
            legalModalDownloadPptx.addEventListener("click", async () => {
                const t = legalModalCurrentText;
                if (!t) {
                    return;
                }
                legalModalDownloadPptx.disabled = true;
                try {
                    const payload = { text: t };
                    if (isSnapshotPackPage && legalDetailsCache.has(t)) {
                        const cached = legalDetailsCache.get(t);
                        payload.fields = cached.fields || [];
                        payload.recipient_email = cached.recipient_email || "";
                        payload.images = cached.images || [];
                    }
                    const r = await fetch(arApiUrl('/export-legal-text-pptx'), {
                        method: "POST",
                        credentials: isSnapshotPackPage ? "omit" : "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    if (!r.ok) {
                        let err = {};
                        try {
                            err = await r.json();
                        } catch {
                            err = {};
                        }
                        alert(err.error || "تعذر تنزيل PowerPoint.");
                        return;
                    }
                    const blob = await r.blob();
                    let fname = "legal-text-export.pptx";
                    const cd = r.headers.get("Content-Disposition") || "";
                    const m = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(cd);
                    if (m && m[1]) {
                        fname = decodeURIComponent(m[1].trim());
                    }
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = fname;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                } catch {
                    alert("تعذر تنزيل PowerPoint.");
                } finally {
                    setLegalModalPptxEnabled(!!legalModalCurrentText);
                }
            });
        }
        legalModal.addEventListener("click", (event) => {
            if (event.target === legalModal) {
                closeLegalModal();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") {
                return;
            }
            if (!legalModal || legalModal.style.display !== "flex") {
                return;
            }
            closeLegalModal();
        });

        const agingModal = document.getElementById("agingModal");
        const agingModalBody = document.getElementById("agingModalBody");
        const agingModalTitle = document.getElementById("agingModalTitle");

        function isAgingModalOpen() {
            return agingModal && agingModal.style.display === "flex";
        }

        function selectedAgingDateSource() {
            const checked = document.querySelector('input[name="agingDateSource"]:checked');
            return checked ? checked.value : "";
        }

        function closeAgingModal() {
            agingModal.style.display = "none";
            agingModalBody.innerHTML = "";
            const toggle = document.getElementById("agingToggle");
            if (toggle) toggle.checked = false;
        }

        function renderAgingMatrix(data) {
            const riskCols = data.risk_columns || [];
            const timeRows = data.time_rows || [];
            const colTotals = data.column_totals || {};

            let head = `<th class="time-col">الفترة الزمنية</th>`;
            riskCols.forEach((rc) => {
                const bg = rc.color || "";
                const fg = rc.text_color || "#ffffff";
                const cls = `aging-risk-${rc.id}`;
                const style = bg ? ` style="background:${bg};color:${fg};"` : "";
                head += `<th class="${cls}"${style}>${escapeHtml(rc.label)}</th>`;
            });
            head += `<th class="total-col">المجموع</th>`;

            let body = "";
            timeRows.forEach((tr) => {
                body += `<tr><td class="time-col">${escapeHtml(tr.label)}</td>`;
                riskCols.forEach((rc) => {
                    const v = tr.cells[rc.id] ?? 0;
                    body += `<td>${toEnglishNumber(v)}</td>`;
                });
                body += `<td class="total-col">${toEnglishNumber(tr.total)}</td></tr>`;
            });

            let foot = `<tr><td class="time-col">المجموع</td>`;
            riskCols.forEach((rc) => {
                const v = colTotals[rc.id] ?? 0;
                foot += `<td>${toEnglishNumber(v)}</td>`;
            });
            foot += `<td class="total-col">${toEnglishNumber(data.grand_total)}</td></tr>`;

            return `<table class="aging-matrix"><thead><tr>${head}</tr></thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table>`;
        }

        async function refreshAgingSummary() {
            const refInput = document.getElementById("agingReferenceDate");
            const ref = refInput.value;
            const source = selectedAgingDateSource();
            if (!ref || !source) {
                return;
            }
            agingModalBody.innerHTML = `<div class="empty-hint">جاري التحميل...</div>`;
            const qs = buildFilterQueryString(state);
            qs.set("reference", ref);
            qs.set("aging_date_source", source);
            const response = await fetch(`${arApiUrl('/aging-summary')}?${qs.toString()}`);
            const data = await response.json();
            if (!response.ok) {
                agingModalBody.innerHTML = `<div class="empty-hint">تعذر حساب ملخص التقادم.</div>`;
                return;
            }
            window.lastAgingExport = data;
            agingModalTitle.textContent = `ملخص التقادم (حتى ${data.reference})`;
            const modeLabel = data.date_source === "modified" ? "تاريخ التصحيح المعدل" : "تاريخ التصحيح المستهدف";
            const intro = `<p class="aging-intro">صف <strong>لم يحن بعد</strong> يعدّ الحالة <strong>مفتوح ( ضمن تاريخ التصحيح)</strong> حسب <strong>مستوى المخاطر المتبقية</strong> أو <strong>مستوى المخاطر الكامنة</strong> عند غياب الأول. صفوف <strong>أقل من 6 أشهر</strong> و<strong>6 أشهر – سنة</strong> و<strong>أكثر من سنة</strong> تعدّ الحالة <strong>مفتوح ( تجاوز تاريخ التصحيح)</strong> حيث يُطرح <strong>${escapeHtml(modeLabel)}</strong> من <strong>تاريخ المرجع</strong> (#agingReferenceDate) وتُصنَّف حسب الفترة.</p>`;
            const otherCol = (data.column_totals && data.column_totals.other) || 0;
            const footnote = `<p class="aging-footnote">تخطّي لحالة غير المفتوح (النوعين أعلاه): ${toEnglishNumber(data.skipped_other_status || 0)} — تصنيف «أخرى» (نص خطورة غير مطابق للمستويات الخمسة أو فارغ): ${toEnglishNumber(otherCol)} — تخطّي لعدم وجود تاريخ صالح: ${toEnglishNumber(data.skipped_unknown_time || 0)}</p>`;
            agingModalBody.innerHTML =
                intro + `<div class="aging-matrix-wrap">${renderAgingMatrix(data)}</div>` + footnote;
        }

        document.getElementById("agingModalClose").addEventListener("click", closeAgingModal);
        agingModal.addEventListener("click", (event) => {
            if (event.target === agingModal) {
                closeAgingModal();
            }
        });

        (function initAgingReferenceDate() {
            const el = document.getElementById("agingReferenceDate");
            if (el && !el.value) {
                el.value = new Date().toISOString().slice(0, 10);
            }
        })();

        document.getElementById("agingToggle").addEventListener("change", async (event) => {
            if (event.target.checked) {
                if (!selectedAgingDateSource()) {
                    event.target.checked = false;
                    window.alert("يرجى اختيار تاريخ التصحيح المستهدف أو تاريخ التصحيح المعدل أولاً.");
                    return;
                }
                agingModal.style.display = "flex";
                await refreshAgingSummary();
            } else {
                closeAgingModal();
            }
        });

        document.querySelectorAll('input[name="agingDateSource"]').forEach((radio) => {
            radio.addEventListener("change", async () => {
                const toggle = document.getElementById("agingToggle");
                if (toggle && toggle.checked && isAgingModalOpen()) {
                    await refreshAgingSummary();
                }
            });
        });

        document.getElementById("agingReferenceDate").addEventListener("change", async () => {
            const toggle = document.getElementById("agingToggle");
            if (toggle && toggle.checked && isAgingModalOpen()) {
                await refreshAgingSummary();
            }
        });

        const legalDetailsCache = new Map();

        function renderLegalModalContent(fields, images, imagesPending) {
            const fieldsHtml = (fields || [])
                .map(
                    (f) => `
                    <div class="detail-card">
                        <h4>${escapeHtml(f.label)}</h4>
                        <p>${escapeHtml(f.value || "—")}</p>
                    </div>`
                )
                .join("");

            const imagesHtml =
                images && images.length
                    ? `<div class="image-grid">${images
                          .map(
                              (src) => `
                            <div class="image-tile">
                                <img src="${escapeHtml(src)}" alt="embedded" loading="lazy" />
                            </div>`
                          )
                          .join("")}</div>`
                    : imagesPending
                      ? `<p class="empty-hint" id="legalImagesPending">جاري تحميل الصور المرفقة…</p>`
                      : "";

            setLegalModalMainContent(`
                <div class="detail-grid">${fieldsHtml}</div>
                ${imagesHtml}
            `);
        }

        async function openLegalDetails(text) {
            legalModalCurrentText = text;
            legalModal.style.display = "flex";
            setLegalModalTitleText("", true);
            setLegalModalEmailPreview("…");
            setLegalModalPptxEnabled(false);

            if (legalDetailsCache.has(text)) {
                const cached = legalDetailsCache.get(text);
                setLegalModalTitleText(text, false);
                legalModalCurrentText = text;
                legalModalCurrentRecipientEmail = (cached.recipient_email || "").trim();
                setLegalModalEmailPreview(cached.recipient_email || "");
                renderLegalModalContent(cached.fields, cached.images, false);
                setLegalModalPptxEnabled(true);
                return;
            }

            setLegalModalMainContent(`<div class="empty-hint">جاري التحميل...</div>`);

            if (legalDetailsController) {
                legalDetailsController.abort();
            }
            legalDetailsController = new AbortController();
            let response;
            let data;
            try {
                response = await fetch(arApiUrl('/legal-text-details'), {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text, include_images: false }),
                    signal: legalDetailsController.signal
                });
                data = await response.json();
            } catch (err) {
                if (err && err.name === "AbortError") {
                    return;
                }
                setLegalModalMainContent(`<div class="empty-hint">تعذر تحميل التفاصيل.</div>`);
                return;
            } finally {
                legalDetailsController = null;
            }
            if (!response.ok) {
                setLegalModalMainContent(`<div class="empty-hint">تعذر تحميل التفاصيل.</div>`);
                return;
            }

            setLegalModalTitleText(text, false);
            legalModalCurrentText = text;
            legalModalCurrentRecipientEmail = (data.recipient_email || "").trim();
            setLegalModalEmailPreview(data.recipient_email || "");

            const excelRow = data.excel_row;
            let images = Array.isArray(data.images) ? data.images.filter(Boolean) : [];
            const needsImages = !images.length && typeof excelRow === "number" && excelRow >= 1;
            renderLegalModalContent(data.fields, images, needsImages);

            if (needsImages) {
                try {
                    const ir = await fetch(`${arApiUrl('/legal-text-row-images')}?excel_row=${encodeURIComponent(excelRow)}`, {
                        credentials: isSnapshotPackPage ? "omit" : "same-origin"
                    });
                    if (ir.ok) {
                        const ij = await ir.json();
                        images = ij.images || [];
                    }
                } catch {
                    images = [];
                }
            }

            while (legalDetailsCache.size >= 100) {
                const k = legalDetailsCache.keys().next().value;
                legalDetailsCache.delete(k);
            }
            legalDetailsCache.set(text, {
                fields: data.fields,
                images,
                recipient_email: data.recipient_email || ""
            });
            legalModalCurrentText = text;
            legalModalCurrentRecipientEmail = (data.recipient_email || "").trim();
            setLegalModalEmailPreview(data.recipient_email || "");
            renderLegalModalContent(data.fields, images, false);
            setLegalModalPptxEnabled(true);
        }

        document.getElementById("clearFiltersBtn").addEventListener("click", () => {
            state.control_category.length = 0;
            state.residual.length = 0;
            state.status.length = 0;
            state.year.length = 0;
            state.department.length = 0;
            state.legislator.length = 0;
            state.compliance_status.length = 0;
            state.system_name.length = 0;
            state.authority.length = 0;
            state.regulation.length = 0;
            state.subsidiary_company.length = 0;
            state.holding_company.length = 0;
            updateSubsidiaryStatusPill();
            syncSubsidiaryListSelection();
            state.legal_text.length = 0;
            activeFieldKey = "";
            closeLegalModal();
            closeAgingModal();
            closeCompliancePlanModal();
            fetchSummary();
        });

        document.getElementById("legalTextDropdownBtn").addEventListener("click", (event) => {
            event.stopPropagation();
            const dropdown = document.getElementById("legalTextDropdown");
            dropdown.classList.toggle("open");
        });

        document.addEventListener("click", (event) => {
            const dropdown = document.getElementById("legalTextDropdown");
            if (!dropdown.contains(event.target)) {
                closeLegalDropdown();
            }
        });

        async function downloadInteractiveSnapshot() {
            const brandQs = buildFilterQueryString({
                subsidiary_company: state.subsidiary_company,
                holding_company: state.holding_company
            });
            const response = await fetch(`${arApiUrl('/export-dashboard-html')}?${brandQs.toString()}`, { credentials: "same-origin" });
            if (!response.ok) {
                alert("تعذر إنشاء ملف HTML.");
                return;
            }
            let html = await response.text();
            const seed = {
                sheetName: compliancePlanState.sheetName,
                headers: compliancePlanState.headers,
                rows: compliancePlanState.rows,
                styles: compliancePlanState.styles,
                selectedCell: compliancePlanState.selectedCell
            };
            const seedTag = `<script id="compliance-plan-seed" type="application/json">${JSON.stringify(seed).replace(
                /</g,
                "\\u003c"
            )}<\/script>`;
            const mainScriptMarker = "<script>\n        const hasChartLib";
            if (html.includes(mainScriptMarker)) {
                html = html.replace(mainScriptMarker, `${seedTag}\n    ${mainScriptMarker}`);
            } else if (html.includes("</body>")) {
                html = html.replace("</body>", `${seedTag}\n</body>`);
            } else {
                html += seedTag;
            }
            const blob = new Blob([html], { type: "text/html;charset=utf-8" });
            const name = `dashboard-snapshot-${new Date().toISOString().slice(0, 10)}.html`;
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = name;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 120000);
        }

        const downloadBtn = document.getElementById("downloadInteractiveHtmlBtn");
        if (downloadBtn) {
            downloadBtn.addEventListener("click", async () => {
                downloadBtn.disabled = true;
                try {
                    await downloadInteractiveSnapshot();
                } finally {
                    downloadBtn.disabled = false;
                }
            });
        }

        updateBrandLogo();
        fetchSummary();