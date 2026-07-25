/** Off-canvas sidebar toggle (main app + admin). */
(function () {
    "use strict";

    function init() {
        var toggle = document.querySelector(".js-sidebar-toggle");
        var sidebar = document.querySelector(".sidebar");
        var backdrop = document.querySelector(".js-sb-backdrop");
        if (!toggle || !sidebar) return;

        function closeSidebar() {
            document.body.classList.remove("sidebar-open");
            toggle.setAttribute("aria-expanded", "false");
        }

        function openSidebar() {
            document.body.classList.add("sidebar-open");
            toggle.setAttribute("aria-expanded", "true");
        }

        toggle.addEventListener("click", function () {
            if (document.body.classList.contains("sidebar-open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });

        if (backdrop) {
            backdrop.addEventListener("click", closeSidebar);
        }

        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") closeSidebar();
        });

        sidebar.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                if (window.matchMedia("(max-width: 767.98px)").matches) {
                    closeSidebar();
                }
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
