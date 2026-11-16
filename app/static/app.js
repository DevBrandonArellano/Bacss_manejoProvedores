/* Manejo de Proveedores — mejoras de uso en el navegador.
 * Todo es mejora progresiva: sin JavaScript los formularios siguen funcionando con los controles normales.
 * Sin dependencias externas (la app no depende de internet).
 */
(function () {
  "use strict";

  var normalizar = function (texto) {
    return (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  };

  // ------------------------------------------------------------------ buscador sobre <select data-buscar>
  var MAX_RESULTADOS = 60;
  var contadorCombos = 0;

  function combobox(select) {
    if (select.dataset.listo) return;
    select.dataset.listo = "1";
    var id = "combo" + ++contadorCombos;

    var envoltura = document.createElement("div");
    envoltura.className = "combo";
    var entrada = document.createElement("input");
    entrada.type = "text";
    entrada.className = "combo-entrada";
    entrada.autocomplete = "off";
    entrada.spellcheck = false;
    entrada.placeholder = select.dataset.buscar || "Escriba para buscar…";
    entrada.setAttribute("role", "combobox");
    entrada.setAttribute("aria-autocomplete", "list");
    entrada.setAttribute("aria-expanded", "false");
    entrada.setAttribute("aria-controls", id + "-lista");
    var lista = document.createElement("ul");
    lista.className = "combo-lista";
    lista.id = id + "-lista";
    lista.setAttribute("role", "listbox");
    lista.hidden = true;

    // La etiqueta pasa a apuntar al buscador.
    if (select.id) {
      var etiqueta = document.querySelector('label[for="' + select.id + '"]');
      entrada.id = select.id + "-buscar";
      if (etiqueta) etiqueta.htmlFor = entrada.id;
    }
    if (select.required) {
      select.required = false;
      entrada.required = true;
    }
    select.parentNode.insertBefore(envoltura, select);
    envoltura.appendChild(entrada);
    envoltura.appendChild(lista);
    envoltura.appendChild(select);
    select.hidden = true;
    select.tabIndex = -1;

    var opciones = Array.prototype.filter.call(select.options, function (o) { return o.value; }).map(function (o) {
      return { opcion: o, texto: o.text, norm: normalizar(o.text), frecuente: o.dataset.frecuente === "1" };
    });
    var visibles = [];
    var activa = -1;

    function textoElegido() {
      var o = select.selectedOptions[0];
      return o && o.value ? o.text : "";
    }
    entrada.value = textoElegido();

    function cerrar() {
      lista.hidden = true;
      entrada.setAttribute("aria-expanded", "false");
      entrada.removeAttribute("aria-activedescendant");
      activa = -1;
    }

    function marcar(i) {
      var items = lista.querySelectorAll("[role=option]");
      if (!items.length) return;
      activa = (i + items.length) % items.length;
      items.forEach(function (li, j) { li.classList.toggle("activa", j === activa); });
      entrada.setAttribute("aria-activedescendant", items[activa].id);
      items[activa].scrollIntoView({ block: "nearest" });
    }

    function agregarTitulo(texto) {
      var li = document.createElement("li");
      li.className = "combo-titulo";
      li.setAttribute("role", "presentation");
      li.textContent = texto;
      lista.appendChild(li);
    }

    function agregar(item) {
      var li = document.createElement("li");
      li.id = id + "-op" + visibles.length;
      li.setAttribute("role", "option");
      li.textContent = item.texto;
      if (item.opcion.value === select.value) li.setAttribute("aria-selected", "true");
      li.addEventListener("mousedown", function (e) { e.preventDefault(); elegir(item); });
      visibles.push(item);
      lista.appendChild(li);
    }

    function mostrar() {
      var q = normalizar(entrada.value);
      if (q === normalizar(textoElegido())) q = "";  // al enfocar con algo ya elegido se ve la lista completa
      var palabras = q ? q.split(" ") : [];
      var coinciden = opciones.filter(function (o) {
        return palabras.every(function (p) { return o.norm.indexOf(p) !== -1; });
      });
      if (q) {
        // Primero lo que empieza por lo escrito.
        coinciden.sort(function (a, b) { return (b.norm.indexOf(q) === 0) - (a.norm.indexOf(q) === 0); });
      }
      lista.innerHTML = "";
      visibles = [];
      if (!q) {
        var frecuentes = coinciden.filter(function (o) { return o.frecuente; });
        if (frecuentes.length) {
          agregarTitulo("Más usados");
          frecuentes.forEach(agregar);
          agregarTitulo("Todos");
        }
      }
      coinciden.slice(0, MAX_RESULTADOS).forEach(agregar);
      if (!coinciden.length) {
        agregarTitulo("Sin coincidencias. Pruebe con otra palabra.");
      } else if (coinciden.length > MAX_RESULTADOS) {
        agregarTitulo("… y " + (coinciden.length - MAX_RESULTADOS) + " más. Siga escribiendo para acotar.");
      }
      lista.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
      activa = -1;
      if (q && visibles.length) marcar(0);
    }

    function elegir(item) {
      var cambio = select.value !== item.opcion.value;
      select.value = item.opcion.value;
      entrada.value = item.texto;
      entrada.setCustomValidity("");
      cerrar();
      if (cambio) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // Al salir, lo escrito tiene que corresponder a una opción; si no, se vuelve a lo elegido o se vacía.
    function sincronizar() {
      var q = normalizar(entrada.value);
      if (q === normalizar(textoElegido())) {
        entrada.value = textoElegido();
        return;
      }
      if (!q) {
        if (select.value) {
          select.value = "";
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        return;
      }
      var exacta = opciones.filter(function (o) { return o.norm === q; });
      if (exacta.length === 1) return elegir(exacta[0]);
      if (visibles.length === 1) return elegir(visibles[0]);
      entrada.value = textoElegido();
    }

    entrada.addEventListener("focus", function () { entrada.select(); mostrar(); });
    entrada.addEventListener("input", mostrar);
    entrada.addEventListener("blur", function () { sincronizar(); cerrar(); });
    entrada.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (lista.hidden) mostrar(); marcar(activa + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); marcar(activa - 1); }
      else if (e.key === "Enter") {
        if (!lista.hidden && activa >= 0) { e.preventDefault(); elegir(visibles[activa]); }
        else { sincronizar(); }
      }
      else if (e.key === "Escape") { if (!lista.hidden) { e.preventDefault(); entrada.value = textoElegido(); cerrar(); } }
    });
  }

  // ------------------------------------------------------------------ mostrar campos según una opción
  // <div data-mostrar-si="credito=dias">: visible solo si el control #credito vale "dias".
  function actualizarCondicionales(raiz) {
    (raiz || document).querySelectorAll("[data-mostrar-si]").forEach(function (el) {
      var partes = el.dataset.mostrarSi.split("=");
      var control = document.getElementById(partes[0]);
      if (!control) return;
      var mostrar = partes[1].split(",").indexOf(control.value) !== -1;
      el.hidden = !mostrar;
      el.querySelectorAll("input, select, textarea").forEach(function (c) { c.disabled = !mostrar; });
    });
  }

  // ------------------------------------------------------------------ validación mientras se escribe
  var CORREO = /^[^@\s;,]+@[^@\s;,]+\.[^@\s;,.]+$/;

  function mensajeCampo(campo, texto) {
    var id = campo.id + "-problema";
    var caja = document.getElementById(id);
    if (!caja) {
      caja = document.createElement("div");
      caja.id = id;
      caja.className = "ayuda-error";
      caja.setAttribute("aria-live", "polite");
      campo.insertAdjacentElement("afterend", caja);
      campo.setAttribute("aria-describedby", ((campo.getAttribute("aria-describedby") || "") + " " + id).trim());
    }
    caja.textContent = texto || "";
    caja.hidden = !texto;
    campo.classList.toggle("con-error", !!texto);
  }

  function validarCampo(campo) {
    var valor = campo.value.replace(/\s+/g, "");
    if (campo.dataset.validar === "id") {
      var tipo = document.getElementById(campo.dataset.tipo);
      var opcion = tipo && tipo.selectedOptions[0];
      var largo = opcion && parseInt(opcion.dataset.largo || "", 10);
      var nombre = opcion ? opcion.text : "";
      if (valor && largo && !(/^\d+$/.test(valor) && valor.length === largo)) {
        mensajeCampo(campo, "Un número de " + nombre + " debe tener " + largo + " dígitos (lleva " + valor.length + ").");
      } else if (valor && tipo && !tipo.value) {
        mensajeCampo(campo, "Elija también el tipo de ID.");
      } else {
        mensajeCampo(campo, "");
      }
    } else if (campo.dataset.validar === "correo") {
      var partes = campo.value.split(";").map(function (p) { return p.trim(); }).filter(Boolean);
      var mal = partes.filter(function (p) { return !CORREO.test(p); });
      mensajeCampo(campo, mal.length ? "Revise el correo: «" + mal[0] + "» no parece válido. Varios se separan con punto y coma." : "");
    }
  }

  // ------------------------------------------------------------------ barra de selección de facturas
  function actualizarSeleccion() {
    var barra = document.getElementById("seleccion");
    if (!barra) return;
    var marcadas = document.querySelectorAll("input[form=seleccion][name=ids]:checked");
    var sumas = {};
    marcadas.forEach(function (c) {
      var moneda = c.dataset.moneda || "USD";
      sumas[moneda] = (sumas[moneda] || 0) + parseInt(c.dataset.valor || "0", 10);
    });
    var total = Object.keys(sumas).sort().map(function (m) {
      return m + " " + (sumas[m] / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }).join(" · ");
    var n = marcadas.length;
    barra.querySelector("[data-cuenta]").textContent = n
      ? n + (n === 1 ? " factura seleccionada" : " facturas seleccionadas") + " · " + total
      : "Marque facturas en la lista para exportarlas o marcarlas como pagadas.";
    barra.classList.toggle("con-seleccion", n > 0);
    barra.querySelectorAll("[data-requiere-seleccion]").forEach(function (b) { b.disabled = n === 0; });
  }

  // ------------------------------------------------------------------ orden y páginas del listado de proveedores
  function irA(enlace) {
    var formulario = document.getElementById("filtros");
    if (!formulario || !window.htmx) return false;
    ["orden", "dir", "pagina"].forEach(function (campo) {
      if (enlace.dataset[campo] !== undefined && formulario.elements[campo]) formulario.elements[campo].value = enlace.dataset[campo];
    });
    if (enlace.dataset.pagina === undefined && formulario.elements.pagina) formulario.elements.pagina.value = "1";
    htmx.trigger(formulario, "buscar");
    return true;
  }

  // ------------------------------------------------------------------ ojito para ver la contraseña
  var OJO = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var OJO_TACHADO = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.9 10.9 0 0112 19c-7 0-11-7-11-7a19.8 19.8 0 015.06-5.94M9.9 4.24A10.9 10.9 0 0112 4c7 0 11 7 11 7a19.8 19.8 0 01-3.17 4.19M14.12 14.12a3 3 0 11-4.24-4.24"/><path d="M1 1l22 22"/></svg>';

  function ojo(campo) {
    if (campo.dataset.ojoListo) return;
    campo.dataset.ojoListo = "1";
    var envoltura = document.createElement("div");
    envoltura.className = "campo-clave";
    campo.parentNode.insertBefore(envoltura, campo);
    envoltura.appendChild(campo);
    var boton = document.createElement("button");
    boton.type = "button";
    boton.className = "ojo";
    boton.setAttribute("aria-pressed", "false");
    boton.setAttribute("aria-label", "Mostrar contraseña");
    boton.title = "Mostrar contraseña";
    boton.innerHTML = OJO;
    // mousedown no quita el foco del campo: se puede seguir escribiendo.
    boton.addEventListener("mousedown", function (e) { e.preventDefault(); });
    boton.addEventListener("click", function () {
      var visible = campo.type === "password";
      campo.type = visible ? "text" : "password";
      boton.setAttribute("aria-pressed", visible ? "true" : "false");
      boton.setAttribute("aria-label", visible ? "Ocultar contraseña" : "Mostrar contraseña");
      boton.title = boton.getAttribute("aria-label");
      boton.innerHTML = visible ? OJO_TACHADO : OJO;
      campo.focus();
    });
    envoltura.appendChild(boton);
    // Al enviar siempre se vuelve a ocultar, para que el navegador no la guarde como texto.
    if (campo.form) campo.form.addEventListener("submit", function () { campo.type = "password"; });
  }

  // ------------------------------------------------------------------ inicio y delegación de eventos
  function iniciar(raiz) {
    raiz = raiz || document;
    raiz.querySelectorAll("input[data-ojo]").forEach(ojo);
    raiz.querySelectorAll("select[data-buscar]").forEach(combobox);
    actualizarCondicionales(raiz);
    raiz.querySelectorAll("[data-validar]").forEach(function (c) { if (c.value) validarCampo(c); });
    actualizarSeleccion();
    // Los avisos de éxito se van solos; los de error y alerta se quedan hasta cerrarlos.
    raiz.querySelectorAll(".aviso[data-cerrable]").forEach(function (aviso) {
      if (aviso.dataset.listo) return;
      aviso.dataset.listo = "1";
      var boton = document.createElement("button");
      boton.type = "button";
      boton.className = "aviso-cerrar";
      boton.setAttribute("aria-label", "Cerrar aviso");
      boton.textContent = "×";
      boton.addEventListener("click", function () { aviso.remove(); });
      aviso.appendChild(boton);
      if (aviso.classList.contains("aviso-ok")) {
        setTimeout(function () { aviso.classList.add("saliendo"); setTimeout(function () { aviso.remove(); }, 400); }, 7000);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () { iniciar(document); });
  document.addEventListener("htmx:afterSettle", function (e) { iniciar(e.target); });

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches && t.matches("[data-marcar-todas]")) {
      document.querySelectorAll(t.dataset.marcarTodas).forEach(function (c) { if (!c.disabled) c.checked = t.checked; });
    }
    actualizarCondicionales();
    if (t.matches && t.matches("[data-validar]")) validarCampo(t);
    if (t.id && document.querySelector('[data-validar][data-tipo="' + t.id + '"]')) {
      validarCampo(document.querySelector('[data-validar][data-tipo="' + t.id + '"]'));
    }
    actualizarSeleccion();
  });

  // En el listado de proveedores, cambiar un filtro vuelve a la página 1 (antes de que HTMX lea el formulario).
  ["input", "change"].forEach(function (tipo) {
    document.addEventListener(tipo, function (e) {
      var formulario = e.target.form;
      if (formulario && formulario.id === "filtros" && e.target.type !== "hidden" && formulario.elements.pagina) {
        formulario.elements.pagina.value = "1";
      }
    }, true);
  });

  document.addEventListener("input", function (e) {
    var t = e.target;
    // Mientras escribe solo se quita el error; se vuelve a revisar al salir del campo.
    if (t.matches && t.matches("[data-validar].con-error")) validarCampo(t);
  });

  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("[data-confirmar], [data-orden], [data-pagina]") : null;
    if (t && t.dataset.confirmar && !window.confirm(t.dataset.confirmar)) {
      e.preventDefault();
      return;
    }
    if (t && t.tagName === "A" && (t.dataset.orden !== undefined || t.dataset.pagina !== undefined)) {
      if (irA(t)) e.preventDefault();
    }
    // Cerrar el menú desplegable al hacer clic fuera.
    document.querySelectorAll("details.menu[open]").forEach(function (m) { if (!m.contains(e.target)) m.removeAttribute("open"); });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll("details.menu[open]").forEach(function (m) { m.removeAttribute("open"); });
  });
})();
