(() => {
    const themeKey = 'tennissel-chat-theme';
    const themes = [
        { value: 'city', label: 'Ciudad' },
        { value: 'coast', label: 'Costa' },
    ];
    const allowedThemes = new Set(['default', 'mountains', 'sunset', 'court', ...themes.map(({ value }) => value)]);

    document.querySelectorAll('[data-chat-theme-select]').forEach((select) => {
        themes.forEach(({ value, label }) => {
            if (!select.querySelector(`option[value="${value}"]`)) {
                select.add(new Option(label, value));
            }
        });
    });

    const applyTheme = (theme) => {
        const selected = allowedThemes.has(theme) ? theme : 'default';
        document.querySelectorAll('.chat-theme-surface').forEach((surface) => {
            surface.dataset.chatTheme = selected;
        });
        document.querySelectorAll('[data-chat-theme-select]').forEach((select) => {
            select.value = selected;
            select.addEventListener('change', () => {
                const nextTheme = allowedThemes.has(select.value) ? select.value : 'default';
                localStorage.setItem(themeKey, nextTheme);
                applyTheme(nextTheme);
            }, { once: true });
        });
    };

    const initializeThemes = () => {
        applyTheme(localStorage.getItem(themeKey) || 'default');
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeThemes, { once: true });
    } else {
        initializeThemes();
    }
})();
