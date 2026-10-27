(() => {
    const form = document.getElementById('chatbot-form');
    const input = document.getElementById('chatbot-input-text');
    const messages = document.getElementById('chatbot-messages-body');
    const sendButton = form?.querySelector('button[type="submit"]');
    if (!form || !input || !messages || !sendButton || form.dataset.initialized) return;
    form.dataset.initialized = 'true';

    const avatarUrl = messages.querySelector('.chatbot-message-avatar')?.src
        || document.querySelector('.widget-chat-profile')?.src
        || '';

    const scrollToLatest = () => {
        messages.scrollTop = messages.scrollHeight;
    };

    const addMessage = (text, own = false, link = null, linkText = 'Más información') => {
        const row = document.createElement('div');
        row.className = `chatbot-message-row ${own ? 'chatbot-message-outgoing' : 'chatbot-message-incoming'}`;

        if (!own && avatarUrl) {
            const avatar = document.createElement('img');
            avatar.className = 'chatbot-message-avatar';
            avatar.src = avatarUrl;
            avatar.alt = '';
            avatar.loading = 'lazy';
            row.appendChild(avatar);
        }

        const bubble = document.createElement('div');
        bubble.className = `msg-bubble ${own ? 'msg-own' : 'msg-other'}`;
        bubble.append(document.createTextNode(text));

        if (link && link.startsWith('/') && !link.startsWith('//')) {
            const anchor = document.createElement('a');
            anchor.href = link;
            anchor.textContent = linkText;
            anchor.className = 'chatbot-more-link';
            bubble.append(document.createElement('br'), anchor);
        }

        const time = document.createElement('time');
        time.className = 'chatbot-message-time';
        time.dateTime = new Date().toISOString();
        time.textContent = new Intl.DateTimeFormat('es-CO', {
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date());
        bubble.appendChild(time);
        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToLatest();
        return row;
    };

    const addTypingIndicator = () => {
        const row = document.createElement('div');
        row.className = 'chatbot-message-row chatbot-message-incoming chatbot-typing-row';
        row.setAttribute('aria-label', 'Tenny está escribiendo');
        if (avatarUrl) {
            const avatar = document.createElement('img');
            avatar.className = 'chatbot-message-avatar';
            avatar.src = avatarUrl;
            avatar.alt = '';
            row.appendChild(avatar);
        }
        const bubble = document.createElement('div');
        bubble.className = 'chatbot-typing';
        for (let index = 0; index < 3; index += 1) {
            bubble.appendChild(document.createElement('span'));
        }
        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToLatest();
        return row;
    };

    const submitMessage = async (text) => {
        const message = text.trim().slice(0, 500);
        if (!message || sendButton.disabled) return;

        addMessage(message, true);
        input.value = '';
        input.focus();
        sendButton.disabled = true;
        form.setAttribute('aria-busy', 'true');
        const typing = addTypingIndicator();

        try {
            const response = await fetch('/api/chatbot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ mensaje: message, pagina: document.body.className })
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || 'Tenny no pudo responder en este momento. Inténtalo de nuevo.');
            }
            if (typeof data.respuesta !== 'string' || !data.respuesta.trim()) {
                throw new Error('No recibimos una respuesta válida. Inténtalo de nuevo.');
            }
            addMessage(data.respuesta, false, data.enlace, data.enlace_texto);
        } catch (error) {
            addMessage(error.message || 'No se pudo conectar con Tenny. Revisa tu conexión e inténtalo de nuevo.');
        } finally {
            typing.remove();
            sendButton.disabled = false;
            form.removeAttribute('aria-busy');
            input.focus();
        }
    };

    document.querySelectorAll('[data-chatbot-prompt]').forEach((button) => {
        button.addEventListener('click', () => submitMessage(button.dataset.chatbotPrompt || ''));
    });
    document.getElementById('chatbot-launcher')?.addEventListener('click', () => {
        window.setTimeout(() => input.focus(), 0);
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        submitMessage(input.value);
    });

    messages.querySelectorAll('.chatbot-message-time').forEach((time) => {
        time.textContent = new Intl.DateTimeFormat('es-CO', {
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date());
    });
})();
