(() => {
    const peopleList = document.getElementById('matchmaking-people');
    const teacherList = document.getElementById('matchmaking-teachers');
    const messages = document.getElementById('matchmaking-messages');
    const input = document.getElementById('matchmaking-input');
    const sendButton = document.getElementById('matchmaking-send');
    const title = document.getElementById('matchmaking-chat-title');
    const chatAvatar = document.getElementById('matchmaking-chat-avatar');
    const liveStatus = document.getElementById('matchmaking-live-status');
    let activeUser = null;
    let loadingMessages = false;
    let renderedMessagesSnapshot = '';
    const directorySnapshots = new Map();
    input.disabled = true;
    sendButton.disabled = true;

    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
    const api = async (url, options = {}) => { const response = await fetch(url, { cache: 'no-store', ...options }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.error || `No se pudo completar la acción (${response.status}).`); return data; };
    const fallbackAvatar = '/static/IMG/avatar-tennisel-1.png?v=20261005-7';
    const avatar = (person) => person.foto || fallbackAvatar;

    const renderPeople = (items, target) => {
        target.innerHTML = items.length ? items.map((person) => `<article class="match-person" data-person="${person.id}" data-name="${escapeHtml(person.nombre)}">
            <img src="${escapeHtml(avatar(person))}" alt="Foto de ${escapeHtml(person.nombre)}" onerror="this.onerror=null;this.src='${fallbackAvatar}'"><div><strong>${escapeHtml(person.nombre)}</strong>${person.rol === 'admin' ? '<small class="match-person-admin">Administración TENNISSEL</small>' : person.rol === 'tienda' ? '<small>Tienda TENNISSEL</small>' : ''}<span>${escapeHtml(person.barrio || 'Barrio no indicado')} · ${escapeHtml(person.nivel || 'Nivel no indicado')}</span>${person.biografia ? `<small class="match-person-bio">${escapeHtml(person.biografia)}</small>` : ''}<small>${escapeHtml(person.mano || 'Mano no indicada')} · ${escapeHtml(person.reves || 'Revés no indicado')}</small></div><button type="button" data-action="${person.estado_chat}" data-contact="${person.contacto_id || ''}">${person.estado_chat === 'aceptado' ? 'Chat' : person.estado_chat === 'recibido' ? 'Aceptar' : person.estado_chat === 'enviado' ? 'Continuar chat' : 'Contactar'}</button></article>`).join('') : '<p class="match-empty">No hay personas disponibles.</p>';
        target.querySelectorAll('.match-person').forEach((card) => {
            card.addEventListener('click', () => openProfile(card.dataset.person));
            card.querySelector('button').addEventListener('click', async (event) => { event.stopPropagation(); await handleContact(card); });
        });
    };

    const handleContact = async (card) => {
        const button = card.querySelector('button');
        const state = button.dataset.action;
        const id = Number(card.dataset.person);
        try {
            const photo = card.querySelector('img')?.src || fallbackAvatar;
            if (state === 'aceptado') return openChat(id, card.dataset.name, photo);
            if (state === 'recibido') { await api('/api/responder_solicitud', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contacto_id: button.dataset.contact, estado: 'aceptada' }) }); return openChat(id, card.dataset.name, photo); }
            const contact = await api('/api/solicitar_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ receptor_id: id }) });
            if (contact.estado === 'aceptada' || contact.status === 'accepted') return openChat(id, card.dataset.name, photo);
            button.textContent = 'Enviada'; button.disabled = true;
        } catch (error) { button.textContent = error.message; }
    };

    const loadPeople = async () => {
        try {
            const people = await api('/api/matchmaking/usuarios');
            const snapshot = JSON.stringify(people);
            if (directorySnapshots.get(peopleList) !== snapshot) {
                renderPeople(people, peopleList);
                directorySnapshots.set(peopleList, snapshot);
            }
        } catch (error) {
            directorySnapshots.delete(peopleList);
            peopleList.innerHTML = `<p class="match-empty">${escapeHtml(error.message)}</p>`;
        }
        if (teacherList) {
            try {
                const teachers = await api('/api/profesores');
                const snapshot = JSON.stringify(teachers);
                if (directorySnapshots.get(teacherList) !== snapshot) {
                    renderPeople(teachers, teacherList);
                    directorySnapshots.set(teacherList, snapshot);
                }
            } catch (error) {
                directorySnapshots.delete(teacherList);
                teacherList.innerHTML = `<p class="match-empty">${escapeHtml(error.message)}</p>`;
            }
        }
    };
    const openChat = (id, name, photo) => {
        activeUser = id;
        renderedMessagesSnapshot = '';
        input.disabled = false;
        document.getElementById('matchmaking-send').disabled = false;
        if (proposalToggle) proposalToggle.disabled = false;
        if (proposalForm) {
            proposalForm.reset();
            proposalForm.hidden = true;
        }
        proposalToggle?.setAttribute('aria-expanded', 'false');
        if (proposalToggle) proposalToggle.title = 'Desplegar propuesta';
        title.textContent = `Chat con ${name}`;
        if (liveStatus) {
            liveStatus.textContent = 'Conectando…';
            liveStatus.dataset.state = 'connecting';
        }
        document.querySelectorAll('.match-person[aria-current="true"]').forEach((card) => {
            card.removeAttribute('aria-current');
            card.classList.remove('is-active');
        });
        document.querySelectorAll('.match-person').forEach((card) => {
            if (Number(card.dataset.person) === Number(id)) {
                card.setAttribute('aria-current', 'true');
                card.classList.add('is-active');
            }
        });
        if (chatAvatar) {
            chatAvatar.src = photo || fallbackAvatar;
            chatAvatar.hidden = false;
        }
        messages.innerHTML = '<p class="match-empty">Cargando conversación...</p>';
        loadMessages();
    };
    const loadMessages = async () => {
        if (!activeUser || loadingMessages) return;
        const conversationUser = activeUser;
        loadingMessages = true;
        try {
            const data = await api(`/api/mensajes/${conversationUser}`);
            if (activeUser !== conversationUser) return;
            const snapshot = JSON.stringify(data);
            if (snapshot === renderedMessagesSnapshot) {
                if (liveStatus) {
                    liveStatus.textContent = 'Sincronizado · mensajes al día';
                    liveStatus.dataset.state = 'online';
                }
                return;
            }
            const wasNearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 90;
            renderedMessagesSnapshot = snapshot;
            messages.innerHTML = data.length ? data.map((message) => {
                const own = message.emisor_id === Number(document.body.dataset.userId);
                if (message.tipo === 'propuesta') {
                    let proposal = {};
                    try { proposal = JSON.parse(message.datos_extra || '{}'); } catch (error) { proposal = {}; }
                    const pending = !own && message.estado_propuesta === 'pendiente';
                    const actions = pending ? `<div class="proposal-actions"><button type="button" data-proposal-action="aceptada" data-message-id="${message.id}">Aceptar reserva</button><button type="button" data-proposal-action="rechazada" data-message-id="${message.id}">Rechazar</button></div>` : `<small>${escapeHtml(message.estado_propuesta || 'pendiente')}</small>`;
                    const reportButton = !own && document.body.dataset.role !== 'admin' ? `<button class="message-report" data-message-id="${message.id}" type="button">Denunciar</button>` : '';
                    return `<div class="match-message ${own ? 'mine' : 'theirs'}"><strong>Propuesta de reserva</strong><br>${escapeHtml(message.texto)}<br><small>${escapeHtml(proposal.fecha_reserva || '')} · ${escapeHtml(proposal.hora_reserva || '')} · ${escapeHtml(proposal.duracion || '1')} hora(s)</small>${actions}${reportButton}</div>`;
                }
                const reportButton = message.id && !own && document.body.dataset.role !== 'admin' ? `<button class="message-report" data-message-id="${message.id}" type="button">Denunciar</button>` : '';
                return `<div class="match-message ${own ? 'mine' : 'theirs'}">${escapeHtml(message.texto)}${reportButton}</div>`;
            }).join('') : '<p class="match-empty">Todavía no hay mensajes.</p>';
            messages.querySelectorAll('[data-proposal-action]').forEach((button) => button.addEventListener('click', async () => {
                button.disabled = true;
                try { await api('/api/responder_propuesta', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mensaje_id: button.dataset.messageId, accion: button.dataset.proposalAction }) }); loadMessages(); }
                catch (error) { button.disabled = false; button.textContent = error.message; }
            }));
            messages.querySelectorAll('.message-report').forEach((button) => button.addEventListener('click', async () => {
                const reason = window.prompt('Motivo de la denuncia:', 'Lenguaje ofensivo o conducta inapropiada.');
                if (!reason) return;
                button.disabled = true;
                try {
                    const result = await api('/api/denunciar_mensaje', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mensaje_id: button.dataset.messageId, motivo: reason }) });
                    activeUser = null;
                    input.disabled = true;
                    document.getElementById('matchmaking-send').disabled = true;
                    if (proposalForm) {
                        proposalForm.reset();
                        proposalForm.hidden = true;
                    }
                    if (proposalToggle) {
                        proposalToggle.disabled = true;
                        proposalToggle.setAttribute('aria-expanded', 'false');
                        proposalToggle.title = 'Desplegar propuesta';
                    }
                    title.textContent = 'Conversación bloqueada';
                    if (chatAvatar) chatAvatar.hidden = true;
                    messages.innerHTML = '<p class="match-empty">Denuncia enviada. Esta conversación quedó bloqueada para ti.</p>';
                    await loadPeople();
                    window.alert(result.suspended
                        ? 'Denuncia enviada. El usuario quedó suspendido mientras administración revisa el caso.'
                        : 'Denuncia enviada. Esta conversación quedó bloqueada para ti.');
                } catch (error) {
                    button.disabled = false;
                    button.textContent = error.message;
                }
            }));
            if (wasNearBottom) messages.scrollTop = messages.scrollHeight;
            if (liveStatus) {
                liveStatus.textContent = 'Sincronizado · mensajes al día';
                liveStatus.dataset.state = 'online';
            }
        } catch (error) {
            if (activeUser === conversationUser) {
                if (liveStatus) {
                    liveStatus.textContent = 'Reconectando…';
                    liveStatus.dataset.state = 'offline';
                }
                if (!renderedMessagesSnapshot) messages.innerHTML = `<p class="match-empty">${escapeHtml(error.message)}</p>`;
            }
        } finally {
            loadingMessages = false;
        }
    };
    const closeProfile = () => { document.getElementById('matchmaking-profile-modal').hidden = true; };
    const openProfile = async (id) => { try { const profile = await api(`/api/perfiles/${id}`); document.getElementById('matchmaking-profile').innerHTML = `<button type="button" class="match-profile-close" data-close-profile aria-label="Cerrar perfil">&times;</button><img src="${escapeHtml(avatar(profile))}" alt="Foto de perfil" onerror="this.onerror=null;this.src='${fallbackAvatar}'"><h3>${escapeHtml(profile.nombre)}</h3>${profile.rol === 'tienda' ? '<p>Tienda TENNISSEL</p>' : ''}<p>${escapeHtml(profile.barrio || 'Barrio no indicado')}</p><p>${escapeHtml(profile.nivel || 'Nivel no indicado')} · ${escapeHtml(profile.mano || 'Mano no indicada')} · ${escapeHtml(profile.reves || 'Revés no indicado')}</p>${profile.biografia ? `<p class="match-profile-bio">${escapeHtml(profile.biografia)}</p>` : '<p>Este usuario todavía no agregó una descripción.</p>'}`; document.getElementById('matchmaking-profile-modal').hidden = false; } catch (error) { window.alert(error.message); } };

    const sendMessage = async () => {
        const text = input.value.trim();
        if (!text || !activeUser) return;
        const sendButton = document.getElementById('matchmaking-send');
        sendButton.disabled = true;
        try {
            await api('/api/enviar_mensaje', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ receptor_id: activeUser, texto: text }) });
            input.value = '';
            loadMessages();
        } catch (error) {
            messages.insertAdjacentHTML('beforeend', `<p class="match-error">${escapeHtml(error.message)}</p>`);
        } finally {
            sendButton.disabled = false;
        }
    };
    document.getElementById('matchmaking-send')?.addEventListener('click', sendMessage);
    input?.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); sendMessage(); } });
    const proposalToggle = document.getElementById('matchmaking-proposal-toggle');
    const proposalForm = document.getElementById('matchmaking-proposal-form');
    const proposalLocation = document.getElementById('matchmaking-proposal-location');
    const proposalDate = document.getElementById('matchmaking-proposal-date');
    const proposalTime = document.getElementById('matchmaking-proposal-time');
    const proposalDuration = document.getElementById('matchmaking-proposal-duration');
    const proposalSummary = document.getElementById('matchmaking-proposal-summary');
    const proposalLocationStatus = document.getElementById('matchmaking-proposal-location-status');
    if (proposalToggle) proposalToggle.disabled = true;
    if (proposalDate) proposalDate.min = new Date().toISOString().slice(0, 10);
    const updateProposalSummary = () => {
        if (!proposalSummary) return;
        const locationName = proposalLocation?.selectedOptions[0]?.text;
        const duration = proposalDuration?.value;
        proposalSummary.textContent = locationName && proposalDate?.value && proposalTime?.value
            ? `${locationName} · ${proposalDate.value} · ${proposalTime.value} · ${duration} hora${duration === '1' ? '' : 's'}`
            : 'Selecciona lugar, fecha y hora';
    };
    [proposalLocation, proposalDate, proposalTime, proposalDuration].forEach((field) => field?.addEventListener('input', updateProposalSummary));
    proposalLocation?.addEventListener('change', updateProposalSummary);
    const loadProposalLocations = async () => {
        if (!proposalLocation || proposalLocation.dataset.loaded === 'true') return;
        proposalLocation.disabled = true;
        if (proposalLocationStatus) proposalLocationStatus.textContent = 'Buscando canchas disponibles...';
        try {
            const locations = await api('/api/locaciones/canchas');
            proposalLocation.innerHTML = locations.length
                ? '<option value="">Selecciona una cancha</option>' + locations.map((location) => `<option value="${location.id}">${escapeHtml(location.nombre)}</option>`).join('')
                : '<option value="">No hay canchas registradas</option>';
            proposalLocation.dataset.loaded = 'true';
            if (proposalLocationStatus) proposalLocationStatus.textContent = locations.length ? `${locations.length} canchas disponibles` : 'Registra una cancha para continuar.';
        } catch (error) {
            proposalLocation.innerHTML = '<option value="">No se pudieron cargar</option>';
            if (proposalLocationStatus) proposalLocationStatus.textContent = error.message;
        } finally {
            proposalLocation.disabled = false;
        }
    };
    proposalToggle?.addEventListener('click', async () => {
        if (!activeUser) return;
        proposalForm.hidden = !proposalForm.hidden;
        proposalToggle.setAttribute('aria-expanded', String(!proposalForm.hidden));
        proposalToggle.title = proposalForm.hidden ? 'Desplegar propuesta' : 'Ocultar propuesta';
        if (!proposalForm.hidden) loadProposalLocations();
    });
    proposalForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!activeUser) return;
        const date = document.getElementById('matchmaking-proposal-date').value;
        const time = document.getElementById('matchmaking-proposal-time').value;
        const duration = document.getElementById('matchmaking-proposal-duration').value;
        const locationName = proposalLocation.selectedOptions[0]?.text || 'Cancha';
        try {
            await api('/api/enviar_mensaje', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ receptor_id: activeUser, tipo: 'propuesta', texto: `Propuesta en ${locationName}`, datos_extra: { locacion_id: proposalLocation.value, fecha_reserva: date, hora_reserva: time, duracion: duration } }) });
            proposalForm.reset(); proposalForm.hidden = true; proposalToggle?.setAttribute('aria-expanded', 'false'); if (proposalToggle) proposalToggle.title = 'Desplegar propuesta'; updateProposalSummary(); loadMessages();
        } catch (error) { messages.insertAdjacentHTML('beforeend', `<p class="match-error">${escapeHtml(error.message)}</p>`); }
    });
    document.getElementById('matchmaking-profile-modal')?.addEventListener('click', (event) => {
        if (event.target.id === 'matchmaking-profile-modal' || event.target.closest('[data-close-profile]')) closeProfile();
    });
    loadPeople();
    window.setInterval(() => {
        if (!document.hidden) loadPeople();
    }, 8000);
    window.setInterval(() => {
        if (!document.hidden && activeUser) loadMessages();
    }, 1200);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            loadPeople();
            if (activeUser) loadMessages();
        }
    });
})();
