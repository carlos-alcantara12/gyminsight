// Planos da unidade: as permissões e validações definitivas ficam na API.
(() => {
  const dialog = document.getElementById('plan-dialog');
  const form = document.getElementById('plan-form');
  const feedback = document.getElementById('plan-feedback');
  const $ = id => document.getElementById(id);
  let current = null, mode = 'create';
  const names = {nome:'Nome',duracao_dias:'Duração',preco:'Preço',categoria:'Categoria',acesso_tradicional_rede:'Acesso Tradicional em rede',ativo:'Disponibilidade',non_field_errors:'Dados'};
  const money = amount => new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(amount));

  function errorText(data,fallback) {
    if (typeof data === 'string') return data;
    if (!data || typeof data !== 'object') return fallback;
    if (data.detail) return String(data.detail);
    return Object.entries(data).map(([field,value]) => `${names[field] || field}: ${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ') || fallback;
  }
  async function api(url,options = {}) {
    const token = document.cookie.split('; ').find(item => item.startsWith('csrftoken='))?.slice(10) || '';
    const response = await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json',...(options.body ? {'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token)} : {})},...options});
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(errorText(data,response.status === 403 ? 'Acesso negado. Confira sua sessão e permissões.' : `Falha na operação (${response.status}).`));
    }
    return response.json();
  }
  function setMode(value) {
    mode = value; form.hidden = value === 'view'; $('plan-details').hidden = value !== 'view';
    $('plan-title').textContent = value === 'create' ? 'Novo plano' : value === 'edit' ? 'Editar plano' : 'Detalhes do plano';
    $('save-plan').textContent = value === 'create' ? 'Criar plano' : 'Salvar alterações';
    feedback.textContent = '';
  }
  function addDetail(label,value) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label; dd.textContent = String(value); $('plan-profile').append(dt,dd);
  }
  function show(plan) {
    current = plan; setMode('view'); $('plan-profile').replaceChildren();
    addDetail('Nome',plan.nome); addDetail('Duração',`${plan.duracao_dias} dias`);
    addDetail('Categoria',plan.categoria); addDetail('Outras Tradicionais',plan.acesso_tradicional_rede ? 'Permitido' : 'Não permitido'); addDetail('Preço',money(plan.preco)); addDetail('Disponibilidade',plan.ativo ? 'Disponível' : 'Inativo');
  }
  $('new-plan')?.addEventListener('click',() => { current = null; form.reset(); setMode('create'); dialog.showModal(); });
  window.addEventListener('gyminsight:plan',async event => {
    setMode('view'); $('plan-profile').replaceChildren(); dialog.showModal(); feedback.textContent = 'Carregando plano…';
    try { show(await api(`/api/planos/${encodeURIComponent(event.detail)}/`)); }
    catch (error) { feedback.textContent = error.message; }
  });
  dialog.querySelectorAll('.close-plan').forEach(button => button.addEventListener('click',() => dialog.close()));
  dialog.addEventListener('click',event => { if (event.target === dialog) dialog.close(); });
  $('edit-plan')?.addEventListener('click',() => {
    if (!current || dialog.dataset.canEdit !== 'true') return;
    setMode('edit'); form.elements.nome.value = current.nome;
    form.elements.duracao_dias.value = current.duracao_dias;
    form.elements.categoria.value = current.categoria;
    form.elements.acesso_tradicional_rede.checked = current.acesso_tradicional_rede;
    form.elements.preco.value = current.preco;
    form.elements.ativo.checked = current.ativo;
  });
  form.addEventListener('submit',async event => {
    event.preventDefault(); feedback.textContent = ''; $('save-plan').disabled = true;
    const data = {
      nome:form.elements.nome.value.trim(),
      categoria:form.elements.categoria.value,
      acesso_tradicional_rede:form.elements.acesso_tradicional_rede.checked,
      duracao_dias:Number(form.elements.duracao_dias.value),
      preco:form.elements.preco.value,
      ativo:form.elements.ativo.checked,
    };
    try {
      show(await api(mode === 'create' ? '/api/planos/' : `/api/planos/${current.id}/`,{
        method:mode === 'create' ? 'POST' : 'PATCH',body:JSON.stringify(data),
      }));
      window.dispatchEvent(new Event('gyminsight:plans-updated'));
    } catch (error) { feedback.textContent = error.message; }
    finally { $('save-plan').disabled = false; }
  });
})();
