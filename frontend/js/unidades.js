(() => {
  const picker = document.getElementById('unit-picker');
  const unitDialog = document.getElementById('unit-dialog');
  const holidayDialog = document.getElementById('holiday-dialog');
  if (!picker || !unitDialog || !holidayDialog) return;
  const unitForm = document.getElementById('unit-form');
  const holidayForm = document.getElementById('holiday-form');
  let editingUnit = null, editingHoliday = null;
  const csrf = () => decodeURIComponent(document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.split('=')[1] || '');

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: {'Accept': 'application/json', ...(options.body ? {'Content-Type': 'application/json', 'X-CSRFToken': csrf()} : {})},
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(Object.values(data).flat().join(' ') || `Erro ao consultar o servidor (${response.status}).`);
    }
    return data;
  }

  async function refreshUnits(selected = picker.dataset.selected) {
    const units = [];
    let url = '/api/unidades/';
    while (url) {
      const page = await api(url);
      units.push(...page.results);
      url = page.next;
    }
    picker.replaceChildren();
    units.filter(unit => unit.ativa).forEach(unit => {
      const option = new Option(`${unit.nome} · ${unit.categoria}`, String(unit.id));
      picker.add(option);
    });
    picker.value = String(selected);
    if (!picker.value && picker.options.length) picker.selectedIndex = 0;
    picker.hidden = picker.options.length < 2;
  }

  picker.addEventListener('change', async () => {
    const old = picker.dataset.selected;
    try {
      await api(`/api/unidades/${picker.value}/selecionar/`, {method: 'POST', body: '{}'});
      location.reload();
    } catch (error) {
      picker.value = old;
      alert(error.message);
    }
  });
  refreshUnits().catch(() => { picker.hidden = true; });

  window.addEventListener('gyminsight:units-open', async () => {
    const rows = document.getElementById('unit-network-rows');
    rows.replaceChildren();
    try {
      const network = await api('/api/unidades/resumo/');
      network.unidades.forEach(unit => {
        const row = document.createElement('tr');
        const cells = [unit.nome, unit.categoria, unit.funcionamento_hoje.abre ? 'Aberta' : 'Fechada',
          unit.alunos, unit.matriculas_ativas, unit.funcionarios_ativos];
        cells.forEach(value => { const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell); });
        rows.append(row);
      });
    } catch (error) {
      const row = document.createElement('tr'), cell = document.createElement('td');
      cell.colSpan = 6; cell.textContent = error.message; row.append(cell); rows.append(row);
    }
  });

  function setSchedule(form, kind) {
    const open = form.elements[`abre_${kind}`];
    if (!open) return;
    const fields = [form.elements[`${kind}_inicio`], form.elements[`${kind}_fim`]];
    function update() {
      fields.forEach(field => {
        field.disabled = !open.checked;
        field.required = open.checked;
        if (!open.checked) field.value = '';
      });
    }
    open.addEventListener('change', update);
    return update;
  }
  const updateSunday = setSchedule(unitForm, 'domingo');
  const updateHolidayHours = setSchedule(unitForm, 'feriado');

  const canEditUnit = !!unitForm.querySelector('button[type=submit]');
  if (!canEditUnit) unitForm.querySelectorAll('input, select').forEach(field => { field.disabled = true; });
  document.getElementById('new-unit')?.addEventListener('click', () => {
    editingUnit = null;
    unitForm.reset();
    updateSunday();
    updateHolidayHours();
    document.getElementById('unit-title').textContent = 'Nova unidade';
    document.getElementById('unit-feedback').textContent = '';
    document.getElementById('unit-check-result').textContent = '';
    document.getElementById('unit-check').hidden = true;
    unitDialog.showModal();
  });
  document.querySelector('.close-unit').addEventListener('click', () => unitDialog.close());
  window.addEventListener('gyminsight:unit', async event => {
    try {
      const unit = await api(`/api/unidades/${event.detail}/`);
      editingUnit = unit.id;
      unitForm.reset();
      ['nome','endereco','categoria','semana_inicio','semana_fim','sabado_inicio','sabado_fim','domingo_inicio','domingo_fim','feriado_inicio','feriado_fim'].forEach(key => {
        unitForm.elements[key].value = unit[key] || '';
      });
      ['ativa','abre_domingo','abre_feriado'].forEach(key => { unitForm.elements[key].checked = unit[key]; });
      updateSunday();
      updateHolidayHours();
      document.getElementById('unit-title').textContent = unit.nome;
      document.getElementById('unit-feedback').textContent = '';
      document.getElementById('unit-check-result').textContent = '';
      document.getElementById('unit-check').hidden = false;
      unitDialog.showModal();
    } catch (error) { alert(error.message); }
  });
  unitForm.addEventListener('submit', async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(unitForm));
    ['ativa','abre_domingo','abre_feriado'].forEach(key => { payload[key] = unitForm.elements[key].checked; });
    ['domingo_inicio','domingo_fim','feriado_inicio','feriado_fim'].forEach(key => { payload[key] = payload[key] || null; });
    try {
      const unit = await api(editingUnit ? `/api/unidades/${editingUnit}/` : '/api/unidades/', {
        method: editingUnit ? 'PATCH' : 'POST', body: JSON.stringify(payload),
      });
      unitDialog.close();
      picker.dataset.selected = String(picker.value);
      await refreshUnits();
      window.dispatchEvent(new Event('gyminsight:units-updated'));
      if (!editingUnit) {
        picker.value = String(unit.id);
        await api(`/api/unidades/${unit.id}/selecionar/`, {method: 'POST', body: '{}'});
        location.reload();
      }
    } catch (error) { document.getElementById('unit-feedback').textContent = error.message; }
  });
  document.getElementById('unit-check').addEventListener('click', async () => {
    if (!editingUnit) return;
    const date = document.getElementById('unit-check-date').value;
    const result = document.getElementById('unit-check-result');
    try {
      const data = await api(`/api/unidades/${editingUnit}/funcionamento/${date ? '?data=' + encodeURIComponent(date) : ''}`);
      result.textContent = `${data.nome || data.tipo}: ${data.abre ? `aberta${data.inicio ? ' das ' + data.inicio.slice(0,5) + ' às ' + data.fim.slice(0,5) : ''}` : 'fechada'} em ${data.data}.`;
    } catch (error) { result.textContent = error.message; }
  });

  const canEditHoliday = !!holidayForm.querySelector('button[type=submit]');
  if (!canEditHoliday) holidayForm.querySelectorAll('input, select').forEach(field => { field.disabled = true; });
  document.getElementById('new-holiday')?.addEventListener('click', () => {
    editingHoliday = null;
    holidayForm.reset();
    document.getElementById('holiday-title').textContent = 'Novo feriado';
    document.getElementById('holiday-feedback').textContent = '';
    holidayDialog.showModal();
  });
  document.querySelector('.close-holiday').addEventListener('click', () => holidayDialog.close());
  window.addEventListener('gyminsight:holiday', async event => {
    try {
      const holiday = await api(`/api/feriados/${event.detail}/`);
      editingHoliday = holiday.id;
      holidayForm.reset();
      ['data','nome','inicio','fim'].forEach(key => { holidayForm.elements[key].value = holiday[key] || ''; });
      holidayForm.elements.abre.value = holiday.abre === null ? '' : String(holiday.abre);
      document.getElementById('holiday-title').textContent = holiday.nome;
      document.getElementById('holiday-feedback').textContent = '';
      holidayDialog.showModal();
    } catch (error) { alert(error.message); }
  });
  holidayForm.addEventListener('submit', async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(holidayForm));
    payload.abre = payload.abre === '' ? null : payload.abre === 'true';
    payload.inicio = payload.inicio || null;
    payload.fim = payload.fim || null;
    try {
      await api(editingHoliday ? `/api/feriados/${editingHoliday}/` : '/api/feriados/', {
        method: editingHoliday ? 'PATCH' : 'POST', body: JSON.stringify(payload),
      });
      holidayDialog.close();
      window.dispatchEvent(new Event('gyminsight:holidays-updated'));
    } catch (error) { document.getElementById('holiday-feedback').textContent = error.message; }
  });
})();
