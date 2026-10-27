(() => {
    if (window.tennisselWidgetsInitialized) return;
    window.tennisselWidgetsInitialized = true;

    const root = document.getElementById('tennissel-widgets');
    if (!root) return;

    const dockToggle = document.getElementById('widget-dock-toggle');
    if (window.matchMedia('(max-width: 760px)').matches || document.body.classList.contains('store-page')) {
        root.classList.add('is-collapsed');
        dockToggle?.setAttribute('aria-expanded', 'false');
        dockToggle?.setAttribute('aria-label', 'Mostrar accesos flotantes');
        if (dockToggle) dockToggle.innerHTML = '<i class="fa-solid fa-chevron-up"></i>';
    }

    const currentUserId = Number(root.dataset.userId);
    const currentRole = root.dataset.role;
    const fallbackAvatar = '/static/IMG/avatar-tennisel-1.png?v=20261005-7';
    const panels = ['chatbot-window', 'widget-window', 'widget-teacher-window', 'chat-universal-box'];
    let activeChatUser = null;

    const showPanel = (id) => {
        panels.forEach((panelId) => {
            const panel = document.getElementById(panelId);
            if (panel) panel.classList.toggle('widget-hidden', panelId !== id);
        });
    };

    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[character]));

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.');
        return data;
    };

    const renderPeople = (items, type) => {
        const container = document.getElementById(type === 'radar' ? 'radar-list' : 'teacher-list');
        if (!container) return;
        if (!items.length) {
            container.innerHTML = '<p class="widget-empty">No hay perfiles disponibles todavía.</p>';
            return;
        }
        container.innerHTML = items.map((person) => {
            const distance = person.distancia_km !== undefined && person.distancia_km < 9999 ? `<small>${escapeHtml(person.distancia_km)} km</small>` : '';
            const state = person.estado_chat === 'aceptado' ? 'Abrir chat' : person.estado_chat === 'enviado' ? 'Continuar chat' : person.estado_chat === 'recibido' ? 'Aceptar solicitud' : 'Contactar';
            const accountType = person.rol === 'tienda' ? '<small>Tienda TENNISSEL</small>' : '';
            return `<article class="widget-person-card" data-profile-id="${person.id}">
                <div class="widget-person-summary"><img class="widget-avatar" src="${escapeHtml(person.foto || fallbackAvatar)}" alt="Foto de ${escapeHtml(person.nombre)}" onerror="this.onerror=null;this.src='${fallbackAvatar}'"><div><strong>${escapeHtml(person.nombre)}</strong>${accountType}<span>${escapeHtml(person.nivel || 'Nivel no indicado')} ${distance}</span>${person.biografia ? `<small class="widget-person-bio">${escapeHtml(person.biografia)}</small>` : ''}</div></div>
                <button class="widget-action" data-person-id="${person.id}" data-person-name="${escapeHtml(person.nombre)}" data-contact-state="${person.estado_chat}">${state}</button>
            </article>`;
        }).join('');
        container.querySelectorAll('[data-person-id]').forEach((button) => {
            button.addEventListener('click', (event) => { event.stopPropagation(); contactPerson(button); });
        });
        container.querySelectorAll('[data-profile-id]').forEach((card) => {
            card.addEventListener('click', () => showProfile(card.dataset.profileId));
        });
    };

    const loadPeople = async (type) => {
        const container = document.getElementById(type === 'radar' ? 'radar-list' : 'teacher-list');
        if (!container) return;
        try {
            const people = await requestJson(type === 'radar' ? '/api/radar' : (currentRole === 'profesor' ? '/api/contactos' : '/api/profesores'));
            renderPeople(people, type);
        } catch (error) {
            container.innerHTML = `<p class="widget-error">${escapeHtml(error.message)}</p>`;
        }
    };

    const contactPerson = async (button) => {
        const personId = Number(button.dataset.personId);
        const state = button.dataset.contactState;
        const personPhoto = button.closest('[data-profile-id]')?.querySelector('.widget-avatar')?.src || fallbackAvatar;
        if (state === 'aceptado') {
            openChat(personId, button.dataset.personName, personPhoto);
            return;
        }
        try {
            if (state === 'recibido') {
                const cards = await requestJson('/api/contactos');
                const contact = cards.find((item) => Number(item.id) === personId);
                if (contact) await requestJson('/api/responder_solicitud', { method: 'POST', body: JSON.stringify({ contacto_id: contact.contacto_id, estado: 'aceptada' }) });
                openChat(personId, button.dataset.personName, personPhoto);
                return;
            }
            const contact = await requestJson('/api/solicitar_chat', {
                method: 'POST', body: JSON.stringify({ receptor_id: personId })
            });
            if (contact.estado === 'aceptada' || contact.status === 'accepted') {
                button.dataset.contactState = 'aceptado';
                button.textContent = 'Abrir chat';
                openChat(personId, button.dataset.personName, personPhoto);
            } else {
                button.textContent = 'Solicitud enviada';
                button.disabled = true;
                button.dataset.contactState = 'enviado';
            }
        } catch (error) {
            button.textContent = error.message;
        }
    };

    const renderMessages = (messages) => {
        const container = document.getElementById('chat-messages-body');
        if (!container) return;
        container.innerHTML = messages.length ? messages.map((message) => {
            const own = Number(message.emisor_id) === currentUserId;
            if (message.tipo === 'propuesta') {
                let proposal = {};
                try { proposal = JSON.parse(message.datos_extra || '{}'); } catch (error) { proposal = {}; }
                const actions = !own && message.estado_propuesta === 'pendiente' ? `<div class="proposal-actions"><button data-proposal-action="aceptada" data-message-id="${message.id}">Aceptar y reservar</button><button data-proposal-action="rechazada" data-message-id="${message.id}">Rechazar</button></div>` : `<small>${escapeHtml(message.estado_propuesta || 'pendiente')}</small>`;
                const reportButton = message.id && !own ? `<button class="message-report" data-message-id="${message.id}" type="button">Denunciar</button>` : '';
                return `<div class="msg-bubble ${own ? 'msg-own' : 'msg-other'}"><strong>Propuesta de clase</strong><br>${escapeHtml(message.texto)}<br><small>${escapeHtml(proposal.fecha_reserva || '')} ${escapeHtml(proposal.hora_reserva || '')}</small>${actions}${reportButton}</div>`;
            }
            const reportButton = message.id && !own ? `<button class="message-report" data-message-id="${message.id}" type="button">Denunciar</button>` : '';
            return `<div class="msg-bubble ${own ? 'msg-own' : 'msg-other'}">${escapeHtml(message.texto)}${reportButton}</div>`;
        }).join('') : '<p class="widget-empty">Todavia no hay mensajes.</p>';
        container.scrollTop = container.scrollHeight;
        container.querySelectorAll('[data-proposal-action]').forEach((button) => {
            button.addEventListener('click', async () => {
                try {
                    await requestJson('/api/responder_propuesta', { method: 'POST', body: JSON.stringify({ mensaje_id: button.dataset.messageId, accion: button.dataset.proposalAction }) });
                    loadMessages();
                } catch (error) { button.textContent = error.message; }
            });
        });
        container.querySelectorAll('.message-report').forEach((button) => {
            button.addEventListener('click', async () => {
                const reason = window.prompt('Motivo de la denuncia:', 'Lenguaje ofensivo o conducta inapropiada.');
                if (!reason) return;
                button.disabled = true;
                try {
                    const result = await requestJson('/api/denunciar_mensaje', { method: 'POST', body: JSON.stringify({ mensaje_id: button.dataset.messageId, motivo: reason }) });
                    activeChatUser = null;
                    showPanel('widget-window');
                    loadPeople('radar');
                    if (document.getElementById('teacher-list')) loadPeople('teachers');
                    window.alert(result.suspended
                        ? 'Denuncia enviada. El usuario quedó suspendido mientras administración revisa el caso.'
                        : 'Denuncia enviada. Esta conversación quedó bloqueada para ti.');
                } catch (error) {
                    button.disabled = false;
                    button.textContent = error.message;
                }
            });
        });
    };

    const loadMessages = async () => {
        if (!activeChatUser) return;
        try {
            renderMessages(await requestJson(`/api/mensajes/${activeChatUser.id}`));
        } catch (error) {
            renderMessages([{ texto: error.message, emisor_id: 0 }]);
        }
    };

    const openChat = (id, name, photo) => {
        activeChatUser = { id, name };
        const avatar = document.getElementById('chat-target-avatar');
        if (avatar) {
            avatar.src = photo || fallbackAvatar;
            avatar.hidden = false;
        }
        document.getElementById('chat-target-name').textContent = name;
        document.getElementById('proposal-form').hidden = true;
        const proposalToggle = document.getElementById('proposal-toggle');
        if (proposalToggle) {
            proposalToggle.hidden = false;
            proposalToggle.setAttribute('aria-expanded', 'false');
            proposalToggle.title = 'Desplegar propuesta';
        }
        showPanel('chat-universal-box');
        loadMessages();
    };

    const showProfile = async (id) => {
        try {
            const profile = await requestJson(`/api/perfiles/${id}`);
            const modal = document.createElement('div');
            modal.className = 'widget-profile-modal';
            modal.innerHTML = `<div class="widget-profile-card"><button class="btn-close-widget widget-profile-close" type="button">&times;</button><img class="widget-profile-photo" src="${escapeHtml(profile.foto || fallbackAvatar)}" alt="Foto de perfil" onerror="this.onerror=null;this.src='${fallbackAvatar}'"><h3>${escapeHtml(profile.nombre)}</h3><p>${escapeHtml(profile.barrio || 'Barrio no indicado')}</p><p>${escapeHtml(profile.nivel || 'Nivel no indicado')} · ${escapeHtml(profile.mano || 'Mano no indicada')} · ${escapeHtml(profile.reves || 'Revés no indicado')}</p>${profile.biografia ? `<p class="widget-profile-bio">${escapeHtml(profile.biografia)}</p>` : '<p>Este usuario todavía no agregó una descripción.</p>'}</div>`;
            document.body.appendChild(modal);
            modal.addEventListener('click', (event) => { if (event.target === modal || event.target.closest('.widget-profile-close')) modal.remove(); });
        } catch (error) { window.alert(error.message); }
    };

    document.getElementById('chatbot-launcher')?.addEventListener('click', () => showPanel('chatbot-window'));
    document.getElementById('widget-launcher')?.addEventListener('click', () => { showPanel('widget-window'); loadPeople('radar'); });
    document.getElementById('widget-teacher-launcher')?.addEventListener('click', () => { showPanel('widget-teacher-window'); loadPeople('teachers'); });
    dockToggle?.addEventListener('click', (event) => {
        const collapsed = root.classList.toggle('is-collapsed');
        event.currentTarget.setAttribute('aria-expanded', String(!collapsed));
        event.currentTarget.setAttribute('aria-label', collapsed ? 'Mostrar accesos flotantes' : 'Ocultar accesos flotantes');
        event.currentTarget.innerHTML = `<i class="fa-solid fa-chevron-${collapsed ? 'up' : 'down'}"></i>`;
    });
    root.querySelectorAll('[data-close-widget]').forEach((button) => button.addEventListener('click', () => showPanel(null)));
    document.getElementById('chat-back-button')?.addEventListener('click', () => showPanel('widget-window'));

    document.getElementById('chat-form')?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = document.getElementById('chat-input-text');
        const text = input.value.trim();
        if (!text || !activeChatUser) return;
        try {
            await requestJson('/api/enviar_mensaje', { method: 'POST', body: JSON.stringify({ receptor_id: activeChatUser.id, texto: text }) });
            input.value = '';
            loadMessages();
        } catch (error) {
            input.setCustomValidity(error.message);
            input.reportValidity();
        }
    });

    document.getElementById('proposal-toggle')?.addEventListener('click', async () => {
        const form = document.getElementById('proposal-form');
        form.hidden = !form.hidden;
        document.getElementById('proposal-toggle').setAttribute('aria-expanded', String(!form.hidden));
        document.getElementById('proposal-toggle').title = form.hidden ? 'Desplegar propuesta' : 'Ocultar propuesta';
        if (!form.hidden && document.getElementById('proposal-location').options.length <= 1) {
            const locations = await requestJson('/api/locaciones/canchas');
            document.getElementById('proposal-location').innerHTML = '<option value="">Cancha</option>' + locations.map((location) => `<option value="${location.id}">${escapeHtml(location.nombre)}</option>`).join('');
        }
    });

    document.getElementById('proposal-form')?.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!activeChatUser) return;
        const location = document.getElementById('proposal-location');
        const date = document.getElementById('proposal-date').value;
        const time = document.getElementById('proposal-time').value;
        const duration = document.getElementById('proposal-duration').value;
        try {
            await requestJson('/api/enviar_mensaje', { method: 'POST', body: JSON.stringify({ receptor_id: activeChatUser.id, tipo: 'propuesta', texto: `Reserva propuesta en ${location.selectedOptions[0].text}`, datos_extra: { locacion_id: location.value, fecha_reserva: date, hora_reserva: time, duracion: duration } }) });
            event.target.reset();
            event.target.hidden = true;
            document.getElementById('proposal-toggle')?.setAttribute('aria-expanded', 'false');
            const proposalToggle = document.getElementById('proposal-toggle');
            if (proposalToggle) proposalToggle.title = 'Desplegar propuesta';
            loadMessages();
        } catch (error) { window.alert(error.message); }
    });

    if (currentRole === 'profesor') {
        document.getElementById('teacher-launcher-label').textContent = 'Mis chats';
        document.getElementById('teacher-launcher-description').textContent = 'Conversaciones de clase';
        document.getElementById('widget-teacher-launcher').setAttribute('aria-label', 'Abrir mis conversaciones de clase');
    }
})();
