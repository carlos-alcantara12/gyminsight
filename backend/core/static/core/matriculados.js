(() => {
  const panel = document.getElementById('enrolled-panel');
  if (!panel) return;
  const $ = id => document.getElementById(id);
  const labels = {em_dia:'Sem pendências', a_vencer:'A vencer', atrasada:'Atrasada', cancelada:'Matrícula cancelada', sem_cobranca:'Sem cobrança', encerrada:'Encerrada'};
  const keys = Object.keys(labels);
  let page = 1, next = null, previous = null, sequence = 0, timer;
  let expiryPage = 1, expiryNext = null, expiryPrevious = null;
  const date = value => value ? value.split('-').reverse().join('/') : '—';
  function cell(row, value) { const td = document.createElement('td'); td.textContent = value ?? '—'; row.append(td); return td; }
  async function loadExpiry() {
    const response = await fetch(`/api/matriculas/avisos-vencimento/?page=${expiryPage}`, {credentials:'same-origin',headers:{Accept:'application/json'}});
    if (response.status === 404 && expiryPage > 1) {expiryPage=1;return loadExpiry();}
    if (!response.ok) throw new Error('Falha ao consultar vencimentos próximos.');
    const data = await response.json();
    $('expiry-alerts').hidden = data.count === 0;
    $('expiry-alert-rows').replaceChildren();
    (data.results || []).forEach(item => {
      const row=document.createElement('tr');
      cell(row,item.aluno_nome);cell(row,item.plano_nome);cell(row,date(item.fim));
      cell(row,String(item.dias_restantes));
      cell(row,item.renovacao_automatica ? 'Prevista após o vencimento' : 'Bloqueada: conferir pagamentos ou plano');
      const action=cell(row,'');const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Ver matrícula';
      button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('gyminsight:enrollment',{detail:item.id})));
      action.append(button);$('expiry-alert-rows').append(row);
    });
    expiryNext=data.next;expiryPrevious=data.previous;
    $('expiry-page').textContent=`Página ${expiryPage} · ${data.count} aviso(s)`;
    $('expiry-previous').disabled=!expiryPrevious;$('expiry-next').disabled=!expiryNext;
  }
  async function load() {
    if (panel.hidden) return;
    const current = ++sequence;
    $('enrolled-error').textContent = '';
    $('enrolled-page').textContent = 'Carregando…';
    $('enrolled-rows').replaceChildren();
    const params = new URLSearchParams({page: String(page)});
    if ($('enrolled-search').value.trim()) params.set('busca', $('enrolled-search').value.trim());
    if ($('enrolled-filter').value) params.set('situacao', $('enrolled-filter').value);
    try {
      const response = await fetch(`/api/matriculas/matriculados/?${params}`, {credentials:'same-origin', headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error(response.status === 403 ? 'Acesso negado à lista de matriculados.' : `Falha ao consultar matrículas (${response.status}).`);
      const data = await response.json();
      if (current !== sequence) return;
      await loadExpiry();
      next = data.next; previous = data.previous;
      $('enrolled-stats').replaceChildren();
      keys.forEach(key => {
        const box = document.createElement('div'), count = document.createElement('strong'), label = document.createElement('span');
        count.textContent = data.totais?.[key] ?? 0; label.textContent = labels[key]; box.append(count, label); $('enrolled-stats').append(box);
      });
      (data.results || []).forEach(item => {
        const row = document.createElement('tr');
        cell(row, item.aluno_nome); cell(row, item.plano_nome); cell(row, date(item.inicio)); cell(row, date(item.fim));
        cell(row, item.status === 'cancelada' ? 'Cancelada' : item.status === 'encerrada' ? 'Encerrada' : 'Ativa');
        const status = cell(row, ''); const pill = document.createElement('span');
        pill.className = 'pill enrollment-status '+item.situacao_financeira;
        pill.textContent = labels[item.situacao_financeira] || item.situacao_financeira; status.append(pill);
        if (item.pendencias?.length) {
          const details = document.createElement('small'); details.className = 'payment-arrears';
          details.textContent = 'Pendente: ' + item.pendencias.map(p =>
            `${p.competencia ? p.competencia.slice(5) + '/' + p.competencia.slice(0,4) : 'competência não informada'} (venc. ${date(p.vencimento)})`
          ).join(', ');
          status.append(details);
        }
        const action = cell(row, ''); const button = document.createElement('button');
        button.type = 'button'; button.className = 'secondary'; button.textContent = 'Ver matrícula';
        button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('gyminsight:enrollment', {detail:item.id})));
        action.append(button); $('enrolled-rows').append(row);
      });
      if (!data.results?.length) {const row = document.createElement('tr'); const empty = cell(row, 'Nenhuma matrícula encontrada.'); empty.colSpan = 7; $('enrolled-rows').append(row);}
      $('enrolled-page').textContent = `Página ${page} · ${data.count} registro(s)`;
    } catch (error) {
      if (current !== sequence) return;
      $('enrolled-error').textContent = error.message; $('enrolled-page').textContent = '';
      next = previous = null;
    } finally {
      if (current === sequence) { $('enrolled-previous').disabled = !previous; $('enrolled-next').disabled = !next; }
    }
  }
  window.addEventListener('gyminsight:enrolled-open', load);
  $('enrolled-refresh').addEventListener('click', load);
  $('enrolled-filter').addEventListener('change', () => {page = 1; load();});
  $('enrolled-search').addEventListener('input', () => {clearTimeout(timer); timer = setTimeout(() => {page = 1; load();}, 250);});
  $('enrolled-previous').addEventListener('click', () => {if (previous) {page--; load();}});
  $('enrolled-next').addEventListener('click', () => {if (next) {page++; load();}});
  $('expiry-previous').addEventListener('click',()=>{if(expiryPrevious){expiryPage--;loadExpiry().catch(error=>{$('enrolled-error').textContent=error.message;});}});
  $('expiry-next').addEventListener('click',()=>{if(expiryNext){expiryPage++;loadExpiry().catch(error=>{$('enrolled-error').textContent=error.message;});}});
})();
