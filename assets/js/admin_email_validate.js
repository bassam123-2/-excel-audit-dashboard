/**
 * Admin user form — validate email and required personal fields.
 */
(function () {
    "use strict";

    var EMAIL_RE = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;

    var MSGS = {
        ar: {
            required: "هذا الحقل مطلوب.",
            email_required: "البريد الإلكتروني مطلوب.",
            invalid: "صيغة البريد الإلكتروني غير صحيحة.",
        },
        en: {
            required: "This field is required.",
            email_required: "Email address is required.",
            invalid: "Enter a valid email address.",
        },
    };

    var REQUIRED_IDS = ["id_first_name", "id_last_name", "id_job_title", "id_username"];

    function lang() {
        var l = (document.documentElement.lang || "en").split("-")[0];
        return MSGS[l] ? l : "en";
    }

    function msg(key) {
        return MSGS[lang()][key] || MSGS.en[key];
    }

    function isUserForm() {
        return /\/auth\/user\/(add|[^/]+\/change)\/?/.test(window.location.pathname);
    }

    function attachEmail() {
        var input = document.getElementById("id_email");
        if (!input) return;

        var form = input.closest("form");
        var required = isUserForm();
        var errEl = document.getElementById("id_email_live_error");

        if (!errEl) {
            errEl = document.createElement("div");
            errEl.id = "id_email_live_error";
            errEl.className = "email-live-error";
            errEl.setAttribute("role", "alert");
            input.insertAdjacentElement("afterend", errEl);
        }

        function validate(showMsg) {
            var value = input.value.trim();
            var valid = true;
            var message = "";

            if (!value) {
                valid = !required;
                if (!valid) message = msg("email_required");
            } else if (!EMAIL_RE.test(value)) {
                valid = false;
                message = msg("invalid");
            }

            input.classList.toggle("email-field-invalid", !valid && (showMsg || value.length > 0));
            input.setCustomValidity(valid ? "" : message);
            errEl.textContent = showMsg && !valid ? message : "";
            errEl.style.display = showMsg && !valid ? "block" : "none";
            return valid;
        }

        input.addEventListener("input", function () {
            validate(true);
        });
        input.addEventListener("blur", function () {
            validate(true);
        });

        if (form) {
            form.addEventListener("submit", function (e) {
                if (!validate(true)) {
                    e.preventDefault();
                    input.focus();
                }
            });
        }

        if (required) {
            input.setAttribute("required", "required");
        }
        input.setAttribute("type", "email");
        input.setAttribute("inputmode", "email");
        validate(false);
    }

    function attachRequiredFields() {
        if (!isUserForm()) return;
        REQUIRED_IDS.forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            el.setAttribute("required", "required");
            el.addEventListener("invalid", function () {
                if (!el.value.trim()) {
                    el.setCustomValidity(msg("required"));
                }
            });
            el.addEventListener("input", function () {
                el.setCustomValidity("");
            });
        });
    }

    function init() {
        attachEmail();
        attachRequiredFields();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
