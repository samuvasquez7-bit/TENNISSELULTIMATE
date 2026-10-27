'use strict';

(() => {
    const script = document.currentScript;
    const copy = document.getElementById('rewardPromoCopy');
    const fill = document.getElementById('rewardProgressFill');
    const progress = document.getElementById('rewardProgressTrack');
    const victories = document.getElementById('rewardVictoryCount');
    const remaining = document.getElementById('rewardRemainingCount');
    const available = document.getElementById('rewardAvailableCount');
    const claim = document.getElementById('rewardClaimButton');
    const result = document.getElementById('rewardResult');
    const prize = document.getElementById('rewardPrize');
    const code = document.getElementById('rewardCode');
    const status = document.getElementById('rewardStatus');

    const showProgress = (data) => {
        const wins = Number(data.victorias);
        const coupons = Number(data.giros);
        const nextReward = Number(data.restantes);
        if (![wins, coupons, nextReward].every(Number.isFinite)) {
            throw new Error('La respuesta de recompensas no es válida.');
        }

        const percentage = wins % 100;
        progress.hidden = false;
        progress.setAttribute('aria-valuenow', String(percentage));
        fill.style.width = `${percentage}%`;
        victories.textContent = `Victorias registradas: ${wins}`;
        remaining.textContent = `Faltan ${nextReward} para el próximo cupón`;
        available.textContent = `Descuentos disponibles: ${coupons}`;
        copy.textContent = `Cada 100 victorias en Tennis Arena desbloqueas un cupón. Llevas ${wins} victorias.`;
        claim.hidden = coupons < 1;
    };

    const loadProgress = async () => {
        try {
            const response = await fetch(script.dataset.progressUrl, {
                headers: { Accept: 'application/json' }
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'No se pudo consultar el progreso.');
            if (!data.autenticado) {
                copy.textContent = 'Inicia sesión y gana partidos para desbloquear cupones de descuento en el catálogo.';
                victories.textContent = 'Inicia sesión para consultar tus victorias';
                remaining.textContent = 'Progreso personal';
                available.textContent = 'Descuentos disponibles: inicia sesión';
                status.textContent = 'Inicia sesión para guardar y consultar tu progreso.';
                return;
            }
            showProgress(data);
        } catch (error) {
            status.textContent = error.message;
        }
    };

    claim.addEventListener('click', async () => {
        claim.disabled = true;
        status.textContent = 'Preparando tu cupón…';
        try {
            const response = await fetch(script.dataset.claimUrl, {
                method: 'POST',
                headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
                body: '{}'
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'No se pudo reclamar el descuento.');
            if (!data.premio || !data.codigo) throw new Error('La respuesta del cupón no es válida.');
            prize.textContent = data.premio.tipo === 'envio' ? '¡Envío gratis!' : `¡${data.premio.valor} de descuento!`;
            code.textContent = data.codigo;
            result.hidden = false;
            showProgress(data);
            status.textContent = 'Copia el código y aplícalo en el carrito.';
        } catch (error) {
            status.textContent = error.message;
        } finally {
            claim.disabled = false;
        }
    });

    document.getElementById('rewardCopyButton').addEventListener('click', async () => {
        try {
            if (!navigator.clipboard) throw new Error('El portapapeles no está disponible.');
            await navigator.clipboard.writeText(code.textContent);
            status.textContent = 'Código copiado.';
        } catch {
            status.textContent = 'Selecciona y copia el código manualmente.';
        }
    });

    const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const revealItems = document.querySelectorAll('.games-reveal');
    if (motionPreference.matches || !('IntersectionObserver' in window)) {
        revealItems.forEach((item) => item.classList.add('is-visible'));
    } else {
        document.documentElement.classList.add('games-motion-ready');
        const observer = new IntersectionObserver((entries, currentObserver) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('is-visible');
                currentObserver.unobserve(entry.target);
            });
        }, { threshold: 0.12, rootMargin: '0px 0px -24px 0px' });
        revealItems.forEach((item) => observer.observe(item));
    }

    const pointerPreference = window.matchMedia('(hover: hover) and (pointer: fine)');
    if (pointerPreference.matches && !motionPreference.matches) {
        document.querySelectorAll('.tilt-card, .games-info-item').forEach((card) => {
            card.addEventListener('pointermove', (event) => {
                const bounds = card.getBoundingClientRect();
                const x = (event.clientX - bounds.left) / bounds.width;
                const y = (event.clientY - bounds.top) / bounds.height;
                const maxTilt = card.classList.contains('tilt-card') ? 5 : 2.5;
                card.style.setProperty('--tilt-x', `${(0.5 - y) * maxTilt}deg`);
                card.style.setProperty('--tilt-y', `${(x - 0.5) * maxTilt}deg`);
                card.style.setProperty('--pointer-x', `${x * 100}%`);
                card.style.setProperty('--pointer-y', `${y * 100}%`);
                card.classList.add('is-pointer-active');
            });
            card.addEventListener('pointerleave', () => {
                card.style.setProperty('--tilt-x', '0deg');
                card.style.setProperty('--tilt-y', '0deg');
                card.classList.remove('is-pointer-active');
            });
        });
    }

    loadProgress();
})();
