const message = document.querySelector('#message');
const button = document.querySelector('#install');
function render(data) {
  document.querySelector('#version').textContent = data.version;
  document.querySelector('#installed').textContent = data.installed_version;
  document.querySelector('#environment').textContent = data.environment_version || 'Non impostata';
  document.querySelector('#force').textContent = data.force_update ? 'Attivo' : 'Disattivo';
  document.querySelector('#release').value = data.version;
}
async function load() {
  try {
    const response = await fetch('/admin/api/version');
    if (!response.ok) throw new Error('Impossibile leggere la versione attiva. Ricarica la pagina.');
    render(await response.json());
    button.disabled = false;
  } catch (error) { message.textContent = error.message; }
}
document.querySelector('#release-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  message.textContent = 'Download e verifica in corso…';
  try {
    const response = await fetch('/admin/api/version', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Autoloader-Admin': '1'},
      body: JSON.stringify({version: document.querySelector('#release').value.trim()})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Aggiornamento non riuscito.');
    render(data);
    message.textContent = 'Versione attivata e salvata.';
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
load();
