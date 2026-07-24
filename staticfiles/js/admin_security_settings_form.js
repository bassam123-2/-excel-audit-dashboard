(function () {
  "use strict";

  var THEME_VARS = [
    "--cl-v2-brand",
    "--cl-v2-brand-soft",
    "--cl-v2-accent",
    "--cl-v2-secondary",
    "--cl-v2-surface",
    "--cl-v2-border",
    "--cl-v2-muted",
    "--cl-v2-text",
    "--cl-v2-input-bg",
    "--cl-v2-shadow-soft",
    "--cl-v2-shadow-card",
    "--cl-v2-radius-lg",
  ];

  function filterLabel(label, query) {
    return label.toLowerCase().indexOf(query.toLowerCase()) !== -1;
  }

  function formatOptionParts(label) {
    var slash = label.indexOf("/");
    if (slash === -1) {
      return { title: label, meta: "" };
    }
    return {
      title: label.slice(slash + 1).replace(/_/g, " "),
      meta: label.slice(0, slash).replace(/_/g, " "),
    };
  }

  function applyThemeVarsToDropdown(dropdown) {
    var themeRoot = document.querySelector("#content-start .admin-cl-v2-form");
    if (!themeRoot) {
      return;
    }
    var computed = window.getComputedStyle(themeRoot);
    THEME_VARS.forEach(function (name) {
      var value = computed.getPropertyValue(name).trim();
      if (value) {
        dropdown.style.setProperty(name, value);
      }
    });
  }

  function buildOptionItem(option, selectedValue) {
    var parts = formatOptionParts(option.label);
    var item = document.createElement("li");
    item.className = "admin-tz-combobox__option";
    item.setAttribute("role", "option");
    item.dataset.value = option.value;

    var leading = document.createElement("span");
    leading.className = "admin-tz-combobox__option-leading";
    leading.innerHTML = '<i class="bi bi-clock" aria-hidden="true"></i>';

    var body = document.createElement("span");
    body.className = "admin-tz-combobox__option-body";

    var title = document.createElement("span");
    title.className = "admin-tz-combobox__option-title";
    title.textContent = parts.title || option.label;

    body.appendChild(title);
    if (parts.meta) {
      var meta = document.createElement("span");
      meta.className = "admin-tz-combobox__option-meta";
      meta.textContent = parts.meta;
      body.appendChild(meta);
    }

    var check = document.createElement("span");
    check.className = "admin-tz-combobox__option-check";
    check.innerHTML = '<i class="bi bi-check-lg" aria-hidden="true"></i>';

    item.appendChild(leading);
    item.appendChild(body);
    item.appendChild(check);

    if (option.value === selectedValue) {
      item.classList.add("is-selected");
      item.setAttribute("aria-selected", "true");
    } else {
      item.setAttribute("aria-selected", "false");
    }

    return item;
  }

  function initTimezoneCombobox(select) {
    if (!select || select.dataset.tzComboboxReady === "1") {
      return;
    }
    select.dataset.tzComboboxReady = "1";

    var options = Array.prototype.slice.call(select.options).map(function (option) {
      return {
        value: option.value,
        label: option.textContent || option.value,
      };
    });

    var wrapper = document.createElement("div");
    wrapper.className = "admin-tz-combobox";

    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "admin-tz-combobox__trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");

    var triggerIcon = document.createElement("span");
    triggerIcon.className = "admin-tz-combobox__trigger-icon";
    triggerIcon.innerHTML = '<i class="bi bi-globe2" aria-hidden="true"></i>';

    var triggerLabel = document.createElement("span");
    triggerLabel.className = "admin-tz-combobox__value";

    var triggerChevron = document.createElement("span");
    triggerChevron.className = "admin-tz-combobox__chevron";
    triggerChevron.setAttribute("aria-hidden", "true");
    triggerChevron.innerHTML = '<i class="bi bi-chevron-down"></i>';

    trigger.appendChild(triggerIcon);
    trigger.appendChild(triggerLabel);
    trigger.appendChild(triggerChevron);

    var dropdown = document.createElement("div");
    dropdown.className = "admin-tz-combobox__dropdown";
    dropdown.hidden = true;

    var searchWrap = document.createElement("div");
    searchWrap.className = "admin-tz-combobox__search-wrap";

    var search = document.createElement("input");
    search.type = "search";
    search.className = "admin-tz-combobox__search";
    search.placeholder = select.getAttribute("data-search-placeholder") || "";
    search.autocomplete = "off";
    search.setAttribute("aria-label", search.placeholder || "Search");

    searchWrap.appendChild(search);

    var list = document.createElement("ul");
    list.className = "admin-tz-combobox__list";
    list.setAttribute("role", "listbox");

    dropdown.appendChild(searchWrap);
    dropdown.appendChild(list);
    wrapper.appendChild(trigger);
    wrapper.appendChild(dropdown);

    select.classList.add("admin-tz-combobox__native");
    select.tabIndex = -1;
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);

    function currentLabel() {
      var selected = select.options[select.selectedIndex];
      return selected ? selected.textContent || selected.value : "";
    }

    function renderList(query) {
      list.innerHTML = "";
      var visibleCount = 0;
      options.forEach(function (option) {
        if (query && !filterLabel(option.label, query)) {
          return;
        }
        visibleCount += 1;
        list.appendChild(buildOptionItem(option, select.value));
      });

      if (!visibleCount) {
        var empty = document.createElement("li");
        empty.className = "admin-tz-combobox__empty";
        empty.innerHTML =
          '<i class="bi bi-search" aria-hidden="true"></i>' +
          '<span>' +
          (select.getAttribute("data-no-results") || "—") +
          "</span>";
        list.appendChild(empty);
      }
    }

    function positionFloatingDropdown() {
      var rect = trigger.getBoundingClientRect();
      var gap = 6;
      dropdown.style.top = Math.round(rect.bottom + gap) + "px";
      dropdown.style.left = Math.round(rect.left) + "px";
      dropdown.style.width = Math.round(rect.width) + "px";
    }

    function mountFloatingDropdown() {
      applyThemeVarsToDropdown(dropdown);
      if (dropdown.parentNode !== document.body) {
        document.body.appendChild(dropdown);
      }
      dropdown.classList.add("admin-tz-combobox__dropdown--floating");
      positionFloatingDropdown();
      dropdown.classList.remove("is-visible");
      window.requestAnimationFrame(function () {
        dropdown.classList.add("is-visible");
      });
    }

    function unmountFloatingDropdown() {
      dropdown.classList.remove("is-visible", "admin-tz-combobox__dropdown--floating");
      dropdown.style.top = "";
      dropdown.style.left = "";
      dropdown.style.width = "";
      if (dropdown.parentNode !== wrapper) {
        wrapper.appendChild(dropdown);
      }
    }

    function setValue(value) {
      select.value = value;
      triggerLabel.textContent = currentLabel();
      renderList(search.value.trim());
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function openDropdown() {
      if (select.disabled) {
        return;
      }
      dropdown.hidden = false;
      wrapper.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      renderList("");
      search.value = "";
      mountFloatingDropdown();
      window.setTimeout(function () {
        search.focus();
      }, 0);
    }

    function closeDropdown() {
      dropdown.classList.remove("is-visible");
      window.setTimeout(function () {
        dropdown.hidden = true;
        wrapper.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
        search.value = "";
        renderList("");
        unmountFloatingDropdown();
      }, 140);
    }

    triggerLabel.textContent = currentLabel();
    renderList("");

    trigger.addEventListener("click", function () {
      if (wrapper.classList.contains("is-open")) {
        closeDropdown();
      } else {
        openDropdown();
      }
    });

    search.addEventListener("input", function () {
      renderList(search.value.trim());
    });

    search.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDropdown();
        trigger.focus();
      }
    });

    list.addEventListener("click", function (event) {
      var item = event.target.closest(".admin-tz-combobox__option");
      if (!item) {
        return;
      }
      setValue(item.dataset.value);
      closeDropdown();
      trigger.focus();
    });

    document.addEventListener("click", function (event) {
      if (!wrapper.contains(event.target) && !dropdown.contains(event.target)) {
        closeDropdown();
      }
    });

    window.addEventListener("resize", function () {
      if (wrapper.classList.contains("is-open")) {
        positionFloatingDropdown();
      }
    });

    window.addEventListener(
      "scroll",
      function () {
        if (wrapper.classList.contains("is-open")) {
          positionFloatingDropdown();
        }
      },
      true
    );
  }

  function boot() {
    document.querySelectorAll("select.admin-searchable-select").forEach(initTimezoneCombobox);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
