(function () {
    function getCsrfToken(fallback) {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : (fallback || '');
    }

    function memberLabel(member) {
        return member.name + ' (@' + member.username + ')';
    }

    function memberSearchText(member) {
        return (member.name + ' ' + member.username).toLowerCase();
    }

    function createListItem(member) {
        var li = document.createElement('li');
        li.className = 'dv-picker-item';
        li.setAttribute('role', 'option');
        li.dataset.userId = String(member.id);
        li.dataset.search = memberSearchText(member);
        li.textContent = memberLabel(member);
        return li;
    }

    function sortListItems(listEl) {
        var items = Array.prototype.slice.call(listEl.querySelectorAll('.dv-picker-item'));
        items.sort(function (a, b) {
            return a.textContent.localeCompare(b.textContent, undefined, { sensitivity: 'base' });
        });
        items.forEach(function (item) {
            listEl.appendChild(item);
        });
    }

    function getSelectedItems(listEl) {
        return Array.prototype.slice.call(listEl.querySelectorAll('.dv-picker-item.is-selected'));
    }

    function clearSelection(listEl) {
        listEl.querySelectorAll('.dv-picker-item.is-selected').forEach(function (item) {
            item.classList.remove('is-selected');
        });
    }

    function moveItems(items, toList) {
        if (!items.length) return;
        items.forEach(function (item) {
            item.classList.remove('is-selected');
            toList.appendChild(item);
        });
        sortListItems(toList);
    }

    function moveSelected(fromList, toList) {
        moveItems(getSelectedItems(fromList), toList);
    }

    function moveAll(fromList, toList, filterText) {
        var q = (filterText || '').trim().toLowerCase();
        var items = Array.prototype.slice.call(fromList.querySelectorAll('.dv-picker-item')).filter(function (item) {
            if (item.hidden) return false;
            if (!q) return true;
            return (item.dataset.search || '').indexOf(q) !== -1;
        });
        moveItems(items, toList);
    }

    function applyFilter(listEl, query) {
        var q = (query || '').trim().toLowerCase();
        listEl.querySelectorAll('.dv-picker-item').forEach(function (item) {
            var match = !q || (item.dataset.search || '').indexOf(q) !== -1;
            item.hidden = !match;
            if (!match) item.classList.remove('is-selected');
        });
    }

    function populateLists(availableList, chosenList, members) {
        availableList.innerHTML = '';
        chosenList.innerHTML = '';
        members.forEach(function (member) {
            var item = createListItem(member);
            if (member.assigned) {
                chosenList.appendChild(item);
            } else {
                availableList.appendChild(item);
            }
        });
        sortListItems(availableList);
        sortListItems(chosenList);
    }

    function bindListSelection(listEl) {
        listEl.addEventListener('click', function (event) {
            var item = event.target.closest('.dv-picker-item');
            if (!item || !listEl.contains(item)) return;
            if (event.ctrlKey || event.metaKey) {
                item.classList.toggle('is-selected');
                return;
            }
            if (event.shiftKey) {
                item.classList.add('is-selected');
                return;
            }
            clearSelection(listEl);
            item.classList.add('is-selected');
        });
    }

    window.initDashboardViewersModal = function (options) {
        var modalEl = document.getElementById(options.modalId || 'viewersModal');
        if (!modalEl) return;

        var transferEl = document.getElementById('viewersTransfer');
        var availableList = document.getElementById('viewersAvailableList');
        var chosenList = document.getElementById('viewersChosenList');
        var availableFilter = document.getElementById('viewersAvailableFilter');
        var chosenFilter = document.getElementById('viewersChosenFilter');
        var loadingEl = document.getElementById('viewersLoading');
        var saveBtn = document.getElementById(options.saveBtnId || 'viewersSaveBtn');
        var errorEl = document.getElementById(options.errorId || 'viewersError');
        var viewersUrl = '';

        if (!availableList || !chosenList) return;

        bindListSelection(availableList);
        bindListSelection(chosenList);

        function setLoading(isLoading) {
            if (loadingEl) loadingEl.classList.toggle('d-none', !isLoading);
            if (transferEl) transferEl.classList.toggle('d-none', isLoading);
            if (saveBtn) saveBtn.disabled = isLoading;
        }

        function hideError() {
            if (!errorEl) return;
            errorEl.classList.add('d-none');
            errorEl.textContent = '';
        }

        function showError(message) {
            if (!errorEl) return;
            errorEl.textContent = message;
            errorEl.classList.remove('d-none');
        }

        function resetFilters() {
            if (availableFilter) {
                availableFilter.value = '';
                applyFilter(availableList, '');
            }
            if (chosenFilter) {
                chosenFilter.value = '';
                applyFilter(chosenList, '');
            }
        }

        function loadMembers() {
            hideError();
            resetFilters();
            setLoading(true);
            fetch(viewersUrl, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            }).then(function (res) {
                if (!res.ok) throw new Error('load failed');
                return res.json();
            }).then(function (data) {
                var members = data.members || [];
                if (!members.length) {
                    showError(options.emptyText || 'No members');
                }
                populateLists(availableList, chosenList, members);
                setLoading(false);
                if (saveBtn) saveBtn.disabled = false;
            }).catch(function () {
                setLoading(false);
                showError(options.errorText || 'Error');
            });
        }

        document.querySelectorAll(options.triggerSelector || '.js-viewers-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                viewersUrl = btn.getAttribute('data-viewers-url') || '';
                loadMembers();
            });
        });

        document.getElementById('viewersChooseBtn').addEventListener('click', function () {
            moveSelected(availableList, chosenList);
        });
        document.getElementById('viewersRemoveBtn').addEventListener('click', function () {
            moveSelected(chosenList, availableList);
        });
        document.getElementById('viewersChooseAll').addEventListener('click', function () {
            moveAll(availableList, chosenList, availableFilter ? availableFilter.value : '');
        });
        document.getElementById('viewersRemoveAll').addEventListener('click', function () {
            moveAll(chosenList, availableList, chosenFilter ? chosenFilter.value : '');
        });

        if (availableFilter) {
            availableFilter.addEventListener('input', function () {
                applyFilter(availableList, availableFilter.value);
            });
        }
        if (chosenFilter) {
            chosenFilter.addEventListener('input', function () {
                applyFilter(chosenList, chosenFilter.value);
            });
        }

        availableList.addEventListener('dblclick', function (event) {
            var item = event.target.closest('.dv-picker-item');
            if (!item || !availableList.contains(item)) return;
            item.classList.add('is-selected');
            moveSelected(availableList, chosenList);
        });
        chosenList.addEventListener('dblclick', function (event) {
            var item = event.target.closest('.dv-picker-item');
            if (!item || !chosenList.contains(item)) return;
            item.classList.add('is-selected');
            moveSelected(chosenList, availableList);
        });

        if (saveBtn) {
            saveBtn.addEventListener('click', function () {
                hideError();
                saveBtn.disabled = true;
                var formData = new FormData();
                chosenList.querySelectorAll('.dv-picker-item').forEach(function (item) {
                    formData.append('user_ids', item.dataset.userId);
                });
                fetch(viewersUrl, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCsrfToken(options.csrfToken),
                    },
                    body: formData,
                }).then(function (res) {
                    if (!res.ok) throw new Error('save failed');
                    return res.json();
                }).then(function () {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }).catch(function () {
                    showError(options.errorText || 'Error');
                }).finally(function () {
                    saveBtn.disabled = false;
                });
            });
        }
    };
})();
