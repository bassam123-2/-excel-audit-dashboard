(function () {
  "use strict";

  function getJQuery() {
    return window.django && window.django.jQuery ? window.django.jQuery : null;
  }

  function getParentExcludePk(parentField) {
    if (!parentField) {
      return "";
    }
    if (parentField.dataset.excludePk) {
      return parentField.dataset.excludePk;
    }
    var match = window.location.pathname.match(/\/company\/(\d+)\/change\/?$/i);
    return match ? match[1] : "";
  }

  function initParentSelect2($, element) {
    var excludePk = getParentExcludePk(element);
    $(element).select2({
      ajax: {
        data: function (params) {
          var payload = {
            term: params.term,
            page: params.page,
            app_label: element.dataset.appLabel,
            model_name: element.dataset.modelName,
            field_name: element.dataset.fieldName,
          };
          if (excludePk) {
            payload.exclude_pk = excludePk;
          }
          return payload;
        },
      },
    });
  }

  function patchDjangoAdminSelect2() {
    var $ = getJQuery();
    if (!$ || !$.fn.djangoAdminSelect2 || $.fn.djangoAdminSelect2.__parentExcludePatch) {
      return;
    }

    $.fn.djangoAdminSelect2 = function () {
      var self = this;
      $.each(this, function (i, element) {
        if (element.id === "id_parent") {
          initParentSelect2($, element);
          return;
        }
        $(element).select2({
          ajax: {
            data: function (params) {
              return {
                term: params.term,
                page: params.page,
                app_label: element.dataset.appLabel,
                model_name: element.dataset.modelName,
                field_name: element.dataset.fieldName,
              };
            },
          },
        });
      });
      return self;
    };
    $.fn.djangoAdminSelect2.__parentExcludePatch = true;
  }

  function refreshParentSelect2() {
    var $ = getJQuery();
    var parentField = document.querySelector("#id_parent");
    if (!$ || !parentField || !parentField.classList.contains("admin-autocomplete")) {
      return;
    }
    var $field = $(parentField);
    if ($field.hasClass("select2-hidden-accessible")) {
      $field.select2("destroy");
    }
    initParentSelect2($, parentField);
  }

  function fixParentSelect2Layout() {
    var parentField = document.querySelector("#id_parent");
    var parentRow = document.querySelector(".field-parent");
    if (!parentField || !parentRow || parentRow.style.display === "none") {
      return;
    }

    var wrapper = parentField.closest(".related-widget-wrapper");
    if (wrapper) {
      wrapper.style.width = "100%";
    }

    var container = parentField.nextElementSibling;
    if (container && container.classList.contains("select2-container")) {
      container.style.setProperty("width", "100%", "important");
    }

    var $ = getJQuery();
    if ($) {
      var $field = $(parentField);
      if ($field.hasClass("select2-hidden-accessible")) {
        $field.next(".select2-container").css("width", "100%");
      }
    }
  }

  function bindParentSelect2Events() {
    var $ = getJQuery();
    if (!$) {
      return;
    }
    var $field = $("#id_parent");
    if (!$field.length || !$field.hasClass("select2-hidden-accessible")) {
      return;
    }
    $field.off("select2:select.parentLayout select2:clear.parentLayout");
    $field.on("select2:select.parentLayout select2:clear.parentLayout", fixParentSelect2Layout);
  }

  function scheduleParentSelect2LayoutFix() {
    window.requestAnimationFrame(function () {
      refreshParentSelect2();
      fixParentSelect2Layout();
      bindParentSelect2Events();
    });
  }

  function toggleParentField() {
    var kindField = document.querySelector("#id_company_kind");
    var parentRow = document.querySelector(".field-parent");
    if (!kindField || !parentRow) {
      return;
    }
    var isSubsidiary = kindField.value === "subsidiary";
    parentRow.style.display = isSubsidiary ? "" : "none";
    var parentField = document.querySelector("#id_parent");
    if (parentField) {
      parentField.required = isSubsidiary;
      if (!isSubsidiary) {
        parentField.value = "";
      }
    }
    if (isSubsidiary) {
      scheduleParentSelect2LayoutFix();
    }
  }

  patchDjangoAdminSelect2();

  document.addEventListener("DOMContentLoaded", function () {
    var kindField = document.querySelector("#id_company_kind");
    if (!kindField) {
      return;
    }
    kindField.addEventListener("change", toggleParentField);
    toggleParentField();
    window.setTimeout(scheduleParentSelect2LayoutFix, 0);
  });
})();
