(() => {
    'use strict';

    const storageKey = 'tw-active-etf-theme';
    const system = window.matchMedia?.('(prefers-color-scheme: dark)');
    const buttonSelector = 'button[data-theme-choice]';
    let storage;
    let preference = null;

    function knownTheme(value) {
        return value === 'light' || value === 'dark' ? value : null;
    }

    function readStoredPreference() {
        if (!storage) return;
        try {
            preference = knownTheme(storage.getItem(storageKey));
        } catch {
            storage = null;
        }
    }

    try { storage = window.localStorage; } catch { storage = null; }
    readStoredPreference();

    function applyTheme() {
        const theme = preference || (system?.matches ? 'dark' : 'light');
        document.documentElement.dataset.theme = theme;
        const browserBar = document.querySelector('meta[name="theme-color"]');
        if (browserBar) browserBar.content = theme === 'dark' ? '#18262c' : '#ffffff';
        for (const button of document.querySelectorAll('.theme-picker ' + buttonSelector)) {
            button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
        }
    }

    function chooseTheme(theme) {
        preference = theme;
        applyTheme();
        try {
            storage?.setItem(storageKey, theme);
        } catch {
            // Keep the selection in this document when the browser declines persistence.
            storage = null;
        }
    }

    function enableControls() {
        for (const picker of document.querySelectorAll('.theme-picker')) {
            const buttons = Array.from(picker.querySelectorAll(buttonSelector));
            for (const [index, button] of buttons.entries()) {
                button.addEventListener('click', () => chooseTheme(button.dataset.themeChoice));
                button.addEventListener('keydown', event => {
                    let next;
                    switch (event.key) {
                        case 'ArrowLeft': next = (index - 1 + buttons.length) % buttons.length; break;
                        case 'ArrowRight': next = (index + 1) % buttons.length; break;
                        case 'Home': next = 0; break;
                        case 'End': next = buttons.length - 1; break;
                        default: return;
                    }
                    event.preventDefault();
                    buttons[next].focus();
                    buttons[next].click();
                });
            }
            picker.hidden = false;
        }
        applyTheme();
    }

    // This classic script runs in the head, before the stylesheets and page content.
    applyTheme();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', enableControls, {once: true});
    } else {
        enableControls();
    }

    const followSystem = () => { if (!preference) applyTheme(); };
    if (system?.addEventListener) system.addEventListener('change', followSystem);
    else system?.addListener(followSystem);

    window.addEventListener('pageshow', event => {
        if (!event.persisted) return;
        readStoredPreference();
        applyTheme();
    });

    window.addEventListener('storage', event => {
        if (event.key !== storageKey && event.key !== null) return;
        if (event.storageArea && event.storageArea !== storage) return;
        preference = knownTheme(event.newValue);
        // A newer choice may already have been saved while this event was queued.
        if (event.storageArea === storage) readStoredPreference();
        applyTheme();
    });
})();
