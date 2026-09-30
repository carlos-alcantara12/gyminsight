// Módulo de alunos: autorização e regras de negócio permanecem na API.
(() => {
  const dialog = document.getElementById('student-dialog');
  const form = document.getElementById('student-form');
  const feedback = document.getElementById('student-feedback');
  const details = document.getElementById('student-details');
  const enrollment = document.getElementById('enrollment-fields');
  const $ = id => document.getElementById(id);
  let student = null, mode = 'create';
  const names = {nome:'Nome',email:'E-mail',telefone:'Telefone',data_nascimento:'Nascimento',plano:'Plano',inicio:'Início',non_field_errors:'Dados'};
  function errorText(data, fallback) {
    if (typeof data === 'string') return data;
    if (!data || typeof data !== 'object') return fallback;
    if (data.detail) return String(data.detail);
    return Object.entries(data).map(([key,value]) => `${names[key] || key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ') || fallback;
  }
  async function api(url, options = {}) {
    const token = document.cookie.split('; ').find(item => item.startsWith('csrftoken='))?.slice(10) || '';
    const response = await fetch(url, {credentials:'same-origin',headers:{Accept:'application/json',...(options.body ? {'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token)} : {})},...options});
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(errorText(data,response.status === 403 ? 'Acesso negado. Confira sua sessão e permissões.' : `Falha na operação (${response.status}).`));
    }
    return response.json();
  }
  function setMode(value) {
    mode = value;
    form.hidden = value === 'view'; details.hidden = value !== 'view'; enrollment.hidden = value !== 'create';
    enrollment.querySelectorAll('select,input').forEach(field => field.disabled = value !== 'create');
    $('student-dialog-title').textContent = value === 'create' ? 'Novo aluno' : value === 'edit' ? 'Editar aluno' : 'Detalhes do aluno';
    $('save-student').textContent = value === 'create' ? 'Cadastrar aluno' : 'Salvar alterações';
    feedback.textContent = '';
  }
  async function plans() {
    const select = form.elements.plano;
    select.replaceChildren(new Option('Selecione um plano',''));
    let url = '/api/planos/';
    while (url) {
      const data = await api(url);
      for (const plan of Array.isArray(data) ? data : data.results || []) if (plan.ativo) select.add(new Option(`${plan.nome} · ${plan.duracao_dias} dias`,plan.id));
      const next = Array.isArray(data) ? null : data.next;
      if (next) {
        const parsed = new URL(next,location.origin);
        if (parsed.origin !== location.origin || !parsed.pathname.startsWith('/api/planos/')) throw new Error('Erro ao consultar os planos.');
        url = parsed.pathname + parsed.search;
      } else url = null;
    }
    if (select.options.length === 1) throw new Error('Cadastre um plano ativo antes de cadastrar alunos.');
  }
  $('new-student')?.addEventListener('click',async () => {
    student = null; form.reset(); setMode('create'); dialog.showModal();
    $('save-student').disabled = true;
    try { await plans(); } catch (error) { feedback.textContent = error.message; }
    finally { $('save-student').disabled = form.elements.plano.options.length === 1; }
  });
  function show(value) {
    student = value; setMode('view');
    const list = $('student-profile'); list.replaceChildren();
    for (const [label,key] of [['Nome','nome'],['Status','status'],['Matrícula ativa','matricula_ativa_id'],['E-mail','email'],['Telefone','telefone'],['Nascimento','data_nascimento']]) {
      if (value[key] === undefined) continue;
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = value[key] === null || value[key] === '' ? '—' : String(value[key]); list.append(dt,dd);
    }
    $('attendance-results').hidden = true; $('attendance-start').value = ''; $('attendance-end').value = '';
  }
  window.addEventListener('gyminsight:student',async event => {
    dialog.showModal(); setMode('view'); $('student-profile').replaceChildren(); feedback.textContent = 'Carregando aluno…';
    try { show(await api(`/api/alunos/${encodeURIComponent(event.detail)}/`)); } catch (error) { feedback.textContent = error.message; }
  });
  dialog.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click',() => dialog.close()));
  dialog.addEventListener('click',event => { if (event.target === dialog) dialog.close(); });
  $('edit-student')?.addEventListener('click',() => {
    if (!student || dialog.dataset.canEdit !== 'true') return;
    form.reset(); setMode('edit');
    for (const key of ['nome','email','telefone','data_nascimento']) if (form.elements[key]) form.elements[key].value = student[key] || '';
  });
  form.addEventListener('submit',async event => {
    event.preventDefault(); feedback.textContent = '';
    const button = $('save-student'); button.disabled = true;
    const data = Object.fromEntries(new FormData(form).entries());
    for (const key of ['email','telefone','data_nascimento']) if (!data[key]) data[key] = key === 'data_nascimento' ? null : '';
    if (mode === 'edit') { delete data.plano; delete data.inicio; }
    try {
      show(await api(mode === 'create' ? '/api/alunos/' : `/api/alunos/${student.id}/`,{method:mode === 'create' ? 'POST' : 'PATCH',body:JSON.stringify(data)}));
      window.dispatchEvent(new Event('gyminsight:students-updated'));
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  $('show-attendance')?.addEventListener('click',() => { $('attendance-results').hidden = false; $('filter-attendance').click(); });
  $('filter-attendance').addEventListener('click',async () => {
    if (!student) return;
    const params = new URLSearchParams();
    if ($('attendance-start').value) params.set('inicio',$('attendance-start').value);
    if ($('attendance-end').value) params.set('fim',$('attendance-end').value);
    feedback.textContent = '';
    try {
      const data = await api(`/api/alunos/${student.id}/frequencia/${params.size ? `?${params}` : ''}`);
      $('attendance-summary').textContent = `${data.total_entradas} entrada(s) em ${data.dias_com_presenca} dia(s) com presença.`;
      const days = $('attendance-days'); days.replaceChildren();
      for (const day of data.por_dia) { const item = document.createElement('li'); item.textContent = `${day.data}: ${day.entradas} entrada(s)`; days.append(item); }
    } catch (error) { feedback.textContent = error.message; }
  });
})();
