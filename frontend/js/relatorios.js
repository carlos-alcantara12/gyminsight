// Relatório agregado da unidade; totais vêm da API e não apenas da página atual.
(() => {
  const $ = id => document.getElementById(id);
  const form = $('report-filters');
  let page = 1, requestNumber = 0;
  let hasNext = false, hasPrevious = false;
  const datetime = value => value ? new Intl.DateTimeFormat('pt-BR',{
    timeZone:'America/Manaus',dateStyle:'short',timeStyle:'short',
  }).format(new Date(value)) : '—';

  function cell(row,value) {
    const td = document.createElement('td'); td.textContent = value == null || value === '' ? '—' : String(value);
    row.append(td); return td;
  }
  async function load() {
    const request = ++requestNumber;
    const initial = form.elements.inicio.value, final = form.elements.fim.value;
    $('report-error').textContent = '';
    if (initial && final && initial > final) {
      $('report-error').textContent = 'A data final não pode ser anterior à inicial.';
      return;
    }
    const params = new URLSearchParams({page:String(page)});
    if (initial) params.set('inicio',initial);
    if (final) params.set('fim',final);
    $('report-rows').replaceChildren(); $('report-page').textContent = 'Carregando…';
    $('report-previous').disabled = true; $('report-next').disabled = true;
    for (const id of ['report-students','report-present','report-entries']) $(id).textContent = '—';
    try {
      const response = await fetch(`/api/alunos/relatorio-frequencia/?${params}`,{credentials:'same-origin',headers:{Accept:'application/json'}});
      if (request !== requestNumber) return;
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(response.status === 403 ? 'Seu perfil não tem permissão para consultar este relatório.' : data?.detail || `Não foi possível carregar o relatório (${response.status}).`);
      }
      const data = await response.json();
      if (request !== requestNumber) return;
      $('report-students').textContent = data.resumo.total_alunos;
      $('report-present').textContent = data.resumo.alunos_com_presenca;
      $('report-entries').textContent = data.resumo.total_entradas;
      for (const item of data.results) {
        const row = document.createElement('tr');
        cell(row,item.nome); cell(row,item.status); cell(row,item.total_entradas);
        cell(row,item.dias_com_presenca); cell(row,datetime(item.ultima_entrada));
        const actions = document.createElement('td'),button = document.createElement('button');
        button.type='button'; button.className='secondary'; button.textContent='Ver aluno';
        button.addEventListener('click',() => window.dispatchEvent(new CustomEvent('gyminsight:student',{detail:item.aluno_id})));
        actions.append(button); row.append(actions); $('report-rows').append(row);
      }
      if (!data.results.length) {
        const row = document.createElement('tr'),empty = cell(row,'Nenhum aluno encontrado.');
        empty.colSpan = 6; $('report-rows').append(row);
      }
      $('report-page').textContent = `Página ${page} · ${data.count} aluno(s)`;
      hasNext = Boolean(data.next); hasPrevious = Boolean(data.previous);
      $('report-previous').disabled = !hasPrevious; $('report-next').disabled = !hasNext;
    } catch (error) {
      if (request !== requestNumber) return;
      $('report-error').textContent = error.message; $('report-page').textContent = '—';
    }
  }
  window.addEventListener('gyminsight:report-open',load);
  window.addEventListener('gyminsight:presence-updated',() => { if (!$('report-panel').hidden) load(); });
  form.addEventListener('submit',event => { event.preventDefault(); page=1; load(); });
  $('clear-report').addEventListener('click',() => { form.reset(); page=1; load(); });
  $('report-previous').addEventListener('click',() => { if (hasPrevious) { page--; load(); } });
  $('report-next').addEventListener('click',() => { if (hasNext) { page++; load(); } });
})();
