(function () {
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    var kindField = document.querySelector("#id_company_kind");
    if (!kindField) {
      return;
    }
    kindField.addEventListener("change", toggleParentField);
    toggleParentField();
  });
})();
