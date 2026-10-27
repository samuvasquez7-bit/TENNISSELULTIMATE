/**
 * TENNISSEL 2.0 - Sistema Interactivo de Catálogo, Carrito y Filtros
 * Ubicación: static/js/carrito.js
 */

function bindNavbarMenu() {
    const menuToggle = document.getElementById("menuToggle");
    const navbarMenu = document.getElementById("navbarMenu");
    const servicesToggle = document.getElementById("servicesToggle");
    const servicesDropdown = document.getElementById("servicesDropdown");
    const mobileMenu = window.matchMedia("(max-width: 1150px)");
    if (!menuToggle || !navbarMenu || menuToggle.dataset.menuBound) return;

    menuToggle.dataset.menuBound = "true";
    const closeNavbarMenu = (restoreFocus = false) => {
        navbarMenu.classList.remove("active");
        menuToggle.classList.remove("open");
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.setAttribute("aria-label", "Abrir menú");
        if (servicesDropdown && servicesToggle) {
            servicesDropdown.classList.remove("open");
            servicesToggle.setAttribute("aria-expanded", "false");
        }
        if (restoreFocus) menuToggle.focus();
    };

    closeNavbarMenu();
    menuToggle.addEventListener("click", (event) => {
        event.stopPropagation();
        if (navbarMenu.classList.contains("active")) {
            closeNavbarMenu();
            return;
        }
        navbarMenu.classList.add("active");
        menuToggle.classList.add("open");
        menuToggle.setAttribute("aria-expanded", "true");
        menuToggle.setAttribute("aria-label", "Cerrar menú");
    });
    servicesToggle?.addEventListener("click", (event) => {
        event.stopPropagation();
        const isOpen = servicesDropdown.classList.toggle("open");
        servicesToggle.setAttribute("aria-expanded", String(isOpen));
    });
    navbarMenu.addEventListener("click", (event) => {
        if (!(event.target instanceof Element) || !event.target.closest("a")) return;
        closeNavbarMenu();
    });
    document.addEventListener("click", (event) => {
        if (!(event.target instanceof Node)) return;
        if (navbarMenu.contains(event.target) || menuToggle.contains(event.target)) return;
        closeNavbarMenu();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        const menuWasOpen = navbarMenu.classList.contains("active");
        const servicesWereOpen = Boolean(servicesDropdown?.classList.contains("open"));
        if (!menuWasOpen && !servicesWereOpen) return;
        event.stopPropagation();
        closeNavbarMenu(menuWasOpen && mobileMenu.matches);
        if (!menuWasOpen && servicesWereOpen) servicesToggle?.focus();
    });
    mobileMenu.addEventListener("change", () => {
        closeNavbarMenu();
    });
}

bindNavbarMenu();

if (typeof window.carritoInitialized === 'undefined') {
    window.carritoInitialized = true;

    document.addEventListener('DOMContentLoaded', () => {
        
        // ==========================================================================
        // 1. CONTROL DE APERTURA DE MENÚS (Navbar & Perfil)
        // ==========================================================================
        const perfilBtn = document.getElementById("perfilBtn");
        const menuPerfil = document.getElementById("menuPerfil");
        const perfilContainer = document.getElementById("perfilContainer");

        bindNavbarMenu();

        if (perfilBtn && menuPerfil && !perfilBtn.dataset.perfilBound) {
            perfilBtn.dataset.perfilBound = "true";
            perfilBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                menuPerfil.classList.toggle("show");
                if (perfilContainer) perfilContainer.classList.toggle("active");
            });
        }

        document.addEventListener("click", (event) => {
            if (menuPerfil) menuPerfil.classList.remove("show");
            if (perfilContainer) perfilContainer.classList.remove("active");
        });

        // ==========================================================================
        // 2. INICIALIZACIÓN Y CONFIGURACIÓN DEL CONTADOR DEL CARRITO
        // ==========================================================================
        actualizarContador();

        // Capturamos los botones de agregar al carrito con protección de duplicados
        const botonesComprar = document.querySelectorAll('.btn-agregar');
        
        botonesComprar.forEach(boton => {
            if (!boton.dataset.carritoBound) {
                boton.dataset.carritoBound = "true";
                boton.addEventListener('click', () => {
                    const id = boton.getAttribute('data-id');
                    const nombre = boton.getAttribute('data-nombre');
                    const precio = parseInt(boton.getAttribute('data-precio'));

                    const productoSeleccionado = {
                        id: id,
                        nombre: nombre,
                        precio: precio,
                        cantidad: 1
                    };

                    añadirAlLocalStorage(productoSeleccionado);
                });
            }
        });

        // ==========================================================================
        // 3. LÓGICA DE FILTRADO DINÁMICO DE PRODUCTOS
        // ==========================================================================
        const botonesFiltro = document.querySelectorAll('.filtro-btn');
        const tarjetasProductos = document.querySelectorAll('.producto-card');

        botonesFiltro.forEach(botonFiltro => {
            if (!botonFiltro.dataset.filtroBound) {
                botonFiltro.dataset.filtroBound = "true";
                botonFiltro.addEventListener('click', () => {
                    botonesFiltro.forEach(btn => btn.classList.remove('active'));
                    botonFiltro.classList.add('active');

                    const categoriaSeleccionada = botonFiltro.getAttribute('data-categoria');

                    tarjetasProductos.forEach(tarjeta => {
                        const categoriaTarjeta = tarjeta.getAttribute('data-categoria');

                        if (categoriaSeleccionada === 'Todos' || categoriaSeleccionada === categoriaTarjeta) {
                            tarjeta.style.display = 'block';
                        } else {
                            tarjeta.style.display = 'none';
                        }
                    });
                });
            }
        });

        // ==========================================================================
        // 4. RENDERIZADO DE LA TABLA DEL CARRITO
        // ==========================================================================
        if (document.getElementById('contenedor-tabla-carrito')) {
            renderizarPaginaCarrito();
        }

        // ==========================================================================
        // 5. LÓGICA DE BÚSQUEDA EN EL NAVBAR
        // ==========================================================================
        const searchInput = document.getElementById('searchInput');
        const searchBtn = document.getElementById('searchBtn');
        const searchResults = document.getElementById('searchResults');

        if (searchInput && searchBtn && searchResults && !searchBtn.dataset.searchBound) {
            searchBtn.dataset.searchBound = 'true';
            const historyKey = 'tennissel:searches:site';
            let activeSearchIndex = -1;
            let searchTimer;
            let searchController;

            const loadRecentSearches = () => {
                try { return JSON.parse(localStorage.getItem(historyKey) || '[]').filter((item) => item && item.text && item.url); }
                catch { return []; }
            };

            const saveRecentSearch = (text, url) => {
                const term = text.trim().slice(0, 100);
                if (!term) return;
                const recent = [{ text: term, url }, ...loadRecentSearches().filter((item) => item.text.toLowerCase() !== term.toLowerCase())].slice(0, 6);
                try { localStorage.setItem(historyKey, JSON.stringify(recent)); } catch {}
            };

            const closeSearchResults = () => {
                searchResults.style.display = 'none';
                searchResults.replaceChildren();
                searchInput.setAttribute('aria-expanded', 'false');
                searchInput.removeAttribute('aria-activedescendant');
                activeSearchIndex = -1;
            };

            const renderSearchResults = (items, heading = '') => {
                searchResults.replaceChildren();
                if (heading) {
                    const title = document.createElement('li');
                    title.className = 'search-results-heading';
                    title.textContent = heading;
                    searchResults.append(title);
                }
                items.forEach((item, index) => {
                    const row = document.createElement('li');
                    row.setAttribute('role', 'option');
                    row.id = `navbar-search-option-${index}`;
                    const link = document.createElement('a');
                    const candidateUrl = item.url || `/productos?q=${encodeURIComponent(item.text || item.valor || '')}`;
                    link.href = candidateUrl.startsWith('/') && !candidateUrl.startsWith('//')
                        ? candidateUrl
                        : `/productos?q=${encodeURIComponent(item.text || item.valor || '')}`;
                    link.setAttribute('aria-selected', 'false');
                    const title = document.createElement('span');
                    title.textContent = item.valor || item.text;
                    const type = document.createElement('small');
                    type.textContent = item.tipo || 'Búsqueda reciente';
                    link.append(title, type);
                    link.addEventListener('click', () => saveRecentSearch(searchInput.value || item.text || item.valor, link.href));
                    row.append(link);
                    searchResults.append(row);
                });
                if (!items.length) {
                    const empty = document.createElement('li');
                    empty.className = 'search-no-results';
                    empty.textContent = 'No se encontraron secciones';
                    searchResults.append(empty);
                }
                searchResults.style.display = 'block';
                searchInput.setAttribute('aria-expanded', 'true');
            };

            const showRecentSearches = () => {
                const recent = loadRecentSearches();
                if (recent.length) renderSearchResults(recent, 'Búsquedas recientes');
                else closeSearchResults();
            };

            const runSearch = () => {
                const term = searchInput.value.trim();
                if (!term) return;
                const url = `/productos?q=${encodeURIComponent(term)}`;
                saveRecentSearch(term, url);
                window.location.href = url;
            };

            searchInput.addEventListener('focus', () => {
                if (!searchInput.value.trim()) showRecentSearches();
            });
            searchInput.addEventListener('input', () => {
                window.clearTimeout(searchTimer);
                if (searchController) searchController.abort();
                const term = searchInput.value.trim();
                if (!term) {
                    showRecentSearches();
                    return;
                }
                searchTimer = window.setTimeout(async () => {
                    searchController = new AbortController();
                    try {
                        const response = await fetch(`/api/buscar-sitio?q=${encodeURIComponent(term)}`, {
                            headers: { Accept: 'application/json' },
                            signal: searchController.signal
                        });
                        const data = await response.json();
                        renderSearchResults(data.sugerencias || []);
                    } catch (error) {
                        if (error.name !== 'AbortError') closeSearchResults();
                    }
                }, 130);
            });
            searchInput.addEventListener('keydown', (event) => {
                const options = [...searchResults.querySelectorAll('[role="option"] a')];
                if (event.key === 'ArrowDown' && options.length) {
                    event.preventDefault();
                    activeSearchIndex = (activeSearchIndex + 1) % options.length;
                } else if (event.key === 'ArrowUp' && options.length) {
                    event.preventDefault();
                    activeSearchIndex = activeSearchIndex <= 0 ? options.length - 1 : activeSearchIndex - 1;
                } else if (event.key === 'Enter') {
                    if (activeSearchIndex >= 0 && options[activeSearchIndex]) {
                        event.preventDefault();
                        options[activeSearchIndex].click();
                    } else {
                        event.preventDefault();
                        runSearch();
                    }
                    return;
                } else if (event.key === 'Escape') {
                    closeSearchResults();
                    return;
                } else {
                    return;
                }
                options.forEach((option, index) => {
                    const active = index === activeSearchIndex;
                    option.setAttribute('aria-selected', String(active));
                    option.closest('[role="option"]').id = `navbar-search-option-${index}`;
                });
                if (activeSearchIndex >= 0 && options[activeSearchIndex]) {
                    searchInput.setAttribute('aria-activedescendant', `navbar-search-option-${activeSearchIndex}`);
                }
            });
            searchBtn.addEventListener('click', runSearch);
            document.addEventListener('click', (event) => {
                if (!event.target.closest('.navbar-search')) closeSearchResults();
            });
        }
    });
}

// ==========================================================================
// FUNCIONES GLOBALES DEL CARRITO (Se mantienen igual)
// ==========================================================================

function añadirAlLocalStorage(producto) {
    let listaCarrito = JSON.parse(localStorage.getItem('carrito')) || [];
    const productoExistente = listaCarrito.find(item => item.id === producto.id);

    if (productoExistente) {
        productoExistente.cantidad += 1;
    } else {
        listaCarrito.push(producto);
    }

    localStorage.setItem('carrito', JSON.stringify(listaCarrito));
    actualizarContador();
    alert(`¡Se ha añadido "${producto.nombre}" con éxito al carrito! 🛒`);
}

function actualizarContador() {
    const contenedorContador = document.getElementById('contador-carrito');
    
    if (contenedorContador) {
        let listaCarrito = JSON.parse(localStorage.getItem('carrito')) || [];
        const totalProductos = listaCarrito.reduce((acumulado, item) => acumulado + item.cantidad, 0);
        contenedorContador.textContent = totalProductos;
    }
}

function renderizarPaginaCarrito() {
    const tabla = document.getElementById('contenedor-tabla-carrito');
    const totalContenedor = document.getElementById('gran-total-carrito');
    
    let carrito = JSON.parse(localStorage.getItem('carrito')) || [];

    if (carrito.length === 0) {
        tabla.innerHTML = `
            <div class="text-center py-5">
                <p class="text-muted fs-5">No tienes productos seleccionados todavía.</p>
                <a href="/productos" class="btn-productos-volver">Ver Catálogo de Productos</a>
            </div>
        `;
        if (totalContenedor) totalContenedor.innerText = "$0";
        return;
    }

    let htmlGenerado = '';
    let sumaGranTotal = 0;

    carrito.forEach(item => {
        let subtotal = item.precio * item.cantidad;
        sumaGranTotal += subtotal;

        htmlGenerado += `
            <div class="carrito-item">
                <div class="carrito-info">
                    <h5>${item.nombre}</h5>
                    <small>Precio unitario: $${item.precio.toLocaleString('es-CO')}</small>
                </div>
                
                <div class="carrito-cantidad">
                    <button class="btn-cantidad" onclick="cambiarCantidad('${item.id}', -1)">-</button>
                    <span class="cantidad-numero">${item.cantidad}</span>
                    <button class="btn-cantidad" onclick="cambiarCantidad('${item.id}', 1)">+</button>
                </div>

                <div class="carrito-acciones">
                    <span class="subtotal-precio">$${subtotal.toLocaleString('es-CO')}</span>
                    <button class="btn-eliminar" onclick="eliminarDelCarrito('${item.id}')">🗑️</button>
                </div>
            </div>
        `;
    });

    tabla.innerHTML = htmlGenerado;
    if (totalContenedor) {
        totalContenedor.innerText = '$' + sumaGranTotal.toLocaleString('es-CO');
    }
}

function cambiarCantidad(id, cambio) {
    let carrito = JSON.parse(localStorage.getItem('carrito')) || [];
    const producto = carrito.find(item => item.id === id);

    if (producto) {
        producto.cantidad += cambio;
        if (producto.cantidad <= 0) {
            carrito = carrito.filter(item => item.id !== id);
        }
    }

    localStorage.setItem('carrito', JSON.stringify(carrito));
    actualizarContador();
    renderizarPaginaCarrito();
}

function eliminarDelCarrito(id) {
    let carrito = JSON.parse(localStorage.getItem('carrito')) || [];
    carrito = carrito.filter(item => item.id !== id);
    
    localStorage.setItem('carrito', JSON.stringify(carrito));
    actualizarContador();
    renderizarPaginaCarrito();
}

function vaciarCarritoCompleto() {
    if (confirm('¿Seguro que deseas remover todos los productos del carrito?')) {
        localStorage.removeItem('carrito');
        actualizarContador();
        renderizarPaginaCarrito();
    }
}

function procesarPagoFinal() {
    alert('Los pagos están temporalmente deshabilitados hasta configurar una pasarela segura. Tu carrito se conservó.');
}
