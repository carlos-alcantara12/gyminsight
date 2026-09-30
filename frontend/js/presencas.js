// Um envio aceito gera uma entrada. Sem reenvio automático para evitar duplicidade.
(() => {
  const dialog = document.getElementById('presence-dialog');
  const form = document.getElementById('presence-form');
  const feedback = document.getElementById('presence-feedback');
  const select = form.elements.matricula;
  const $ = id => document.getElementById(id);
  let available = new Map();
  let sending = false;

  function errorText(data,fallback) {
    if (typeof data === 'string') return data;
    if (!data || typeof data !== 'object') return fallback;
    if (data.detail) return String(data.detail);
    return Object.entries(data).map(([key,value]) => `${key === 'matricula' ? 'Matrícula' : key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ') || fallback;
  }
  async function api(url,options = {}) {
    const token = document.cookie.split('; ').find(item => item.startsWith('csrftoken='))?.slice(10) || '';
    let response;
    try {
      response = await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json',...(options.body ? {'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token)} : {})},...options});
    } catch (error) {
      throw new Error(options.body ? 'A conexão falhou. Confira o histórico antes de tentar novamente: a entrada pode ter sido registrada.' : 'Não foi possível consultar as matrículas.');
    }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new Error(errorText(data,response.status === 403 ? 'Acesso negado. Confira sua sessão e permissões.' : `Falha na operação (${response.status}).`));
    }
    return response.json();
  }
  function todayManaus() {
    const pieces = new Intl.DateTimeFormat('en-US',{timeZone:'America/Manaus',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const values = Object.fromEntries(pieces.map(piece => [piece.type,piece.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }
  async function listValidEnrollments() {
    select.replaceChildren(new Option('Selecione a matrícula',''));
    available = new Map();
    const today = todayManaus();
    let url = '/api/frequencias/elegiveis/';
    while (url) {
      const data = await api(url);
      for (const item of Array.isArray(data) ? data : data.results || []) {
        if (item.status !== 'ativa' || item.inicio > today || item.fim < today) continue;
        available.set(String(item.id),item);
        select.add(new Option(`${item.aluno_nome} · ${item.plano_nome} · matrícula ${item.id}`,item.id));
      }
      const next = Array.isArray(data) ? null : data.next;
      if (!next) { url = null; continue; }
      const candidate = new URL(next,location.origin);
      if (candidate.origin !== location.origin || !candidate.pathname.startsWith('/api/frequencias/elegiveis/')) throw new Error('Não foi possível carregar as matrículas.');
      url = candidate.pathname + candidate.search;
    }
    if (available.size === 0) throw new Error('Não há matrículas vigentes nesta unidade.');
  }
  select.addEventListener('change',() => {
    const item = available.get(select.value);
    $('presence-selected').textContent = item ? `Aluno: ${item.aluno_nome} · Plano: ${item.plano_nome} (${item.categoria_acesso}) · Validade: ${item.inicio} a ${item.fim}` : '';
  });
  $('new-presence')?.addEventListener('click',async () => {
    form.reset(); feedback.textContent = ''; $('presence-selected').textContent = '';
    form.hidden = false; $('presence-result').hidden = true;
    $('save-presence').disabled = true; dialog.showModal();
    try { await listValidEnrollments(); $('save-presence').disabled = false; }
    catch (error) { feedback.textContent = error.message; }
  });
  dialog.querySelectorAll('.close-presence').forEach(button => button.addEventListener('click',() => { if (!sending) dialog.close(); }));
  dialog.addEventListener('cancel',event => { if (sending) event.preventDefault(); });
  dialog.addEventListener('click',event => { if (event.target === dialog && !sending) dialog.close(); });
  form.addEventListener('submit',async event => {
    event.preventDefault();
    if (sending || !available.has(select.value)) return;
    sending = true; $('save-presence').disabled = true; feedback.textContent = '';
    try {
      const record = await api('/api/frequencias/',{method:'POST',body:JSON.stringify({matricula:select.value})});
      form.hidden = true; $('presence-result').hidden = false;
      const list = $('presence-profile'); list.replaceChildren();
      const values = [
        ['Aluno',record.aluno_nome],['Matrícula',record.matricula],['Unidade de entrada',record.unidade_nome],
        ['Horário (Manaus)',new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Manaus',dateStyle:'short',timeStyle:'medium'}).format(new Date(record.entrada_em))],
        ['Registro',record.id],
      ];
      for (const [label,value] of values) {
        const dt = document.createElement('dt'),dd = document.createElement('dd');
        dt.textContent = label; dd.textContent = String(value); list.append(dt,dd);
      }
      window.dispatchEvent(new Event('gyminsight:presence-updated'));
    } catch (error) { feedback.textContent = error.message; }
    finally { sending = false; $('save-presence').disabled = false; }
  });
})();
