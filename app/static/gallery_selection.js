/** Features.md §4 — gallery bulk selection (sessionStorage). */
(function (global) {
  const STORAGE_KEY = 'imageStore.gallerySelection';

  function galleryContextKey() {
    const p = new URLSearchParams(global.location.search);
    return JSON.stringify({
      q: p.get('q') || '',
      category: p.get('category') || 'general',
      sharing: p.get('sharing') || 'public_and_shared',
      random: p.get('random') === '1' ? '1' : '0',
    });
  }

  function loadState() {
    try {
      const raw = global.sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return { contextKey: galleryContextKey(), selected: {} };
      const parsed = JSON.parse(raw);
      const selected = parsed.selected && typeof parsed.selected === 'object' ? parsed.selected : {};
      return { contextKey: parsed.contextKey || '', selected };
    } catch {
      return { contextKey: galleryContextKey(), selected: {} };
    }
  }

  function saveState(state) {
    global.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function ensureContext(state) {
    const key = galleryContextKey();
    if (state.contextKey !== key) {
      return { contextKey: key, selected: {} };
    }
    return state;
  }

  function getSelectedIds(state) {
    return Object.keys(state.selected);
  }

  function setSelected(state, id, name, on) {
    if (on) {
      state.selected[id] = { name: name || id };
    } else {
      delete state.selected[id];
    }
    saveState(state);
    return state;
  }

  function selectAllOnPage(state) {
    document.querySelectorAll('.thumb-cell[data-image-id]').forEach((cell) => {
      const id = cell.dataset.imageId;
      const name = cell.dataset.imageName || id;
      state.selected[id] = { name };
      const cb = cell.querySelector('.gallery-select-cb');
      if (cb) cb.checked = true;
    });
    saveState(state);
    return state;
  }

  function clearAll(state) {
    state.selected = {};
    saveState(state);
    document.querySelectorAll('.gallery-select-cb').forEach((cb) => {
      cb.checked = false;
    });
    return state;
  }

  function clearSelectionStorage() {
    global.sessionStorage.removeItem(STORAGE_KEY);
  }

  function syncToolbar(state) {
    const count = getSelectedIds(state).length;
    const wrap = document.getElementById('selection-count-wrap');
    const countEl = document.getElementById('selection-count');
    const bulkBtn = document.getElementById('selection-bulk-edit');
    if (wrap) wrap.classList.toggle('hidden', count === 0);
    if (countEl) countEl.textContent = count === 1 ? '1 selected' : `${count} selected`;
    if (bulkBtn) bulkBtn.disabled = count === 0;
  }

  function syncCheckboxesFromState(state) {
    document.querySelectorAll('.thumb-cell[data-image-id]').forEach((cell) => {
      const id = cell.dataset.imageId;
      const cb = cell.querySelector('.gallery-select-cb');
      if (cb) cb.checked = Boolean(state.selected[id]);
    });
  }

  function initGallerySelection() {
    let state = ensureContext(loadState());
    saveState(state);
    syncCheckboxesFromState(state);
    syncToolbar(state);

    document.querySelectorAll('.thumb-cell[data-image-id]').forEach((cell) => {
      const id = cell.dataset.imageId;
      const name = cell.dataset.imageName || id;
      const cb = cell.querySelector('.gallery-select-cb');
      if (!cb) return;
      cb.addEventListener('click', (e) => e.stopPropagation());
      cb.addEventListener('change', () => {
        state = setSelected(state, id, name, cb.checked);
        syncToolbar(state);
      });
      const label = cell.querySelector('.thumb-select');
      if (label) {
        label.addEventListener('click', (e) => e.stopPropagation());
      }
    });

    const selectAllBtn = document.getElementById('selection-select-all');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        state = selectAllOnPage(state);
        syncToolbar(state);
      });
    }

    const clearBtn = document.getElementById('selection-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        state = clearAll(state);
        syncToolbar(state);
      });
    }

    const bulkBtn = document.getElementById('selection-bulk-edit');
    if (bulkBtn) {
      bulkBtn.addEventListener('click', () => {
        if (getSelectedIds(state).length === 0) return;
        global.location.href = '/bulk-edit';
      });
    }

    const searchForm = document.getElementById('gallery-search-form');
    if (searchForm) {
      searchForm.addEventListener('submit', () => {
        clearSelectionStorage();
      });
    }
  }

  global.ImageStoreGallerySelection = {
    STORAGE_KEY,
    galleryContextKey,
    loadState,
    saveState,
    ensureContext,
    getSelectedIds,
    clearSelectionStorage,
    initGallerySelection,
  };
})(window);
