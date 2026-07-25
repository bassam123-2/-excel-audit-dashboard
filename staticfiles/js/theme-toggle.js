(function () {
    "use strict";

    var STORAGE_KEY = "ui-theme";

    function getCsrfToken() {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function currentMode() {
        return document.documentElement.getAttribute("data-theme") === "dark"
            ? "dark"
            : "light";
    }

    function updateToggleIcons(mode) {
        document.querySelectorAll(".js-theme-toggle").forEach(function (btn) {
            var icon = btn.querySelector("i");
            if (!icon) {
                return;
            }
            icon.classList.toggle("bi-moon-stars", mode !== "dark");
            icon.classList.toggle("bi-sun", mode === "dark");
        });
    }

    function applyTheme(mode) {
        var root = document.documentElement;
        root.setAttribute("data-ui-theme", mode);
        if (mode === "dark") {
            root.setAttribute("data-theme", "dark");
        } else {
            root.removeAttribute("data-theme");
        }
        updateToggleIcons(mode);
    }

    function persistThemeLocally(mode) {
        try {
            localStorage.setItem(STORAGE_KEY, mode);
        } catch (e) {
            /* ignore */
        }
    }

    function persistThemeOnServer(mode) {
        var url = window.UI_THEME_SWITCH_URL;
        if (!url) {
            return;
        }
        fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
            body: "theme=" + encodeURIComponent(mode),
            credentials: "same-origin",
        }).catch(function () {
            /* non-fatal */
        });
    }

    function initThemeFromPage() {
        var root = document.documentElement;
        var serverTheme = root.getAttribute("data-ui-theme");
        if (serverTheme === "dark" || serverTheme === "light") {
            applyTheme(serverTheme);
            persistThemeLocally(serverTheme);
            return;
        }
        try {
            applyTheme(localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light");
        } catch (e) {
            applyTheme("light");
        }
    }

    function bindToggles() {
        document.querySelectorAll(".js-theme-toggle").forEach(function (btn) {
            if (btn.dataset.themeBound === "1") {
                return;
            }
            btn.dataset.themeBound = "1";
            btn.addEventListener("click", function () {
                var next = currentMode() === "dark" ? "light" : "dark";
                applyTheme(next);
                persistThemeLocally(next);
                persistThemeOnServer(next);
            });
        });
    }

    initThemeFromPage();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindToggles);
    } else {
        bindToggles();
    }
})();
