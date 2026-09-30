(() => {
  const open = document.getElementById('new-employee');
  const dialog = document.getElementById('employee-dialog');
  if (!open || !dialog) return;
  const form = document.getElementById('employee-form');
  const feedback = document.getElementById('employee-feedback');
  open.addEventListener('click', () => { form.reset(); feedback.textContent = ''; dialog.showModal(); });
  document.getElementById('close-employee').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    feedback.textContent = '';
    const data = Object.fromEntries(new FormData(form));
    data.ativo = form.elements.ativo.checked;
    if (data.usuario) data.usuario = Number(data.usuario);
    else delete data.usuario;
    const token = document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.split('=')[1] || '';
    try {
      const response = await fetch('/api/funcionarios/', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token)},
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const error = await response.json();
        feedback.textContent = Object.values(error).flat().join(' ') || 'Não foi possível salvar o funcionário.';
        return;
      }
      dialog.close();
      window.dispatchEvent(new Event('gyminsight:employees-updated'));
    } catch (_) {
      feedback.textContent = 'Falha de conexão ao salvar o funcionário.';
    }
  });
})();
