// Formulario de nueva venta: agregar/quitar líneas y mostrar un total estimado.
// El total real (con promociones y stock) lo calcula y valida el servidor.
(function () {
  const contenedor = document.getElementById('lineas');
  const plantilla = document.getElementById('plantilla-linea');
  const totalForms = document.getElementById('id_lineas-TOTAL_FORMS');
  const precios = JSON.parse(document.getElementById('precios').textContent);
  const moneda = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' });

  function lineas() {
    return contenedor.querySelectorAll('.linea-venta');
  }

  // Renumera los nombres lineas-N-campo para que Django reciba un formset continuo.
  function renumerar() {
    lineas().forEach((linea, indice) => {
      linea.querySelectorAll('[name], [id], label[for]').forEach((el) => {
        ['name', 'id', 'for'].forEach((attr) => {
          const valor = el.getAttribute(attr);
          if (valor) el.setAttribute(attr, valor.replace(/lineas-(\d+|__prefix__)-/, `lineas-${indice}-`));
        });
      });
    });
    totalForms.value = lineas().length;
  }

  function recalcular() {
    let total = 0;
    lineas().forEach((linea) => {
      const libro = linea.querySelector('select').value;
      const cantidad = parseInt(linea.querySelector('input[type=number]').value, 10) || 0;
      const nota = linea.querySelector('.estimado-linea');
      const datos = precios[libro];
      if (!datos || cantidad < 1) {
        nota.textContent = '';
        return;
      }
      const subtotal = parseFloat(datos.final) * cantidad;
      total += subtotal;
      nota.textContent = datos.promo
        ? `${cantidad} × ${moneda.format(datos.final)} (antes ${moneda.format(datos.precio)}, ${datos.promo}) = ${moneda.format(subtotal)}`
        : `${cantidad} × ${moneda.format(datos.precio)} = ${moneda.format(subtotal)}`;
    });
    document.getElementById('total-estimado').textContent = moneda.format(total);
  }

  document.getElementById('agregar-linea').addEventListener('click', () => {
    contenedor.appendChild(plantilla.content.cloneNode(true));
    renumerar();
    recalcular();
  });

  contenedor.addEventListener('click', (evento) => {
    if (!evento.target.classList.contains('quitar-linea')) return;
    if (lineas().length === 1) return; // siempre queda al menos una línea
    evento.target.closest('.linea-venta').remove();
    renumerar();
    recalcular();
  });

  contenedor.addEventListener('input', recalcular);
  contenedor.addEventListener('change', recalcular);
  recalcular();
})();
