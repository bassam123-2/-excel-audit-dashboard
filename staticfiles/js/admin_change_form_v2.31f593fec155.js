(function () {
    function fileHintFromAccept(accept) {
        if (!accept) {
            return "";
        }
        if (accept.indexOf("image") !== -1) {
            return "PNG, JPG, GIF, WebP";
        }
        return accept.replace(/\./g, "").toUpperCase();
    }

    function fileIconFromAccept(accept) {
        if (accept && accept.indexOf("image") !== -1) {
            return "bi-image";
        }
        return "bi-cloud-arrow-up";
    }

    function defaultFileText(accept) {
        if (accept && accept.indexOf("image") !== -1) {
            return "Choose an image or drag here";
        }
        return "Choose a file or drag here";
    }

    function initFileZones() {
        var panel = document.querySelector("#content-start .admin-cl-v2-form__panel");
        if (!panel) {
            return;
        }

        panel.querySelectorAll('input[type="file"]:not([data-cl-v2-file-ready])').forEach(function (input) {
            input.dataset.clV2FileReady = "1";

            var zone = document.createElement("div");
            zone.className = "admin-cl-v2-file-zone";

            var body = document.createElement("div");
            body.className = "admin-cl-v2-file-zone__body";

            var icon = document.createElement("span");
            icon.className = "admin-cl-v2-file-zone__icon";
            icon.setAttribute("aria-hidden", "true");
            icon.innerHTML = '<i class="bi ' + fileIconFromAccept(input.accept) + '"></i>';

            var text = document.createElement("span");
            text.className = "admin-cl-v2-file-zone__text";
            text.textContent = defaultFileText(input.accept);

            var hintText = fileHintFromAccept(input.accept);
            var hint = null;
            if (hintText) {
                hint = document.createElement("span");
                hint.className = "admin-cl-v2-file-zone__hint";
                hint.textContent = hintText;
            }

            var selected = document.createElement("span");
            selected.className = "admin-cl-v2-file-zone__selected";
            selected.hidden = true;

            body.appendChild(icon);
            body.appendChild(text);
            if (hint) {
                body.appendChild(hint);
            }
            body.appendChild(selected);

            input.parentNode.insertBefore(zone, input);
            zone.appendChild(input);
            zone.appendChild(body);

            function updateSelected() {
                var file = input.files && input.files[0];
                if (file) {
                    zone.classList.add("is-filled");
                    selected.hidden = false;
                    selected.textContent = file.name;
                    text.textContent = "File selected";
                    return;
                }
                zone.classList.remove("is-filled");
                selected.hidden = true;
                selected.textContent = "";
                text.textContent = defaultFileText(input.accept);
            }

            input.addEventListener("change", updateSelected);

            zone.addEventListener("dragover", function (event) {
                event.preventDefault();
                zone.classList.add("is-dragover");
            });

            zone.addEventListener("dragleave", function () {
                zone.classList.remove("is-dragover");
            });

            zone.addEventListener("drop", function (event) {
                event.preventDefault();
                zone.classList.remove("is-dragover");
                if (!event.dataTransfer || !event.dataTransfer.files.length) {
                    return;
                }
                input.files = event.dataTransfer.files;
                input.dispatchEvent(new Event("change", { bubbles: true }));
            });

            updateSelected();
        });
    }

    document.addEventListener("DOMContentLoaded", initFileZones);
})();
