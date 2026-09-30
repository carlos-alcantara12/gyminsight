(() => {
  const panel = document.getElementById('finance-panel');
  if (!panel) return;
  const $ = id => document.getElementById(id);
  const money = value => new Intl.NumberFormat('pt-BR', {style:'currency',currency:'BRL'}).format(Number(value || 0));
  const date = value => value ? value.split('-').reverse().join('/') : '—';
  const labels = {pago:'Pago',pendente:'A vencer',atrasada:'Atrasada',cancelado:'Cancelado'};
  let page = 1, next = null, previous = null, sequence = 0, legacyPage = 1, legacyNext = null, legacyPrevious = null;
  $('finance-month').value = new Intl.DateTimeFormat('sv-SE', {timeZone:'America/Manaus',year:'numeric',month:'2-digit'}).format(new Date());
  const csrf = () => decodeURIComponent(document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.split('=')[1] || '');
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', headers:{Accept:'application/json',...(options.body ? {'Content-Type':'application/json','X-CSRFToken':csrf()} : {})}, ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(Object.values(data).flat().join(' ') || `Erro na consulta (${response.status}).`);
    return data;
  }
  function cell(row, value) {const td = document.createElement('td'); td.textContent = value; row.append(td); return td;}
  function renderPie(summary) {
    const colors = {pix:'#1c5ba8',card:'#64a5e8',legacy:'#8199bb',pending:'#d64242'};
    const values = [
      ['pix',Number(summary.recebido_pix || 0)],
      ['card',Number(summary.recebido_cartao || 0)],
      ['legacy',Number(summary.recebido_sem_forma || 0)],
      ['pending',Number(summary.em_aberto || 0)],
    ];
    const total = values.reduce((sum,[,amount])=>sum+amount,0);
    let cursor=0;
    const segments=values.filter(([,amount])=>amount>0).map(([key,amount])=>{
      const start=cursor;cursor+=amount/total*100;
      return `${colors[key]} ${start}% ${cursor}%`;
    });
    $('finance-pie').style.background=segments.length ? `conic-gradient(${segments.join(',')})` : '#e7ecea';
    $('finance-pie-description').setAttribute('aria-label',`Faturamento previsto ${money(summary.faturamento_previsto)}; recebido em Pix ${money(summary.recebido_pix)}; recebido em cartão ${money(summary.recebido_cartao)}; recebido sem forma informada ${money(summary.recebido_sem_forma)}; pendente ${money(summary.em_aberto)}.`);
    for(const [id,value] of [['expected',summary.faturamento_previsto],['pix',summary.recebido_pix],['card',summary.recebido_cartao],['legacy',summary.recebido_sem_forma],['pending',summary.em_aberto]]){
      $(`finance-pie-${id}`).textContent=money(value);
    }
    $('finance-chart-updated').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR',{timeZone:'America/Manaus',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  async function refreshPie() {
    if (document.hidden || panel.hidden || !$('finance-month').value) return;
    const month=$('finance-month').value, current=sequence;
    try {
      const summary=await api(`/api/pagamentos/faturamento/?competencia=${encodeURIComponent(month)}`);
      if(current===sequence && month===$('finance-month').value && !panel.hidden) renderPie(summary);
    } catch { $('finance-chart-updated').textContent='Atualização indisponível'; }
  }
  async function loadLegacy() {
    if (!$('legacy-queue') || panel.hidden) return;
    const result = await api(`/api/matriculas/pendencias-legadas/?page=${legacyPage}`);
    const rows = $('legacy-queue-rows'); rows.replaceChildren();
    (result.results || []).forEach(item => {
      const row = document.createElement('tr');
      cell(row,item.aluno_nome);cell(row,date(item.inicio));cell(row,item.valor_contratado === null ? 'A confirmar' : money(item.valor_contratado));
      cell(row,String(item.pagamentos_legados.length));
      const action=cell(row,'');const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Conferir';
      button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('gyminsight:enrollment',{detail:item.id})));
      action.append(button);rows.append(row);
    });
    if (!result.results?.length) {const row=document.createElement('tr');const td=cell(row,'Nenhuma pendência histórica.');td.colSpan=5;rows.append(row);}
    legacyNext=result.next;legacyPrevious=result.previous;
    $('legacy-page').textContent=`Página ${legacyPage} · ${result.count} contrato(s) para conferir`;
    $('legacy-previous').disabled=!legacyPrevious;$('legacy-next').disabled=!legacyNext;
  }
  async function load() {
    if (panel.hidden || !$('finance-month').value) return;
    const current = ++sequence;
    $('finance-error').textContent = '';
    $('finance-rows').replaceChildren();
    $('finance-page').textContent = 'Carregando…';
    try {
      const month = encodeURIComponent($('finance-month').value);
      const [summary, list, network] = await Promise.all([
        api(`/api/pagamentos/faturamento/?competencia=${month}`),
        api(`/api/pagamentos/?competencia=${month}&page=${page}`),
        api(`/api/pagamentos/consolidado/?competencia=${month}`),
      ]);
      if (current !== sequence) return;
      const stats = [
        ['Faturamento previsto', money(summary.faturamento_previsto)],
        ['Recebido da competência', money(summary.recebido_da_competencia)],
        ['Recebido em Pix', money(summary.recebido_pix)],
        ['Recebido em cartão', money(summary.recebido_cartao)],
        ['Recebido sem forma informada (histórico)', money(summary.recebido_sem_forma)],
        ['Em aberto', money(summary.em_aberto)],
        ['Vencido em aberto', money(summary.vencido_em_aberto)],
        ['Recebido no mês (caixa)', money(summary.recebido_no_mes)],
        ['Caixa em Pix', money(summary.caixa_pix)],
        ['Caixa em cartão', money(summary.caixa_cartao)],
        ['Caixa sem forma informada (histórico)', money(summary.caixa_sem_forma)],
      ];
      const unitRows = $('finance-unit-rows'), total = $('finance-network-total');
      unitRows.replaceChildren(); total.replaceChildren();
      function consolidatedRow(target, item, heading = false) {
        const row = document.createElement('tr');
        if (item.id === network.unidade_selecionada) row.className = 'finance-selected-unit';
        const values = [heading ? 'Total da rede autorizada' : item.nome+(item.id === network.unidade_selecionada ? ' · selecionada' : ''), item.matriculas_iniciadas, item.matriculas_sem_cobranca, item.cobrancas, money(item.previsto), money(item.recebido), money(item.pix), money(item.cartao), money(item.sem_forma), money(item.em_aberto), money(item.vencido)];
        values.forEach(value => cell(row,value));target.append(row);
      }
      network.unidades.forEach(item => consolidatedRow(unitRows,item));
      consolidatedRow(total, network.total_rede, true);
      renderPie(summary);
      await loadLegacy();
      $('finance-stats').replaceChildren();
      stats.forEach(([label,value]) => {const box=document.createElement('div'), strong=document.createElement('strong'), span=document.createElement('span');strong.textContent=value;span.textContent=label;box.append(strong,span);$('finance-stats').append(box);});
      (list.results || []).forEach(item => {
        const row = document.createElement('tr');
        cell(row,item.aluno_nome);cell(row,money(item.valor));cell(row,date(item.vencimento));
        const td = cell(row,'');const pill=document.createElement('span');pill.className='pill enrollment-status '+item.situacao;pill.textContent=labels[item.situacao]||item.situacao;td.append(pill);
        cell(row,item.status==='pago' ? ({pix:'Pix',cartao:'Cartão'})[item.forma_pagamento] || 'Não informado (histórico)' : '—');
        const action=cell(row,'');
        if (item.status==='pendente' && $('finance-generate')) {
          const choice=document.createElement('select');choice.setAttribute('aria-label',`Forma de pagamento de ${item.aluno_nome}`);
          choice.add(new Option('Selecione a forma',''));choice.add(new Option('Pix','pix'));choice.add(new Option('Cartão','cartao'));
          const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Confirmar pagamento';
          button.addEventListener('click', async () => {if(!choice.value){$('finance-error').textContent='Selecione Pix ou cartão antes de confirmar.';choice.focus();return;}if(!confirm(`Confirmar o recebimento integral de ${money(item.valor)} por ${choice.selectedOptions[0].textContent}?`))return;button.disabled=true;try {await api(`/api/pagamentos/${item.id}/`,{method:'PATCH',body:JSON.stringify({status:'pago',forma_pagamento:choice.value})});await load();window.dispatchEvent(new Event('gyminsight:enrollments-updated'));}catch(error){$('finance-error').textContent=error.message;button.disabled=false;}});
          action.append(choice,button);
        }
        $('finance-rows').append(row);
      });
      if (!list.results?.length) {const row=document.createElement('tr');const empty=cell(row,'Nenhuma cobrança nesta competência.');empty.colSpan=6;$('finance-rows').append(row);}
      next=list.next;previous=list.previous;
      $('finance-page').textContent=`Página ${page} · ${list.count} cobrança(s)`;
    } catch(error) {if (current!==sequence)return;$('finance-error').textContent=error.message;next=previous=null;$('finance-page').textContent='';}
    finally {if(current===sequence){$('finance-previous').disabled=!previous;$('finance-next').disabled=!next;}}
  }
  window.addEventListener('gyminsight:finance-open',load);
  window.addEventListener('gyminsight:enrollments-updated',()=>{if(!panel.hidden)load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshPie();});
  setInterval(refreshPie,10000);
  $('finance-form').addEventListener('submit',event=>{event.preventDefault();page=1;load();});
  $('finance-generate')?.addEventListener('click',async()=>{const button=$('finance-generate');button.disabled=true;$('finance-error').textContent='';try{const data=await api('/api/pagamentos/gerar-mensalidades/',{method:'POST',body:JSON.stringify({competencia:$('finance-month').value})});page=1;await load();$('finance-error').textContent=`${data.cobrancas_criadas} cobrança(s) ausente(s) criada(s).`;window.dispatchEvent(new Event('gyminsight:enrollments-updated'));}catch(error){$('finance-error').textContent=error.message;}finally{button.disabled=false;}});
  $('finance-previous').addEventListener('click',()=>{if(previous){page--;load();}});
  $('finance-next').addEventListener('click',()=>{if(next){page++;load();}});
  $('legacy-previous')?.addEventListener('click',()=>{if(legacyPrevious){legacyPage--;loadLegacy().catch(error=>{$('finance-error').textContent=error.message;});}});
  $('legacy-next')?.addEventListener('click',()=>{if(legacyNext){legacyPage++;loadLegacy().catch(error=>{$('finance-error').textContent=error.message;});}});
})();
