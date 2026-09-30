// Interface das matrículas: as regras e permissões finais são verificadas pela API.
(() => {
  const dialog = document.getElementById('enrollment-dialog');
  const form = document.getElementById('enrollment-form');
  const cancelForm = document.getElementById('cancel-enrollment-form');
  const priceForm = document.getElementById('contract-price-form');
  const legacyForm = document.getElementById('legacy-reconcile-form');
  const feedback = document.getElementById('enrollment-feedback');
  const $ = id => document.getElementById(id);
  let enrollment = null;
  const labels = {aluno:'Aluno',plano:'Plano',inicio:'Início',status:'Status',motivo_cancelamento:'Motivo',non_field_errors:'Dados'};

  function errorText(data, fallback) {
    if (typeof data === 'string') return data;
    if (!data || typeof data !== 'object') return fallback;
    if (data.detail) return String(data.detail);
    return Object.entries(data).map(([key,value]) => `${labels[key] || key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ') || fallback;
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
  async function fillSelect(resource, select, name, predicate = () => true) {
    select.replaceChildren(new Option(`Selecione ${name}`,''));
    let url = `/api/${resource}/`;
    while (url) {
      const data = await api(url);
      for (const item of Array.isArray(data) ? data : data.results || []) {
        if (predicate(item)) select.add(new Option(item.nome,item.id));
      }
      const next = Array.isArray(data) ? null : data.next;
      if (!next) { url = null; continue; }
      const candidate = new URL(next,location.origin);
      if (candidate.origin !== location.origin || !candidate.pathname.startsWith(`/api/${resource}/`)) throw new Error(`Falha ao carregar ${resource}.`);
      url = candidate.pathname + candidate.search;
    }
    if (select.options.length === 1) throw new Error(`Nenhum ${name} disponível nesta unidade.`);
  }
  function mode(value) {
    form.hidden = value !== 'create';
    $('enrollment-details').hidden = value !== 'details';
    $('enrollment-title').textContent = value === 'create' ? 'Nova matrícula' : 'Detalhes da matrícula';
    feedback.textContent = '';
  }
  $('new-enrollment')?.addEventListener('click',async () => {
    enrollment = null; form.reset(); mode('create'); dialog.showModal();
    $('save-enrollment').disabled = true;
    try {
      await Promise.all([
        fillSelect('alunos',form.elements.aluno,'um aluno'),
        fillSelect('planos',form.elements.plano,'um plano ativo',item => item.ativo),
      ]);
      $('save-enrollment').disabled = false;
    } catch (error) { feedback.textContent = error.message; }
  });
  function detail(label,value) {
    if (value === undefined) return;
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label; dd.textContent = value === null || value === '' ? '—' : String(value);
    $('enrollment-profile').append(dt,dd);
  }
  const hoje = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Manaus',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const dinheiro = value => value === null ? 'A confirmar' : new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(value));
  function show(value) {
    enrollment = value; mode('details'); $('enrollment-profile').replaceChildren();
    detail('Aluno',value.aluno_nome); detail('Plano',value.plano_nome);
    detail('Início',value.inicio); detail('Fim',value.fim);
    detail('Valor contratado',dinheiro(value.valor_contratado));
    detail('Período anterior',value.matricula_anterior || 'Primeira contratação');
    detail('Status',value.status); detail('Motivo',value.motivo_cancelamento);
    const legacy = $('legacy-enrollment');
    if (legacy) {
      const payments = value.pagamentos_legados || [];
      legacy.hidden = payments.length === 0;
      $('legacy-payments').replaceChildren();
      legacyForm.hidden = payments.length === 0;
      legacyForm.elements.pagamento.replaceChildren();
      payments.forEach(item => {
        const line = document.createElement('p');
        line.textContent = `Lançamento #${item.id}: ${dinheiro(item.valor)} · ${item.status} · vencimento ${item.vencimento}${item.pago_em ? ' · pago em '+item.pago_em : ''}`;
        $('legacy-payments').append(line);
        legacyForm.elements.pagamento.add(new Option(`#${item.id} · ${dinheiro(item.valor)} · ${item.status}`,item.id));
      });
      if (payments.length) legacyForm.elements.destino.value = value.valor_contratado === null ? 'avulso' : 'associado';
    }
    if (value.acerto) {
      detail('Decisão financeira',({manter:'Manter',cancelar:'Cobrança cancelada',reembolsar:'Reembolso solicitado'})[value.acerto.decisao]);
      detail('Justificativa financeira',value.acerto.justificativa);
      if (value.acerto.decisao === 'reembolsar') detail('Devolução',value.acerto.reembolsado_em ? `Confirmada em ${value.acerto.reembolsado_em}` : `Pendente · ${dinheiro(value.acerto.valor_reembolso)}`);
    }
    cancelForm.hidden = true; cancelForm.reset(); priceForm.hidden = true; priceForm.reset();
    $('begin-cancel')?.toggleAttribute('hidden',value.status !== 'ativa' || dialog.dataset.canCancel !== 'true');
    $('renew-enrollment')?.toggleAttribute('hidden',value.status === 'cancelada' || value.fim >= hoje());
    $('begin-confirm-price')?.toggleAttribute('hidden',value.valor_contratado !== null);
  }
  window.addEventListener('gyminsight:enrollment',async event => {
    mode('details'); dialog.showModal(); $('enrollment-profile').replaceChildren();
    $('begin-cancel')?.setAttribute('hidden',''); feedback.textContent = 'Carregando matrícula…';
    try { show(await api(`/api/matriculas/${encodeURIComponent(event.detail)}/`)); }
    catch (error) { feedback.textContent = error.message; }
  });
  dialog.querySelectorAll('.close-enrollment').forEach(button => button.addEventListener('click',() => dialog.close()));
  dialog.addEventListener('click',event => { if (event.target === dialog) dialog.close(); });
  form.addEventListener('submit',async event => {
    event.preventDefault(); feedback.textContent = ''; $('save-enrollment').disabled = true;
    try {
      const body = Object.fromEntries(new FormData(form).entries());
      show(await api('/api/matriculas/',{method:'POST',body:JSON.stringify(body)}));
      window.dispatchEvent(new Event('gyminsight:enrollments-updated'));
    } catch (error) { feedback.textContent = error.message; }
    finally { $('save-enrollment').disabled = false; }
  });
  $('renew-enrollment')?.addEventListener('click',async () => {
    if (!enrollment || !confirm('Renovar este aluno com o mesmo plano e o preço vigente para o próximo período?')) return;
    const button=$('renew-enrollment'); button.disabled=true; feedback.textContent='';
    try { show(await api(`/api/matriculas/${enrollment.id}/renovar/`,{method:'POST',body:'{}'})); window.dispatchEvent(new Event('gyminsight:enrollments-updated')); }
    catch(error){feedback.textContent=error.message;}finally{button.disabled=false;}
  });
  $('begin-confirm-price')?.addEventListener('click',() => {priceForm.hidden=false;priceForm.elements.valor.focus();});
  priceForm.addEventListener('submit',async event => {
    event.preventDefault();if(!enrollment)return;
    const button=priceForm.querySelector('button[type=submit]');button.disabled=true;feedback.textContent='';
    try { show(await api(`/api/matriculas/${enrollment.id}/confirmar-valor/`,{method:'POST',body:JSON.stringify({valor:priceForm.elements.valor.value})}));window.dispatchEvent(new Event('gyminsight:enrollments-updated')); }
    catch(error){feedback.textContent=error.message;}finally{button.disabled=false;}
  });
  legacyForm?.addEventListener('submit',async event => {
    event.preventDefault();if(!enrollment)return;
    if (legacyForm.elements.destino.value === 'avulso' && !confirm('Este recebimento NÃO quitará o período contratado. Se não houver outra cobrança, uma nova poderá ser emitida. Confirma que o recibo é avulso?')) return;
    if (legacyForm.elements.destino.value === 'descartado' && !confirm('A cobrança pendente será cancelada sem apagar o histórico. Confirma?')) return;
    const button=legacyForm.querySelector('button[type=submit]');button.disabled=true;feedback.textContent='';
    const paymentId=legacyForm.elements.pagamento.value;
    try {
      await api(`/api/pagamentos/${encodeURIComponent(paymentId)}/conciliar/`,{method:'POST',body:JSON.stringify({destino:legacyForm.elements.destino.value,justificativa:legacyForm.elements.justificativa.value.trim()})});
      show(await api(`/api/matriculas/${enrollment.id}/`));
      window.dispatchEvent(new Event('gyminsight:enrollments-updated'));
      window.dispatchEvent(new Event('gyminsight:finance-open'));
    }catch(error){feedback.textContent=error.message;}finally{button.disabled=false;}
  });
  $('begin-cancel')?.addEventListener('click',() => {
    if (!enrollment || enrollment.status !== 'ativa') return;
    cancelForm.hidden = false; $('begin-cancel').hidden = true; cancelForm.elements.motivo_cancelamento.focus();
  });
  $('abort-cancel').addEventListener('click',() => {
    cancelForm.hidden = true; cancelForm.reset(); priceForm.hidden = true; priceForm.reset(); $('begin-cancel').hidden = false; feedback.textContent = '';
  });
  cancelForm.addEventListener('submit',async event => {
    event.preventDefault(); if (!enrollment) return;
    feedback.textContent = ''; $('confirm-cancel').disabled = true;
    try {
      show(await api(`/api/matriculas/${enrollment.id}/cancelar/`,{
        method:'POST',body:JSON.stringify({motivo_cancelamento:cancelForm.elements.motivo_cancelamento.value.trim(),decisao:cancelForm.elements.decisao.value,justificativa:cancelForm.elements.justificativa.value.trim()}),
      }));
      window.dispatchEvent(new Event('gyminsight:enrollments-updated'));
    } catch (error) { feedback.textContent = error.message; }
    finally { $('confirm-cancel').disabled = false; }
  });
})();
