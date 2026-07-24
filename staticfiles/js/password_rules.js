/**
 * Live password rules checklist — profile page + Django admin user forms.
 * Unified behaviour: copy blocked on password1, paste blocked on password2,
 * live red/green rule checklist below the primary password field.
 *
 * Optional on <html>: data-pw-username — username for similarity check
 */
(function () {
    "use strict";

    var COMMON_PASSWORDS = [
        "password", "12345678", "123456789", "1234567890", "qwerty123",
        "admin1234", "letmein", "welcome", "monkey", "dragon",
        "master", "login", "princess", "football", "iloveyou",
        "admin@1234", "password1", "password123", "abc12345",
    ];

    var SPECIAL_SYMBOL_RE = /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?`~]/;

    var RULE_KEYS = [
        "min_length",
        "has_lower",
        "has_upper",
        "has_digit",
        "has_symbol",
        "not_numeric",
        "not_common",
        "not_similar",
        "passwords_match",
    ];

    var STRINGS = {
        ar: {
            heading: "قواعد كلمة المرور",
            min_length: "8 أحرف على الأقل",
            has_lower: "يحتوي على حرف صغير واحد على الأقل",
            has_upper: "يحتوي على حرف كبير واحد على الأقل",
            has_digit: "يحتوي على رقم واحد على الأقل",
            has_symbol: "يحتوي على رمز خاص واحد على الأقل (@ # $ …)",
            not_numeric: "لا يمكن أن تكون أرقاماً فقط",
            not_common: "ليست كلمة مرور شائعة الاستخدام",
            not_similar: "ليست مشابهة لاسم المستخدم",
            passwords_match: "كلمتا المرور متطابقتان",
        },
        en: {
            heading: "Password requirements",
            min_length: "At least 8 characters",
            has_lower: "At least one lowercase letter",
            has_upper: "At least one uppercase letter",
            has_digit: "At least one digit",
            has_symbol: "At least one special symbol (@ # $ …)",
            not_numeric: "Cannot be entirely numeric",
            not_common: "Not a commonly used password",
            not_similar: "Not too similar to your username",
            passwords_match: "Passwords match",
        },
    };

    function lang() {
        var l = (document.documentElement.lang || "en").split("-")[0];
        return STRINGS[l] ? l : "en";
    }

    function t(key) {
        return STRINGS[lang()][key] || STRINGS.en[key];
    }

    function username() {
        var fromAttr = document.documentElement.getAttribute("data-pw-username") || "";
        if (fromAttr) {
            return fromAttr;
        }
        var un = document.getElementById("id_username")
            || document.querySelector('input[name="username"]');
        return un ? un.value : "";
    }

    function fieldsInScope(scope) {
        return {
            p1: scope.querySelector("#np1")
                || scope.querySelector("#id_password1")
                || scope.querySelector('input[name="password1"]')
                || scope.querySelector('input[name="new_password1"]'),
            p2: scope.querySelector("#np2")
                || scope.querySelector("#id_password2")
                || scope.querySelector('input[name="password2"]')
                || scope.querySelector('input[name="new_password2"]'),
        };
    }

    function isCommon(pw) {
        var lower = pw.toLowerCase();
        for (var i = 0; i < COMMON_PASSWORDS.length; i++) {
            if (lower === COMMON_PASSWORDS[i]) {
                return false;
            }
        }
        return true;
    }

    function isNotSimilar(pw, user) {
        if (!user || user.length < 3) {
            return true;
        }
        var pl = pw.toLowerCase();
        var ul = user.toLowerCase();
        return pl.indexOf(ul) === -1 && ul.indexOf(pl) === -1;
    }

    function evaluate(pw, confirm, user) {
        return {
            min_length: pw.length >= 8,
            has_lower: /[a-z]/.test(pw),
            has_upper: /[A-Z]/.test(pw),
            has_digit: /\d/.test(pw),
            has_symbol: SPECIAL_SYMBOL_RE.test(pw),
            not_numeric: pw.length === 0 || !/^\d+$/.test(pw),
            not_common: pw.length === 0 || isCommon(pw),
            not_similar: pw.length === 0 || isNotSimilar(pw, user || username()),
            passwords_match: confirm.length > 0 && pw === confirm,
        };
    }

    function allRulesMet(pw, confirm, user) {
        if (!pw || !confirm) {
            return false;
        }
        var r = evaluate(pw, confirm, user);
        for (var i = 0; i < RULE_KEYS.length; i++) {
            if (!r[RULE_KEYS[i]]) {
                return false;
            }
        }
        return true;
    }

    window.pwRulesAllMet = allRulesMet;
    window.pwRulesEvaluate = evaluate;

    function buildChecklist(container) {
        container.innerHTML = "";
        container.className = "pw-rules-box";

        var heading = document.createElement("div");
        heading.className = "pw-rules-heading";
        heading.textContent = t("heading");
        container.appendChild(heading);

        RULE_KEYS.forEach(function (key) {
            var li = document.createElement("div");
            li.className = "pw-rule-item pw-rule-pending";
            li.setAttribute("data-rule", key);
            li.innerHTML =
                '<span class="pw-rule-icon"><i class="bi bi-circle"></i></span>' +
                '<span class="pw-rule-text">' + t(key) + "</span>";
            container.appendChild(li);
        });
    }

    function updateUI(container, results) {
        container.querySelectorAll(".pw-rule-item").forEach(function (el) {
            var key = el.getAttribute("data-rule");
            var met = results[key];
            var icon = el.querySelector(".pw-rule-icon i");
            el.classList.remove("pw-rule-met", "pw-rule-fail", "pw-rule-pending");

            if (!results.p1_has_value && key !== "passwords_match") {
                el.classList.add("pw-rule-pending");
                icon.className = "bi bi-circle";
                return;
            }
            if (key === "passwords_match" && !results.p2_has_value) {
                el.classList.add("pw-rule-pending");
                icon.className = "bi bi-circle";
                return;
            }

            if (met) {
                el.classList.add("pw-rule-met");
                icon.className = "bi bi-check-circle-fill";
            } else {
                el.classList.add("pw-rule-fail");
                icon.className = "bi bi-x-circle-fill";
            }
        });
    }

    function blockClipboard(fields) {
        function stop(e) {
            e.preventDefault();
        }
        if (fields.p1) {
            fields.p1.addEventListener("copy", stop);
            fields.p1.addEventListener("cut", stop);
        }
        if (fields.p2) {
            fields.p2.addEventListener("paste", stop);
            fields.p2.addEventListener("drop", stop);
        }
    }

    function hideDjangoPasswordHelp() {
        ["id_password1_helptext", "id_password2_helptext"].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.style.display = "none";
            }
        });
    }

    function placeChecklist(box, input) {
        var host = input.closest(".pw-field-primary")
            || input.closest(".password-field-group--primary")
            || input.closest(".form-row")
            || input.parentElement;
        if (host) {
            var adminRow = host.classList.contains("form-row")
                || host.classList.contains("pw-field-primary");
            box.classList.add(adminRow ? "pw-rules-admin-row" : "pw-rules-inline");
            host.appendChild(box);
            return;
        }
        box.classList.add("pw-rules-inline");
        input.insertAdjacentElement("afterend", box);
    }

    function bindSubmitGuard(form, fields, options) {
        options = options || {};
        if (!form || form.dataset.pwRulesBound === "1") {
            return;
        }
        form.dataset.pwRulesBound = "1";
        form.addEventListener("submit", function (e) {
            if (options.skipIfSplitPassword) {
                return;
            }
            if (!fields.p1 || !fields.p2) {
                return;
            }
            var p1 = fields.p1.value;
            var p2 = fields.p2.value;
            if (!p1 && !p2) {
                return;
            }
            if (!allRulesMet(p1, p2)) {
                e.preventDefault();
            }
        });
    }

    function checklistIdFor(scope) {
        return "pw-rules-checklist-" + (scope.getAttribute("data-pw-scope") || scope.id || "default");
    }

    function initScope(scope) {
        if (!scope || scope.dataset.pwRulesReady === "1") {
            return;
        }
        var fields = fieldsInScope(scope);
        if (!fields.p1) {
            return;
        }

        var boxId = checklistIdFor(scope);
        if (document.getElementById(boxId)) {
            scope.dataset.pwRulesReady = "1";
            return;
        }

        scope.dataset.pwRulesReady = "1";
        hideDjangoPasswordHelp();
        blockClipboard(fields);

        var box = document.createElement("div");
        box.id = boxId;
        placeChecklist(box, fields.p1);
        buildChecklist(box);

        function onInput() {
            var pw = fields.p1.value;
            var confirm = fields.p2 ? fields.p2.value : "";
            var results = evaluate(pw, confirm);
            results.p1_has_value = pw.length > 0;
            results.p2_has_value = confirm.length > 0;
            updateUI(box, results);
        }

        fields.p1.addEventListener("input", onInput);
        if (fields.p2) {
            fields.p2.addEventListener("input", onInput);
        }

        var un = document.getElementById("id_username")
            || document.querySelector('input[name="username"]');
        if (un) {
            un.addEventListener("input", onInput);
        }

        onInput();

        if (scope.id === "changePwForm" || scope.id === "setPwForm") {
            bindSubmitGuard(scope, fields);
            return;
        }

        if (scope.classList.contains("password-reset-section")) {
            var passwordForm = document.getElementById("user_password_form");
            bindSubmitGuard(passwordForm, fields);
            return;
        }

        if (scope.id === "user_form") {
            bindSubmitGuard(scope, fields, {
                skipIfSplitPassword: !!document.querySelector(".password-reset-section"),
            });
        }
    }

    function discoverScopes() {
        var scopes = [];
        var profileForm = document.getElementById("changePwForm");
        if (profileForm) {
            scopes.push(profileForm);
        }
        var setPwForm = document.getElementById("setPwForm");
        if (setPwForm) {
            scopes.push(setPwForm);
        }
        document.querySelectorAll('.password-reset-section[data-pw-scope="admin-reset"]').forEach(function (el) {
            scopes.push(el);
        });
        var userForm = document.getElementById("user_form");
        var hasAdminReset = document.querySelector(
            '.password-reset-section[data-pw-scope="admin-reset"]'
        );
        if (userForm && !hasAdminReset) {
            scopes.push(userForm);
        }
        return scopes;
    }

    function init() {
        discoverScopes().forEach(initScope);
    }

    window.initPasswordRules = init;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
