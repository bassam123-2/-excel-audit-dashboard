/**
 * Admin — generate compliant password from server (staff-only endpoint).
 */
(function () {
    "use strict";

    var GENERATE_PATH = "/admin/auth/user/generate-password/";

    function getCsrfToken() {
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : "";
    }

    function passwordFields() {
        var p1 = document.getElementById("id_password1") || document.getElementById("np1");
        var p2 = document.getElementById("id_password2") || document.getElementById("np2");
        return { p1: p1, p2: p2 };
    }

    function setPasswordFields(password) {
        var fields = passwordFields();
        if (fields.p1) {
            fields.p1.value = password;
            fields.p1.dispatchEvent(new Event("input", { bubbles: true }));
        }
        if (fields.p2) {
            fields.p2.value = password;
            fields.p2.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }

    function fetchPassword() {
        return fetch(GENERATE_PATH, {
            method: "GET",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCsrfToken(),
            },
            credentials: "same-origin",
        }).then(function (res) {
            if (!res.ok) {
                throw new Error("generate failed");
            }
            return res.json();
        });
    }

    function toggleVisibility(btn, input) {
        if (!input) return;
        var visible = input.type === "text";
        input.type = visible ? "password" : "text";
        btn.setAttribute("aria-pressed", visible ? "false" : "true");
        btn.textContent = visible ? btn.getAttribute("data-label-show") : btn.getAttribute("data-label-hide");
    }

    function copyPassword(input, btn) {
        if (!input || !input.value) return;
        navigator.clipboard.writeText(input.value).then(function () {
            var orig = btn.textContent;
            btn.textContent = btn.getAttribute("data-copied-label") || "Copied";
            setTimeout(function () {
                btn.textContent = orig;
            }, 1500);
        });
    }

    function wrapField(input) {
        if (!input || input.closest(".pw-generate-wrap")) return;
        var wrap = document.createElement("div");
        wrap.className = "pw-generate-wrap";
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        var actions = document.createElement("div");
        actions.className = "pw-generate-actions";
        wrap.appendChild(actions);

        var lang = (document.documentElement.lang || "en").split("-")[0];
        var labels = {
            ar: { gen: "توليد", show: "إظهار", hide: "إخفاء", copy: "نسخ", copied: "تم النسخ" },
            en: { gen: "Generate", show: "Show", hide: "Hide", copy: "Copy", copied: "Copied" },
        };
        var L = labels[lang] || labels.en;

        var genBtn = document.createElement("button");
        genBtn.type = "button";
        genBtn.className = "button pw-gen-btn";
        genBtn.textContent = L.gen;
        genBtn.addEventListener("click", function () {
            genBtn.disabled = true;
            fetchPassword()
                .then(function (data) {
                    setPasswordFields(data.password);
                })
                .catch(function () { /* silent */ })
                .finally(function () {
                    genBtn.disabled = false;
                });
        });

        var toggleBtn = document.createElement("button");
        toggleBtn.type = "button";
        toggleBtn.className = "button pw-toggle-btn";
        toggleBtn.setAttribute("data-label-show", L.show);
        toggleBtn.setAttribute("data-label-hide", L.hide);
        toggleBtn.textContent = L.show;
        toggleBtn.addEventListener("click", function () {
            toggleVisibility(toggleBtn, input);
        });

        var copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "button pw-copy-btn";
        copyBtn.setAttribute("data-copied-label", L.copied);
        copyBtn.textContent = L.copy;
        copyBtn.addEventListener("click", function () {
            copyPassword(input, copyBtn);
        });

        actions.appendChild(genBtn);
        actions.appendChild(toggleBtn);
        actions.appendChild(copyBtn);
    }

    function init() {
        var fields = passwordFields();
        if (fields.p1) wrapField(fields.p1);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
