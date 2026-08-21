(() => {
  const root = document.documentElement;
  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    try { localStorage.setItem('viralclip-theme', theme); } catch (_) {}
  };
  document.addEventListener('click', (event) => {
    const theme = event.target.closest('#theme-toggle');
    if (theme) applyTheme(root.dataset.theme === 'light' ? 'dark' : 'light');
    const toggle = event.target.closest('[data-sidebar-toggle]');
    if (toggle) document.body.classList.toggle('sidebar-open');
  });
  document.querySelectorAll('.drop-zone').forEach((zone) => {
    const input = zone.querySelector('input[type=file]');
    if (!input) return;
    const label = zone.querySelector('[data-file-label]');
    const setFile = (file) => { if (label && file) label.textContent = file.name; };
    input.addEventListener('change', () => setFile(input.files && input.files[0]));
    ['dragenter','dragover'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.add('dragging'); }));
    ['dragleave','drop'].forEach((name) => zone.addEventListener(name, (e) => { e.preventDefault(); zone.classList.remove('dragging'); }));
    zone.addEventListener('drop', (event) => {
      const files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length) return;
      try { const dt = new DataTransfer(); dt.items.add(files[0]); input.files = dt.files; } catch (_) {}
      setFile(files[0]);
    });
  });
})();

// V3.2 browser acceleration probe. Heavy video work always stays in the
// Local Worker; this capability only chooses the fastest interactive preview.
(async () => {
  let mode = 'canvas2d';
  try {
    if (navigator.gpu) {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) mode = 'webgpu';
    }
  } catch (_) {}
  if (mode !== 'webgpu') {
    try {
      const canvas = document.createElement('canvas');
      if (canvas.getContext('webgl2') || canvas.getContext('webgl')) mode = 'webgl';
    } catch (_) {}
  }
  document.documentElement.dataset.browserAcceleration = mode;
  window.ViralClipBrowserAcceleration = mode;
window.dispatchEvent(new CustomEvent('viralclip:browser-acceleration', { detail: { mode } }));
})();

document.querySelectorAll('[data-cut-wizard]').forEach((wizard) => { let step=0; const steps=[...wizard.querySelectorAll('[data-wizard-step]')], back=wizard.querySelector('[data-wizard-back]'), next=wizard.querySelector('[data-wizard-next]'), submit=wizard.querySelector('[data-wizard-submit]'), status=wizard.querySelector('[data-wizard-status]'), title=wizard.querySelector('[data-wizard-title]'), desc=wizard.querySelector('[data-wizard-description]'), copy=[['Defina o formato do vídeo','Escolha a proporção e o enquadramento ideal para seu conteúdo.'],['Ajuste a duração do seu vídeo','Defina a duração dos cortes e a faixa que será analisada.'],['Revise e crie seus cortes','Personalize layout e legendas antes de processar.']]; const draw=()=>{steps.forEach((x,i)=>x.hidden=i!==step);wizard.querySelectorAll('.cut-progress i').forEach((x,i)=>x.classList.toggle('active',i<=step));back.hidden=step===0;next.hidden=step===2;submit.hidden=step!==2;status.textContent=`Etapa ${step+1} de 3`;title.textContent=copy[step][0];desc.textContent=copy[step][1]};next.onclick=()=>{step++;draw()};back.onclick=()=>{step--;draw()};wizard.querySelectorAll('[name="duration_preset"]').forEach(x=>x.onchange=()=>{if(x.value!=='auto')['min_duration','max_duration','target_duration'].forEach(n=>wizard.querySelector(`[name="${n}"]`).value=x.value)});});
