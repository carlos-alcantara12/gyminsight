const sections = {
  unidades: {title:'Unidades', columns:[['id','ID'],['nome','Unidade'],['categoria','Categoria'],['ativa','Ativa'],['abre_domingo','Domingos'],['abre_feriado','Feriados']]},
  feriados: {title:'Feriados', columns:[['id','ID'],['data','Data'],['nome','Feriado'],['abre','Abertura excepcional']]},
  alunos: {title:'Alunos', columns:[['id','ID'],['nome','Nome'],['status','Status'],['matricula_ativa_id','Matrícula ativa']]},
  planos: {title:'Planos', columns:[['id','ID'],['nome','Plano'],['categoria','Categoria'],['duracao_dias','Duração (dias)'],['preco','Preço'],['ativo','Ativo']]},
  matriculas: {title:'Matrículas', columns:[['id','ID'],['aluno_nome','Aluno'],['plano_nome','Plano'],['valor_contratado','Valor contratado'],['inicio','Início'],['fim','Fim'],['status','Status']]},
  frequencias: {title:'Entradas', columns:[['id','ID'],['aluno_nome','Aluno'],['unidade_nome','Unidade de entrada'],['entrada_em','Horário'],['registrada_por','Registrada por']]},
  pagamentos: {title:'Pagamentos', columns:[['id','ID'],['aluno_nome','Aluno'],['valor','Valor'],['vencimento','Vencimento'],['status','Status']]},
  funcionarios: {title:'Funcionários', columns:[['id','ID'],['nome','Nome'],['cargo','Cargo'],['ativo','Ativo']]},
  auditoria: {title:'Auditoria', columns:[['id','ID'],['ocorrido_em','Horário'],['acao','Ação'],['entidade','Entidade'],['objeto_id','Registro']]}
};
let section='alunos', page=1, next=null, previous=null;
const $ = id => document.getElementById(id);
function renderCell(value,key){
  const td=document.createElement('td');
  if(value===null || value===undefined || value===''){td.textContent='—';return td;}
  if(key==='status'||key==='ativo'){const pill=document.createElement('span');pill.className='pill'+(value===false||value==='inativo'||value==='cancelada'||value==='encerrada'?' muted':'');pill.textContent=value===true?'Sim':value===false?'Não':String(value);td.append(pill);}
  else if(key==='preco'||key==='valor'||key==='valor_contratado'){const n=Number(value);td.textContent=Number.isFinite(n)?new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(n):String(value);}
  else if(key==='entrada_em'||key==='ocorrido_em'){const d=new Date(value);td.textContent=Number.isNaN(d.getTime())?String(value):d.toLocaleString('pt-BR');}
  else td.textContent=String(value);
  return td;
}
async function load(){
  $('unit-network-summary').hidden=section!=='unidades';
  if(section==='unidades')window.dispatchEvent(new Event('gyminsight:units-open'));
  $('finance-panel')?.setAttribute('hidden','');
  if(section==='financeiro'){
    document.querySelector('main > .panel:not(#unit-network-summary)').hidden=true;
    $('report-panel').hidden=true;
    $('enrolled-panel')?.setAttribute('hidden','');
    $('finance-panel').hidden=false;
    $('title').textContent='Financeiro';
    $('subtitle').textContent='Mensalidades e faturamento da unidade selecionada.';
    window.dispatchEvent(new Event('gyminsight:finance-open'));
    return;
  }
  if(section==='matriculados'){
    document.querySelector('main > .panel:not(#unit-network-summary)').hidden=true;
    $('report-panel').hidden=true;
    $('enrolled-panel').hidden=false;
    $('title').textContent='Matriculados';
    $('subtitle').textContent='Situação das matrículas da unidade selecionada.';
    window.dispatchEvent(new Event('gyminsight:enrolled-open'));
    return;
  }
  $('enrolled-panel')?.setAttribute('hidden','');
  if(section==='relatorios'){
    document.querySelector('main > .panel:not(#unit-network-summary)').hidden=true;
    $('report-panel').hidden=false;
    $('title').textContent='Relatórios';
    $('subtitle').textContent='Frequência dos alunos da sua unidade.';
    window.dispatchEvent(new Event('gyminsight:report-open'));
    return;
  }
  document.querySelector('main > .panel:not(#unit-network-summary)').hidden=false;
  $('report-panel').hidden=true;
  const config=sections[section];$('title').textContent=config.title;$('list-title').textContent=config.title+' cadastrados';$('notice').textContent='';$('rows').replaceChildren();$('page-label').textContent='Carregando…';
  $('head').replaceChildren();const tr=document.createElement('tr');config.columns.forEach(([,label])=>{const th=document.createElement('th');th.textContent=label;tr.append(th)});if(['alunos','matriculas','planos','unidades','feriados'].includes(section)){const th=document.createElement('th');th.textContent='Ações';tr.append(th)}$('head').append(tr);
  try{
    const response=await fetch(`/api/${section}/?page=${page}`,{credentials:'same-origin',headers:{Accept:'application/json'}});
    if(response.status===401||response.status===403){$('notice').textContent='Você não tem permissão para consultar esta seção ou sua sessão expirou.';$('page-label').textContent='';return;}
    if(!response.ok)throw new Error(`Falha ao carregar dados (${response.status}).`);
    const data=await response.json();const items=Array.isArray(data)?data:data.results||[];next=data.next;previous=data.previous;
    items.forEach(item=>{const row=document.createElement('tr');config.columns.forEach(([key])=>row.append(renderCell(item[key],key)));if(['alunos','matriculas','planos','unidades','feriados'].includes(section)){const cell=document.createElement('td'),button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Ver detalhes';const eventName={alunos:'gyminsight:student',matriculas:'gyminsight:enrollment',planos:'gyminsight:plan',unidades:'gyminsight:unit',feriados:'gyminsight:holiday'}[section];button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent(eventName,{detail:item.id})));cell.append(button);row.append(cell)}$('rows').append(row)});
    if(!items.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=config.columns.length+(['alunos','matriculas','planos'].includes(section)?1:0);cell.textContent='Nenhum registro encontrado.';row.append(cell);$('rows').append(row)}
    $('page-label').textContent=`Página ${page}${typeof data.count==='number'?` · ${data.count} registros`:''}`;
  }catch(error){$('notice').textContent=error.message;$('page-label').textContent='';}finally{$('previous').disabled=!previous;$('next').disabled=!next;}
}
document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{document.querySelector('.nav.active')?.classList.remove('active');button.classList.add('active');section=button.dataset.section;$('new-student')?.toggleAttribute('hidden',section!=='alunos');$('new-enrollment')?.toggleAttribute('hidden',section!=='matriculas');$('new-plan')?.toggleAttribute('hidden',section!=='planos');$('new-presence')?.toggleAttribute('hidden',section!=='frequencias');$('new-employee')?.toggleAttribute('hidden',section!=='funcionarios');$('new-unit')?.toggleAttribute('hidden',section!=='unidades');$('new-holiday')?.toggleAttribute('hidden',section!=='feriados');page=1;next=previous=null;load()}));
$('refresh').addEventListener('click',load);$('previous').addEventListener('click',()=>{if(previous){page--;load()}});$('next').addEventListener('click',()=>{if(next){page++;load()}});load();
window.addEventListener('gyminsight:students-updated',()=>{if(section==='alunos')load()});
window.addEventListener('gyminsight:enrollments-updated',()=>{if(section==='matriculas')load();else if(section==='matriculados')window.dispatchEvent(new Event('gyminsight:enrolled-open'))});
window.addEventListener('gyminsight:plans-updated',()=>{if(section==='planos')load()});
window.addEventListener('gyminsight:presence-updated',()=>{if(section==='frequencias')load()});

window.addEventListener('gyminsight:employees-updated',()=>{if(section==='funcionarios')load()});

window.addEventListener('gyminsight:units-updated',()=>{if(section==='unidades')load()});
window.addEventListener('gyminsight:holidays-updated',()=>{if(section==='feriados')load()});
